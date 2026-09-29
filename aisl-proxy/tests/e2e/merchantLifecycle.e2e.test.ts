import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { MerchantRepository } from '../../src/db/repositories/merchants.js';
import { AislError } from '../../src/lib/errors.js';
import { isSealedPayload } from '../../src/lib/crypto.js';
import { startHarness, type Harness } from '../helpers/harness.js';

let harness: Harness;
let merchants: MerchantRepository;

beforeAll(async () => {
  harness = await startHarness();
  merchants = harness.deps.repositories.merchants;
});

afterAll(async () => {
  await harness.close();
});

async function seedShopifyMerchant(name: string, token = 'shpstf_original') {
  return merchants.create({
    name,
    commissionRateBps: 500,
    aislCutBps: 80,
    credentials: {
      platform: 'shopify',
      store_domain: `${name.toLowerCase().replace(/\s+/g, '-')}.myshopify.com`,
      storefront_token: token,
      storefront_api_version: '2026-01',
      admin_token: 'shpat_original',
      admin_api_version: '2026-01',
    },
  });
}

describe('credential rotation', () => {
  it('replaces the sealed credentials and records when it happened', async () => {
    const merchant = await seedShopifyMerchant('Rotate Co');
    expect(merchant.credentialsRotatedAt).toBeNull();

    const rotated = await merchants.rotateCredentials(merchant.id, {
      platform: 'shopify',
      store_domain: 'rotate-co.myshopify.com',
      storefront_token: 'shpstf_rotated',
      storefront_api_version: '2026-01',
      admin_token: 'shpat_rotated',
      admin_api_version: '2026-01',
    });

    expect(rotated.credentials).toMatchObject({ storefront_token: 'shpstf_rotated' });
    expect(rotated.credentialsRotatedAt).toBeInstanceOf(Date);

    // A fresh read decrypts to the new value, not a cached old one.
    const reread = await merchants.findById(merchant.id);
    expect(reread?.credentials).toMatchObject({ storefront_token: 'shpstf_rotated' });
  });

  it('leaves no trace of the superseded token in the database', async () => {
    const merchant = await seedShopifyMerchant('Leak Co', 'shpstf_leaked_token');
    await merchants.rotateCredentials(merchant.id, {
      platform: 'shopify',
      store_domain: 'leak-co.myshopify.com',
      storefront_token: 'shpstf_replacement',
      storefront_api_version: '2026-01',
      admin_api_version: '2026-01',
    });

    const { rows } = await harness.db.query<{ api_credentials_encrypted: unknown }>(
      'SELECT api_credentials_encrypted FROM merchants WHERE id = $1',
      [merchant.id],
    );
    const stored = JSON.stringify(rows[0]?.api_credentials_encrypted);

    expect(isSealedPayload(rows[0]?.api_credentials_encrypted)).toBe(true);
    expect(stored).not.toContain('shpstf_leaked_token');
    expect(stored).not.toContain('shpstf_replacement');
  });

  it('refuses to change a merchant to a different platform', async () => {
    const merchant = await seedShopifyMerchant('Platform Co');

    await expect(
      merchants.rotateCredentials(merchant.id, {
        platform: 'woocommerce',
        base_url: 'https://platform-co.example',
        consumer_key: 'ck',
        consumer_secret: 'cs',
      }),
    ).rejects.toBeInstanceOf(AislError);
  });

  it('rejects rotation for a merchant that does not exist', async () => {
    await expect(
      merchants.rotateCredentials('018f4a1e-8e3b-7000-8432-1b1f9b3bffff', {
        platform: 'shopify',
        store_domain: 'nobody.myshopify.com',
        storefront_token: 'shpstf',
        storefront_api_version: '2026-01',
        admin_api_version: '2026-01',
      }),
    ).rejects.toBeInstanceOf(AislError);
  });
});

describe('merchant enable and disable', () => {
  it('drops a disabled merchant out of catalogue fan-out but keeps it addressable', async () => {
    const merchant = await seedShopifyMerchant('Closing Co');
    expect((await merchants.listSearchable(100)).map((m) => m.id)).toContain(merchant.id);

    const disabled = await merchants.setEnabled(merchant.id, false);
    expect(disabled.enabled).toBe(false);

    const searchable = await merchants.listSearchable(100);
    expect(searchable.map((m) => m.id)).not.toContain(merchant.id);

    // Still readable by id, so existing orders and ledger rows stay explicable.
    expect(await merchants.findById(merchant.id)).toMatchObject({ id: merchant.id, enabled: false });
    expect((await merchants.listAll()).map((m) => m.id)).toContain(merchant.id);
  });

  it('re-enables a merchant back into search', async () => {
    const merchant = await seedShopifyMerchant('Reopening Co');
    await merchants.setEnabled(merchant.id, false);
    const reenabled = await merchants.setEnabled(merchant.id, true);

    expect(reenabled.enabled).toBe(true);
    expect((await merchants.listSearchable(100)).map((m) => m.id)).toContain(merchant.id);
  });

  it('rejects enabling a merchant that does not exist', async () => {
    await expect(merchants.setEnabled('018f4a1e-8e3b-7000-8432-1b1f9b3beeee', true)).rejects.toBeInstanceOf(
      AislError,
    );
  });
});
