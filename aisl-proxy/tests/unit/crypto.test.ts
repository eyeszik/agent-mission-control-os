import { describe, expect, it } from 'vitest';
import { attributionSignature, isSealedPayload, open, safeEqual, seal } from '../../src/lib/crypto.js';
import { newClickId, isUuidV7, uuidV7Timestamp } from '../../src/lib/ids.js';

const SALT = 'aisl-test-attribution-salt-0123456789abcdef';
const KEY = Buffer.alloc(32, 7).toString('base64');

describe('attributionSignature', () => {
  it('is deterministic for the same binding', () => {
    const params = { salt: SALT, clickId: 'c', agentId: 'a', merchantId: 'm' };
    expect(attributionSignature(params)).toBe(attributionSignature(params));
  });

  it('changes when any bound field changes', () => {
    const base = attributionSignature({ salt: SALT, clickId: 'c', agentId: 'a', merchantId: 'm' });
    expect(attributionSignature({ salt: SALT, clickId: 'c2', agentId: 'a', merchantId: 'm' })).not.toBe(base);
    expect(attributionSignature({ salt: SALT, clickId: 'c', agentId: 'a2', merchantId: 'm' })).not.toBe(base);
    expect(attributionSignature({ salt: SALT, clickId: 'c', agentId: 'a', merchantId: 'm2' })).not.toBe(base);
    expect(attributionSignature({ salt: `${SALT}x`, clickId: 'c', agentId: 'a', merchantId: 'm' })).not.toBe(base);
  });

  it('is not confusable by shifting characters across field boundaries', () => {
    // Without a separator, ("ab","c") and ("a","bc") would hash identically.
    const left = attributionSignature({ salt: SALT, clickId: 'x', agentId: 'ab', merchantId: 'c' });
    const right = attributionSignature({ salt: SALT, clickId: 'x', agentId: 'a', merchantId: 'bc' });
    expect(left).not.toBe(right);
  });
});

describe('safeEqual', () => {
  it('compares equal and unequal values without throwing on length mismatch', () => {
    expect(safeEqual('abc', 'abc')).toBe(true);
    expect(safeEqual('abc', 'abd')).toBe(false);
    expect(safeEqual('abc', 'abcdef')).toBe(false);
    expect(safeEqual('', '')).toBe(true);
  });
});

describe('credential sealing', () => {
  it('round-trips a credential blob', () => {
    const plaintext = JSON.stringify({ platform: 'shopify', storefront_token: 'shpstf_secret' });
    const sealed = seal(plaintext, KEY);

    expect(isSealedPayload(sealed)).toBe(true);
    expect(JSON.stringify(sealed)).not.toContain('shpstf_secret');
    expect(open(sealed, KEY)).toBe(plaintext);
  });

  it('produces a different ciphertext each time for the same plaintext', () => {
    const a = seal('secret', KEY);
    const b = seal('secret', KEY);
    expect(a.ct === b.ct && a.iv === b.iv).toBe(false);
  });

  it('refuses to open a tampered payload', () => {
    const sealed = seal('secret', KEY);
    const tampered = { ...sealed, ct: Buffer.from('tampered').toString('base64') };
    expect(() => open(tampered, KEY)).toThrow();
  });

  it('refuses a key of the wrong length', () => {
    expect(() => seal('secret', Buffer.alloc(16, 1).toString('base64'))).toThrow(/32 bytes/);
  });
});

describe('click identifiers', () => {
  it('mints UUIDv7 values', () => {
    const id = newClickId();
    expect(isUuidV7(id)).toBe(true);
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });

  it('is monotonically ordered as a string', () => {
    const ids = Array.from({ length: 200 }, () => newClickId());
    expect([...ids].sort()).toEqual(ids);
  });

  it('carries a recoverable creation timestamp', () => {
    const before = Date.now();
    const id = newClickId();
    const embedded = uuidV7Timestamp(id).getTime();
    expect(embedded).toBeGreaterThanOrEqual(before - 1_000);
    expect(embedded).toBeLessThanOrEqual(Date.now() + 1_000);
  });
});
