export interface StoredSession {
  access_token: string;
  refresh_token: string;
  expires_at: number;
  tenant_id?: string;
}

const SESSION_KEY = 'amc.supabase.session';

export function readSession(): StoredSession | null {
  if (typeof window === 'undefined') return null;
  const raw = window.sessionStorage.getItem(SESSION_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as StoredSession;
  } catch {
    window.sessionStorage.removeItem(SESSION_KEY);
    return null;
  }
}

export function writeSession(session: StoredSession): void {
  window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export function clearSession(): void {
  if (typeof window !== 'undefined') window.sessionStorage.removeItem(SESSION_KEY);
}
