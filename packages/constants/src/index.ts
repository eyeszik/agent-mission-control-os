/**
 * Canonical AMC vocabularies for the TypeScript workspace.
 *
 * These mirror the Python backend's `services/langgraph/core/constants.py`.
 * The two stacks never import each other; a backend test checks that both
 * sides declare the same values.
 */

/** Environments with defined behaviour. Any other value is treated as non-production. */
export const AMC_ENVIRONMENTS = ['local', 'production'] as const;
export type AmcEnvironment = (typeof AMC_ENVIRONMENTS)[number];
export const ENVIRONMENT = { local: 'local', production: 'production' } as const satisfies Record<string, AmcEnvironment>;

/** Backend authentication modes (`AMC_AUTH_MODE`). `disabled` refuses every request. */
export const AMC_AUTH_MODES = ['disabled', 'local', 'supabase'] as const;
export type AmcAuthMode = (typeof AMC_AUTH_MODES)[number];
export const AUTH_MODE = { disabled: 'disabled', local: 'local', supabase: 'supabase' } as const satisfies Record<string, AmcAuthMode>;

/** Auth modes the web client can run in (`NEXT_PUBLIC_AUTH_MODE`). */
export const WEB_AUTH_MODES = ['local', 'supabase'] as const satisfies readonly AmcAuthMode[];
export type WebAuthMode = (typeof WEB_AUTH_MODES)[number];

/** Persistence backends (`AMC_DATABASE_BACKEND`). */
export const AMC_DATABASE_BACKENDS = ['sqlite', 'postgres'] as const;
export type AmcDatabaseBackend = (typeof AMC_DATABASE_BACKENDS)[number];
export const DATABASE_BACKEND = { sqlite: 'sqlite', postgres: 'postgres' } as const satisfies Record<string, AmcDatabaseBackend>;

/** Log levels, lowest to highest severity. */
export const AMC_LOG_LEVELS = ['debug', 'info', 'warn', 'error'] as const;
export type AmcLogLevel = (typeof AMC_LOG_LEVELS)[number];

/** Default roles that may decide an approval (backend `DEFAULT_APPROVER_ROLES`). */
export const AMC_APPROVER_ROLES = ['reviewer', 'approver', 'admin', 'owner'] as const;
export type AmcApproverRole = (typeof AMC_APPROVER_ROLES)[number];

/** Agency run lifecycle states (mirrors `AgencyRunStatusSchema` in @amc/shared). */
export const AMC_AGENCY_RUN_STATES = ['running', 'needs_approval', 'delivering', 'completed', 'rejected', 'failed'] as const;
export type AmcAgencyRunState = (typeof AMC_AGENCY_RUN_STATES)[number];
export const TERMINAL_AGENCY_RUN_STATES = ['completed', 'rejected', 'failed'] as const satisfies readonly AmcAgencyRunState[];

/** Narrow an unknown value to a member of a constant vocabulary. */
export function isOneOf<const T extends readonly string[]>(values: T, value: unknown): value is T[number] {
  return typeof value === 'string' && (values as readonly string[]).includes(value);
}
