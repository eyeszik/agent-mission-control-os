import { getAppConfig } from '../config';
import { clearSession, readSession, StoredSession, writeSession } from './session';

interface SupabaseTokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

function config() {
  const supabase = getAppConfig().supabase;
  if (!supabase) throw new Error('Supabase authentication is not configured');
  return { url: supabase.url, key: supabase.publishableKey };
}

function store(payload: SupabaseTokenResponse, tenantId?: string): StoredSession {
  // Only store access_token and metadata - NOT refresh_token
  // Refresh tokens should be handled server-side via httpOnly cookies
  const session: StoredSession = {
    access_token: payload.access_token,
    expires_at: Math.floor(Date.now() / 1000) + payload.expires_in,
    tenant_id: tenantId,
  };
  writeSession(session);
  return session;
}

export async function signInWithPassword(email: string, password: string): Promise<StoredSession> {
  const { url, key } = config();
  const response = await fetch(`${url}/auth/v1/token?grant_type=password`, {
    method: 'POST',
    headers: { apikey: key, 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) throw new Error('Unable to sign in');
  return store((await response.json()) as SupabaseTokenResponse);
}

export async function signUp(email: string, password: string): Promise<void> {
  const { url, key } = config();
  const response = await fetch(`${url}/auth/v1/signup`, {
    method: 'POST',
    headers: { apikey: key, 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) throw new Error('Unable to create account');
}

export async function ensureAccessToken(): Promise<string | null> {
  const session = readSession();
  if (!session) return null;
  
  // Check if access token is still valid (with 60s buffer)
  if (session.expires_at - Math.floor(Date.now() / 1000) > 60) {
    return session.access_token;
  }
  
  // Access token expired - clear session and require re-authentication
  // This is more secure than storing refresh tokens in sessionStorage
  clearSession();
  return null;
}

export function signOut(): void {
  clearSession();
}
