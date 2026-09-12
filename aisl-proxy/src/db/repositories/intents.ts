import type { Database } from '../pool.js';

export interface IntentBinding {
  clickId: string;
  agentId: string;
  subId1: string | null;
  subId2: string | null;
  merchantId: string;
  productId: string;
  variantId: string;
  quotedPriceCents: number;
  currency: string;
  query: string;
  expiresAt: Date;
  createdAt: Date;
}

interface IntentJoinRow {
  click_id: string;
  agent_id: string;
  sub_id_1: string | null;
  sub_id_2: string | null;
  merchant_id: string;
  created_at: Date;
  product_id: string;
  variant_id: string;
  quoted_price_cents: string | number;
  currency: string;
  query: string;
  expires_at: Date;
}

export class IntentRepository {
  constructor(private readonly db: Database) {}

  /**
   * Persist a batch of minted click tokens in one transaction. Either every
   * product in a search response is attributable or none of them are — a
   * partially written batch would hand the agent tokens that fail at checkout.
   */
  async recordBatch(bindings: readonly IntentBinding[]): Promise<void> {
    if (bindings.length === 0) return;

    await this.db.transaction(async (tx) => {
      for (const binding of bindings) {
        await tx.query(
          `INSERT INTO agent_intents (click_id, agent_id, sub_id_1, sub_id_2, merchant_id, created_at)
           VALUES ($1, $2, $3, $4, $5, $6)`,
          [
            binding.clickId,
            binding.agentId,
            binding.subId1,
            binding.subId2,
            binding.merchantId,
            binding.createdAt,
          ],
        );
        await tx.query(
          `INSERT INTO agent_intent_bindings
             (click_id, product_id, variant_id, quoted_price_cents, currency, query, expires_at, created_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
          [
            binding.clickId,
            binding.productId,
            binding.variantId,
            binding.quotedPriceCents,
            binding.currency,
            binding.query,
            binding.expiresAt,
            binding.createdAt,
          ],
        );
      }
    });
  }

  async findByClickId(clickId: string): Promise<IntentBinding | null> {
    const { rows } = await this.db.query<IntentJoinRow>(
      `SELECT i.click_id, i.agent_id, i.sub_id_1, i.sub_id_2, i.merchant_id, i.created_at,
              b.product_id, b.variant_id, b.quoted_price_cents, b.currency, b.query, b.expires_at
         FROM agent_intents i
         JOIN agent_intent_bindings b ON b.click_id = i.click_id
        WHERE i.click_id = $1`,
      [clickId],
    );
    const row = rows[0];
    if (!row) return null;

    return {
      clickId: row.click_id,
      agentId: row.agent_id,
      subId1: row.sub_id_1,
      subId2: row.sub_id_2,
      merchantId: row.merchant_id,
      productId: row.product_id,
      variantId: row.variant_id,
      quotedPriceCents: Number(row.quoted_price_cents),
      currency: row.currency,
      query: row.query,
      expiresAt: row.expires_at,
      createdAt: row.created_at,
    };
  }
}
