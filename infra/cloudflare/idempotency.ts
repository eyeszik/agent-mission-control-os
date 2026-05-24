import { Env } from './bindings';

export async function verifyIdempotency(env: Env, key: string): Promise<boolean> {
  // Real KV binding usage implemented
  if (!env.KV_CACHE) return false;
  const val = await env.KV_CACHE.get(`idempotency:${key}`);
  return val !== null;
}

export async function recordIdempotency(env: Env, key: string, result: any, ttlSeconds: number = 86400): Promise<void> {
  // Real KV binding usage implemented
  if (!env.KV_CACHE) return;
  await env.KV_CACHE.put(`idempotency:${key}`, JSON.stringify(result), { expirationTtl: ttlSeconds });
}
