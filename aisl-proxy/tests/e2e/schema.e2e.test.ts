import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { createDatabase, type Database } from '../../src/db/pool.js';
import { runMigrations } from '../../src/db/migrate.js';
import { testEnv } from '../helpers/testEnv.js';
import { truncateAll } from '../helpers/harness.js';

/**
 * TASK 2 validation gate: "Execute test migration script against test Postgres
 * instance. Assert all tables and foreign keys exist; test unique constraint on
 * external_order_id."
 */
describe('database schema and ledger deployment', () => {
  let db: Database;

  beforeAll(async () => {
    db = createDatabase(testEnv());
    await runMigrations(db);
    await truncateAll(db);
  });

  afterAll(async () => {
    await db.close();
  });

  it('creates every blueprint table', async () => {
    const { rows } = await db.query<{ table_name: string }>(
      `SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'`,
    );
    const tables = new Set(rows.map((row) => row.table_name));

    for (const table of ['merchants', 'agent_intents', 'conversions', 'idempotency_keys']) {
      expect(tables, `blueprint table ${table}`).toContain(table);
    }
    for (const table of ['ledger_entries', 'webhook_events', 'checkout_idempotency', 'agent_intent_bindings']) {
      expect(tables, `settlement table ${table}`).toContain(table);
    }
    for (const table of ['agent_accounts', 'payouts', 'payout_items']) {
      expect(tables, `payout table ${table}`).toContain(table);
    }
  });

  it('lets a conversion be claimed by only one payout', async () => {
    await db.query(
      `INSERT INTO agent_accounts (agent_id, stripe_account_id) VALUES ('agent_schema', 'acct_schema')`,
    );
    const { rows: merchant } = await db.query<{ id: string }>(
      `INSERT INTO merchants (name, platform, api_credentials_encrypted)
       VALUES ('Schema Co', 'shopify', '{}'::jsonb) RETURNING id`,
    );
    const merchantId = merchant[0]?.id;

    const { rows: conversion } = await db.query<{ id: string }>(
      `INSERT INTO conversions
         (merchant_id, external_order_id, gross_amount_cents, commission_total_cents,
          aisl_fee_cents, agent_payout_cents, merchant_net_cents, currency, agent_id)
       VALUES ($1, 'schema-order-1', 10000, 500, 80, 420, 9500, 'USD', 'agent_schema')
       RETURNING id`,
      [merchantId],
    );
    const conversionId = conversion[0]?.id;

    const payoutIds: string[] = [];
    for (const key of ['schema_key_a', 'schema_key_b']) {
      const { rows } = await db.query<{ id: string }>(
        `INSERT INTO payouts (agent_id, currency, amount_cents, idempotency_key)
         VALUES ('agent_schema', 'USD', 420, $1) RETURNING id`,
        [key],
      );
      payoutIds.push(rows[0]?.id ?? '');
    }

    await db.query(`INSERT INTO payout_items (payout_id, conversion_id, amount_cents) VALUES ($1, $2, 420)`, [
      payoutIds[0],
      conversionId,
    ]);

    // The double-payment guard: the same conversion cannot fund a second transfer.
    await expect(
      db.query(`INSERT INTO payout_items (payout_id, conversion_id, amount_cents) VALUES ($1, $2, 420)`, [
        payoutIds[1],
        conversionId,
      ]),
    ).rejects.toThrow(/duplicate key|unique/i);
  });

  it('wires the declared foreign keys', async () => {
    const { rows } = await db.query<{ child: string; column_name: string; parent: string }>(
      `SELECT tc.table_name AS child, kcu.column_name, ccu.table_name AS parent
         FROM information_schema.table_constraints tc
         JOIN information_schema.key_column_usage kcu
           ON kcu.constraint_name = tc.constraint_name
         JOIN information_schema.constraint_column_usage ccu
           ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'`,
    );
    const edges = new Set(rows.map((row) => `${row.child}.${row.column_name}->${row.parent}`));

    expect(edges).toContain('agent_intents.merchant_id->merchants');
    expect(edges).toContain('conversions.click_id->agent_intents');
    expect(edges).toContain('conversions.merchant_id->merchants');
    expect(edges).toContain('ledger_entries.conversion_id->conversions');
    expect(edges).toContain('ledger_entries.merchant_id->merchants');
  });

  it('enforces the unique constraint on external_order_id', async () => {
    const merchantId = await seedMerchant(db);
    const clickId = '018f4a1e-8e3b-7000-8432-1b1f9b3b0aa1';
    await db.query(`INSERT INTO agent_intents (click_id, agent_id, merchant_id) VALUES ($1, 'agent', $2)`, [
      clickId,
      merchantId,
    ]);

    const insert = `
      INSERT INTO conversions (click_id, merchant_id, external_order_id, currency,
                               gross_amount_cents, commission_total_cents, aisl_fee_cents,
                               agent_payout_cents, merchant_net_cents)
      VALUES ($1, $2, 'ORDER-DUP-1', 'USD', 10000, 500, 80, 420, 9500)`;

    await db.query(insert, [clickId, merchantId]);
    await expect(db.query(insert, [clickId, merchantId])).rejects.toThrow(/duplicate key|unique/i);
  });

  it('rejects an unbalanced conversion row at the database level', async () => {
    const merchantId = await seedMerchant(db);
    const clickId = '018f4a1e-8e3b-7000-8432-1b1f9b3b0aa2';
    await db.query(`INSERT INTO agent_intents (click_id, agent_id, merchant_id) VALUES ($1, 'agent', $2)`, [
      clickId,
      merchantId,
    ]);

    // commission_total (500) != aisl_fee (80) + agent_payout (100)
    await expect(
      db.query(
        `INSERT INTO conversions (click_id, merchant_id, external_order_id, currency,
                                  gross_amount_cents, commission_total_cents, aisl_fee_cents,
                                  agent_payout_cents, merchant_net_cents)
         VALUES ($1, $2, 'ORDER-UNBALANCED', 'USD', 10000, 500, 80, 100, 9500)`,
        [clickId, merchantId],
      ),
    ).rejects.toThrow(/conversions_split_balance_check/);
  });

  it('is idempotent: a second migration run applies nothing', async () => {
    const second = await runMigrations(db);
    expect(second.applied).toEqual([]);
    expect(second.skipped.length).toBeGreaterThanOrEqual(2);
  });
});

async function seedMerchant(db: Database): Promise<string> {
  const { rows } = await db.query<{ id: string }>(
    `INSERT INTO merchants (name, platform, api_credentials_encrypted)
     VALUES ('Schema Test Merchant', 'shopify', '{"v":1,"alg":"aes-256-gcm","iv":"x","tag":"y","ct":"z"}'::jsonb)
     RETURNING id`,
  );
  const id = rows[0]?.id;
  if (!id) throw new Error('merchant seed failed');
  return id;
}
