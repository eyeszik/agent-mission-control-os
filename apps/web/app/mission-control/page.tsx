"use client";

import { MissionControlProvider } from "../../components/mission-control/MissionControlProvider";
import { CommandInputPanel } from "../../components/mission-control/CommandInputPanel";
import { WorkflowMapPanel } from "../../components/mission-control/WorkflowMapPanel";
import { LiveStepProgressPanel } from "../../components/mission-control/LiveStepProgressPanel";
import { IntelligentResultsList } from "../../components/mission-control/IntelligentResultsList";
import { ApprovalInbox } from "../../components/mission-control/ApprovalInbox";
import { QualityScorePanel } from "../../components/mission-control/QualityScorePanel";
import { FileOrganizationPanel } from "../../components/mission-control/FileOrganizationPanel";
import { ArtifactPreviewPanel } from "../../components/mission-control/ArtifactPreviewPanel";

export default function MissionControlPage() {
  return (
    <main className="min-h-[100dvh] p-4 lg:p-6 flex flex-col gap-4 max-w-[1920px] mx-auto">
      <MissionControlProvider />
      {/* Top App Bar Area */}
        <header className="flex justify-between items-center pb-2 border-b border-zinc-800/50">
          <h1 className="text-zinc-100 font-medium tracking-tight">Mission Control</h1>
          <div className="flex items-center gap-3">
            <QualityScorePanel />
            <div className="h-6 w-px bg-zinc-800" />
            <ApprovalInbox />
          </div>
        </header>

        {/* Asymmetric Bento 2.0 Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 flex-1">
          
          {/* Left Column: Command & Context (Span 3) */}
          <div className="lg:col-span-3 flex flex-col gap-4">
            <CommandInputPanel />
            <FileOrganizationPanel />
          </div>

          {/* Center Column: Live Progress & Map (Span 5) */}
          <div className="lg:col-span-5 flex flex-col gap-4">
            <div className="flex-1 bg-zinc-900/40 border border-zinc-800/60 rounded-xl overflow-hidden relative flex flex-col">
              <div className="p-3 border-b border-zinc-800/60 bg-zinc-900/80 backdrop-blur-sm z-10 flex justify-between items-center">
                <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Topology Map</span>
              </div>
              <WorkflowMapPanel />
            </div>
            <div className="h-48 shrink-0">
              <LiveStepProgressPanel />
            </div>
          </div>

          {/* Right Column: Output & Artifacts (Span 4) */}
          <div className="lg:col-span-4 flex flex-col gap-4">
            <IntelligentResultsList />
            <div className="flex-1 border border-zinc-800/60 rounded-xl overflow-hidden bg-zinc-900/40">
              <ArtifactPreviewPanel />
            </div>
          </div>

          </div>
          </main>
          );
          }
