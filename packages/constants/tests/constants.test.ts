import { describe, expect, it } from 'vitest';
import {
  AMC_APPROVER_ROLES,
  AMC_AUTH_MODES,
  AMC_DATABASE_BACKENDS,
  AMC_LOG_LEVELS,
  AUTH_MODE,
  TERMINAL_AGENCY_RUN_STATES,
  WEB_AUTH_MODES,
  isOneOf,
} from '../src/index';

describe('@amc/constants', () => {
  it('declares the backend vocabularies', () => {
    expect(AMC_AUTH_MODES).toEqual(['disabled', 'local', 'supabase']);
    expect(AMC_DATABASE_BACKENDS).toEqual(['sqlite', 'postgres']);
    expect(AMC_LOG_LEVELS).toEqual(['debug', 'info', 'warn', 'error']);
    expect(AMC_APPROVER_ROLES).toEqual(['reviewer', 'approver', 'admin', 'owner']);
  });

  it('keeps web auth modes a subset of backend auth modes', () => {
    for (const mode of WEB_AUTH_MODES) expect(AMC_AUTH_MODES).toContain(mode);
    expect(AUTH_MODE.supabase).toBe('supabase');
    expect(TERMINAL_AGENCY_RUN_STATES).toEqual(['completed', 'rejected', 'failed']);
  });

  it('narrows unknown values', () => {
    expect(isOneOf(AMC_DATABASE_BACKENDS, 'postgres')).toBe(true);
    expect(isOneOf(AMC_DATABASE_BACKENDS, 'mysql')).toBe(false);
    expect(isOneOf(AMC_DATABASE_BACKENDS, 1)).toBe(false);
  });
});
