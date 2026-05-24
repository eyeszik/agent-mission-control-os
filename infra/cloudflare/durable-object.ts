import { Env } from './bindings';

/**
 * One Durable Object per Project for coordinating run state, idempotency keys,
 * checkpoint logs, and websocket hubs.
 */
export class ProjectCoordinatorDO {
  state: DurableObjectState;
  env: Env;

  constructor(state: DurableObjectState, env: Env) {
    this.state = state;
    this.env = env;
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    
    // Check idempotency for mutations
    if (request.method === 'POST' || request.method === 'PUT') {
      const idempotencyKey = request.headers.get('Idempotency-Key');
      if (idempotencyKey) {
        const hasProcessed = await this.state.storage.get(`idempotency:${idempotencyKey}`);
        if (hasProcessed) {
          return new Response(JSON.stringify({ status: 'already_processed', cached: true }), {
            headers: { 'Content-Type': 'application/json' }
          });
        }
        // Mark as processed (simplistic lock, needs proper atomicity)
        await this.state.storage.put(`idempotency:${idempotencyKey}`, true);
      }
    }

    if (url.pathname === '/ws') {
      return this.handleWebSocket(request);
    }

    return new Response('Not Found in DO', { status: 404 });
  }

  handleWebSocket(request: Request): Response {
    // Scaffold: Accept WebSocket connection for SSE / real-time event distribution
    return new Response('WebSocket Scaffold', { status: 101 });
  }
}
