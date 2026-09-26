"use client";

import { useEffect, useMemo, useState } from 'react';
import {
  STYLE_CATEGORIES,
  STYLE_DIMENSIONS,
  type ComposedStyle,
  type StyleCatalogResponse,
  type StyleDefinition,
  type StyleDimension,
  type StyleSelection,
} from '@amc/shared';
import { composeDesignStyle, getDesignStyleLibrary } from '../../lib/api/design';
import {
  MAX_LAYERS,
  addLayer,
  filterStyles,
  indexStyles,
  precheck,
  removeLayer,
  selectionKey,
  setRole,
  setStrength,
  toDesignStyleSelection,
  toggleDimension,
  toggleLock,
  type StyleIndex,
} from '../../lib/design/composer';
import { useDesignStore } from '../../lib/stores/designStore';

type CatalogState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; catalog: StyleCatalogResponse };

const inputClass =
  'w-full bg-zinc-950/50 border border-zinc-800/80 rounded-lg p-2 text-sm text-zinc-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60';
const chipBase = 'text-[10px] font-mono px-1.5 py-0.5 rounded border transition-colors';

function Swatches({ colors }: { colors: readonly string[] }) {
  return (
    <div className="flex gap-1" aria-hidden="true">
      {colors.slice(0, 6).map((color, index) => (
        <span
          key={`${color}-${index}`}
          className="h-3 w-3 rounded-sm border border-zinc-700/80"
          style={{ backgroundColor: color /* amc-allow-hex: previews catalog palette data, not UI chrome */ }}
        />
      ))}
    </div>
  );
}

function StyleCard({
  style,
  role,
  full,
  onAdd,
}: {
  style: StyleDefinition;
  role: StyleSelection['role'] | null;
  full: boolean;
  onAdd: (style: StyleDefinition, role: StyleSelection['role']) => void;
}) {
  const disabled = style.status === 'disabled';
  return (
    <li className="border border-zinc-800/80 rounded-lg p-3 bg-zinc-950/40 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm text-zinc-200 font-medium truncate">{style.name}</div>
          <div className="text-[10px] font-mono text-zinc-500">
            {style.id} · {style.category}
            {style.status !== 'active' && <span className="ml-1 text-amber-400">· {style.status}</span>}
          </div>
        </div>
        <Swatches colors={style.palette.colors} />
      </div>
      <p className="text-xs text-zinc-400 leading-snug">{style.description}</p>
      <div className="flex flex-wrap gap-1">
        {style.design_dimensions.map((dimension) => (
          <span key={dimension} className={`${chipBase} border-zinc-800 text-zinc-400`}>{dimension}</span>
        ))}
      </div>
      {style.suitable_for.length > 0 && (
        <div className="text-[11px] text-zinc-500">Suits: {style.suitable_for.slice(0, 3).join(', ')}</div>
      )}
      <div className="flex gap-2 pt-1">
        <button
          type="button"
          disabled={disabled || role === 'primary' || (full && role === null)}
          onClick={() => onAdd(style, 'primary')}
          aria-label={`Set ${style.name} as primary style`}
          className="text-xs px-2 py-1 rounded border border-emerald-500/30 text-emerald-300 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-emerald-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60"
        >
          {role === 'primary' ? 'Primary' : 'Set primary'}
        </button>
        <button
          type="button"
          disabled={disabled || role !== null || full}
          onClick={() => onAdd(style, 'secondary')}
          aria-label={`Add ${style.name} as a secondary layer`}
          className="text-xs px-2 py-1 rounded border border-zinc-700 text-zinc-300 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-zinc-800/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60"
        >
          {role === 'secondary' ? 'Layered' : 'Add layer'}
        </button>
      </div>
    </li>
  );
}

function LayerRow({
  layer,
  style,
  onRole,
  onStrength,
  onDimension,
  onLock,
  onRemove,
}: {
  layer: StyleSelection;
  style: StyleDefinition | undefined;
  onRole: (id: string, role: StyleSelection['role']) => void;
  onStrength: (id: string, value: number) => void;
  onDimension: (id: string, dimension: StyleDimension) => void;
  onLock: (id: string) => void;
  onRemove: (id: string) => void;
}) {
  const name = style?.name ?? layer.style_id;
  const declared = new Set<string>(style?.design_dimensions ?? []);
  const sliderId = `strength-${layer.style_id}`;
  return (
    <li className="border border-zinc-800/80 rounded-lg p-3 bg-zinc-950/40 flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm text-zinc-200 font-medium truncate">{name}</span>
          <span
            className={`${chipBase} ${layer.role === 'primary' ? 'border-emerald-500/40 text-emerald-300' : 'border-zinc-700 text-zinc-400'}`}
          >
            {layer.role}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {layer.role !== 'primary' && (
            <button
              type="button"
              onClick={() => onRole(layer.style_id, 'primary')}
              className="text-[11px] text-zinc-400 hover:text-emerald-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60 rounded"
            >
              Make primary
            </button>
          )}
          <button
            type="button"
            aria-pressed={layer.locked}
            aria-label={`${layer.locked ? 'Unlock' : 'Lock'} ${name} dimensions`}
            onClick={() => onLock(layer.style_id)}
            className={`${chipBase} ${layer.locked ? 'border-amber-500/50 text-amber-300 bg-amber-500/10' : 'border-zinc-700 text-zinc-400'} focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60`}
          >
            {layer.locked ? 'Locked' : 'Lock'}
          </button>
          <button
            type="button"
            aria-label={`Remove ${name}`}
            onClick={() => onRemove(layer.style_id)}
            className="text-[11px] text-zinc-500 hover:text-red-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60 rounded"
          >
            Remove
          </button>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <label htmlFor={sliderId} className="text-xs text-zinc-500 shrink-0">Strength</label>
        <input
          id={sliderId}
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={layer.strength}
          onChange={(event) => onStrength(layer.style_id, Number(event.target.value))}
          className="flex-1 accent-emerald-500"
        />
        <span className="text-xs font-mono text-zinc-400 w-10 text-right">{layer.strength.toFixed(2)}</span>
      </div>
      <fieldset className="flex flex-wrap gap-1">
        <legend className="sr-only">{name} dimensions</legend>
        {STYLE_DIMENSIONS.map((dimension) => {
          const active = layer.dimensions.includes(dimension);
          const native = declared.has(dimension);
          return (
            <button
              key={dimension}
              type="button"
              aria-pressed={active}
              onClick={() => onDimension(layer.style_id, dimension)}
              title={native ? `${name} declares ${dimension}` : `${name} does not declare ${dimension}`}
              className={`${chipBase} ${
                active
                  ? native
                    ? 'border-emerald-500/40 text-emerald-300 bg-emerald-500/10'
                    : 'border-amber-500/40 text-amber-300 bg-amber-500/10'
                  : native
                    ? 'border-zinc-700 text-zinc-400'
                    : 'border-zinc-800 text-zinc-600'
              } focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60`}
            >
              {dimension}
            </button>
          );
        })}
      </fieldset>
    </li>
  );
}

function ComposedResult({ composed, index }: { composed: ComposedStyle; index: StyleIndex }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(composed.prompt);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  return (
    <section aria-label="Composed design direction" className="flex flex-col gap-3">
      {composed.blocking ? (
        <div role="alert" className="text-xs text-red-300 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">
          Blocked — this direction cannot be attached: {composed.conflicts.join(' ')}
        </div>
      ) : (
        <div className="text-xs text-emerald-300 bg-emerald-500/10 border border-emerald-500/20 rounded px-3 py-2">
          Composed {composed.composition_id} · catalog {composed.catalog_version}
        </div>
      )}
      <div>
        <div className="text-xs font-mono text-zinc-500 uppercase tracking-wider mb-1">Resolved dimensions</div>
        <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1">
          {STYLE_DIMENSIONS.filter((dimension) => composed.resolved_dimensions[dimension]).map((dimension) => {
            const owner = composed.resolved_dimensions[dimension] ?? '';
            return (
              <div key={dimension} className="flex justify-between gap-2 text-xs">
                <dt className="text-zinc-500">{dimension}</dt>
                <dd className="text-zinc-300 truncate">{index.get(owner)?.name ?? owner}</dd>
              </div>
            );
          })}
        </dl>
      </div>
      {composed.warnings.length > 0 && (
        <ul className="text-[11px] text-amber-300/90 list-disc pl-4 space-y-0.5">
          {composed.warnings.map((warning) => <li key={warning}>{warning}</li>)}
        </ul>
      )}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Compiled prompt</span>
          <button
            type="button"
            onClick={copy}
            className="text-[11px] text-zinc-400 hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60 rounded"
          >
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
        <p className="text-xs text-zinc-300 leading-relaxed bg-zinc-950/60 border border-zinc-800/80 rounded-lg p-3 whitespace-pre-wrap">
          {composed.prompt}
        </p>
        {composed.negative_prompt && (
          <p className="mt-2 text-[11px] text-zinc-500">
            <span className="font-mono uppercase tracking-wider">Negative:</span> {composed.negative_prompt}
          </p>
        )}
      </div>
    </section>
  );
}

export function DesignStyleComposerPanel() {
  const [state, setState] = useState<CatalogState>({ status: 'loading' });
  const [reloadToken, setReloadToken] = useState(0);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('');
  const [hideDisabled, setHideDisabled] = useState(true);
  const [layers, setLayers] = useState<StyleSelection[]>([]);
  const [objective, setObjective] = useState('');
  const [format, setFormat] = useState('');
  const [rationale, setRationale] = useState('');
  const [composing, setComposing] = useState(false);
  const [composeError, setComposeError] = useState<string | null>(null);
  const [composed, setComposed] = useState<ComposedStyle | null>(null);
  const [composedKey, setComposedKey] = useState<string | null>(null);

  const attachedId = useDesignStore((store) => store.attached?.compositionId ?? null);
  const attach = useDesignStore((store) => store.attach);

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });
    getDesignStyleLibrary()
      .then((catalog) => {
        if (!cancelled) setState({ status: 'ready', catalog });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({ status: 'error', message: error instanceof Error ? error.message : 'Failed to load the style catalog' });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  const styles = useMemo(() => (state.status === 'ready' ? state.catalog.styles : []), [state]);
  const index = useMemo(() => indexStyles(styles), [styles]);
  const visible = useMemo(() => filterStyles(styles, { query, category, hideDisabled }), [styles, query, category, hideDisabled]);
  const roles = useMemo(() => new Map(layers.map((layer) => [layer.style_id, layer.role])), [layers]);
  const checks = useMemo(() => precheck(layers, index), [layers, index]);
  const currentKey = useMemo(() => selectionKey(layers), [layers]);
  const stale = composed !== null && composedKey !== currentKey;
  const full = layers.length >= MAX_LAYERS;

  const updateLayers = (next: StyleSelection[]) => {
    setLayers(next);
    setComposeError(null);
  };

  const handleCompose = async () => {
    if (layers.length === 0 || checks.conflicts.length > 0) return;
    setComposing(true);
    setComposeError(null);
    try {
      const result = await composeDesignStyle(layers, {
        objective: objective.trim() || undefined,
        format: format.trim() || undefined,
      });
      setComposed(result);
      setComposedKey(currentKey);
    } catch (error) {
      setComposeError(error instanceof Error ? error.message : 'Composition failed');
    } finally {
      setComposing(false);
    }
  };

  const canAttach = composed !== null && !composed.blocking && !stale && checks.conflicts.length === 0;
  const handleAttach = () => {
    if (!canAttach || composed === null) return;
    const ordered = [...layers].sort((a, b) => (a.role === 'primary' ? -1 : b.role === 'primary' ? 1 : 0));
    attach({
      selection: toDesignStyleSelection(layers, rationale),
      compositionId: composed.composition_id,
      label: ordered.map((layer) => index.get(layer.style_id)?.name ?? layer.style_id).join(' + '),
    });
  };

  return (
    <div className="bg-zinc-900/40 border border-zinc-800/60 rounded-xl flex flex-col min-h-0">
      <div className="p-3 border-b border-zinc-800/60 flex items-center justify-between gap-2">
        <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Design Style Composer</span>
        {state.status === 'ready' && (
          <span className="text-[10px] font-mono text-zinc-500">
            {state.catalog.version} · {styles.length} styles
          </span>
        )}
      </div>

      {state.status === 'loading' && <div className="p-6 text-sm text-zinc-500">Loading style catalog…</div>}

      {state.status === 'error' && (
        <div className="p-4 flex flex-col gap-2">
          <div role="alert" className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">
            {state.message}
          </div>
          <button
            type="button"
            onClick={() => setReloadToken((token) => token + 1)}
            className="self-start text-xs px-3 py-1.5 rounded border border-zinc-700 text-zinc-300 hover:bg-zinc-800/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60"
          >
            Retry
          </button>
        </div>
      )}

      {state.status === 'ready' && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 p-4 min-h-0">
          <section aria-label="Style catalog" className="flex flex-col gap-3 min-h-0">
            <div className="flex flex-col gap-2">
              <label htmlFor="style-search" className="text-xs text-zinc-500">Search styles</label>
              <input
                id="style-search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Name, id, dimension, use case…"
                className={inputClass}
              />
              <div className="flex items-center gap-3">
                <label htmlFor="style-category" className="sr-only">Category</label>
                <select
                  id="style-category"
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                  className={`${inputClass} w-auto`}
                >
                  <option value="">All categories</option>
                  {STYLE_CATEGORIES.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
                <label className="flex items-center gap-1.5 text-xs text-zinc-500">
                  <input type="checkbox" checked={hideDisabled} onChange={(event) => setHideDisabled(event.target.checked)} />
                  Hide disabled
                </label>
              </div>
            </div>
            {state.catalog.pending_references.length > 0 && (
              <p className="text-[11px] text-zinc-500">
                Referenced but not yet in the catalog: {state.catalog.pending_references.join(', ')}.
              </p>
            )}
            <ul className="flex flex-col gap-2 overflow-y-auto max-h-[60vh] pr-1">
              {visible.map((style) => (
                <StyleCard
                  key={style.id}
                  style={style}
                  role={roles.get(style.id) ?? null}
                  full={full}
                  onAdd={(target, role) => updateLayers(addLayer(layers, target, role))}
                />
              ))}
              {visible.length === 0 && <li className="text-xs text-zinc-500">No styles match these filters.</li>}
            </ul>
          </section>

          <section aria-label="Composition" className="flex flex-col gap-3 min-h-0">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono text-zinc-500 uppercase tracking-wider">
                Layers ({layers.length}/{MAX_LAYERS})
              </span>
              {layers.length > 0 && (
                <button
                  type="button"
                  onClick={() => updateLayers([])}
                  className="text-[11px] text-zinc-500 hover:text-zinc-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/60 rounded"
                >
                  Clear
                </button>
              )}
            </div>

            {layers.length === 0 ? (
              <p className="text-xs text-zinc-500">
                Set a primary style, then add layers. Each dimension resolves to one style — locked layers win, then strength.
              </p>
            ) : (
              <ul className="flex flex-col gap-2">
                {layers.map((layer) => (
                  <LayerRow
                    key={layer.style_id}
                    layer={layer}
                    style={index.get(layer.style_id)}
                    onRole={(id, role) => updateLayers(setRole(layers, id, role))}
                    onStrength={(id, value) => updateLayers(setStrength(layers, id, value))}
                    onDimension={(id, dimension) => updateLayers(toggleDimension(layers, id, dimension))}
                    onLock={(id) => updateLayers(toggleLock(layers, id))}
                    onRemove={(id) => updateLayers(removeLayer(layers, id))}
                  />
                ))}
              </ul>
            )}

            {checks.conflicts.length > 0 && (
              <div role="alert" className="text-xs text-red-300 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">
                {checks.conflicts.join(' ')}
              </div>
            )}
            {checks.warnings.length > 0 && (
              <ul className="text-[11px] text-amber-300/90 list-disc pl-4 space-y-0.5">
                {checks.warnings.map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <div className="flex flex-col gap-1">
                <label htmlFor="design-objective" className="text-xs text-zinc-500">Objective</label>
                <input id="design-objective" value={objective} onChange={(event) => setObjective(event.target.value)} className={inputClass} />
              </div>
              <div className="flex flex-col gap-1">
                <label htmlFor="design-format" className="text-xs text-zinc-500">Output format</label>
                <input id="design-format" value={format} onChange={(event) => setFormat(event.target.value)} className={inputClass} />
              </div>
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor="design-rationale" className="text-xs text-zinc-500">Rationale</label>
              <textarea id="design-rationale" rows={2} value={rationale} onChange={(event) => setRationale(event.target.value)} className={inputClass} />
            </div>

            {composeError && (
              <div role="alert" className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-3 py-2">
                {composeError}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={handleCompose}
                disabled={composing || layers.length === 0 || checks.conflicts.length > 0}
                className="px-4 py-1.5 bg-zinc-100 text-zinc-900 text-sm font-medium rounded-md disabled:opacity-50 disabled:cursor-not-allowed hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 transition-colors"
              >
                {composing ? 'Composing…' : 'Validate & compose'}
              </button>
              <button
                type="button"
                onClick={handleAttach}
                disabled={!canAttach}
                className="px-4 py-1.5 border border-emerald-500/40 text-emerald-300 text-sm font-medium rounded-md disabled:opacity-40 disabled:cursor-not-allowed hover:bg-emerald-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 transition-colors"
              >
                {composed && attachedId === composed.composition_id && !stale ? 'Attached to next run' : 'Attach to next run'}
              </button>
              {stale && <span className="text-[11px] text-amber-300">Layers changed — recompose before attaching.</span>}
            </div>

            {composed && <ComposedResult composed={composed} index={index} />}
          </section>
        </div>
      )}
    </div>
  );
}
