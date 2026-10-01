"use client";

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ArtifactMetadataV2, ProjectWorkspaceV2 } from '@amc/shared';
import { createProject, getProject, getWorkspace, listProjectArtifacts, listProjects, type WorkspaceView } from '../../lib/api/projects';
import { useProjectStore } from '../../lib/stores/projectStore';

type Snapshot = Awaited<ReturnType<typeof getProject>>['snapshot'];

const MEDIA_FILTERS = ['', 'text', 'image', 'video', 'audio', 'data'] as const;

function AssetRow({ asset }: { asset: ArtifactMetadataV2 }) {
  return (
    <li className="flex items-center justify-between gap-2 text-xs py-1 border-b border-zinc-800/40 last:border-0">
      <span className="truncate text-zinc-200" title={asset.artifact_id}>{asset.artifact_key}</span>
      <span className="shrink-0 text-zinc-500 font-mono">
        {asset.artifact_type}{asset.channel ? ` · ${asset.channel}` : ''} · v{asset.version}
        {asset.variant_of ? ' · variant' : ''}
      </span>
    </li>
  );
}

export function ProjectWorkspacePanel() {
  const activeProjectId = useProjectStore((state) => state.activeProjectId);
  const setActiveProject = useProjectStore((state) => state.setActiveProject);
  const [projects, setProjects] = useState<ProjectWorkspaceV2[]>([]);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceView | null>(null);
  const [assets, setAssets] = useState<ArtifactMetadataV2[]>([]);
  const [mediaType, setMediaType] = useState<string>('');
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);

  const refreshProjects = useCallback(async () => {
    try {
      const result = await listProjects();
      setProjects(result.projects);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load projects');
    }
  }, []);

  useEffect(() => {
    void refreshProjects();
  }, [refreshProjects]);

  useEffect(() => {
    if (!activeProjectId) {
      setSnapshot(null);
      setWorkspace(null);
      return;
    }
    let cancelled = false;
    Promise.all([getProject(activeProjectId), getWorkspace(activeProjectId)])
      .then(([detail, view]) => {
        if (cancelled) return;
        setSnapshot(detail.snapshot);
        setWorkspace(view);
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : 'Could not load project'));
    return () => {
      cancelled = true;
    };
  }, [activeProjectId]);

  useEffect(() => {
    if (!activeProjectId) {
      setAssets([]);
      return;
    }
    let cancelled = false;
    listProjectArtifacts(activeProjectId, { media_type: mediaType || undefined })
      .then((result) => !cancelled && setAssets(result.artifacts))
      .catch(() => !cancelled && setAssets([]));
    return () => {
      cancelled = true;
    };
  }, [activeProjectId, mediaType]);

  // ⚡ Bolt: folder counts derived once per workspace payload, not per render.
  const folderCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const file of workspace?.files ?? []) counts.set(file.folder, (counts.get(file.folder) ?? 0) + 1);
    return Array.from(counts.entries());
  }, [workspace]);

  const onCreate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    try {
      const created = await createProject({ display_name: name.trim() });
      setName('');
      await refreshProjects();
      setActiveProject(created.project.project_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create project');
    }
  };

  return (
    <section aria-labelledby="project-workspace-heading" className="bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-3 flex flex-col gap-3 min-h-0">
      <div className="flex items-center justify-between">
        <h2 id="project-workspace-heading" className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Project Workspace</h2>
        {snapshot && <span className="text-xs text-zinc-500 font-mono">{snapshot.lifecycle_state}</span>}
      </div>
      <label className="text-xs text-zinc-400 flex flex-col gap-1">
        Project
        <select
          value={activeProjectId ?? ''}
          onChange={(event) => setActiveProject(event.target.value || null)}
          className="bg-zinc-950 border border-zinc-800 rounded-md px-2 py-1 text-sm text-zinc-100"
        >
          <option value="">Select a project…</option>
          {projects.map((project) => (
            <option key={project.project_id} value={project.project_id}>{project.display_name}</option>
          ))}
        </select>
      </label>
      <form onSubmit={onCreate} className="flex gap-2">
        <label className="sr-only" htmlFor="new-project-name">New project name</label>
        <input
          id="new-project-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="New project name"
          className="flex-1 min-w-0 bg-zinc-950 border border-zinc-800 rounded-md px-2 py-1 text-sm text-zinc-100"
        />
        <button type="submit" className="text-xs px-2.5 py-1 rounded-md bg-zinc-100 text-zinc-900 disabled:opacity-50" disabled={!name.trim()}>
          Create
        </button>
      </form>
      {error && <p role="alert" className="text-xs text-rose-300">{error}</p>}
      {snapshot && (
        <dl className="grid grid-cols-3 gap-2 text-xs">
          <div><dt className="text-zinc-500">Artifacts</dt><dd className="text-zinc-100 font-mono">{snapshot.artifact_heads.length}</dd></div>
          <div><dt className="text-zinc-500">Runs</dt><dd className="text-zinc-100 font-mono">{snapshot.run_ids.length}</dd></div>
          <div><dt className="text-zinc-500">Stale</dt><dd className={`font-mono ${snapshot.stale_artifact_count ? 'text-amber-300' : 'text-zinc-100'}`}>{snapshot.stale_artifact_count}</dd></div>
        </dl>
      )}
      {workspace && (
        <div className="text-xs">
          <p className="text-zinc-500 mb-1">Workspace mirror <span className="text-zinc-600">(materialized view; the database is canonical)</span></p>
          {folderCounts.length === 0 ? (
            <p className="text-zinc-600">No files materialized yet.</p>
          ) : (
            <ul className="flex flex-wrap gap-1.5">
              {folderCounts.map(([folder, count]) => (
                <li key={folder} className="px-1.5 py-0.5 rounded border border-zinc-800 text-zinc-300 font-mono">{folder} · {count}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {activeProjectId && (
        <div className="flex flex-col gap-1 min-h-0">
          <div className="flex items-center justify-between">
            <p className="text-xs text-zinc-500">Assets</p>
            <label className="text-xs text-zinc-500 flex items-center gap-1">
              Media
              <select value={mediaType} onChange={(event) => setMediaType(event.target.value)} className="bg-zinc-950 border border-zinc-800 rounded px-1 text-zinc-200">
                {MEDIA_FILTERS.map((value) => <option key={value} value={value}>{value || 'all'}</option>)}
              </select>
            </label>
          </div>
          {assets.length === 0 ? (
            <p className="text-xs text-zinc-600">No assets match.</p>
          ) : (
            <ul className="overflow-auto max-h-48">{assets.map((asset) => <AssetRow key={asset.artifact_id} asset={asset} />)}</ul>
          )}
        </div>
      )}
    </section>
  );
}
