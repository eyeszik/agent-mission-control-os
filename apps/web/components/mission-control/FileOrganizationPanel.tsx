"use client";

import { useEffect, useState } from "react";
import { getAgencyRun } from "../../lib/api/agency";
import { useRunStore } from "../../lib/stores/runStore";

type WorkspaceExport = {
  root_folder: string;
  business_folder: string;
  branding_folder: string;
  design_system_folder: string;
  rendered_assets_folder: string;
  files_written: string[];
};

export function FileOrganizationPanel() {
  const activeRunId = useRunStore((state) => state.activeRunId);
  const [workspaceExport, setWorkspaceExport] = useState<WorkspaceExport | null>(null);

  useEffect(() => {
    if (!activeRunId) {
      setWorkspaceExport(null);
      return;
    }
    let cancelled = false;
    getAgencyRun(activeRunId)
      .then((run) => {
        if (!cancelled) {
          setWorkspaceExport((run.workspace_export as WorkspaceExport | null | undefined) ?? null);
        }
      })
      .catch(() => {
        if (!cancelled) setWorkspaceExport(null);
      });
    return () => {
      cancelled = true;
    };
  }, [activeRunId]);

  return (
    <div className="flex-1 bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-4 flex flex-col gap-3 min-h-[300px]">
      <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Context Tree</span>
      {!workspaceExport ? (
        <div className="flex-1 border border-zinc-800/40 rounded-lg p-3 text-xs text-zinc-600 flex items-center justify-center">
          Idea workspace appears here after a run compiles.
        </div>
      ) : (
        <div className="flex-1 border border-zinc-800/40 rounded-lg p-3 flex flex-col gap-2 text-xs text-zinc-300 overflow-auto">
          <div>
            <div className="text-zinc-500">root</div>
            <div className="font-mono break-all">{workspaceExport.root_folder}</div>
          </div>
          <div className="pl-3">
            <div className="text-zinc-500">business</div>
            <div className="font-mono break-all">{workspaceExport.business_folder}</div>
          </div>
          <div className="pl-3">
            <div className="text-zinc-500">branding</div>
            <div className="font-mono break-all">{workspaceExport.branding_folder}</div>
          </div>
          <div className="pl-6">
            <div className="text-zinc-500">design-system</div>
            <div className="font-mono break-all">{workspaceExport.design_system_folder}</div>
          </div>
          <div className="pl-6">
            <div className="text-zinc-500">rendered-assets</div>
            <div className="font-mono break-all">{workspaceExport.rendered_assets_folder}</div>
          </div>
          <div className="pt-2 border-t border-zinc-800/40">
            <div className="text-zinc-500 mb-1">files written</div>
            <div className="font-mono text-[11px] space-y-1">
              {workspaceExport.files_written.slice(0, 8).map((file) => (
                <div key={file} className="break-all">{file}</div>
              ))}
              {workspaceExport.files_written.length > 8 ? (
                <div className="text-zinc-500">+{workspaceExport.files_written.length - 8} more</div>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
