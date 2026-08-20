import { clearSession, readSession, StoredSession, writeSession } from './session';

interface SupabaseTokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

function config() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !key) throw new Error('Supabase authentication is not configured');
  return { url: url.replace(/\/$/, ''), key };
}

function store(payload: SupabaseTokenResponse, tenantId?: string): StoredSession {
  const session: StoredSession = {
    access_token: payload.access_token,
    refresh_token: payload.refresh_token,
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
  if (session.expires_at - Math.floor(Date.now() / 1000) > 60) return session.access_token;
  const { url, key } = config();
  const response = await fetch(`${url}/auth/v1/token?grant_type=refresh_token`, {
    method: 'POST',
    headers: { apikey: key, 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: session.refresh_token }),
  });
  if (!response.ok) {
    clearSession();
    return null;
  }
  return store((await response.json()) as SupabaseTokenResponse, session.tenant_id).access_token;
}

export function signOut(): void {
  clearSession();
}
