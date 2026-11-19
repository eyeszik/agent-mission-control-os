import { describe, expect, it } from 'vitest';
import { BrowserCapabilities, ExtractionResult } from '../src/schemas/browser';
describe('local browser trust boundary', () => {
  it('rejects an inconsistent public browsing capability', () => {
    expect(BrowserCapabilities.safeParse({ provider:'obscura', enabled:true, mode:'SUPPLIED_HTML_ONLY', public_browsing:true, max_input_bytes:16000 }).success).toBe(false);
  });
  it('rejects an extraction that upgrades supplied HTML to verified evidence', () => {
    expect(ExtractionResult.safeParse({ run_id:'fixture', status:'SUCCEEDED', replayed:false, content:{ markdown:'fixture', source_status:'VERIFIED', input_sha256:'fixture', output_sha256:'fixture' }, proof:{} }).success).toBe(false);
  });
});
