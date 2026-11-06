import { RenderCapabilitiesSchema, RenderJobSchema, type RenderEngineId } from '@amc/shared';
import { apiFetch } from './client';
const base = (project: string) => `/foundry/projects/${encodeURIComponent(project)}/renders`;
export const renderCapabilities = (signal?: AbortSignal, project?: string | null) => apiFetch('/foundry/render-capabilities'+(project ? `?project_id=${encodeURIComponent(project)}` : ''), { signal }, RenderCapabilitiesSchema);
export const getRenderJob = (project: string, job: string, signal?: AbortSignal) => apiFetch(`${base(project)}/${encodeURIComponent(job)}`, { signal }, RenderJobSchema);
export const cancelRenderJob = (project: string, job: string, signal?: AbortSignal) => apiFetch(`${base(project)}/${encodeURIComponent(job)}/cancel`, { method: 'POST', signal }, RenderJobSchema);
export function submitRender(project: string, brief: string, engine: RenderEngineId, key: string, signal?: AbortSignal, format: 'svg'|'png'|'mp4'|'webm' = 'svg', frames = 30) {
  return apiFetch(base(project), { method: 'POST', idempotencyKey: key, signal, body: JSON.stringify({
    workflow_id: `creative-${key}`, task_id: 'geometric-study', brief, engine, output_format: format,
    clock: {total_frames: format==='mp4' || format==='webm' ? frames : 1},
    ...(format==='mp4' || format==='webm' ? {motion:{x:100,y:0}} : {}),
    scene: { primitives: [{ kind: 'rectangle', x: 160, y: 120, width: 400, height: 240 }] },
  }) }, RenderJobSchema);
}

export const resumeRenderJob = (project: string, job: string, signal?: AbortSignal) => apiFetch(`${base(project)}/${encodeURIComponent(job)}/resume`, { method: 'POST', signal }, RenderJobSchema);
