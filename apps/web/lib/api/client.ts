import { AMCError, errorFromResponse } from '@amc/errors';
import { ensureAccessToken } from '../auth/supabase';
import { readSession } from '../auth/session';
import { getAppConfig, usesSupabaseAuth } from '../config';

/** An API failure. An AMCError, so `isAMCError` and the envelope helpers apply. */
export class ServiceError extends AMCError {
  constructor(status: number, code: string, message: string) {
    super(message, { status, code });
    this.name = 'ServiceError';
  }
}

interface FetchOptions extends RequestInit {
  idempotencyKey?: string;
}

export interface RuntimeSchema<T> {
  parse(input: unknown): T;
}

export async function apiFetch<T>(endpoint: string, options: FetchOptions = {}, schema?: RuntimeSchema<T>): Promise<T> {
  const headers = new Headers(options.headers || {});
  headers.set('Content-Type', 'application/json');
  if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey);

  const config = getAppConfig();
  if (usesSupabaseAuth(config)) {
    const token = await ensureAccessToken();
    if (!token) throw new ServiceError(401, 'AUTH_REQUIRED', 'Authentication required');
    headers.set('Authorization', `Bearer ${token}`);
    const tenantId = readSession()?.tenant_id;
    if (tenantId) headers.set('X-AMC-Tenant', tenantId);
  }

  const response = await fetch(`${config.apiBaseUrl}${endpoint}`, { ...options, headers });
  if (!response.ok) {
    let errorData: unknown = {};
    try { errorData = await response.json(); } catch { errorData = {}; }
    // Accepts FastAPI's { detail } and the AMC envelope { error: { code, message } }.
    const typed = errorFromResponse(response.status, errorData, response.statusText || 'API request failed');
    throw new ServiceError(response.status, typed.code, typed.message);
  }
  const data: unknown = await response.json();
  if (schema) return schema.parse(data);
  return data as T;
}
