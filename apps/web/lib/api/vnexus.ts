import {
  ArtDirectionClaimSchema,
  AuditResponseSchema,
  BranchComparisonSchema,
  BranchSchema,
  BrandSchema,
  CompareResponseSchema,
  GenomeVersionSchema,
  GraphNodeSchema,
  GraphViewSchema,
  ImmuneScanSchema,
  ImpactSchema,
  MediaJobSchema,
  PromptInventorySchema,
  ProviderSchema,
  ReadinessSchema,
  ResolveResponseSchema,
  TwinSnapshotSchema,
  type ArtDirectionClaim,
  type AuditResponse,
  type BranchComparison,
  type ChangeSet,
  type CompareResponse,
  type GenomeDocument,
  type GenomeVersion,
  type GraphNode,
  type GraphView,
  type ImmuneScan,
  type Impact,
  type MediaJob,
  type MediaProvider,
  type PromptInventory,
  type Readiness,
  type ResolveResponse,
  type TwinSnapshot,
  type VnexusBranch,
  type VnexusBrand,
  type VnexusScope,
} from '@amc/shared';
import { apiFetch, type RuntimeSchema } from './client';

// VNEXUS client. Every response that has a Zod twin is parsed with it
// (packages/shared/src/schemas/vnexus.ts), so a drifted backend fails at the
// boundary. Production reports are large, evolving documents; they are
// checked for their top-level keys only and rendered defensively.

interface Parser<T> { parse(input: unknown): T }

function isObject(v: unknown): v is Record<string, unknown> { return typeof v === 'object' && v !== null && !Array.isArray(v); }

function field<T>(key: string, inner: Parser<T>): RuntimeSchema<T> {
  return { parse(input: unknown): T { if (!isObject(input) || !(key in input)) throw new Error(`vnexus: response missing '${key}'`); return inner.parse(input[key]); } };
}

function list<T>(inner: Parser<T>): Parser<T[]> {
  return { parse(input: unknown): T[] { if (!Array.isArray(input)) throw new Error('vnexus: expected a list'); return input.map((x) => inner.parse(x)); } };
}

function keys<T>(name: string, required: string[]): RuntimeSchema<T> {
  return { parse(input: unknown): T {
    if (!isObject(input)) throw new Error(`${name}: expected an object`);
    const missing = required.filter((k) => !(k in input));
    if (missing.length) throw new Error(`${name}: missing ${missing.join(', ')}`);
    return input as T;
  } };
}

const whole = <T>(p: Parser<T>): RuntimeSchema<T> => ({ parse: (v: unknown) => p.parse(v) });

function newKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

const enc = encodeURIComponent;
const post = (body: unknown, idempotent = false) => ({ method: 'POST', body: JSON.stringify(body), ...(idempotent ? { idempotencyKey: newKey() } : {}) });

export interface ScopeTarget { scope: VnexusScope; scope_ref: string }
export interface ProductionTarget extends ScopeTarget { project_id: string }

// ---------------------------------------------------------------- brands and genome versions
export const listBrands = () => apiFetch('/vnexus/brands', { method: 'GET' }, field('brands', list(BrandSchema)));
export const createBrand = (input: { brand_id: string; display_name: string; owner_project_id: string }) =>
  apiFetch('/vnexus/brands', post(input, true), field('brand', BrandSchema));
export const listVersions = (brandId: string) =>
  apiFetch(`/vnexus/brands/${enc(brandId)}/versions`, { method: 'GET' }, field('versions', list(GenomeVersionSchema)));
export const createVersion = (brandId: string, input: ScopeTarget & { document: GenomeDocument; experimental?: boolean }) =>
  apiFetch(`/vnexus/brands/${enc(brandId)}/versions`, post(input, true), field('version', GenomeVersionSchema));
export const getVersion = (versionId: string) => apiFetch(`/vnexus/versions/${enc(versionId)}`, { method: 'GET' }, field('version', GenomeVersionSchema));
export const editVersion = (versionId: string, expectedRevision: number, document: GenomeDocument) =>
  apiFetch(`/vnexus/versions/${enc(versionId)}`, { method: 'PUT', body: JSON.stringify({ expected_revision: expectedRevision, document }) },
    field('version', GenomeVersionSchema));
export const versionReadiness = (versionId: string) =>
  apiFetch(`/vnexus/versions/${enc(versionId)}/readiness`, { method: 'GET' }, field('readiness', ReadinessSchema));
export const submitVersion = (versionId: string) => apiFetch(`/vnexus/versions/${enc(versionId)}/submit`, post({}, true), field('version', GenomeVersionSchema));
export const withdrawVersion = (versionId: string) => apiFetch(`/vnexus/versions/${enc(versionId)}/withdraw`, post({}), field('version', GenomeVersionSchema));
export const settleVersion = (versionId: string) => apiFetch(`/vnexus/versions/${enc(versionId)}/settle`, post({}), field('version', GenomeVersionSchema));
export const revertVersion = (versionId: string) => apiFetch(`/vnexus/versions/${enc(versionId)}/revert`, post({}, true), field('version', GenomeVersionSchema));
export const compareVersions = (from: string, to: string) =>
  apiFetch(`/vnexus/compare?from=${enc(from)}&to=${enc(to)}`, { method: 'GET' }, whole(CompareResponseSchema));
export const resolveScope = (brandId: string, t: ScopeTarget, previewVersionId?: string) =>
  apiFetch(`/vnexus/brands/${enc(brandId)}/resolve?scope=${t.scope}&scope_ref=${enc(t.scope_ref)}${previewVersionId ? `&preview_version_id=${enc(previewVersionId)}` : ''}`,
    { method: 'GET' }, whole(ResolveResponseSchema));
export const auditTrail = (brandId: string) => apiFetch(`/vnexus/brands/${enc(brandId)}/audit`, { method: 'GET' }, whole(AuditResponseSchema));

// ---------------------------------------------------------------- graph
export const graphView = (brandId: string, asOf?: string) =>
  apiFetch(`/vnexus/brands/${enc(brandId)}/graph${asOf ? `?as_of=${enc(asOf)}` : ''}`, { method: 'GET' }, whole(GraphViewSchema));
export const addNode = (brandId: string, input: { kind: GraphNode['kind']; label: string; attributes: Record<string, unknown> }) =>
  apiFetch(`/vnexus/brands/${enc(brandId)}/graph/nodes`, post(input), field('node', GraphNodeSchema));
export const addEdge = (brandId: string, input: { kind: string; src_node_id: string; dst_node_id: string }) =>
  apiFetch(`/vnexus/brands/${enc(brandId)}/graph/edges`, post({ ...input, provenance: {} }), keys<{ edge: unknown }>('edge', ['edge']));
export const supersedeNode = (nodeId: string, input: { label: string; attributes: Record<string, unknown> }) =>
  apiFetch(`/vnexus/graph/nodes/${enc(nodeId)}/supersede`, post(input), field('node', GraphNodeSchema));
export const graphImpact = (brandId: string, nodeIds: string[]) =>
  apiFetch(`/vnexus/brands/${enc(brandId)}/graph/impact`, post({ node_ids: nodeIds }), whole(ImpactSchema));
export interface Evidence { node_id: string; considered: string[]; evidence: { node_id: string; label: string }[]; approvals: { node_id: string; label: string }[]; unsupported: boolean; history: string[] }
export const nodeEvidence = (nodeId: string) =>
  apiFetch(`/vnexus/graph/nodes/${enc(nodeId)}/evidence`, { method: 'GET' }, keys<Evidence>('evidence', ['evidence', 'approvals', 'history']));

// ---------------------------------------------------------------- multiverse
export const listBranches = (brandId: string) => apiFetch(`/vnexus/brands/${enc(brandId)}/branches`, { method: 'GET' }, field('branches', list(BranchSchema)));
export const forkBranch = (brandId: string, input: { base_version_id: string; name: string; hypothesis: string; changes: ChangeSet; parent_branch_id?: string }) =>
  apiFetch(`/vnexus/brands/${enc(brandId)}/branches`, post(input, true), field('branch', BranchSchema));
export const getBranch = (branchId: string) => apiFetch(`/vnexus/branches/${enc(branchId)}`, { method: 'GET' }, field('branch', BranchSchema));
export const compareBranch = (branchId: string) =>
  apiFetch(`/vnexus/branches/${enc(branchId)}/compare`, { method: 'GET' }, field('comparison', BranchComparisonSchema));
export interface TwoBranchComparison { comparable: boolean; reason?: string; only_a?: string[]; only_b?: string[]; agree?: string[]; conflicts?: { key: string }[]; mergeable?: boolean }
export const compareTwoBranches = (a: string, b: string) =>
  apiFetch(`/vnexus/branches/${enc(a)}/compare/${enc(b)}`, { method: 'GET' }, field('comparison', keys<TwoBranchComparison>('comparison', ['comparable'])));
export const evaluateBranch = (branchId: string) => apiFetch(`/vnexus/branches/${enc(branchId)}/evaluations`, post({}), keys<{ evaluation: unknown }>('evaluation', ['evaluation']));
export const branchFeedback = (branchId: string, text: string, decision?: 'prefer' | 'reject' | 'revise') =>
  apiFetch(`/vnexus/branches/${enc(branchId)}/feedback`, post({ text, decision }), keys<{ evaluation: unknown }>('evaluation', ['evaluation']));
export const mergeBranches = (a: string, b: string, name: string) =>
  apiFetch(`/vnexus/branches/${enc(a)}/merge`, post({ other_branch_id: b, name }, true), keys<{ branch: VnexusBranch }>('merge', ['branch']));
export const rebaseBranch = (branchId: string) => apiFetch(`/vnexus/branches/${enc(branchId)}/rebase`, post({}), keys<{ branch: VnexusBranch }>('rebase', ['branch']));
export const submitBranch = (branchId: string) =>
  apiFetch(`/vnexus/branches/${enc(branchId)}/submit`, post({}, true), keys<{ branch: VnexusBranch; proposal: GenomeVersion }>('submit', ['branch', 'proposal']));
export const settleBranch = (branchId: string) => apiFetch(`/vnexus/branches/${enc(branchId)}/settle`, post({}), field('branch', BranchSchema));
export const archiveBranch = (branchId: string) => apiFetch(`/vnexus/branches/${enc(branchId)}/archive`, post({}), field('branch', BranchSchema));

// ---------------------------------------------------------------- fabric
export const listProviders = () => apiFetch('/vnexus/fabric/providers', { method: 'GET' }, field('providers', list(ProviderSchema)));
export const listMediaJobs = (projectId: string) =>
  apiFetch(`/vnexus/projects/${enc(projectId)}/media-jobs`, { method: 'GET' }, field('jobs', list(MediaJobSchema)));
export const getMediaJob = (jobId: string) => apiFetch(`/vnexus/media-jobs/${enc(jobId)}`, { method: 'GET' }, field('job', MediaJobSchema));
export const jobAction = (jobId: string, action: 'authorize' | 'run' | 'retry' | 'cancel') =>
  apiFetch(`/vnexus/media-jobs/${enc(jobId)}/${action}`, post({}), field('job', MediaJobSchema));

// ---------------------------------------------------------------- production
export interface ProductionOutput { deliverable: string; name: string; capability: string; job_id: string; state: string; error: string | null; artifact_id: string | null; sha256: string | null; claimable_as_generated: boolean }
export interface Check { output?: string; check: string; status: 'PASSED' | 'FAILED' | 'NOT_RUN'; severity: string; detail: string }
export interface IdentityReport { kind: 'identity'; status: string; outputs: ProductionOutput[]; validations: Check[]; human_review_required: string[]; genome_ref: string }
export const produceIdentity = (brandId: string, t: ProductionTarget, deliverables: string[], copy: Record<string, string>) =>
  apiFetch(`/vnexus/brands/${enc(brandId)}/production/identity`, post({ ...t, deliverables, copy_text: copy }, true),
    keys<IdentityReport>('identity report', ['status', 'outputs', 'validations']));
export interface ExperienceReport { status: string; package: { stages: { stage: string; stage_hash: string; payload: Record<string, unknown> }[]; package_hash: string; assumptions: string[] }; stored: Record<string, string>; verification: { status: string; findings?: string[]; scenarios?: { id: string; passed: boolean }[]; reason?: string } }
export const produceExperience = (brandId: string, t: ProductionTarget, request: Record<string, unknown>) =>
  apiFetch(`/vnexus/brands/${enc(brandId)}/production/experience`, post({ ...t, request }, true), keys<ExperienceReport>('experience report', ['status', 'package', 'verification']));
export interface ArtDirectionReport { brief: { claims: ArtDirectionClaim[]; claim_counts: Record<string, number>; rubric: { criterion: string; method: string; how: string }[]; excluded_references: string[] }; artifact_id: string }
export const produceArtDirection = async (brandId: string, t: ProductionTarget, request: Record<string, unknown>) => {
  const out = await apiFetch(`/vnexus/brands/${enc(brandId)}/production/art-direction`, post({ ...t, request }, true), keys<ArtDirectionReport>('art direction', ['brief', 'artifact_id']));
  out.brief.claims.forEach((c) => ArtDirectionClaimSchema.parse(c));
  return out;
};
export interface VideoReport { status: string; label: string; stages: { script: { lines: { scene: string; on_screen: string }[]; placeholders: string[] }; shot_list: { shot_id: string; kind: string; duration_s: number; path: string }[]; render_jobs: { state: string; error: string | null; blocked_shots: { shot_id: string; error: string | null }[] }; audio: { status: string; reason?: string }; master: { status: string; deliverables: Record<string, string> }; quality_control: { checks?: { check: string; passed: boolean }[] } } }
export const produceVideo = (brandId: string, t: ProductionTarget, brief: Record<string, unknown>) =>
  apiFetch(`/vnexus/brands/${enc(brandId)}/production/video`, post({ ...t, brief }, true), keys<VideoReport>('video report', ['status', 'stages']));

// ---------------------------------------------------------------- intelligence
export interface CampaignPlan { plan: { plan_hash: string; segments: { segment_id: string; name: string; evidence: string }[]; messaging_matrix: { segment_id: string; stage: string; message: string; proof: unknown }[]; content_calendar: { date: string; channel: string; status: string; publishing: string }[]; experiments: { hypothesis_id: string; statement: string; sample_size_per_arm: number | null; sample_size_kind: string }[]; gaps: string[]; assumptions: string[] }; artifact_id: string }
export const planCampaign = (brandId: string, t: ProductionTarget, request: Record<string, unknown>) =>
  apiFetch(`/vnexus/brands/${enc(brandId)}/campaigns`, post({ ...t, request }, true), keys<CampaignPlan>('campaign', ['plan']));
export const recordMeasurement = (projectId: string, m: Record<string, unknown>) =>
  apiFetch(`/vnexus/projects/${enc(projectId)}/measurements`, post(m), keys<{ measurement: unknown }>('measurement', ['measurement']));
export interface CampaignReport { metrics: { metric: string; rate?: number | null; rate_kind?: string; value_kind?: string; numerator: { value: number | null; sources: string[] } }[]; note: string }
export const campaignReport = (projectId: string, ref: string) =>
  apiFetch(`/vnexus/projects/${enc(projectId)}/campaigns/${enc(ref)}/report`, { method: 'GET' }, field('report', keys<CampaignReport>('report', ['metrics'])));
export interface PromptRow { prompt_version_id: string; prompt_id: string; version: number; status: string; source_kind: string; source_hash: string | null; content_hash: string }
export const listPrompts = (brandId: string) =>
  apiFetch(`/vnexus/brands/${enc(brandId)}/prompts`, { method: 'GET' }, keys<{ prompts: PromptRow[]; inventory: PromptInventory }>('prompts', ['prompts', 'inventory']))
    .then((r) => ({ ...r, inventory: PromptInventorySchema.parse(r.inventory) }));
export const createPrompt = (brandId: string, promptId: string, document: Record<string, unknown>) =>
  apiFetch(`/vnexus/brands/${enc(brandId)}/prompts`, post({ prompt_id: promptId, document }), keys<{ prompt: PromptRow }>('prompt', ['prompt']));
export const importPrompt = (brandId: string, input: { prompt_id: string; text: string; source_ref: string }) =>
  apiFetch(`/vnexus/brands/${enc(brandId)}/prompts/import`, post(input), keys<{ prompt: PromptRow }>('prompt', ['prompt']));
export interface PromptCompileResult { final_state: string; missing_genome_keys: string[]; package_hash?: string | null; checks?: Record<string, boolean>; adapted?: { target: string; body: Record<string, unknown> } }
export const compilePrompt = (promptVersionId: string, t: ScopeTarget, adaptTo?: string) =>
  apiFetch(`/vnexus/prompts/${enc(promptVersionId)}/compile`, post({ ...t, adapt_to: adaptTo }), keys<PromptCompileResult>('compile', ['final_state']));
export const immuneScan = (brandId: string, t: ScopeTarget) => apiFetch(`/vnexus/brands/${enc(brandId)}/immune/scan`, post(t), whole(ImmuneScanSchema));
export const immuneRemediate = (brandId: string, t: ScopeTarget, findingIds: string[]) =>
  apiFetch(`/vnexus/brands/${enc(brandId)}/immune/remediate`, post({ ...t, finding_ids: findingIds }),
    keys<{ applied: Record<string, unknown>[]; refused: { finding_id: string; reason: string }[] }>('remediate', ['applied', 'refused']));
export const twinSnapshot = (brandId: string) => apiFetch(`/vnexus/brands/${enc(brandId)}/twin`, { method: 'GET' }, whole(TwinSnapshotSchema));
export interface TwinSimulation { projection: string; regeneration_needed: number; label: string; own: { invariant_violations: { kind: string; key: string }[] }; descendants: { scope_ref: string; new_conflicts: string[][]; newly_failed: string[] }[]; projected_drift: { label: string; would_fail: string[] }[] }
export const twinSimulate = (brandId: string, t: ScopeTarget, changes: ChangeSet) =>
  apiFetch(`/vnexus/brands/${enc(brandId)}/twin/simulate`, post({ ...t, changes }), keys<TwinSimulation>('twin', ['projection', 'label']));

export type { AuditResponse, BranchComparison, CompareResponse, GenomeDocument, GenomeVersion, GraphView, ImmuneScan, Impact, MediaJob,
  MediaProvider, Readiness, ResolveResponse, TwinSnapshot, VnexusBranch, VnexusBrand };
