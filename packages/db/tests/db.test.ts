import { ConflictError, ValidationError } from '@amc/errors';
import { describe, expect, it } from 'vitest';
import { type DbDriver, createDbClient, dbConfigFromEnv, requireTx, withTransaction } from '../src/index';

function fakeDriver() {
  const log: string[] = [];
  const driver: DbDriver = {
    async query(sql) {
      log.push(sql);
      if (sql === 'FAIL') throw new Error('query failed');
      return [{ sql }];
    },
    async begin() { log.push('BEGIN'); },
    async commit() { log.push('COMMIT'); },
    async rollback() { log.push('ROLLBACK'); },
    async close() { log.push('CLOSE'); },
  };
  return { driver, log };
}

describe('@amc/db', () => {
  it('validates config and never exposes the url', () => {
    expect(() => createDbClient({ backend: 'postgres' }, fakeDriver().driver)).toThrow(ValidationError);
    expect(() => dbConfigFromEnv({ AMC_DATABASE_BACKEND: 'mysql' })).toThrow(ValidationError);
    const client = createDbClient(dbConfigFromEnv({ AMC_DATABASE_BACKEND: 'postgres', DATABASE_URL: 'postgresql://u:p@h/db' }), fakeDriver().driver);
    expect(client.config).toEqual({ backend: 'postgres', hasUrl: true });
    expect(dbConfigFromEnv({})).toEqual({ backend: 'sqlite' });
  });

  it('commits on success and rolls back on failure', async () => {
    const { driver, log } = fakeDriver();
    const client = createDbClient({ backend: 'sqlite' }, driver);
    const rows = await withTransaction(client, (tx) => tx.query('SELECT 1'));
    expect(rows).toEqual([{ sql: 'SELECT 1' }]);
    await expect(client.transaction((tx) => tx.query('FAIL'))).rejects.toThrow('query failed');
    expect(log).toEqual(['BEGIN', 'SELECT 1', 'COMMIT', 'BEGIN', 'FAIL', 'ROLLBACK']);
  });

  it('serializes transactions and rejects nesting', async () => {
    const { driver, log } = fakeDriver();
    const client = createDbClient({ backend: 'sqlite' }, driver);
    await Promise.all([
      client.transaction(async (tx) => { await tx.query('A1'); await tx.query('A2'); }),
      client.transaction(async (tx) => { await tx.query('B1'); }),
    ]);
    expect(log).toEqual(['BEGIN', 'A1', 'A2', 'COMMIT', 'BEGIN', 'B1', 'COMMIT']);
    await expect(client.transaction(() => client.transaction(async () => 1))).rejects.toBeInstanceOf(ConflictError);
  });

  it('requires an active transaction handle', async () => {
    const client = createDbClient({ backend: 'sqlite' }, fakeDriver().driver);
    expect(() => requireTx(undefined)).toThrow(/active transaction/);
    let escaped: Parameters<typeof requireTx>[0];
    await client.transaction(async (tx) => {
      expect(requireTx(tx)).toBe(tx);
      escaped = tx;
    });
    expect(() => requireTx(escaped)).toThrow(/active transaction/);
    await expect(escaped!.query('SELECT 1')).rejects.toThrow(/active transaction/);
  });

  it('refuses work after close', async () => {
    const { driver, log } = fakeDriver();
    const client = createDbClient({ backend: 'sqlite' }, driver);
    await client.close();
    expect(log).toEqual(['CLOSE']);
    expect(() => client.query('SELECT 1')).toThrow(/closed/);
  });
});
