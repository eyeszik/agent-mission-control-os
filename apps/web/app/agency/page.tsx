"use client";

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AgencyShell } from '../../components/agency/AgencyShell';
import { readSession } from '../../lib/auth/session';
import { usesSupabaseAuth } from '../../lib/config';

// Same session guard as Mission Control: in production auth mode an
// unauthenticated visitor is sent to /login; the API enforces it regardless.
export default function AgencyPage() {
  const router = useRouter();
  const productionAuth = usesSupabaseAuth();
  const [ready, setReady] = useState(!productionAuth);
  useEffect(() => {
    if (!productionAuth) return;
    if (!readSession()) router.replace('/login');
    else setReady(true);
  }, [productionAuth, router]);
  if (!ready) return <main className="grid min-h-[100dvh] place-items-center text-sm text-fg">Checking session…</main>;
  return <AgencyShell />;
}
