"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { MissionControlProvider } from "../../components/mission-control/MissionControlProvider";
import { CommandInputPanel } from "../../components/mission-control/CommandInputPanel";
import { WorkflowMapPanel } from "../../components/mission-control/WorkflowMapPanel";
import { LiveStepProgressPanel } from "../../components/mission-control/LiveStepProgressPanel";
import { IntelligentResultsList } from "../../components/mission-control/IntelligentResultsList";
import { ApprovalInbox } from "../../components/mission-control/ApprovalInbox";
import { QualityScorePanel } from "../../components/mission-control/QualityScorePanel";
import { TrustStatusPanel } from "../../components/mission-control/TrustStatusPanel";
import { ConsequentialLifecyclePanel } from "../../components/mission-control/ConsequentialLifecyclePanel";
import { ArtifactPreviewPanel } from "../../components/mission-control/ArtifactPreviewPanel";
import { FileOrganizationPanel } from "../../components/mission-control/FileOrganizationPanel";
import { DesignStyleComposerPanel } from "../../components/mission-control/DesignStyleComposerPanel";
import { readSession } from "../../lib/auth/session";
import { signOut } from "../../lib/auth/supabase";

export default function MissionControlPage() {
  const router = useRouter();
  const productionAuth = process.env.NEXT_PUBLIC_AUTH_MODE === 'supabase';
  const [ready, setReady] = useState(!productionAuth);
  const [mode, setMode] = useState<'operations' | 'design'>('operations');

  useEffect(() => {
    if (!productionAuth) return;
    if (!readSession()) router.replace('/login');
    else setReady(true);
  }, [productionAuth, router]);

  if (!ready) return <main className="min-h-[100dvh] grid place-items-center text-sm text-zinc-500">Checking session…</main>;

  return (
    <main className="min-h-[100dvh] p-4 lg:p-6 flex flex-col gap-4 max-w-[1920px] mx-auto">
      <MissionControlProvider />
      <header className="flex flex-wrap justify-between items-center gap-x-4 gap-y-2 pb-2 border-b border-zinc-800/50">
        <div className="flex items-center gap-4 shrink-0">
          <h1 className="text-zinc-100 font-medium tracking-tight whitespace-nowrap">Mission Control</h1>
          <div role="group" aria-label="Mission Control mode" className="flex rounded-md border border-zinc-800 p-0.5 bg-zinc-900/60">
            {([["operations", "Operations"], ["design", "Design Mode"]] as const).map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={mode === value}
                onClick={() => setMode(value)}
                className={`text-xs px-2.5 py-1 rounded whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60 ${mode === value ? "bg-zinc-100 text-zinc-900" : "text-zinc-400 hover:text-zinc-100"}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-3 min-w-0">
          <QualityScorePanel />
          <TrustStatusPanel />
          <div className="h-6 w-px bg-zinc-800" />
          <ApprovalInbox />
          {productionAuth && <button type="button" onClick={() => { signOut(); router.replace('/login'); }} className="text-xs text-zinc-400 hover:text-zinc-100">Sign out</button>}
        </div>
      </header>
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 flex-1">
        <div className="lg:col-span-3 flex flex-col gap-4"><CommandInputPanel /><ConsequentialLifecyclePanel /></div>
        {mode === 'design' ? (
          <div className="lg:col-span-9 flex flex-col gap-4 min-h-0"><DesignStyleComposerPanel /></div>
        ) : (
          <>
        <div className="lg:col-span-5 flex flex-col gap-4">
          <div className="flex-1 bg-zinc-900/40 border border-zinc-800/60 rounded-xl overflow-hidden relative flex flex-col">
            <div className="p-3 border-b border-zinc-800/60 bg-zinc-900/80 backdrop-blur-sm z-10 flex justify-between items-center"><span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Topology Map</span></div>
            <WorkflowMapPanel />
          </div>
          <div className="h-48 shrink-0"><LiveStepProgressPanel /></div>
        </div>
        <div className="lg:col-span-4 flex flex-col gap-4"><IntelligentResultsList /><FileOrganizationPanel /><div className="flex-1 border border-zinc-800/60 rounded-xl overflow-hidden bg-zinc-900/40"><ArtifactPreviewPanel /></div></div>
          </>
        )}
      </div>
    </main>
  );
}
