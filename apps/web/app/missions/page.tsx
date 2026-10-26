"use client";

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AgencyShell } from '../../components/agency/AgencyShell';
import { readSession } from '../../lib/auth/session';
import { usesSupabaseAuth } from '../../lib/config';

// Direct link to the Mission Council section of the Agency OS shell, with the
// same session guard as /agency; the API enforces auth regardless.
export default function MissionsPage() {
  const router = useRouter();
  const productionAuth = usesSupabaseAuth();
  const [ready, setReady] = useState(!productionAuth);
  useEffect(() => {
    if (!productionAuth) return;
    if (!readSession()) router.replace('/login');
    else setReady(true);
  }, [productionAuth, router]);
  if (!ready) return <main className="grid min-h-[100dvh] place-items-center text-sm text-fg">Checking session…</main>;
  return <AgencyShell initialSection="council" />;
}
