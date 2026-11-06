import {
  ActionPreviewSchema,
  ActionViewSchema,
  AnalyticsSchema,
  AttentionItemSchema,
  AuthorityTwinSchema,
  AutonomyResponseSchema,
  BudgetEnvelopeSchema,
  DriftReportSchema,
  FreezeListSchema,
  LooseRecordSchema,
  CatalogSnapshotSchema,
  ClientSchema,
  DeliverableSchema,
  DeliveryManifestSchema,
  EvidenceSchema,
  LifecycleSchema,
  LiveEnablementSchema,
  MissionPreviewSchema,
  MissionSummarySchema,
  RecoveryItemSchema,
  UncertaintyDebtSchema,
  type ActionEvidence,
  type ActionPreview,
  type ActionView,
  type AgencyAnalytics,
  type AgencyClient,
  type AttentionItem,
  type AuthorityTwin,
  type AutonomyLevel,
  type CatalogSnapshot,
  type Deliverable,
  type DeliveryManifest,
  type Lifecycle,
  type MissionPreview,
  type MissionSummary,
  type RecoveryItem,
} from '@amc/shared';
import { apiFetch, type RuntimeSchema } from './client';

// Agency OS client (/agency-os and /actions). Every response is parsed with its
// Zod twin (packages/shared/src/schemas/agencyOs.ts), so a drifted backend fails
// here, at the boundary, instead of rendering something wrong.

export function newKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

const enc = encodeURIComponent;
interface Parser<T> { parse(input: unknown): T }
const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
/** Parse `{ [key]: T }` and return the inner value. */
function wrap<T>(key: string, inner: Parser<T>): RuntimeSchema<T> {
  return { parse(input: unknown): T { if (!isObject(input) || !(key in input)) throw new Error(`agency-os: response missing '${key}'`); return inner.parse(input[key]); } };
}
function list<T>(inner: Parser<T>): Parser<T[]> {
  return { parse(input: unknown): T[] { if (!Array.isArray(input)) throw new Error('agency-os: expected a list'); return input.map((x) => inner.parse(x)); } };
}
const R = LooseRecordSchema;
const post = (body: unknown, idempotencyKey?: string) => ({ method: 'POST', body: JSON.stringify(body), ...(idempotencyKey ? { idempotencyKey } : {}) });

// ---- catalogue and governance
export const getCatalog = (): Promise<CatalogSnapshot> => apiFetch('/actions/catalog', { method: 'GET' }, CatalogSnapshotSchema);
export const getLive = () => apiFetch('/actions/live', { method: 'GET' }, LiveEnablementSchema);
export const getDrift = () => apiFetch('/actions/drift', { method: 'GET' }, DriftReportSchema);
export const getBudget = () => apiFetch('/actions/budget', { method: 'GET' }, BudgetEnvelopeSchema);
export const simulateBudget = (body: { scope_kind: string; scope_ref: string; currency: string; ceiling_minor: number }) =>
  apiFetch('/actions/budget/simulate', post(body), R);
export const getFreezes = () => apiFetch('/actions/freezes', { method: 'GET' }, FreezeListSchema);
export const getUncertainty = () => apiFetch('/actions/uncertainty', { method: 'GET' }, UncertaintyDebtSchema);
export const createFreeze = (body: { scope_kind: 'TENANT' | 'PROJECT'; scope_ref?: string; reason: string }) =>
  apiFetch('/actions/freezes', post(body), wrap('freeze', R));
export const liftFreeze = (freezeId: string, reason: string) =>
  apiFetch(`/actions/freezes/${enc(freezeId)}/lift`, post({ reason }), wrap('freeze', R));
const AutonomyResponse = AutonomyResponseSchema;
export const getAutonomy = (projectId: string) => apiFetch(`/actions/projects/${enc(projectId)}/autonomy`, { method: 'GET' }, AutonomyResponse);
export const setAutonomy = (projectId: string, autonomy: AutonomyLevel) =>
  apiFetch(`/actions/projects/${enc(projectId)}/autonomy`, { method: 'PUT', body: JSON.stringify({ autonomy }) }, AutonomyResponse);

// ---- governed actions
export interface ProposalInput {
  capability_id: string;
  project_id: string;
  environment: 'LOCAL' | 'SANDBOX' | 'LIVE';
  args: Record<string, unknown>;
  dependency_refs?: string[];
  ttl_seconds?: number;
}
export const previewAction = (body: ProposalInput): Promise<ActionPreview> => apiFetch('/actions/preview', post(body), ActionPreviewSchema);
export const proposeAction = (body: ProposalInput, idempotencyKey: string): Promise<ActionView> =>
  apiFetch('/actions', post(body, idempotencyKey), wrap('action', ActionViewSchema));
export const listActions = (projectId?: string): Promise<ActionView[]> =>
  apiFetch(`/actions${projectId ? `?project_id=${enc(projectId)}` : ''}`, { method: 'GET' }, wrap('actions', list(ActionViewSchema)));
export const getAction = (id: string): Promise<ActionView> => apiFetch(`/actions/${enc(id)}`, { method: 'GET' }, wrap('action', ActionViewSchema));
export const getEvidence = (id: string): Promise<ActionEvidence> => apiFetch(`/actions/${enc(id)}/evidence`, { method: 'GET' }, EvidenceSchema);
const actionOp = (id: string, op: string, body: unknown = {}) => apiFetch(`/actions/${enc(id)}/${op}`, post(body), wrap('action', ActionViewSchema));
export const dispatchAction = (id: string) => actionOp(id, 'dispatch');
export const cancelAction = (id: string, reason: string) => actionOp(id, 'cancel', { reason });
export const reconcileAction = (id: string) => actionOp(id, 'reconcile');
export const retryAction = (id: string) => actionOp(id, 'retry');
export const getRecovery = (): Promise<RecoveryItem[]> => apiFetch('/actions/recovery', { method: 'GET' }, wrap('items', list(RecoveryItemSchema)));

// ---- agency OS
export const getMe = (): Promise<AuthorityTwin> => apiFetch('/agency-os/me', { method: 'GET' }, AuthorityTwinSchema);
export const listClients = (): Promise<AgencyClient[]> => apiFetch('/agency-os/clients', { method: 'GET' }, wrap('clients', list(ClientSchema)));
export const createClient = (display_name: string, notes = ''): Promise<AgencyClient> =>
  apiFetch('/agency-os/clients', post({ display_name, notes }), wrap('client', ClientSchema));
export const linkProject = (clientId: string, projectId: string) =>
  apiFetch(`/agency-os/clients/${enc(clientId)}/projects`, post({ project_id: projectId }), wrap('link', R));
export const getOffboarding = (clientId: string) =>
  apiFetch(`/agency-os/clients/${enc(clientId)}/offboarding`, { method: 'GET' }, R);
export const startOffboarding = (clientId: string) =>
  apiFetch(`/agency-os/clients/${enc(clientId)}/offboarding`, post({}), wrap('client', ClientSchema));
export const archiveClient = (clientId: string) => apiFetch(`/agency-os/clients/${enc(clientId)}/archive`, post({}), wrap('client', ClientSchema));

export const previewMission = (brief: string, projectId: string): Promise<MissionPreview> =>
  apiFetch('/agency-os/missions/preview', post({ brief, project_id: projectId }), MissionPreviewSchema);
export const launchMission = (brief: string, projectId: string, idempotencyKey: string): Promise<MissionSummary> =>
  apiFetch('/agency-os/missions', post({ brief, project_id: projectId }, idempotencyKey), wrap('mission', MissionSummarySchema));
export const listMissions = (projectId: string) =>
  apiFetch(`/agency-os/projects/${enc(projectId)}/missions`, { method: 'GET' }, wrap('missions', list(R)));
export const requestRevision = (projectId: string, artifactId: string, note: string) =>
  apiFetch(`/agency-os/projects/${enc(projectId)}/revisions`, post({ artifact_id: artifactId, note }), wrap('revision', R));
export const getLifecycle = (projectId: string): Promise<Lifecycle> =>
  apiFetch(`/agency-os/projects/${enc(projectId)}/lifecycle`, { method: 'GET' }, LifecycleSchema);
export const getDeliverables = (projectId: string): Promise<Deliverable[]> =>
  apiFetch(`/agency-os/projects/${enc(projectId)}/deliverables`, { method: 'GET' }, wrap('deliverables', list(DeliverableSchema)));
export const exportManifest = (projectId: string, artifactIds: string[]): Promise<DeliveryManifest> =>
  apiFetch(`/agency-os/projects/${enc(projectId)}/deliverables/export`, post({ artifact_ids: artifactIds }), wrap('manifest', DeliveryManifestSchema));
export const getAttention = (): Promise<AttentionItem[]> => apiFetch('/agency-os/attention', { method: 'GET' }, wrap('items', list(AttentionItemSchema)));
export const getAnalytics = (projectId?: string): Promise<AgencyAnalytics> =>
  apiFetch(`/agency-os/analytics${projectId ? `?project_id=${enc(projectId)}` : ''}`, { method: 'GET' }, AnalyticsSchema);

// ---- project foundation (existing Project OS routes)
export const createFoundationArtifact = (projectId: string, artifactType: string, text: string) =>
  apiFetch(`/projects/${enc(projectId)}/artifacts`, post({ artifact_key: artifactType, artifact_type: artifactType, content_text: text }, newKey()),
    R);
export const canonizeBrand = (projectId: string, brandName: string, palette: Record<string, string>) =>
  apiFetch(`/projects/${enc(projectId)}/memory`, post({
    scope: 'M1_BRAND_CANON', authority: 'BRAND_CANON', subject_key: 'brand.identity',
    body: { brand_name: brandName, palette }, source_refs: ['art:brand_core:v1'],
  }), R);
