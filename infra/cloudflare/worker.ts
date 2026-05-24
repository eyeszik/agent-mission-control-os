import { Env } from './bindings';

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === '/health') {
      return new Response(JSON.stringify({ status: 'ok', environment: 'cloudflare' }), {
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // Scaffold: Route to specific Durable Object based on project shard
    if (url.pathname.startsWith('/api/v1/projects/')) {
      // Logic handled in shard.ts / durable-object.ts
      return new Response('Not implemented', { status: 501 });
    }

    return new Response('Not found', { status: 404 });
  },
};
