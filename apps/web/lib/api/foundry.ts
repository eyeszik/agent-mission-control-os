import { apiFetch, apiFetchBlob, type RuntimeSchema } from './client';

// Creative Foundry client. Responses are checked at the boundary by small
// structural validators (the foundry contract is Python-owned and not yet in
// @amc/shared), so a drifted backend fails loudly instead of rendering wrong.

export type DeliverableType =
  | 'genome' | 'logo_family' | 'poster' | 'design_tokens' | 'website_section' | 'variants' | 'product_scene' | 'motion' | 'icon_family';

export const DELIVERABLES: readonly { id: DeliverableType; label: string; heavy?: boolean }[] = [
  { id: 'logo_family', label: 'Logo family + icons' },
  { id: 'poster', label: 'Brand poster (SVG + PNG)' },
  { id: 'design_tokens', label: 'Design tokens (DTCG + CSS)' },
  { id: 'variants', label: 'Three creative directions' },
  { id: 'website_section', label: 'Working website section' },
  { id: 'product_scene', label: '3D package scene', heavy: true },
  { id: 'motion', label: 'Logo reveal (MP4)', heavy: true },
];

export interface FoundryBrief {
  organization: string;
  offering: string;
  business_objective: string;
  target_audience: string;
  desired_action: string;
  deliverable_types: DeliverableType[];
  visual_direction: Record<string, number>;
  generation_intensity: 'conservative' | 'balanced' | 'exploratory';
  render_quality: 'draft' | 'standard';
  reference_assets: string[];
}

export interface Capability { capability_id: string; implementation: string; status: string; installed_version: string | null; blockers: string[] }
export interface Grammar { grammar_id: string; name: string; lineage_note: string; variation_axes: string[] }
export interface CapabilitiesResponse { capabilities: Capability[]; grammars: Grammar[]; discovery_adapters: { adapter_id: string; status: string }[] }
export interface Validation { check: string; level: string; passed: boolean | null; detail: string }
export interface MissionArtifact {
  deliverable: string; name: string; artifact_id: string; version: number; action: string; mime_type: string; sha256: string;
  bytes: number; invalidated: string[]; proof_state: string; blocked_at: string | null; validations: Validation[];
}
export interface MissionResponse {
  mission_id: string; genome_hash: string; genome_artifact: string; artifacts: MissionArtifact[];
  routes: { deliverable: string; selected: string; status: string; rejected: { route: string; reason: string }[] }[];
  capability_gaps: { deliverable: string; missing: string[]; blockers: string[] }[];
  assumptions: { field: string; value: unknown; reason: string }[]; external_effects: string;
}
export interface ApprovalResponse { approval: { approval_id: string; status: string; subject_hash?: string } }

function isObject(v: unknown): v is Record<string, unknown> { return typeof v === 'object' && v !== null && !Array.isArray(v); }

function shape<T>(name: string, keys: string[]): RuntimeSchema<T> {
  return {
    parse(input: unknown): T {
      if (!isObject(input)) throw new Error(`${name}: expected an object`);
      const missing = keys.filter((k) => !(k in input));
      if (missing.length) throw new Error(`${name}: missing ${missing.join(', ')}`);
      return input as T;
    },
  };
}

function newKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

const base = (projectId: string) => `/foundry/projects/${encodeURIComponent(projectId)}`;

export const getFoundryCapabilities = () =>
  apiFetch('/foundry/capabilities', { method: 'GET' }, shape<CapabilitiesResponse>('capabilities', ['capabilities', 'grammars']));

export function runFoundryMission(projectId: string, brief: FoundryBrief, copyText: Record<string, string> = {}) {
  return apiFetch(`${base(projectId)}/missions`, {
    method: 'POST', idempotencyKey: newKey(),
    body: JSON.stringify({ brief: { ...brief, deliverable_types: ['genome', ...brief.deliverable_types] }, copy_text: copyText }),
  }, shape<MissionResponse>('mission', ['mission_id', 'artifacts', 'routes', 'capability_gaps']));
}

export function createFoundryVariant(projectId: string, input: { dimensions: string[]; seed: number; edits?: Record<string, unknown> }) {
  return apiFetch(`${base(projectId)}/variants`, { method: 'POST', body: JSON.stringify({ ...input, edits: input.edits ?? {} }) },
    shape<{ status: string; artifact?: MissionArtifact & { proof: { state: string } }; candidate: { candidate_id: string; parents: string[]; mutations: unknown[] } }>('variant', ['status', 'candidate']));
}

export function requestFoundryApproval(projectId: string, artifactId: string, missionId: string) {
  return apiFetch(`${base(projectId)}/artifacts/${encodeURIComponent(artifactId)}/approval`,
    { method: 'POST', body: JSON.stringify({ mission_id: missionId }) }, shape<ApprovalResponse>('approval', ['approval']));
}

export async function fetchFoundryContent(projectId: string, artifactId: string) {
  return apiFetchBlob(`${base(projectId)}/artifacts/${encodeURIComponent(artifactId)}/content`);
}

/** Read a local file as base64 for the existing project upload route (rights start as unknown). */
export async function uploadReference(projectId: string, file: File): Promise<string> {
  const buffer = new Uint8Array(await file.arrayBuffer());
  let binary = '';
  for (let i = 0; i < buffer.length; i += 0x8000) binary += String.fromCharCode.apply(null, Array.from(buffer.subarray(i, i + 0x8000)));
  const key = `reference-${file.name.replace(/[^A-Za-z0-9._-]/g, '-').slice(0, 60)}-${Date.now()}`;
  const res = await apiFetch(`/projects/${encodeURIComponent(projectId)}/uploads`, {
    method: 'POST', idempotencyKey: newKey(),
    body: JSON.stringify({ artifact_key: key, content_base64: btoa(binary), v2: { mime_type: file.type || 'application/octet-stream' } }),
  }, shape<{ artifact: { artifact_id: string } }>('upload', ['artifact']));
  return res.artifact.artifact_id;
}

// ---- pure helpers (unit-tested) ------------------------------------------------------------

export const ZOOM_MIN = 0.25;
export const ZOOM_MAX = 4;

export function clampZoom(z: number): number {
  if (!Number.isFinite(z)) return 1;
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(z * 100) / 100));
}

export function directionWeights(primary: string, secondary: string | null, secondaryWeight: number): Record<string, number> {
  if (!secondary || secondary === primary || secondaryWeight <= 0) return { [primary]: 1 };
  const w = Math.min(0.9, Math.max(0.05, secondaryWeight));
  return { [primary]: Math.round((1 - w) * 100) / 100, [secondary]: Math.round(w * 100) / 100 };
}

export function proofTone(state: string): 'ok' | 'warn' | 'bad' {
  if (state === 'VERIFIED' || state === 'APPROVED' || state === 'RELEASE_ELIGIBLE' || state === 'APPROVAL_PENDING') return 'ok';
  if (state === 'OUTPUT_OBSERVED' || state === 'EXECUTED' || state === 'COMPILED') return 'bad';
  return 'warn';
}

export function isPreviewable(mime: string): 'image' | 'video' | 'html' | 'text' {
  if (mime.startsWith('image/')) return 'image';
  if (mime === 'video/mp4') return 'video';
  if (mime === 'text/html') return 'html';
  return 'text';
}
