"use client";

import type { Blueprint, IdeaDetail } from '@amc/shared';
import { extractBlueprint, promoteBlueprint } from '../../lib/api/missions';
import { Badge, Button, Empty, Hash, KeyValue, RunnerOutput, useRunner } from '../agency/ui';

function BlueprintCard({ blueprint, onChanged }: { blueprint: Blueprint; onChanged: () => void }) {
  const runner = useRunner();
  const c = blueprint.content;
  const verification = blueprint.verification as ({ verified: boolean; missions?: { mission_id: string; problems: string[] }[] } | null);
  const problems = verification?.missions?.flatMap((m) => m.problems.map((p) => `${m.mission_id}: ${p}`)) ?? [];
  return (
    <li className="flex min-w-0 flex-col gap-3 rounded-md border border-line p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-sm font-medium text-fg-strong"><Hash value={blueprint.blueprint_id} /></span>
        <Badge label={blueprint.status === 'PROMOTED' ? 'Promoted' : 'Draft'} tone={blueprint.status === 'PROMOTED' ? 'success' : 'neutral'} />
      </div>
      <KeyValue items={[
        ['Strategy from', `${c.strategy.source_engine}: ${c.strategy.summary}`],
        ['Scaffold from', `${c.scaffold.source_engine}: ${c.scaffold.components.map((x) => x.name).join(', ')}`],
        ['Security', `${c.security.level} · ${c.security.findings.map((f) => f.code).join(', ') || 'no findings'}`],
        ['Content hash', <Hash key="h" value={blueprint.content_hash} />],
      ]} />
      <ul className="flex flex-col gap-1 text-xs text-fg" aria-label="Source missions">
        {blueprint.sources.map((s) => (
          <li key={s.mission_id} className="flex flex-wrap items-center gap-2">
            <Badge status={s.status.toUpperCase()} label={s.status} />
            <span>{s.engine}</span>
            <span>{s.used_for.length ? `used for ${s.used_for.join(', ')}` : 'not used'}</span>
            {s.excluded_reason && <span>· excluded from the build: {s.excluded_reason}</span>}
          </li>
        ))}
      </ul>
      {verification && (
        <p className={`text-xs ${verification.verified ? 'text-status-success' : 'text-status-danger'}`}>
          {verification.verified ? 'Timelines verified: every source mission ran in order, was approved and completed.' : `Verification failed: ${problems.join('; ')}`}
        </p>
      )}
      {blueprint.status === 'DRAFT' && (
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" disabled={runner.busy}
            onClick={() => runner.run('Promote blueprint', async () => {
              const promoted = await promoteBlueprint(blueprint.blueprint_id);
              onChanged();
              return promoted.status === 'PROMOTED' ? 'Blueprint promoted: timelines verified' : 'Promotion not recorded';
            })}>
            Verify timelines and promote
          </Button>
        </div>
      )}
      <RunnerOutput message={runner.message} error={runner.error} />
    </li>
  );
}

/** Extract the best parts of the idea's completed missions into a blueprint, then promote it after timeline verification. */
export function BlueprintPanel({ idea, onChanged }: { idea: IdeaDetail; onChanged: () => void }) {
  const runner = useRunner();
  // ⚡ Bolt: Use zero-allocation reduce instead of .filter().length
  const completed = idea.missions.reduce((acc, m) => acc + (m.status === 'completed' ? 1 : 0), 0);
  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-fg">{completed} completed mission{completed === 1 ? '' : 's'} to draw from.</p>
        <Button disabled={runner.busy || completed === 0}
          onClick={() => runner.run('Extract blueprint', async () => {
            const bp = await extractBlueprint(idea.idea_id);
            onChanged();
            // ⚡ Bolt: Use zero-allocation reduce instead of .filter().length
            const sourceCount = bp.sources.reduce((acc, s) => acc + (s.used_for.length ? 1 : 0), 0);
            return `Blueprint ${bp.blueprint_id} extracted from ${sourceCount} mission(s)`;
          })}>
          Extract blueprint
        </Button>
      </div>
      <RunnerOutput message={runner.message} error={runner.error} />
      {idea.blueprints.length === 0 ? (
        <Empty title="No blueprint yet">Complete at least one mission, then extract its best strategy, security review and scaffold.</Empty>
      ) : (
        <ul className="flex flex-col gap-3">
          {idea.blueprints.map((b) => <BlueprintCard key={b.blueprint_id} blueprint={b} onChanged={onChanged} />)}
        </ul>
      )}
    </div>
  );
}
