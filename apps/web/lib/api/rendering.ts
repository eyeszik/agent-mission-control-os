import { RenderCapabilitiesSchema, RenderJobSchema, type RenderEngineId } from '@amc/shared';
import { apiFetch } from './client';
const base = (project: string) => `/foundry/projects/${encodeURIComponent(project)}/renders`;
export const renderCapabilities = (signal?: AbortSignal) => apiFetch('/foundry/render-capabilities', { signal }, RenderCapabilitiesSchema);
export const getRenderJob = (project: string, job: string, signal?: AbortSignal) => apiFetch(`${base(project)}/${encodeURIComponent(job)}`, { signal }, RenderJobSchema);
export const cancelRenderJob = (project: string, job: string, signal?: AbortSignal) => apiFetch(`${base(project)}/${encodeURIComponent(job)}/cancel`, { method: 'POST', signal }, RenderJobSchema);
export function submitRender(project: string, brief: string, engine: RenderEngineId, key: string, signal?: AbortSignal) {
  return apiFetch(base(project), { method: 'POST', idempotencyKey: key, signal, body: JSON.stringify({
    workflow_id: `creative-${key}`, task_id: 'geometric-study', brief, engine,
    scene: { primitives: [{ kind: 'rectangle', x: 160, y: 120, width: 400, height: 240 }] },
  }) }, RenderJobSchema);
}

export const resumeRenderJob = (project: string, job: string, signal?: AbortSignal) => apiFetch(`${base(project)}/${encodeURIComponent(job)}/resume`, { method: 'POST', signal }, RenderJobSchema);
