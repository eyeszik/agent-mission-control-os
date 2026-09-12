import { createServer, type Server, type ServerResponse } from 'node:http';
import { once } from 'node:events';
import type { AddressInfo } from 'node:net';

export interface MockStripeState {
  paymentIntents: Array<{
    id: string;
    amount: number;
    currency: string;
    token: string | null;
    idempotencyKey: string | null;
    stripeAccount: string | null;
    chargeId: string;
  }>;
  refunds: Array<{ id: string; paymentIntentId: string }>;
  /** Decline the next PaymentIntent, to exercise the 402 path. */
  declineNext: boolean;
  /** Fail every refund, to exercise the orphaned-capture alarm. */
  failRefunds: boolean;
}

export interface MockStripe {
  host: string;
  port: number;
  state: MockStripeState;
  close: () => Promise<void>;
}

/**
 * Stand-in for `api.stripe.com` covering the two calls the payment adapter
 * makes. It asserts the shared-payment-token parameter shape documented at
 * https://docs.stripe.com/agentic-commerce/concepts/shared-payment-tokens
 * so a regression in the adapter surfaces as a failing test, not a live
 * payment error.
 */
export async function startMockStripe(): Promise<MockStripe> {
  const state: MockStripeState = {
    paymentIntents: [],
    refunds: [],
    declineNext: false,
    failRefunds: false,
  };
  let sequence = 0;

  const server: Server = createServer((request, response) => {
    const chunks: Buffer[] = [];
    request.on('data', (chunk: Buffer) => chunks.push(chunk));
    request.on('end', () => {
      const path = (request.url ?? '').split('?')[0] ?? '';
      const form = new URLSearchParams(Buffer.concat(chunks).toString('utf8'));

      if (path === '/v1/payment_intents' && request.method === 'POST') {
        const token = form.get('payment_method_data[shared_payment_granted_token]');
        if (!token) {
          return json(response, 400, {
            error: {
              type: 'invalid_request_error',
              code: 'parameter_missing',
              message: 'payment_method_data[shared_payment_granted_token] is required to redeem a shared payment token',
            },
          });
        }
        if (form.get('confirm') !== 'true') {
          return json(response, 400, {
            error: { type: 'invalid_request_error', code: 'parameter_invalid', message: 'confirm must be true' },
          });
        }
        if (state.declineNext) {
          state.declineNext = false;
          return json(response, 402, {
            error: { type: 'card_error', code: 'card_declined', message: 'Your card was declined.' },
          });
        }

        sequence += 1;
        const id = `pi_test_${String(sequence).padStart(6, '0')}`;
        const chargeId = `ch_test_${String(sequence).padStart(6, '0')}`;
        const amount = Number(form.get('amount') ?? 0);
        const currency = form.get('currency') ?? 'usd';

        state.paymentIntents.push({
          id,
          amount,
          currency,
          token,
          idempotencyKey: header(request.headers['idempotency-key']),
          stripeAccount: header(request.headers['stripe-account']),
          chargeId,
        });

        return json(response, 200, {
          id,
          object: 'payment_intent',
          amount,
          amount_received: amount,
          currency,
          status: 'succeeded',
          latest_charge: chargeId,
        });
      }

      if (path === '/v1/refunds' && request.method === 'POST') {
        if (state.failRefunds) {
          return json(response, 400, {
            error: { type: 'invalid_request_error', code: 'charge_already_refunded', message: 'refund unavailable' },
          });
        }
        sequence += 1;
        const id = `re_test_${String(sequence).padStart(6, '0')}`;
        state.refunds.push({ id, paymentIntentId: form.get('payment_intent') ?? '' });
        return json(response, 200, { id, object: 'refund', status: 'succeeded' });
      }

      json(response, 404, {
        error: { type: 'invalid_request_error', code: 'resource_missing', message: `no mock route for ${path}` },
      });
    });
  });

  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const { port } = server.address() as AddressInfo;

  return {
    host: '127.0.0.1',
    port,
    state,
    close: async () => {
      server.close();
      await once(server, 'close');
    },
  };
}

function header(value: string | string[] | undefined): string | null {
  if (Array.isArray(value)) return value[0] ?? null;
  return value ?? null;
}

function json(response: ServerResponse, status: number, body: unknown): void {
  const payload = JSON.stringify(body);
  response.writeHead(status, {
    'content-type': 'application/json',
    'content-length': Buffer.byteLength(payload),
    'request-id': `req_mock_${Math.random().toString(36).slice(2, 10)}`,
  });
  response.end(payload);
}
