import { ValidationError } from '@amc/errors';
import { describe, expect, it } from 'vitest';
import { loadAppConfig, loadConfig, z } from '../src/index';

describe('@amc/config', () => {
  it('applies defaults and treats blank values as unset', () => {
    expect(loadAppConfig({ NEXT_PUBLIC_AUTH_MODE: '', NEXT_PUBLIC_API_BASE_URL: '  ' })).toEqual({
      apiBaseUrl: 'http://localhost:8000',
      authMode: 'local',
      supabase: null,
      logLevel: 'info',
    });
  });

  it('reads a supabase deployment', () => {
    const config = loadAppConfig({
      NEXT_PUBLIC_API_BASE_URL: 'https://api.example.test',
      NEXT_PUBLIC_AUTH_MODE: ' Supabase ',
      NEXT_PUBLIC_SUPABASE_URL: 'https://proj.supabase.co/',
      NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: 'pk_test',
      NEXT_PUBLIC_LOG_LEVEL: 'WARNING',
    });
    expect(config).toEqual({
      apiBaseUrl: 'https://api.example.test',
      authMode: 'supabase',
      supabase: { url: 'https://proj.supabase.co', publishableKey: 'pk_test' },
      logLevel: 'warn',
    });
    expect(loadAppConfig({ NEXT_PUBLIC_API_BASE_URL: '/api' }).apiBaseUrl).toBe('/api');
  });

  it('rejects invalid values without echoing them', () => {
    let thrown: unknown;
    try {
      loadAppConfig({ NEXT_PUBLIC_AUTH_MODE: 'open-sesame', NEXT_PUBLIC_API_BASE_URL: 'ftp://secret-host' });
    } catch (error) {
      thrown = error;
    }
    expect(thrown).toBeInstanceOf(ValidationError);
    const error = thrown as ValidationError;
    expect(error.code).toBe('CONFIG_INVALID');
    expect(error.message).toContain('NEXT_PUBLIC_AUTH_MODE');
    expect(error.message).not.toContain('open-sesame');
    expect(error.message).not.toContain('secret-host');
  });

  it('validates arbitrary schemas and ignores undeclared keys', () => {
    const schema = z.object({ PORT: z.coerce.number().int().positive() });
    expect(loadConfig(schema, { PORT: '8080', SECRET_TOKEN: 'x' })).toEqual({ PORT: 8080 });
    expect(() => loadConfig(schema, { PORT: '-1' })).toThrow(ValidationError);
  });
});
