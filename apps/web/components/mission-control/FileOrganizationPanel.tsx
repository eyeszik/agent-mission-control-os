"use client";

import { useEffect, useState, useMemo } from "react";
import type { ArtifactBinding, AgencyRun } from "@amc/shared";
import { getAgencyRun } from "../../lib/api/agency";
import { globalBus } from "../../lib/events/bus";
import { useRunStore } from "../../lib/stores/runStore";

type WorkspaceExport = NonNullable<AgencyRun["workspace_export"]>;

function deriveWorkspaceExport(bindings: ArtifactBinding[]): WorkspaceExport | null {
  if (bindings.length === 0) return null;
  const byKey = Object.fromEntries(bindings.map((binding) => [binding.artifact_key, binding]));
  const campaignPath = byKey.campaign_package?.content_location ?? null;
  const businessFolder = byKey.business_model_spec?.content_location ?? null;
  const brandingFolder = byKey.brand_core?.content_location ?? null;
  const designSystemFolder = byKey.design_system_spec?.content_location ?? byKey.design_token_set?.content_location ?? null;
  const renderedAssetsFolder = byKey.website_lockup_spec?.content_location ?? null;
  const rootFolder = campaignPath ? campaignPath.replace(/\/workspace-package\.json$/, "") : null;
  if (!rootFolder || !businessFolder || !brandingFolder || !designSystemFolder || !renderedAssetsFolder) {
    return null;
  }
  return {
    root_folder: rootFolder,
    business_folder: businessFolder,
    branding_folder: brandingFolder,
    design_system_folder: designSystemFolder.endsWith("/tokens.json")
      ? designSystemFolder.replace(/\/tokens\.json$/, "")
      : designSystemFolder,
    rendered_assets_folder: renderedAssetsFolder,
    files_written: [],
  };
}

function bindingTone(binding: ArtifactBinding) {
  if (binding.changed) return "text-amber-300 border-amber-500/30";
  if (binding.created) return "text-emerald-300 border-emerald-500/30";
  return "text-zinc-300 border-zinc-800/50";
}

function bindingStatus(binding: ArtifactBinding) {
  if (binding.changed) return "revised";
  if (binding.created) return "created";
  return "stable";
}

export function FileOrganizationPanel() {
  const activeRunId = useRunStore((state) => state.activeRunId);
  const [workspaceExport, setWorkspaceExport] = useState<WorkspaceExport | null>(null);
  const [artifactBindings, setArtifactBindings] = useState<ArtifactBinding[]>([]);

  // ⚡ Bolt: Wrapped derived workspace calculation in useMemo to prevent redundant
  // array allocations and derivations when unrelated state triggers re-renders.
  const effectiveWorkspaceExport = useMemo(() => {
    return workspaceExport ?? deriveWorkspaceExport(artifactBindings);
  }, [workspaceExport, artifactBindings]);

  useEffect(() => {
    if (!activeRunId) {
      setWorkspaceExport(null);
      setArtifactBindings([]);
      return;
    }
    let cancelled = false;
    const refresh = async () => {
      try {
        const run = await getAgencyRun(activeRunId);
        if (!cancelled) {
          setWorkspaceExport((run.workspace_export as WorkspaceExport | null | undefined) ?? null);
          setArtifactBindings(run.artifact_bindings ?? []);
        }
      } catch {
        if (!cancelled) setWorkspaceExport(null);
        if (!cancelled) setArtifactBindings([]);
      }
    };
    const onLifecycle = (event: { run_id: string }) => {
      if (event.run_id === activeRunId) void refresh();
    };
    void refresh();
    globalBus.on("lifecycle_event_received", onLifecycle as any);
    return () => {
      cancelled = true;
      globalBus.off("lifecycle_event_received", onLifecycle as any);
    };
  }, [activeRunId]);

  return (
    <div className="flex-1 bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-4 flex flex-col gap-3 min-h-[360px]">
      <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Artifact Lineage & Export</span>
      {!effectiveWorkspaceExport && artifactBindings.length === 0 ? (
        <div className="flex-1 border border-zinc-800/40 rounded-lg p-3 text-xs text-zinc-600 flex items-center justify-center">
          Idea workspace appears here after a run compiles.
        </div>
      ) : (
        <div className="flex-1 border border-zinc-800/40 rounded-lg p-3 flex flex-col gap-4 text-xs text-zinc-300 overflow-auto">
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-mono uppercase tracking-wider text-zinc-500">Export tree</span>
              <span className="text-[10px] font-mono text-zinc-500">{effectiveWorkspaceExport?.files_written.length ?? 0} files</span>
            </div>
            <div data-testid="artifact-export-tree" className="space-y-2">
              <div>
                <div className="text-zinc-500">root</div>
                <div className="font-mono break-all">{effectiveWorkspaceExport?.root_folder ?? "derived from canonical bindings"}</div>
              </div>
              <div className="pl-3">
                <div className="text-zinc-500">business</div>
                <div className="font-mono break-all">{effectiveWorkspaceExport?.business_folder ?? "pending"}</div>
              </div>
              <div className="pl-3">
                <div className="text-zinc-500">branding</div>
                <div className="font-mono break-all">{effectiveWorkspaceExport?.branding_folder ?? "pending"}</div>
              </div>
              <div className="pl-6">
                <div className="text-zinc-500">design-system</div>
                <div className="font-mono break-all">{effectiveWorkspaceExport?.design_system_folder ?? "pending"}</div>
              </div>
              <div className="pl-6">
                <div className="text-zinc-500">rendered-assets</div>
                <div className="font-mono break-all">{effectiveWorkspaceExport?.rendered_assets_folder ?? "pending"}</div>
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-2 pt-2 border-t border-zinc-800/40">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-mono uppercase tracking-wider text-zinc-500">Artifact bindings</span>
              <span className="text-[10px] font-mono text-zinc-500">{artifactBindings.length} tracked</span>
            </div>
            <div data-testid="artifact-bindings-panel" className="space-y-2">
              {artifactBindings.length === 0 ? (
                <div className="rounded-lg border border-zinc-800/50 bg-zinc-950/40 px-3 py-2 text-[11px] font-mono text-zinc-600">
                  No canonical artifact bindings have been materialized yet.
                </div>
              ) : (
                artifactBindings.map((binding) => (
                  <div
                    key={binding.artifact_key}
                    data-testid={`artifact-binding-${binding.artifact_key}`}
                    className={`rounded-lg border bg-zinc-950/40 px-3 py-2 flex flex-col gap-1 ${bindingTone(binding)}`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-[11px] font-mono">{binding.artifact_key}</span>
                      <span
                        data-testid={`artifact-binding-version-${binding.artifact_key}`}
                        className="text-[11px] font-mono"
                      >
                        v{binding.version} · {bindingStatus(binding)}
                      </span>
                    </div>
                    <div className="text-[10px] font-mono text-zinc-500">
                      {binding.artifact_type} · {binding.owner_department}
                    </div>
                    {binding.content_location ? (
                      <div className="text-[10px] font-mono break-all text-zinc-400">{binding.content_location}</div>
                    ) : null}
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="pt-2 border-t border-zinc-800/40">
            <div className="text-zinc-500 mb-1">files written</div>
            <div data-testid="artifact-files-written" className="font-mono text-[11px] space-y-1">
              {(effectiveWorkspaceExport?.files_written ?? []).slice(0, 8).map((file) => (
                <div key={file} className="break-all">{file}</div>
              ))}
              {(effectiveWorkspaceExport?.files_written.length ?? 0) > 8 ? (
                <div className="text-zinc-500">+{(effectiveWorkspaceExport?.files_written.length ?? 0) - 8} more</div>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
