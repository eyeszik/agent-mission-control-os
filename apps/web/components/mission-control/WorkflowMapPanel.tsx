"use client";

import { useNodeStatusStore } from '../../lib/stores/nodeStatusStore';
import { useRunStore } from '../../lib/stores/runStore';

// Mirrors services/langgraph/graph/agency/nodes.py AGENCY_PIPELINE_STAGES —
// keep in sync manually until this is generated from the OpenAPI contract.
const AGENCY_PIPELINE_STAGES = [
  'brief_intake',
  'brand_strategy',
  'creative_concepting',
  'copywriting',
  'design_brief',
  'campaign_assembly',
  'brand_safety_qa',
  'hitl_gate',
  'delivery',
] as const;

const STAGE_LABELS: Record<string, string> = {
  brief_intake: 'INTAKE',
  brand_strategy: 'STRATEGY',
  creative_concepting: 'CONCEPT',
  copywriting: 'COPY',
  design_brief: 'DESIGN',
  campaign_assembly: 'ASSEMBLY',
  brand_safety_qa: 'QA',
  hitl_gate: 'HITL',
  delivery: 'DELIVER',
};

const COLS = 3;
const CELL_W = 120;
const CELL_H = 90;
const NODE_R = 14;

export function WorkflowMapPanel() {
  const activeRunId = useRunStore((state) => state.activeRunId);
  const statuses = useNodeStatusStore((state) => activeRunId ? state.statuses[activeRunId] : null);

  const getNodeColor = (nodeId: string) => {
    if (!statuses) return 'text-zinc-700';
    const status = statuses[nodeId];
    if (status === 'completed') return 'text-emerald-500';
    if (status === 'running') return 'text-amber-500 animate-pulse';
    if (status === 'failed') return 'text-red-500';
    return 'text-zinc-700'; // idle
  };

  const positions = AGENCY_PIPELINE_STAGES.map((stage, i) => ({
    stage,
    x: (i % COLS) * CELL_W + CELL_W / 2,
    y: Math.floor(i / COLS) * CELL_H + CELL_H / 2,
  }));

  const width = COLS * CELL_W;
  const rows = Math.ceil(AGENCY_PIPELINE_STAGES.length / COLS);
  const height = rows * CELL_H;

  return (
    <div className="flex-1 flex items-center justify-center p-8 relative">
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <svg className="w-full h-full" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet">
          {positions.slice(0, -1).map((p, i) => {
            const next = positions[i + 1];
            return (
              <line
                key={`edge-${p.stage}`}
                x1={p.x}
                y1={p.y}
                x2={next.x}
                y2={next.y}
                stroke="#3f3f46"
                strokeWidth="2"
                strokeDasharray="4 4"
              />
            );
          })}

          {positions.map((p) => (
            <g key={p.stage}>
              <circle
                cx={p.x}
                cy={p.y}
                r={NODE_R}
                className={`${getNodeColor(p.stage)} fill-current transition-colors duration-500`}
              />
              <text
                x={p.x}
                y={p.y + NODE_R + 14}
                textAnchor="middle"
                className="text-[9px] fill-zinc-500 font-mono"
              >
                {STAGE_LABELS[p.stage] ?? p.stage.toUpperCase()}
              </text>
            </g>
          ))}
        </svg>
      </div>
      {!activeRunId && (
        <div className="text-center z-10 bg-zinc-950/80 px-4 py-2 rounded-full backdrop-blur-sm border border-zinc-800">
          <p className="text-sm text-zinc-400 font-mono">Graph Idle</p>
        </div>
      )}
    </div>
  );
}
