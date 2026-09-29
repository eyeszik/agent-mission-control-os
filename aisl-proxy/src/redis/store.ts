import { Redis } from 'ioredis';

export interface RateLimitDecision {
  allowed: boolean;
  remaining: number;
  retryAfterMs: number;
}

/**
 * The narrow Redis surface the gateway actually needs.
 *
 * Keeping it this small means the deduplication and rate-limit semantics are
 * testable against an in-memory implementation with identical behaviour, and
 * that no route can reach for a Redis primitive whose failure mode has not
 * been considered.
 */
export interface KeyValueStore {
  /** Atomic SETNX + EX. True when this caller won the key. */
  setIfAbsent(key: string, value: string, ttlSeconds: number): Promise<boolean>;
  get(key: string): Promise<string | null>;
  set(key: string, value: string, ttlSeconds: number): Promise<void>;
  del(key: string): Promise<void>;
  /** Atomic token-bucket consumption. */
  consumeToken(key: string, capacity: number, refillPerSecond: number): Promise<RateLimitDecision>;
  ping(): Promise<boolean>;
  close(): Promise<void>;
}

/**
 * Token bucket as a single Lua script so refill and consume cannot interleave
 * across gateway replicas.
 *
 * KEYS[1] bucket key
 * ARGV[1] capacity, ARGV[2] refill tokens/second, ARGV[3] now (ms)
 */
const TOKEN_BUCKET_SCRIPT = `
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])

if tokens == nil then
  tokens = capacity
  ts = now
end

local elapsed = math.max(0, now - ts) / 1000
tokens = math.min(capacity, tokens + elapsed * refill)

local allowed = 0
local retry_after_ms = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry_after_ms = math.ceil(((1 - tokens) / refill) * 1000)
end

redis.call('HSET', key, 'tokens', tokens, 'ts', now)
-- Expire well after a full refill so idle buckets are reclaimed.
redis.call('PEXPIRE', key, math.ceil((capacity / refill) * 1000) + 1000)

return { allowed, math.floor(tokens), retry_after_ms }
`;

export class RedisStore implements KeyValueStore {
  private readonly client: Redis;
  private readonly prefix: string;

  constructor(url: string, prefix: string) {
    this.client = new Redis(url, {
      maxRetriesPerRequest: 2,
      enableReadyCheck: true,
      lazyConnect: false,
      retryStrategy: (times: number) => Math.min(times * 200, 2_000),
    });
    // Without a listener, ioredis surfaces connection errors as unhandled
    // events and takes the process down on a transient blip.
    this.client.on('error', (error: Error) => {
      process.emitWarning(`redis error: ${error.message}`, 'AislRedisWarning');
    });
    this.prefix = prefix;
  }

  private k(key: string): string {
    return `${this.prefix}:${key}`;
  }

  async setIfAbsent(key: string, value: string, ttlSeconds: number): Promise<boolean> {
    const result = await this.client.set(this.k(key), value, 'EX', ttlSeconds, 'NX');
    return result === 'OK';
  }

  async get(key: string): Promise<string | null> {
    return this.client.get(this.k(key));
  }

  async set(key: string, value: string, ttlSeconds: number): Promise<void> {
    if (ttlSeconds > 0) {
      await this.client.set(this.k(key), value, 'EX', ttlSeconds);
    } else {
      await this.client.set(this.k(key), value);
    }
  }

  async del(key: string): Promise<void> {
    await this.client.del(this.k(key));
  }

  async consumeToken(key: string, capacity: number, refillPerSecond: number): Promise<RateLimitDecision> {
    const result = (await this.client.eval(
      TOKEN_BUCKET_SCRIPT,
      1,
      this.k(key),
      String(capacity),
      String(refillPerSecond),
      String(Date.now()),
    )) as [number, number, number];

    return {
      allowed: result[0] === 1,
      remaining: result[1],
      retryAfterMs: result[2],
    };
  }

  async ping(): Promise<boolean> {
    try {
      return (await this.client.ping()) === 'PONG';
    } catch {
      return false;
    }
  }

  async close(): Promise<void> {
    await this.client.quit().catch(() => this.client.disconnect());
  }
}

interface MemoryEntry {
  value: string;
  expiresAt: number | null;
}

interface MemoryBucket {
  tokens: number;
  ts: number;
}

/**
 * In-process equivalent used by unit tests and single-node development.
 * Single-threaded JS gives the same atomicity the Lua script gives Redis.
 */
export class InMemoryStore implements KeyValueStore {
  private readonly entries = new Map<string, MemoryEntry>();
  private readonly buckets = new Map<string, MemoryBucket>();

  private live(key: string): MemoryEntry | undefined {
    const entry = this.entries.get(key);
    if (!entry) return undefined;
    if (entry.expiresAt !== null && entry.expiresAt <= Date.now()) {
      this.entries.delete(key);
      return undefined;
    }
    return entry;
  }

  async setIfAbsent(key: string, value: string, ttlSeconds: number): Promise<boolean> {
    if (this.live(key)) return false;
    this.entries.set(key, { value, expiresAt: Date.now() + ttlSeconds * 1000 });
    return true;
  }

  async get(key: string): Promise<string | null> {
    return this.live(key)?.value ?? null;
  }

  async set(key: string, value: string, ttlSeconds: number): Promise<void> {
    this.entries.set(key, { value, expiresAt: ttlSeconds > 0 ? Date.now() + ttlSeconds * 1000 : null });
  }

  async del(key: string): Promise<void> {
    this.entries.delete(key);
  }

  async consumeToken(key: string, capacity: number, refillPerSecond: number): Promise<RateLimitDecision> {
    const now = Date.now();
    const bucket = this.buckets.get(key) ?? { tokens: capacity, ts: now };
    const elapsed = Math.max(0, now - bucket.ts) / 1000;
    let tokens = Math.min(capacity, bucket.tokens + elapsed * refillPerSecond);

    let allowed = false;
    let retryAfterMs = 0;
    if (tokens >= 1) {
      tokens -= 1;
      allowed = true;
    } else {
      retryAfterMs = Math.ceil(((1 - tokens) / refillPerSecond) * 1000);
    }

    this.buckets.set(key, { tokens, ts: now });
    return { allowed, remaining: Math.floor(tokens), retryAfterMs };
  }

  async ping(): Promise<boolean> {
    return true;
  }

  async close(): Promise<void> {
    this.entries.clear();
    this.buckets.clear();
  }
}
