import { describe, it, expect } from 'vitest';
import { generateIdempotencyKey } from '../lib/utils/idempotency';

const UUID_V4_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

describe('Idempotency Key Generator', () => {
  it('should generate valid UUID v4 formats', () => {
    const key = generateIdempotencyKey();
    expect(key).toMatch(UUID_V4_RE);
  });

  it('should generate unique keys across successive calls', () => {
    const keys = new Set(Array.from({ length: 1000 }, () => generateIdempotencyKey()));
    expect(keys.size).toBe(1000);
  });
});
