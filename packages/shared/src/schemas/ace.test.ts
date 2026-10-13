import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { AceContractSchemas } from './ace';

interface Vector {
  model: keyof typeof AceContractSchemas;
  accept: boolean;
  input: Record<string, unknown>;
}
const vectors = JSON.parse(
  readFileSync(join(process.cwd(), 'ace-v100-contract-fixtures.json'), 'utf8')
) as { cases: Vector[] };

describe('ACE v100 cross-language strict wire conformance', () => {
  for (const [index, vector] of vectors.cases.entries()) {
    it(`${index} ${vector.model} accept=${vector.accept}`, () => {
      const schema = AceContractSchemas[vector.model];
      const parsed = schema.safeParse(vector.input);
      expect(parsed.success).toBe(vector.accept);
      if (parsed.success) {
        expect(schema.safeParse(JSON.parse(JSON.stringify(parsed.data))).success).toBe(true);
        expect(JSON.stringify(parsed.data)).not.toContain('untrusted_grant');
      }
    });
  }
});
