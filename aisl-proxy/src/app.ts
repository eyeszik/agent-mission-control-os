import Fastify, { type FastifyInstance, type FastifyReply, type FastifyRequest } from 'fastify';
import { z, ZodError } from 'zod';
import { AislError, isAislError } from './lib/errors.js';
import { safeEqual } from './lib/crypto.js';
import { isUuid } from './lib/ids.js';
import type { AppDependencies } from './container.js';
import { IntentService } from './services/intentService.js';
import { CheckoutService } from './services/checkoutService.js';
import { WebhookService } from './services/webhookService.js';
import { ReconciliationService } from './services/reconciliationService.js';
import {
  ACP_CONFIG,
  CheckoutRequestSchema,
  IntentRequestSchema,
  type OrderStatusResponse,
} from './types/acp.js';

declare module 'fastify' {
  interface FastifyRequest {
    /** Raw request bytes, retained so webhook signatures verify against the exact payload. */
    rawBody?: Buffer;
    agentKeyId?: string;
  }
}

const AGENT_ROUTE_PREFIX = '/v1/agent';

export async function buildServer(deps: AppDependencies): Promise<FastifyInstance> {
  const { env } = deps;

  const app = Fastify({
    logger: {
      level: env.LOG_LEVEL,
      redact: {
        paths: [
          'req.headers.authorization',
          'req.headers["stripe-signature"]',
          'req.body.payment_credential.token',
        ],
        censor: '[redacted]',
      },
    },
    trustProxy: true,
    bodyLimit: 1_048_576,
  });

  // Stripe signature verification requires the exact bytes that were signed,
  // so JSON is parsed from a retained buffer rather than a stream.
  app.addContentTypeParser('application/json', { parseAs: 'buffer' }, (request, body, done) => {
    const buffer = Buffer.isBuffer(body) ? body : Buffer.from(body);
    request.rawBody = buffer;
    if (buffer.length === 0) {
      done(null, undefined);
      return;
    }
    try {
      done(null, JSON.parse(buffer.toString('utf8')));
    } catch (error) {
      done(AislError.badRequest('invalid_json', `request body is not valid JSON: ${(error as Error).message}`), undefined);
    }
  });

  app.setErrorHandler((error, request, reply) => {
    const mapped = mapError(error);
    if (mapped.statusCode >= 500) {
      request.log.error({ err: error, code: mapped.code }, 'request failed');
    } else {
      request.log.warn({ code: mapped.code, message: mapped.message }, 'request rejected');
    }
    reply.status(mapped.statusCode).send(mapped.toBody());
  });

  app.setNotFoundHandler((request, reply) => {
    reply
      .status(404)
      .send(AislError.notFound('route_not_found', `no route for ${request.method} ${request.url}`).toBody());
  });

  // Order matters: authentication runs first so the rate limiter can meter a
  // known API key rather than a shared egress IP.
  registerAgentAuth(app, deps);
  registerRateLimit(app, deps);

  registerDiscoveryRoutes(app, deps);
  registerAgentRoutes(app, deps);
  registerWebhookRoutes(app, deps);

  return app;
}

/* -------------------------------------------------------------------------- */
/* Cross-cutting hooks                                                         */
/* -------------------------------------------------------------------------- */

function registerRateLimit(app: FastifyInstance, deps: AppDependencies): void {
  const { env } = deps;
  if (!env.RATE_LIMIT_ENABLED) return;

  app.addHook('onRequest', async (request, reply) => {
    // Discovery and health are deliberately unmetered: an agent must always be
    // able to learn what this gateway supports.
    if (!request.url.startsWith(AGENT_ROUTE_PREFIX)) return;

    const identity = agentIdentity(request);
    const decision = await deps.cache.consumeToken(
      `ratelimit:${identity}`,
      env.RATE_LIMIT_CAPACITY,
      env.RATE_LIMIT_REFILL_PER_SECOND,
    );

    reply.header('x-ratelimit-limit', String(env.RATE_LIMIT_CAPACITY));
    reply.header('x-ratelimit-remaining', String(Math.max(0, decision.remaining)));

    if (!decision.allowed) {
      reply.header('retry-after', String(Math.ceil(decision.retryAfterMs / 1000)));
      throw AislError.rateLimited(
        `rate limit exceeded for ${identity}; retry in ${Math.ceil(decision.retryAfterMs / 1000)}s`,
      );
    }
  });
}

function registerAgentAuth(app: FastifyInstance, deps: AppDependencies): void {
  const { env } = deps;
  // Enforcement needs both the switch and at least one key. `loadEnv` already
  // refuses to boot a production process that has the switch on and no keys,
  // so this can only be off in development and test.
  const enforced = env.AISL_REQUIRE_AGENT_AUTH && env.AISL_AGENT_API_KEYS.length > 0;
  if (!enforced) {
    app.log.warn('agent authentication is disabled; /v1/agent/* is open to unauthenticated callers');
    return;
  }

  app.addHook('onRequest', async (request) => {
    if (!request.url.startsWith(AGENT_ROUTE_PREFIX)) return;

    const header = request.headers.authorization;
    const presented = typeof header === 'string' && header.startsWith('Bearer ') ? header.slice(7).trim() : '';
    if (presented.length === 0) {
      throw AislError.unauthorized('missing_credentials', 'Authorization: Bearer <agent api key> is required');
    }
    // Compare against every configured key so the response time does not
    // reveal how many keys exist or which prefix matched.
    const matched = env.AISL_AGENT_API_KEYS.reduce(
      (found, key, index) => (safeEqual(key, presented) ? index : found),
      -1,
    );
    if (matched < 0) {
      throw AislError.unauthorized('invalid_credentials', 'the presented agent API key is not recognised');
    }
    request.agentKeyId = `key_${matched}`;
  });
}

/**
 * Rate-limit bucket key. Runs in `onRequest`, before body parsing, so the
 * request body is deliberately not consulted here.
 */
function agentIdentity(request: FastifyRequest): string {
  return request.agentKeyId ?? `ip:${request.ip}`;
}

/* -------------------------------------------------------------------------- */
/* Routes                                                                      */
/* -------------------------------------------------------------------------- */

function registerDiscoveryRoutes(app: FastifyInstance, deps: AppDependencies): void {
  /**
   * ACP discovery manifest.
   *
   * Served from a frozen in-memory object with no I/O on the path: the
   * blueprint's acceptance criterion is a sub-10ms response.
   */
  app.get('/.well-known/acp/config.json', async (_request, reply) => {
    reply
      .header('content-type', 'application/json; charset=utf-8')
      .header('cache-control', 'public, max-age=300')
      .send(ACP_CONFIG);
  });

  app.get('/health', async () => ({ status: 'ok', service: 'aisl-proxy-gateway' }));

  /**
   * Operator reconciliation probe.
   *
   * Answers 200 when the books agree with reality and 503 when they do not, so
   * an uptime monitor can alert on it without parsing the body. It sits
   * alongside /health and /ready rather than under /v1/agent, and is therefore
   * outside both the agent auth hook and the rate limiter: expose it only on an
   * internal listener or behind your ingress' own access control.
   */
  app.get('/internal/reconciliation', async (_request, reply) => {
    const report = await new ReconciliationService({
      db: deps.db,
      conversions: deps.repositories.conversions,
      payouts: deps.repositories.payouts,
    }).run();

    reply.status(report.healthy ? 200 : 503).send(report);
  });

  app.get('/ready', async (_request, reply) => {
    const [database, cache] = await Promise.all([
      deps.db
        .query('SELECT 1 AS ok')
        .then(() => true)
        .catch(() => false),
      deps.cache.ping().catch(() => false),
    ]);

    const ready = database && cache;
    reply.status(ready ? 200 : 503).send({ status: ready ? 'ready' : 'degraded', database, cache });
  });
}

function registerAgentRoutes(app: FastifyInstance, deps: AppDependencies): void {
  const intentService = new IntentService({
    env: deps.env,
    merchants: deps.repositories.merchants,
    intents: deps.repositories.intents,
    connectors: deps.connectors,
    cache: deps.cache,
    logger: app.log,
  });

  const checkoutService = new CheckoutService({
    env: deps.env,
    merchants: deps.repositories.merchants,
    intents: deps.repositories.intents,
    conversions: deps.repositories.conversions,
    idempotency: deps.repositories.idempotency,
    connectors: deps.connectors,
    payments: deps.payments,
    logger: app.log,
  });

  app.post('/v1/agent/intent', async (request, reply) => {
    const parsed = parseBody(IntentRequestSchema, request.body);
    const response = await intentService.search(parsed);
    reply.status(200).send(response);
  });

  app.post('/v1/agent/checkout', async (request, reply) => {
    const headerKey = request.headers['idempotency-key'];
    const body = request.body as Record<string, unknown> | undefined;
    if (body && typeof headerKey === 'string' && body.idempotency_key === undefined) {
      body.idempotency_key = headerKey;
    }

    const parsed = parseBody(CheckoutRequestSchema, body);
    const { response, replayed } = await checkoutService.execute(parsed);
    reply.status(replayed ? 200 : 201).header('idempotent-replay', String(replayed)).send(response);
  });

  app.get('/v1/agent/order/:order_id', async (request, reply) => {
    const { order_id: orderId } = request.params as { order_id: string };
    if (!isUuid(orderId)) {
      throw AislError.badRequest('invalid_order_id', 'order_id must be a UUID', 'order_id');
    }

    const family = await deps.repositories.conversions.findOrderFamily(orderId);
    if (!family) {
      throw AislError.notFound('order_not_found', `no order ${orderId}`, 'order_id');
    }

    const { sale, reversals } = family;
    const net = reversals.reduce(
      (accumulator, reversal) => ({
        gross: accumulator.gross + reversal.split.grossAmountCents,
        commission: accumulator.commission + reversal.split.commissionTotalCents,
        aisl: accumulator.aisl + reversal.split.aislFeeCents,
        agent: accumulator.agent + reversal.split.agentPayoutCents,
      }),
      {
        gross: sale.split.grossAmountCents,
        commission: sale.split.commissionTotalCents,
        aisl: sale.split.aislFeeCents,
        agent: sale.split.agentPayoutCents,
      },
    );

    const response: OrderStatusResponse = {
      order_id: sale.id,
      external_order_id: sale.externalOrderId,
      merchant_id: sale.merchantId,
      click_id: sale.clickId,
      status: sale.status,
      amounts: {
        currency: sale.currency,
        gross_amount_cents: sale.split.grossAmountCents,
        commission_total_cents: sale.split.commissionTotalCents,
        aisl_fee_cents: sale.split.aislFeeCents,
        agent_payout_cents: sale.split.agentPayoutCents,
      },
      net_amounts: {
        currency: sale.currency,
        gross_amount_cents: net.gross,
        commission_total_cents: net.commission,
        aisl_fee_cents: net.aisl,
        agent_payout_cents: net.agent,
      },
      reversals: reversals.map((reversal) => ({
        conversion_id: reversal.id,
        external_order_id: reversal.externalOrderId,
        gross_amount_cents: reversal.split.grossAmountCents,
        created_at: reversal.createdAt.toISOString(),
      })),
      created_at: sale.createdAt.toISOString(),
    };

    reply.status(200).send(response);
  });
}

function registerWebhookRoutes(app: FastifyInstance, deps: AppDependencies): void {
  const webhookService = new WebhookService({
    env: deps.env,
    conversions: deps.repositories.conversions,
    events: deps.repositories.webhookEvents,
    cache: deps.cache,
    logger: app.log,
  });

  app.post('/v1/webhooks/stripe-acp', async (request: FastifyRequest, reply: FastifyReply) => {
    const rawBody = request.rawBody;
    if (!rawBody || rawBody.length === 0) {
      throw AislError.badRequest('empty_webhook_body', 'webhook body is empty');
    }

    const signature = request.headers['stripe-signature'];
    const event = deps.webhookVerifier.construct(
      rawBody,
      typeof signature === 'string' ? signature : undefined,
    );

    const result = await webhookService.handle(event, rawBody);
    // Stripe retries anything that is not 2xx, so a recognised duplicate still
    // answers 200 -- it is a successful no-op, not a failure.
    reply.status(200).send(result);
  });
}

/* -------------------------------------------------------------------------- */
/* Helpers                                                                     */
/* -------------------------------------------------------------------------- */

function parseBody<T extends z.ZodType>(schema: T, body: unknown): z.infer<T> {
  const result = schema.safeParse(body ?? {});
  if (!result.success) {
    throw zodToAislError(result.error);
  }
  return result.data;
}

function zodToAislError(error: ZodError): AislError {
  const first = error.issues[0];
  const param = first ? first.path.map(String).join('.') : undefined;
  const message = first ? `${param || 'body'}: ${first.message}` : 'request body failed validation';
  return AislError.badRequest('schema_validation_failed', message, param);
}

function mapError(error: unknown): AislError {
  if (isAislError(error)) return error;
  if (error instanceof ZodError) return zodToAislError(error);

  const candidate = error as { statusCode?: number; code?: string; message?: string };
  if (typeof candidate?.statusCode === 'number' && candidate.statusCode < 500) {
    return new AislError({
      statusCode: candidate.statusCode,
      type: 'invalid_request',
      code: candidate.code ?? 'bad_request',
      message: candidate.message ?? 'request rejected',
    });
  }
  return AislError.internal('internal_error', 'the gateway failed to process this request', error);
}
