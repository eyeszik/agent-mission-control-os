"use client";

import { FormEvent, useState } from 'react';
import { signInWithPassword, signUp } from '../../lib/auth/supabase';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function login(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      await signInWithPassword(email, password);
      window.location.assign('/mission-control');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to sign in');
    } finally {
      setBusy(false);
    }
  }

  async function createAccount() {
    setBusy(true);
    setMessage(null);
    try {
      await signUp(email, password);
      setMessage('Account created. Complete any email verification, then sign in. Access remains blocked until an administrator assigns a tenant membership.');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Unable to create account');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-[100dvh] grid place-items-center p-6">
      <form onSubmit={login} className="w-full max-w-sm rounded-xl border border-zinc-800 bg-zinc-900/60 p-6 space-y-4">
        <div><h1 className="text-lg font-medium text-zinc-100">Agent Mission Control</h1><p className="text-sm text-zinc-500">Production sign in</p></div>
        <label className="block text-sm text-zinc-400">Email<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className="mt-1 w-full rounded-md border border-zinc-700 bg-zinc-950 p-2 text-zinc-100" /></label>
        <label className="block text-sm text-zinc-400">Password<input type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1 w-full rounded-md border border-zinc-700 bg-zinc-950 p-2 text-zinc-100" /></label>
        {message && <p role="status" className="text-xs text-zinc-400">{message}</p>}
        <button disabled={busy} type="submit" className="w-full rounded-md bg-zinc-100 p-2 text-sm font-medium text-zinc-900 disabled:opacity-50">{busy ? 'Working…' : 'Sign in'}</button>
        <button disabled={busy || !email || password.length < 8} type="button" onClick={createAccount} className="w-full rounded-md border border-zinc-700 p-2 text-sm text-zinc-300 disabled:opacity-50">Create account</button>
      </form>
    </main>
  );
}
