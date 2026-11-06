"use client";

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import type { VnexusBrand, VnexusScope } from '@amc/shared';
import { createBrand, listBrands } from '../../../lib/api/vnexus';
import { SCOPES, scopeRefHint } from '../../../lib/design/vnexus-editor';
import { useProjectStore } from '../../../lib/stores/projectStore';
import { useVnexusStore, type VnexusArea } from '../../../lib/stores/vnexusStore';
import { GenomeEditorArea, HistoryArea, OverviewArea } from './GenomeAreas';
import { GraphArea, MultiverseArea } from './GraphAreas';
import { ArtDirectionArea, ExperienceArea, GraphicArea, JobsArea, VideoArea } from './ProductionAreas';
import { BrandBookArea } from './BrandBookArea';
import { DirectionsArea } from './DirectionsArea';
import { GovernanceArea, ImmuneArea, MarketingArea, PromptsArea } from './IntelligenceAreas';
import { Empty, Field, StatusLine, buttonClass, inputClass, useAction } from './ui';

const AREAS: { id: VnexusArea; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'genome', label: 'Brand Genome' },
  { id: 'history', label: 'Versions' },
  { id: 'graph', label: 'Knowledge Graph' },
  { id: 'multiverse', label: 'Multiverse' },
  { id: 'experience', label: 'Experience' },
  { id: 'art', label: 'Art Direction' },
  { id: 'graphic', label: 'Graphic Design' },
  { id: 'directions', label: 'Creative Directions' },
  { id: 'brandbook', label: 'Brand Book' },
  { id: 'video', label: 'Video & Motion' },
  { id: 'marketing', label: 'Marketing' },
  { id: 'prompts', label: 'Prompt Genome' },
  { id: 'jobs', label: 'Provider Jobs' },
  { id: 'immune', label: 'Immune System' },
  { id: 'governance', label: 'Governance' },
];

function BrandBar({ brands, onCreated }: { brands: VnexusBrand[]; onCreated: (b: VnexusBrand) => void }) {
  const brandId = useVnexusStore((s) => s.brandId);
  const setBrand = useVnexusStore((s) => s.setBrand);
  const scope = useVnexusStore((s) => s.scope);
  const scopeRef = useVnexusStore((s) => s.scopeRef);
  const setScope = useVnexusStore((s) => s.setScope);
  const projectId = useProjectStore((s) => s.activeProjectId);
  const [name, setName] = useState('');
  const { state, run, busy } = useAction();

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!projectId || !name.trim()) return;
    const id = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60) || 'brand';
    const made = await run('Creating brand', () => createBrand({ brand_id: id, display_name: name.trim(), owner_project_id: projectId }),
      (b) => `Created ${b.display_name}`);
    if (made) { onCreated(made); setName(''); }
  };

  return (
    <div className="flex flex-wrap items-end gap-3">
      <Field label="Brand">
        <select className={inputClass} value={brandId ?? ''} onChange={(e) => setBrand(e.target.value || null)}>
          <option value="">Select a brand…</option>
          {brands.map((b) => <option key={b.brand_id} value={b.brand_id}>{b.display_name}</option>)}
        </select>
      </Field>
      <Field label="Scope">
        <select className={inputClass} value={scope} disabled={!brandId}
          onChange={(e) => { const s = e.target.value as VnexusScope; setScope(s, scopeRefHint(s, brandId ?? '', projectId)); }}>
          {SCOPES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </Field>
      <Field label="Scope reference" hint="brand id, or project[/page[/component[/asset]]]">
        <input className={inputClass} value={scopeRef} disabled={!brandId} onChange={(e) => setScope(scope, e.target.value)} />
      </Field>
      <form onSubmit={create} className="flex items-end gap-2">
        <Field label="New brand" hint={projectId ? `owned by project ${projectId}` : 'select a project first'}>
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} placeholder="Display name" disabled={!projectId} />
        </Field>
        <button type="submit" className={buttonClass} disabled={!projectId || !name.trim() || busy}>Create</button>
      </form>
      <StatusLine state={state} />
    </div>
  );
}

export function VnexusStudio() {
  const area = useVnexusStore((s) => s.area);
  const setArea = useVnexusStore((s) => s.setArea);
  const brandId = useVnexusStore((s) => s.brandId);
  const [brands, setBrands] = useState<VnexusBrand[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);

  const refresh = useCallback(async () => {
    try { setBrands(await listBrands()); setLoadError(null); }
    catch (e) { setLoadError(e instanceof Error ? e.message : String(e)); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  const onKey = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const next = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? index + 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? index - 1
      : e.key === 'Home' ? 0 : e.key === 'End' ? AREAS.length - 1 : null;
    if (next === null) return;
    e.preventDefault();
    const target = (next + AREAS.length) % AREAS.length;
    setArea(AREAS[target].id);
    tabs.current[target]?.focus();
  };

  return (
    <section aria-label="VNEXUS creative studio" className="flex flex-col gap-4 min-w-0">
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-zinc-100 font-medium">VNEXUS creative studio</h2>
          <p className="text-[11px] text-zinc-500">Local renders only. Publishing, ad spend and hosted generation are disabled.</p>
        </div>
        <BrandBar brands={brands} onCreated={() => void refresh()} />
        {loadError && <p role="alert" className="text-xs text-red-300">Could not load brands: {loadError}</p>}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-[12rem_1fr] gap-4 min-w-0">
        <div role="tablist" aria-label="VNEXUS areas" aria-orientation="vertical" className="flex lg:flex-col flex-wrap gap-1">
          {AREAS.map((a, i) => (
            <button key={a.id} ref={(el) => { tabs.current[i] = el; }} id={`vnx-tab-${a.id}`} type="button" role="tab"
              aria-selected={area === a.id} aria-controls={`vnx-panel-${a.id}`} tabIndex={area === a.id ? 0 : -1}
              onClick={() => setArea(a.id)} onKeyDown={(e) => onKey(e, i)}
              className={`text-left text-xs px-2.5 py-1.5 rounded-sm focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-emerald-500/60 ${area === a.id ? 'bg-zinc-100 text-zinc-900' : 'text-zinc-400 hover:text-zinc-100'}`}>
              {a.label}
            </button>
          ))}
        </div>
        <div role="tabpanel" id={`vnx-panel-${area}`} aria-labelledby={`vnx-tab-${area}`} className="min-w-0 flex flex-col gap-4">
          {!brandId ? <Empty>Select or create a brand to begin. A brand belongs to the project that owns it.</Empty> : (
            <>
              {area === 'overview' && <OverviewArea />}
              {area === 'genome' && <GenomeEditorArea />}
              {area === 'history' && <HistoryArea />}
              {area === 'graph' && <GraphArea />}
              {area === 'multiverse' && <MultiverseArea />}
              {area === 'experience' && <ExperienceArea />}
              {area === 'art' && <ArtDirectionArea />}
              {area === 'graphic' && <GraphicArea />}
              {area === 'directions' && <DirectionsArea />}
              {area === 'brandbook' && <BrandBookArea />}
              {area === 'video' && <VideoArea />}
              {area === 'marketing' && <MarketingArea />}
              {area === 'prompts' && <PromptsArea />}
              {area === 'jobs' && <JobsArea />}
              {area === 'immune' && <ImmuneArea />}
              {area === 'governance' && <GovernanceArea />}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
