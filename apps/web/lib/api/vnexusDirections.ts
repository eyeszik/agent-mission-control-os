import {
  DirectionFreezeSchema,
  DirectionGenerateSchema,
  DirectionHandoffSchema,
  DirectionImportSchema,
  DirectionIntentCreatedSchema,
  DirectionIntentListSchema,
  DirectionReconstructionSchema,
  DirectionReviewSchema,
  DirectionRouteRegistrySchema,
  DirectionSelectionSchema,
  DirectionStateSchema,
  type DirectionBrief,
  type DirectionReviewMode,
} from '@amc/shared';
import { apiFetch, apiFetchBlob } from './client';
import type { ProductionTarget } from './vnexus';

// VNEXUS creative directions client. Every response is parsed with its Zod twin
// (packages/shared/src/schemas/vnexusDirections.ts). A review recommends; selection and the
// master are decided in the approval queue; hosted generation routes are disabled.

const enc = encodeURIComponent;
const key = () => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);
const base = (brandId: string) => `/vnexus/brands/${enc(brandId)}/directions/intents`;
const intentUrl = (brandId: string, intentId: string) => `${base(brandId)}/${enc(intentId)}`;
const post = (body: unknown, idempotent = false) => ({
  method: 'POST', body: JSON.stringify(body), ...(idempotent ? { idempotencyKey: key() } : {}),
});

export interface DirectionFindingInput {
  candidate: string;
  seat: string;
  criterion: string;
  evidence_class: 'OBSERVED' | 'INFERRED' | 'PROPOSED' | 'UNKNOWN';
  observation: string;
  severity?: 'BLOCKER' | 'MAJOR' | 'MINOR' | 'NOTE';
  proposed_change?: string;
  acceptance_check?: string;
  score?: number;
  gate?: string;
  gate_status?: 'PASS' | 'FAIL';
}

export const getDirectionRoutes = () => apiFetch('/vnexus/directions/routes', { method: 'GET' }, DirectionRouteRegistrySchema);

export const listDirectionIntents = (brandId: string, projectId: string) =>
  apiFetch(`${base(brandId)}?project_id=${enc(projectId)}`, { method: 'GET' }, DirectionIntentListSchema);

export const createDirectionIntent = (brandId: string, t: ProductionTarget, brief: Partial<DirectionBrief> & Pick<DirectionBrief, 'asset_role' | 'objective'>) =>
  apiFetch(base(brandId), post({ ...t, brief }, true), DirectionIntentCreatedSchema);

export const getDirectionState = (brandId: string, intentId: string, projectId: string) =>
  apiFetch(`${intentUrl(brandId, intentId)}?project_id=${enc(projectId)}`, { method: 'GET' }, DirectionStateSchema);

export const getDirectionHandoff = (brandId: string, intentId: string, projectId: string) =>
  apiFetch(`${intentUrl(brandId, intentId)}/handoff?project_id=${enc(projectId)}`, { method: 'GET' }, DirectionHandoffSchema);

export const generateDirections = (brandId: string, intentId: string, projectId: string, routeId: string) =>
  apiFetch(`${intentUrl(brandId, intentId)}/generate`, post({ project_id: projectId, route_id: routeId }, true), DirectionGenerateSchema);

export const importDirectionCandidate = (brandId: string, intentId: string, projectId: string, input: {
  slot: number; mime: 'image/png' | 'image/svg+xml'; data_base64: string; reported: Record<string, unknown>;
}) => apiFetch(`${intentUrl(brandId, intentId)}/candidates`, post({ project_id: projectId, ...input }, true), DirectionImportSchema);

export const directionCandidateContent = (brandId: string, intentId: string, projectId: string, candidateId: string) =>
  apiFetchBlob(`${intentUrl(brandId, intentId)}/candidates/${enc(candidateId)}/content?project_id=${enc(projectId)}`);

export const reviewDirections = (brandId: string, intentId: string, projectId: string, mode: DirectionReviewMode, candidateIds: string[],
  findings: DirectionFindingInput[], baseSessionId?: string) =>
  apiFetch(`${intentUrl(brandId, intentId)}/reviews`, post({
    project_id: projectId, mode, candidate_ids: candidateIds, findings, base_session_id: baseSessionId ?? null,
  }, true), DirectionReviewSchema);

export const getDirectionReview = (brandId: string, intentId: string, projectId: string, sessionId: string) =>
  apiFetch(`${intentUrl(brandId, intentId)}/reviews/${enc(sessionId)}?project_id=${enc(projectId)}`, { method: 'GET' }, DirectionReviewSchema);

export const requestDirectionSelection = (brandId: string, intentId: string, projectId: string, candidateId: string, sessionId: string) =>
  apiFetch(`${intentUrl(brandId, intentId)}/selection`, post({ project_id: projectId, candidate_id: candidateId, session_id: sessionId }),
    DirectionSelectionSchema);

export const reconstructDirection = (brandId: string, intentId: string, projectId: string, input: {
  candidate_id: string; method: 'controlled_trace' | 'native_path_import'; svg?: string; text_region?: [number, number, number, number];
}) => apiFetch(`${intentUrl(brandId, intentId)}/reconstructions`, post({ project_id: projectId, ...input }, true), DirectionReconstructionSchema);

export const freezeDirection = (brandId: string, intentId: string, projectId: string, masterCandidateId: string, sessionId: string) =>
  apiFetch(`${intentUrl(brandId, intentId)}/freeze`, post({ project_id: projectId, master_candidate_id: masterCandidateId, session_id: sessionId }),
    DirectionFreezeSchema);
