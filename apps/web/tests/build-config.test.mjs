import { createHash } from 'node:crypto';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { validateBuild } from '../scripts/check-build.mjs';

afterEach(() => vi.unstubAllEnvs());
describe('frontend build configuration boundary', () => {
  it('refuses mismatched API, auth mode and Supabase bindings before startup', () => {
    const directory=mkdtempSync(resolve(tmpdir(),'amc-build-fixture-'));
    vi.stubEnv('NEXT_PUBLIC_API_BASE_URL','http://127.0.0.1:8000');
    vi.stubEnv('NEXT_PUBLIC_AUTH_MODE','local');
    vi.stubEnv('NEXT_PUBLIC_SUPABASE_URL','');
    vi.stubEnv('NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY','');
    vi.stubEnv('NEXT_PUBLIC_LOG_LEVEL','info');
    const config={apiBaseUrl:'http://127.0.0.1:8000',authMode:'local',supabase:null,logLevel:'info'};
    const fingerprint=createHash('sha256').update(JSON.stringify(config)).digest('hex');
    try {
      writeFileSync(resolve(directory,'BUILD_ID'),'fictional-build');
      writeFileSync(resolve(directory,'amc-config.json'),JSON.stringify({schema_version:'amc-web-build/v1',apiBaseUrl:config.apiBaseUrl,authMode:'local',fingerprint}));
      expect(() => validateBuild(directory)).not.toThrow();
      vi.stubEnv('NEXT_PUBLIC_API_BASE_URL','http://127.0.0.1:8100');
      expect(() => validateBuild(directory)).toThrow('BUILD_CONFIGURATION_MISMATCH');
      vi.stubEnv('NEXT_PUBLIC_API_BASE_URL',config.apiBaseUrl);
      vi.stubEnv('NEXT_PUBLIC_AUTH_MODE','supabase');
      expect(() => validateBuild(directory)).toThrow('BUILD_CONFIGURATION_MISMATCH');
      vi.stubEnv('NEXT_PUBLIC_AUTH_MODE','local');
      vi.stubEnv('NEXT_PUBLIC_SUPABASE_URL','https://fixture.supabase.co');
      vi.stubEnv('NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY','fictional-public-key');
      expect(() => validateBuild(directory)).toThrow('BUILD_CONFIGURATION_MISMATCH');
    } finally { rmSync(directory,{recursive:true,force:true}); }
  });
});
