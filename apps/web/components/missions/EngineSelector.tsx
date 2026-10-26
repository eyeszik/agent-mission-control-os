"use client";

import type { CouncilEngine, EnginesResponse } from '@amc/shared';
import { Badge, focusRing } from '../agency/ui';

const ENGINE_LABEL: Record<CouncilEngine, { name: string; detail: string }> = {
  langgraph: { name: 'LangGraph', detail: 'State graph with a native interrupt at the Sentinel gate and SQLite/Postgres checkpoints.' },
  crewai: { name: 'CrewAI', detail: 'Sequential crew: strategy, then security audit, then prototype, with task context.' },
  autogen: { name: 'AutoGen', detail: 'Bounded round-robin team with explicit termination and no code executor.' },
};

/** Engine choice for a dispatch. Unavailable engines (extra not installed) are shown, disabled, with the reason. */
export function EngineSelector({ engines, value, onChange, disabled = false }: {
  engines: EnginesResponse;
  value: CouncilEngine;
  onChange: (engine: CouncilEngine) => void;
  disabled?: boolean;
}) {
  return (
    <fieldset className="flex min-w-0 flex-col gap-2" disabled={disabled}>
      <legend className="mb-1 text-sm font-medium text-fg-strong">Engine</legend>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
        {engines.engines.map((e) => {
          const label = ENGINE_LABEL[e.engine];
          const checked = value === e.engine;
          return (
            <label key={e.engine}
              className={`flex flex-col gap-1 rounded-md border p-3 text-sm ${e.available ? 'cursor-pointer' : 'cursor-not-allowed opacity-60'} ${checked ? 'border-accent bg-surface-raised' : 'border-line-strong bg-surface hover:bg-surface-raised'}`}>
              <span className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 font-medium text-fg-strong">
                  <input type="radio" name="council-engine" value={e.engine} checked={checked} disabled={!e.available}
                    aria-label={label.name} aria-describedby={`engine-${e.engine}-desc`}
                    onChange={() => onChange(e.engine)} className={`accent-accent ${focusRing}`} />
                  {label.name}
                </span>
                <Badge label={e.available ? 'Installed' : 'Not installed'} tone={e.available ? 'success' : 'neutral'} />
              </span>
              <span id={`engine-${e.engine}-desc`} className="flex flex-col gap-1 text-xs text-fg">
                <span>{e.available ? 'Installed.' : 'Not installed.'} {label.detail}</span>
                {!e.available && <span>{e.detail}</span>}
              </span>
            </label>
          );
        })}
      </div>
      <p className="text-xs text-fg">
        Model: {engines.model_mode === 'MOCK_DETERMINISTIC'
          ? 'deterministic mock (no network, no API key). Set ENABLE_REAL_MODELS=true to use a provider.'
          : `provider "${engines.default_provider}". A missing credential fails the seat; nothing is invented.`}
      </p>
    </fieldset>
  );
}
