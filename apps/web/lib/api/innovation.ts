import { InnovationDetailSchema, InnovationListSchema, InnovationGenerationStageSchema, InnovationLocalExperimentSchema, type InnovationBrief } from '@amc/shared';
import { apiFetch } from './client';

const base = (project: string) => `/innovation/projects/${encodeURIComponent(project)}/runs`;
const runPath = (project: string, run: string) => `${base(project)}/${encodeURIComponent(run)}`;
export const listInnovationRuns = (project: string, signal?: AbortSignal) =>
  apiFetch(`${base(project)}?limit=20&offset=0`, { signal }, InnovationListSchema);
export const getInnovationRun = (project: string, run: string, signal?: AbortSignal) =>
  apiFetch(runPath(project, run), { signal }, InnovationDetailSchema);
export const createInnovationRun = (project: string, brief: InnovationBrief, key: string, signal?: AbortSignal) =>
  apiFetch(base(project), { method: 'POST', idempotencyKey: key, body: JSON.stringify(brief), signal }, InnovationDetailSchema);
export const tickInnovationRun = (project: string, run: string, version: number, signal?: AbortSignal) =>
  apiFetch(`${runPath(project, run)}/tick`, { method: 'POST', body: JSON.stringify({ expected_version: version }), signal }, InnovationDetailSchema);
export const controlInnovationRun = (project: string, run: string, version: number, action: 'pause' | 'resume' | 'cancel', signal?: AbortSignal) =>
  apiFetch(`${runPath(project, run)}/control`, { method: 'POST', body: JSON.stringify({ expected_version: version, action }), signal }, InnovationDetailSchema);

export const getGenerationStage = (project: string, run: string, signal?: AbortSignal) =>
  apiFetch(`${runPath(project, run)}/generation`, { signal }, InnovationGenerationStageSchema);
export const prepareGenerationStage = (project: string, run: string, version: number, signal?: AbortSignal) =>
  apiFetch(`${runPath(project, run)}/generation`, { method: 'POST', body: JSON.stringify({ expected_version: version }), signal }, InnovationGenerationStageSchema);
export const tickGenerationStage = (project: string, run: string, version: number, signal?: AbortSignal) =>
  apiFetch(`${runPath(project, run)}/generation/tick`, { method: 'POST', body: JSON.stringify({ expected_version: version }), signal }, InnovationGenerationStageSchema);
export const getLocalExperiment = (project: string, run: string, version: number, signal?: AbortSignal) =>
  apiFetch(`${runPath(project, run)}/local-experiment?expected_version=${version}`, { signal }, InnovationLocalExperimentSchema);
export const runLocalExperiment = (project: string, run: string, version: number, signal?: AbortSignal) =>
  apiFetch(`${runPath(project, run)}/local-experiment`, { method: 'POST', body: JSON.stringify({ expected_version: version }), signal }, InnovationLocalExperimentSchema);
