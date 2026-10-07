/**
 * Zod-validated configuration loaders.
 *
 * Loaders take an explicit env record instead of reading `process.env`
 * themselves: Next.js inlines `NEXT_PUBLIC_*` values into browser code only
 * where they are read as literal `process.env.NEXT_PUBLIC_X`, so the app
 * builds the record and passes it in. Empty strings count as unset.
 *
 * Validation failures throw `ValidationError` listing the failing keys and
 * messages, never the values (an env value may be a secret).
 */

import { AMC_LOG_LEVELS, WEB_AUTH_MODES, type AmcLogLevel, type WebAuthMode } from '@amc/constants';
import { ValidationError } from '@amc/errors';
import { z } from 'zod';

export type EnvRecord = Readonly<Record<string, string | undefined>>;

const blankToUndefined = (value: unknown) => (typeof value === 'string' && value.trim() === '' ? undefined : value);
const lowercase = (value: unknown) => (typeof value === 'string' ? value.trim().toLowerCase() : value);
const optionalString = <T extends z.ZodTypeAny>(schema: T) => z.preprocess(blankToUndefined, schema);

/** An absolute http(s) URL, or a same-origin path such as `/api`. */
const baseUrl = z
  .string()
  .trim()
  .refine((value) => value.startsWith('/') || /^https?:\/\/[^\s/]+/i.test(value), {
    message: 'must be an absolute http(s) URL or a path starting with /',
  });

/** Describe an issue without the received value (zod's own messages can echo it). */
function describeIssue(issue: z.ZodIssue): string {
  switch (issue.code) {
    case z.ZodIssueCode.invalid_enum_value:
      return `must be one of ${issue.options.join(', ')}`;
    case z.ZodIssueCode.invalid_type:
      return issue.received === 'undefined' ? 'is required' : `must be a ${issue.expected}`;
    case z.ZodIssueCode.invalid_string:
      return `is not a valid ${typeof issue.validation === 'string' ? issue.validation : 'string'}`;
    case z.ZodIssueCode.too_small:
    case z.ZodIssueCode.too_big:
    case z.ZodIssueCode.custom:
      return issue.message;
    default:
      return 'is invalid';
  }
}

/**
 * Parse `env` with `schema`. Only keys the schema declares are read, so
 * unrelated (possibly secret) variables are never touched.
 */
export function loadConfig<S extends z.ZodTypeAny>(schema: S, env: EnvRecord): z.output<S> {
  const result = schema.safeParse(env);
  if (!result.success) {
    const issues = result.error.issues.map((issue) => ({ key: issue.path.join('.') || '(root)', message: describeIssue(issue) }));
    throw new ValidationError(
      `Invalid configuration: ${issues.map((i) => `${i.key} ${i.message}`).join('; ')}`,
      { code: 'CONFIG_INVALID', details: { issues } },
    );
  }
  return result.data;
}

export const AppEnvSchema = z.object({
  NEXT_PUBLIC_API_BASE_URL: optionalString(baseUrl.default('http://localhost:8000')),
  NEXT_PUBLIC_AUTH_MODE: optionalString(z.preprocess(lowercase, z.enum(WEB_AUTH_MODES)).default('local')),
  NEXT_PUBLIC_SUPABASE_URL: optionalString(z.string().trim().url().optional()),
  NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: optionalString(z.string().trim().min(1).optional()),
  NEXT_PUBLIC_LOG_LEVEL: optionalString(
    z.preprocess((v) => (typeof v === 'string' ? v.trim().toLowerCase().replace(/^warning$/, 'warn') : v), z.enum(AMC_LOG_LEVELS)).default('info'),
  ),
});
export type AppEnv = z.output<typeof AppEnvSchema>;

export interface AppConfig {
  apiBaseUrl: string;
  authMode: WebAuthMode;
  supabase: { url: string; publishableKey: string } | null;
  logLevel: AmcLogLevel;
}

/**
 * Typed web-app configuration. Supabase credentials are optional here: they
 * are only required when a sign-in is actually attempted, so a misconfigured
 * deployment still renders and reports the problem at that point.
 */
export function loadAppConfig(env: EnvRecord): AppConfig {
  const parsed = loadConfig(AppEnvSchema, env);
  const url = parsed.NEXT_PUBLIC_SUPABASE_URL;
  const key = parsed.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  return {
    apiBaseUrl: parsed.NEXT_PUBLIC_API_BASE_URL,
    authMode: parsed.NEXT_PUBLIC_AUTH_MODE,
    supabase: url && key ? { url: url.replace(/\/$/, ''), publishableKey: key } : null,
    logLevel: parsed.NEXT_PUBLIC_LOG_LEVEL,
  };
}

export { z };
