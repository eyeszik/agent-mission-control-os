/**
 * Driver-agnostic database contracts.
 *
 * All AMC persistence lives in the Python backend; nothing in the TypeScript
 * workspace talks to a database today. This package defines the client and
 * transaction contracts (and their semantics) so any future TypeScript
 * service uses one shape. A concrete driver (e.g. `pg`, `better-sqlite3`) is
 * supplied by the caller through `DbDriver`; none is bundled.
 *
 * Semantics:
 * - one driver = one connection; operations are serialized through a queue,
 *   so a transaction never interleaves with other statements;
 * - `transaction` commits on success and rolls back (then rethrows) on error;
 *   a transaction handle is inactive once it settles;
 * - nested transactions are rejected rather than silently flattened;
 * - inside `transaction`, query through the `tx` handle: `client.query` waits
 *   for the transaction to finish, so calling it from inside one deadlocks.
 */

import { AMC_DATABASE_BACKENDS, type AmcDatabaseBackend, isOneOf } from '@amc/constants';
import { AMCError, ConflictError, ValidationError } from '@amc/errors';

export interface DbConfig {
  backend: AmcDatabaseBackend;
  /** Connection URL; required for postgres. Never logged. */
  url?: string;
  /** File path for sqlite. */
  sqlitePath?: string;
}

export type Row = Record<string, unknown>;
export type Params = readonly unknown[];

export interface DbDriver {
  query(sql: string, params: Params): Promise<Row[]>;
  begin(): Promise<void>;
  commit(): Promise<void>;
  rollback(): Promise<void>;
  close(): Promise<void>;
}

export interface DbTransaction {
  readonly id: number;
  readonly active: boolean;
  query<T extends Row = Row>(sql: string, params?: Params): Promise<T[]>;
}

export interface DbClient {
  readonly config: Readonly<Omit<DbConfig, 'url'>> & { hasUrl: boolean };
  query<T extends Row = Row>(sql: string, params?: Params): Promise<T[]>;
  transaction<T>(fn: (tx: DbTransaction) => Promise<T>): Promise<T>;
  close(): Promise<void>;
}

export function validateDbConfig(config: DbConfig): DbConfig {
  if (!isOneOf(AMC_DATABASE_BACKENDS, config.backend)) {
    throw new ValidationError(`Unsupported database backend ${JSON.stringify(config.backend)}`, { code: 'DB_CONFIG_INVALID' });
  }
  if (config.backend === 'postgres' && !config.url) {
    throw new ValidationError('A connection url is required when backend is postgres', { code: 'DB_CONFIG_INVALID' });
  }
  return config;
}

/** Build a DbConfig from `AMC_DATABASE_BACKEND` / `DATABASE_URL` / `AMC_DB_PATH`. */
export function dbConfigFromEnv(env: Readonly<Record<string, string | undefined>>): DbConfig {
  const backend = (env.AMC_DATABASE_BACKEND?.trim().toLowerCase() || 'sqlite') as AmcDatabaseBackend;
  const url = env.DATABASE_URL?.trim();
  const sqlitePath = env.AMC_DB_PATH?.trim();
  return validateDbConfig({ backend, ...(url ? { url } : {}), ...(sqlitePath ? { sqlitePath } : {}) });
}

class Transaction implements DbTransaction {
  active = true;
  constructor(readonly id: number, private readonly driver: DbDriver) {}

  async query<T extends Row = Row>(sql: string, params: Params = []): Promise<T[]> {
    requireTx(this);
    return (await this.driver.query(sql, params)) as T[];
  }
}

export function createDbClient(config: DbConfig, driver: DbDriver): DbClient {
  const checked = validateDbConfig(config);
  let queue: Promise<unknown> = Promise.resolve();
  let nextId = 1;
  let inTransaction = false;
  let closed = false;

  const exclusive = <T>(op: () => Promise<T>): Promise<T> => {
    const run = queue.then(op, op);
    queue = run.catch(() => undefined);
    return run;
  };
  const ensureOpen = () => {
    if (closed) throw new AMCError('Database client is closed', { code: 'DB_CLOSED', status: 500 });
  };

  return {
    config: {
      backend: checked.backend,
      hasUrl: Boolean(checked.url),
      ...(checked.sqlitePath ? { sqlitePath: checked.sqlitePath } : {}),
    },
    query<T extends Row = Row>(sql: string, params: Params = []) {
      ensureOpen();
      return exclusive(async () => (await driver.query(sql, params)) as T[]);
    },
    transaction<T>(fn: (tx: DbTransaction) => Promise<T>) {
      ensureOpen();
      if (inTransaction) {
        return Promise.reject(new ConflictError('Nested transactions are not supported', { code: 'DB_NESTED_TRANSACTION' }));
      }
      return exclusive(async () => {
        inTransaction = true;
        const tx = new Transaction(nextId++, driver);
        try {
          await driver.begin();
          const result = await fn(tx);
          await driver.commit();
          return result;
        } catch (error) {
          await driver.rollback();
          throw error;
        } finally {
          tx.active = false;
          inTransaction = false;
        }
      });
    },
    async close() {
      if (closed) return;
      closed = true;
      await queue;
      await driver.close();
    },
  };
}

/** Run `fn` inside a transaction on `client`. */
export function withTransaction<T>(client: DbClient, fn: (tx: DbTransaction) => Promise<T>): Promise<T> {
  return client.transaction(fn);
}

/** Assert that a live transaction handle was passed (for functions that must run inside one). */
export function requireTx(tx: DbTransaction | null | undefined): DbTransaction {
  if (!tx || !tx.active) {
    throw new AMCError('This operation must run inside an active transaction', { code: 'DB_TRANSACTION_REQUIRED', status: 500 });
  }
  return tx;
}
