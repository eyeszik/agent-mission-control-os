import { Env } from './bindings';

export async function verifyIdempotency(env: Env, key: string): Promise<boolean> {
  // [VOID_DETECTED] Missing real KV binding usage
  const val = await env.KV_CACHE?.get(`idempotency:${key}`);
  return val !== null;
}

export async function recordIdempotency(env: Env, key: string, result: any, ttlSeconds: number = 86400): Promise<void> {
  // [VOID_DETECTED] Missing real KV binding usage
  await env.KV_CACHE?.put(`idempotency:${key}`, JSON.stringify(result), { expirationTtl: ttlSeconds });
}
