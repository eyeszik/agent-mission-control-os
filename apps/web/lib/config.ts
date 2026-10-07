import { loadAppConfig, type AppConfig } from '@amc/config';
import { AUTH_MODE } from '@amc/constants';

/**
 * Runtime configuration for the web app, validated by @amc/config.
 *
 * Each variable is read as a literal `process.env.NEXT_PUBLIC_*` expression:
 * Next.js only inlines public env values into browser bundles at literal
 * references, so passing `process.env` itself would yield an empty object in
 * the browser. Parsing is cheap and done per call, so tests that stub env
 * values see them immediately.
 */
export function getAppConfig(): AppConfig {
  return loadAppConfig({
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
    NEXT_PUBLIC_AUTH_MODE: process.env.NEXT_PUBLIC_AUTH_MODE,
    NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL,
    NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
    NEXT_PUBLIC_LOG_LEVEL: process.env.NEXT_PUBLIC_LOG_LEVEL,
  });
}

export function usesSupabaseAuth(config: AppConfig = getAppConfig()): boolean {
  return config.authMode === AUTH_MODE.supabase;
}
