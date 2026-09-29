import { z } from 'zod';
import type { Database } from '../pool.js';
import { isSealedPayload, open, seal } from '../../lib/crypto.js';
import { AislError } from '../../lib/errors.js';

export const MERCHANT_PLATFORMS = ['shopify', 'woocommerce', 'stripe_custom'] as const;
export type MerchantPlatform = (typeof MERCHANT_PLATFORMS)[number];

export const ShopifyCredentialsSchema = z.object({
  platform: z.literal('shopify'),
  store_domain: z.string().min(1),
  storefront_token: z.string().min(1),
  storefront_api_version: z.string().default('2026-01'),
  admin_token: z.string().optional(),
  admin_api_version: z.string().default('2026-01'),
  stripe_account_id: z.string().optional(),
});

export const WooCommerceCredentialsSchema = z.object({
  platform: z.literal('woocommerce'),
  base_url: z.url(),
  consumer_key: z.string().min(1),
  consumer_secret: z.string().min(1),
  stripe_account_id: z.string().optional(),
});

export const StripeCustomCredentialsSchema = z.object({
  platform: z.literal('stripe_custom'),
  stripe_account_id: z.string().min(1),
  catalog_feed_url: z.url().optional(),
});

export const MerchantCredentialsSchema = z.discriminatedUnion('platform', [
  ShopifyCredentialsSchema,
  WooCommerceCredentialsSchema,
  StripeCustomCredentialsSchema,
]);

export type MerchantCredentials = z.infer<typeof MerchantCredentialsSchema>;

export interface MerchantRow {
  id: string;
  name: string;
  platform: string;
  api_credentials_encrypted: unknown;
  commission_rate_bps: number;
  aisl_cut_bps: number;
  created_at: Date;
  enabled?: boolean;
  credentials_rotated_at?: Date | null;
}

export interface Merchant {
  id: string;
  name: string;
  platform: MerchantPlatform;
  commissionRateBps: number;
  aislCutBps: number;
  createdAt: Date;
  credentials: MerchantCredentials;
  /** A disabled merchant keeps its ledger history but leaves catalogue fan-out. */
  enabled: boolean;
  credentialsRotatedAt: Date | null;
}

export class MerchantRepository {
  constructor(
    private readonly db: Database,
    private readonly encryptionKey: string,
  ) {}

  async findById(id: string): Promise<Merchant | null> {
    const { rows } = await this.db.query<MerchantRow>(
      `SELECT id, name, platform, api_credentials_encrypted, commission_rate_bps, aisl_cut_bps, created_at, enabled, credentials_rotated_at
         FROM merchants WHERE id = $1`,
      [id],
    );
    const row = rows[0];
    return row ? this.hydrate(row) : null;
  }

  async listSearchable(limit = 25): Promise<Merchant[]> {
    const { rows } = await this.db.query<MerchantRow>(
      `SELECT id, name, platform, api_credentials_encrypted, commission_rate_bps, aisl_cut_bps, created_at, enabled, credentials_rotated_at
         FROM merchants
        WHERE enabled
        ORDER BY created_at ASC
        LIMIT $1`,
      [limit],
    );
    return rows.map((row) => this.hydrate(row));
  }

  async create(input: {
    name: string;
    credentials: MerchantCredentials;
    commissionRateBps?: number;
    aislCutBps?: number;
  }): Promise<Merchant> {
    const commissionRateBps = input.commissionRateBps ?? 500;
    const aislCutBps = input.aislCutBps ?? 80;
    if (aislCutBps > commissionRateBps) {
      throw AislError.badRequest(
        'invalid_commission_split',
        'aisl_cut_bps must not exceed commission_rate_bps',
        'aisl_cut_bps',
      );
    }

    const sealed = seal(JSON.stringify(input.credentials), this.encryptionKey);
    const { rows } = await this.db.query<MerchantRow>(
      `INSERT INTO merchants (name, platform, api_credentials_encrypted, commission_rate_bps, aisl_cut_bps)
       VALUES ($1, $2, $3, $4, $5)
       RETURNING id, name, platform, api_credentials_encrypted, commission_rate_bps, aisl_cut_bps, created_at, enabled, credentials_rotated_at`,
      [input.name, input.credentials.platform, JSON.stringify(sealed), commissionRateBps, aislCutBps],
    );
    const row = rows[0];
    if (!row) {
      throw AislError.internal('merchant_insert_failed', 'merchant insert returned no row');
    }
    return this.hydrate(row);
  }

  /**
   * Re-seal a merchant's API credentials under a new secret.
   *
   * The platform may not change: conversions, ledger entries and connector
   * routing are all keyed off it, so a platform switch is a new merchant, not
   * an edit. The previous ciphertext is overwritten rather than archived — a
   * rotated-away token should stop existing here.
   */
  async rotateCredentials(merchantId: string, credentials: MerchantCredentials): Promise<Merchant> {
    const existing = await this.findById(merchantId);
    if (!existing) {
      throw AislError.notFound('merchant_not_found', `merchant ${merchantId} does not exist`, 'merchant_id');
    }
    if (existing.platform !== credentials.platform) {
      throw AislError.badRequest(
        'merchant_platform_immutable',
        `merchant ${merchantId} is a ${existing.platform} merchant; credentials for ${credentials.platform} cannot replace them`,
        'platform',
      );
    }

    const sealed = seal(JSON.stringify(credentials), this.encryptionKey);
    const { rows } = await this.db.query<MerchantRow>(
      `UPDATE merchants
          SET api_credentials_encrypted = $2,
              credentials_rotated_at = NOW(),
              updated_at = NOW()
        WHERE id = $1
        RETURNING id, name, platform, api_credentials_encrypted, commission_rate_bps, aisl_cut_bps, created_at, enabled, credentials_rotated_at`,
      [merchantId, JSON.stringify(sealed)],
    );
    const row = rows[0];
    if (!row) {
      throw AislError.internal('merchant_rotate_failed', 'credential rotation returned no row');
    }
    return this.hydrate(row);
  }

  /** Take a merchant out of (or back into) catalogue fan-out without losing its history. */
  async setEnabled(merchantId: string, enabled: boolean): Promise<Merchant> {
    const { rows } = await this.db.query<MerchantRow>(
      `UPDATE merchants SET enabled = $2, updated_at = NOW() WHERE id = $1 RETURNING id, name, platform, api_credentials_encrypted, commission_rate_bps, aisl_cut_bps, created_at, enabled, credentials_rotated_at`,
      [merchantId, enabled],
    );
    const row = rows[0];
    if (!row) {
      throw AislError.notFound('merchant_not_found', `merchant ${merchantId} does not exist`, 'merchant_id');
    }
    return this.hydrate(row);
  }

  /** Every merchant, disabled ones included — for operator tooling, not search. */
  async listAll(limit = 100): Promise<Merchant[]> {
    const { rows } = await this.db.query<MerchantRow>(
      `SELECT id, name, platform, api_credentials_encrypted, commission_rate_bps, aisl_cut_bps, created_at, enabled, credentials_rotated_at FROM merchants ORDER BY created_at ASC LIMIT $1`,
      [limit],
    );
    return rows.map((row) => this.hydrate(row));
  }

  private hydrate(row: MerchantRow): Merchant {
    const stored = row.api_credentials_encrypted;
    if (!isSealedPayload(stored)) {
      throw AislError.internal(
        'merchant_credentials_corrupt',
        `merchant ${row.id} credentials are not a sealed AES-256-GCM envelope`,
      );
    }

    let credentials: MerchantCredentials;
    try {
      credentials = MerchantCredentialsSchema.parse(JSON.parse(open(stored, this.encryptionKey)));
    } catch (error) {
      throw AislError.internal(
        'merchant_credentials_unreadable',
        `merchant ${row.id} credentials failed to decrypt or validate`,
        error,
      );
    }

    if (credentials.platform !== row.platform) {
      throw AislError.internal(
        'merchant_platform_mismatch',
        `merchant ${row.id} platform column (${row.platform}) disagrees with sealed credentials (${credentials.platform})`,
      );
    }

    return {
      id: row.id,
      name: row.name,
      platform: credentials.platform,
      commissionRateBps: row.commission_rate_bps,
      aislCutBps: row.aisl_cut_bps,
      createdAt: row.created_at,
      credentials,
      enabled: row.enabled ?? true,
      credentialsRotatedAt: row.credentials_rotated_at ?? null,
    };
  }
}
