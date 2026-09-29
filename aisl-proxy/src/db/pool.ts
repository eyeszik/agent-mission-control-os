import { Pool, type PoolClient, type QueryResultRow } from 'pg';
import type { Env } from '../config/env.js';

/**
 * Deterministic query surface over a pooled Postgres connection.
 *
 * `transaction()` is the only way to get multi-statement atomicity, and it
 * always releases its client — a leaked client is what turns one slow merchant
 * API call into a gateway-wide outage.
 */
export interface Database {
  query<T extends QueryResultRow = QueryResultRow>(
    text: string,
    params?: readonly unknown[],
  ): Promise<{ rows: T[]; rowCount: number }>;
  transaction<T>(fn: (tx: Database) => Promise<T>): Promise<T>;
  close(): Promise<void>;
}

class PoolDatabase implements Database {
  constructor(private readonly pool: Pool) {}

  async query<T extends QueryResultRow = QueryResultRow>(
    text: string,
    params: readonly unknown[] = [],
  ): Promise<{ rows: T[]; rowCount: number }> {
    const result = await this.pool.query<T>(text, params as unknown[]);
    return { rows: result.rows, rowCount: result.rowCount ?? 0 };
  }

  async transaction<T>(fn: (tx: Database) => Promise<T>): Promise<T> {
    const client = await this.pool.connect();
    try {
      await client.query('BEGIN');
      const result = await fn(new ClientDatabase(client));
      await client.query('COMMIT');
      return result;
    } catch (error) {
      try {
        await client.query('ROLLBACK');
      } catch {
        // A rollback failure means the connection is already unusable; the
        // original error is the one worth surfacing.
      }
      throw error;
    } finally {
      client.release();
    }
  }

  async close(): Promise<void> {
    await this.pool.end();
  }
}

class ClientDatabase implements Database {
  constructor(private readonly client: PoolClient) {}

  async query<T extends QueryResultRow = QueryResultRow>(
    text: string,
    params: readonly unknown[] = [],
  ): Promise<{ rows: T[]; rowCount: number }> {
    const result = await this.client.query<T>(text, params as unknown[]);
    return { rows: result.rows, rowCount: result.rowCount ?? 0 };
  }

  /** Nested transactions reuse the outer one; Postgres has no true nesting here. */
  async transaction<T>(fn: (tx: Database) => Promise<T>): Promise<T> {
    return fn(this);
  }

  async close(): Promise<void> {
    // The pool owns this client's lifecycle.
  }
}

export function createDatabase(env: Env): Database {
  const pool = new Pool({
    connectionString: env.DATABASE_URL,
    max: env.DATABASE_POOL_MAX,
    statement_timeout: env.DATABASE_STATEMENT_TIMEOUT_MS,
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: 5_000,
    allowExitOnIdle: false,
  });

  // A pool-level error (server restart, network blip) must not crash the
  // process: pg emits it on idle clients, which node would otherwise treat as
  // an unhandled 'error' event.
  pool.on('error', (error) => {
    process.emitWarning(`postgres pool error: ${error.message}`, 'AislPoolWarning');
  });

  return new PoolDatabase(pool);
}
