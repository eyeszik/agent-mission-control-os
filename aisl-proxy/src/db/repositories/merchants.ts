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
}

export interface Merchant {
  id: string;
  name: string;
  platform: MerchantPlatform;
  commissionRateBps: number;
  aislCutBps: number;
  createdAt: Date;
  credentials: MerchantCredentials;
}

export class MerchantRepository {
  constructor(
    private readonly db: Database,
    private readonly encryptionKey: string,
  ) {}

  async findById(id: string): Promise<Merchant | null> {
    const { rows } = await this.db.query<MerchantRow>(
      `SELECT id, name, platform, api_credentials_encrypted, commission_rate_bps, aisl_cut_bps, created_at
         FROM merchants WHERE id = $1`,
      [id],
    );
    const row = rows[0];
    return row ? this.hydrate(row) : null;
  }

  async listSearchable(limit = 25): Promise<Merchant[]> {
    const { rows } = await this.db.query<MerchantRow>(
      `SELECT id, name, platform, api_credentials_encrypted, commission_rate_bps, aisl_cut_bps, created_at
         FROM merchants
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
       RETURNING id, name, platform, api_credentials_encrypted, commission_rate_bps, aisl_cut_bps, created_at`,
      [input.name, input.credentials.platform, JSON.stringify(sealed), commissionRateBps, aislCutBps],
    );
    const row = rows[0];
    if (!row) {
      throw AislError.internal('merchant_insert_failed', 'merchant insert returned no row');
    }
    return this.hydrate(row);
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
    };
  }
}
