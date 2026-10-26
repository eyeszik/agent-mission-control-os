import {
  AvicApprovalResponseSchema,
  AvicAssetListSchema,
  AvicAssetViewSchema,
  AvicCapabilitiesSchema,
  AvicCompileResponseSchema,
  AvicEditResponseSchema,
  AvicRecompileResponseSchema,
  AvicReleaseResponseSchema,
  type AvicApprovalResponse,
  type AvicAssetView,
  type AvicCapabilities,
  type AvicCompileResponse,
  type AvicEditOp,
  type AvicEditResponse,
  type AvicRecompileResponse,
  type AvicReleaseResponse,
} from '@amc/shared';
import { apiFetch, apiFetchBlob } from './client';

// Visual compiler API (/avic). Responses are validated with the shared Zod twins. Writes carry an
// Idempotency-Key; an edit names the SVG it was made against, so a concurrent change is a 409, never
// an overwrite. Approval is decided in the approval queue; release is a local record with no effect.

const idem = () => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);
const enc = encodeURIComponent;
const assets = (projectId: string) => `/avic/projects/${enc(projectId)}/assets`;
const asset = (projectId: string, assetId: string) => `${assets(projectId)}/${enc(assetId)}`;

export const getAvicCapabilities = (): Promise<AvicCapabilities> =>
  apiFetch('/avic/capabilities', { method: 'GET' }, AvicCapabilitiesSchema);

export const listAssets = (projectId: string) =>
  apiFetch(assets(projectId), { method: 'GET' }, AvicAssetListSchema).then((r) => r.assets);

export const compileAsset = (projectId: string, requirement: unknown, styleProfile: string, seed: number): Promise<AvicCompileResponse> =>
  apiFetch(assets(projectId), {
    method: 'POST', idempotencyKey: idem(), body: JSON.stringify({ requirement, style_profile: styleProfile, seed }),
  }, AvicCompileResponseSchema);

export const getAsset = (projectId: string, assetId: string): Promise<AvicAssetView> =>
  apiFetch(asset(projectId, assetId), { method: 'GET' }, AvicAssetViewSchema);

export const fetchPreview = (projectId: string, assetId: string) => apiFetchBlob(`${asset(projectId, assetId)}/preview.png`);
export const fetchMasterSvg = (projectId: string, assetId: string) => apiFetchBlob(`${asset(projectId, assetId)}/master.svg`);

export const editAsset = (projectId: string, assetId: string, op: AvicEditOp, args: Record<string, unknown>,
  baseSvgSha256: string): Promise<AvicEditResponse> =>
  apiFetch(`${asset(projectId, assetId)}/edits`, {
    method: 'POST', idempotencyKey: idem(), body: JSON.stringify({ op, args, base_svg_sha256: baseSvgSha256 }),
  }, AvicEditResponseSchema);

export const recompileAsset = (projectId: string, assetId: string): Promise<AvicRecompileResponse> =>
  apiFetch(`${asset(projectId, assetId)}/recompile`, { method: 'POST', idempotencyKey: idem() }, AvicRecompileResponseSchema);

export const requestApproval = (projectId: string, assetId: string): Promise<AvicApprovalResponse> =>
  apiFetch(`${asset(projectId, assetId)}/approval`, { method: 'POST' }, AvicApprovalResponseSchema);

export const releaseLocal = (projectId: string, assetId: string, approvalId: string | null): Promise<AvicReleaseResponse> =>
  apiFetch(`${asset(projectId, assetId)}/release`, { method: 'POST', body: JSON.stringify({ approval_id: approvalId }) },
    AvicReleaseResponseSchema);
