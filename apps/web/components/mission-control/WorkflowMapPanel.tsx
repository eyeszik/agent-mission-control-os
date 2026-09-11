"use client";

import { AGENCY_PIPELINE_STAGES } from '@amc/shared';
import { useNodeStatusStore } from '../../lib/stores/nodeStatusStore';
import { useRunStore } from '../../lib/stores/runStore';

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

// Optimization: Compute static positions and SVG dimensions once at module load
// rather than re-calculating them on every component render.
const positions = AGENCY_PIPELINE_STAGES.map((stage, index) => ({
  stage,
  x: (index % COLS) * CELL_W + CELL_W / 2,
  y: Math.floor(index / COLS) * CELL_H + CELL_H / 2,
}));

const width = COLS * CELL_W;
const height = Math.ceil(AGENCY_PIPELINE_STAGES.length / COLS) * CELL_H;

// Optimization: Hoist static edge array calculations outside the render function
// to prevent O(N) mapping overhead on every component re-render.
const edges = positions.slice(0, -1).map((position, index) => {
  const next = positions[index + 1];
  return { key: `edge-${position.stage}`, x1: position.x, y1: position.y, x2: next.x, y2: next.y };
});

export function WorkflowMapPanel() {
  const activeRunId = useRunStore((state) => state.activeRunId);
  const statuses = useNodeStatusStore((state) => activeRunId ? state.statuses[activeRunId] : null);

  const getNodeColor = (nodeId: string) => {
    if (!statuses) return 'text-zinc-700';
    const status = statuses[nodeId];
    if (status === 'completed') return 'text-emerald-500';
    if (status === 'running') return 'text-amber-500 animate-pulse';
    if (status === 'failed') return 'text-red-500';
    return 'text-zinc-700';
  };

  return (
    <div className="flex-1 flex items-center justify-center p-8 relative">
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <svg className="w-full h-full" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet" aria-label="Agency workflow">
          {edges.map((edge) => (
            <line key={edge.key} x1={edge.x1} y1={edge.y1} x2={edge.x2} y2={edge.y2} stroke="currentColor" className="text-zinc-700" strokeWidth="2" strokeDasharray="4 4" />
          ))}
          {positions.map((position) => (
            <g key={position.stage}>
              <circle cx={position.x} cy={position.y} r={NODE_R} className={`${getNodeColor(position.stage)} fill-current transition-colors duration-500`} />
              <text x={position.x} y={position.y + NODE_R + 14} textAnchor="middle" className="text-[9px] fill-zinc-500 font-mono">
                {STAGE_LABELS[position.stage] ?? position.stage.toUpperCase()}
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
