import {
  AfApplicabilityResultSchema,
  AfAssuranceListSchema,
  AfAssuranceRecordSchema,
  AfAuditSchema,
  AfCatalogSchema,
  AfGatesSchema,
  AfInstanceSchema,
  AfMetricsSchema,
  AfPlanListSchema,
  AfPlanViewSchema,
  AfTaskDetailSchema,
  AfTaskListSchema,
  type AfApplicability,
  type AfApplicabilityResult,
  type AfArchetype,
  type AfAssuranceKind,
  type AfAssuranceRecord,
  type AfAssuranceRow,
  type AfCatalog,
  type AfGate,
  type AfMetrics,
  type AfPlanRecord,
  type AfPlanView,
  type AfTaskDetail,
  type AfTaskRow,
  type AfTaskState,
} from '@amc/shared';
import { apiFetch } from './client';

// Agency operating framework API (/agency-framework). Every response is runtime-
// validated with the shared Zod twins; writes carry an Idempotency-Key and task
// writes an expected_version, so a retried click is safe and a stale one is a 409.

const idem = () => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);
const base = '/agency-framework';
const enc = encodeURIComponent;

export const getCatalog = (): Promise<AfCatalog> => apiFetch(`${base}/catalog`, { method: 'GET' }, AfCatalogSchema);

export const listPlans = (projectId: string): Promise<AfPlanRecord[]> =>
  apiFetch(`${base}/plans?project_id=${enc(projectId)}`, { method: 'GET' }, AfPlanListSchema).then((r) => r.items);

export const createPlan = (body: { project_id: string; archetype: AfArchetype; engagement_scope: string }): Promise<AfPlanView> =>
  apiFetch(`${base}/plans`, { method: 'POST', body: JSON.stringify(body), idempotencyKey: idem() }, AfPlanViewSchema);

export const getPlan = (planId: string): Promise<AfPlanView> => apiFetch(`${base}/plans/${enc(planId)}`, { method: 'GET' }, AfPlanViewSchema);

export const listTasks = (planId: string, filters: { module_id?: string; state?: string; applicability?: string; q?: string }): Promise<AfTaskRow[]> => {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) if (v) params.set(k, v);
  return apiFetch(`${base}/plans/${enc(planId)}/tasks?${params.toString()}`, { method: 'GET' }, AfTaskListSchema).then((r) => r.items);
};

export const getTask = (planId: string, taskId: string): Promise<AfTaskDetail> =>
  apiFetch(`${base}/plans/${enc(planId)}/tasks/${enc(taskId)}`, { method: 'GET' }, AfTaskDetailSchema);

export const decideApplicability = (planId: string, decisions: { task_id: string; applicability: AfApplicability; reason: string }[]): Promise<AfApplicabilityResult> =>
  apiFetch(`${base}/plans/${enc(planId)}/applicability`, { method: 'POST', body: JSON.stringify({ decisions }), idempotencyKey: idem() }, AfApplicabilityResultSchema);

const taskWrite = (planId: string, taskId: string, action: string, body: unknown) =>
  apiFetch(`${base}/plans/${enc(planId)}/tasks/${enc(taskId)}/${action}`, { method: action === 'refs' ? 'PUT' : 'POST', body: JSON.stringify(body), idempotencyKey: idem() }, AfInstanceSchema);

export const transitionTask = (planId: string, taskId: string, target: AfTaskState, expectedVersion: number, reason = '') =>
  taskWrite(planId, taskId, 'transition', { target, expected_version: expectedVersion, reason });
export const unblockTask = (planId: string, taskId: string, expectedVersion: number) =>
  taskWrite(planId, taskId, 'unblock', { expected_version: expectedVersion });
export const setTaskRefs = (planId: string, taskId: string, expectedVersion: number, refs: { evidence_refs: string[]; artifact_refs: string[]; decision_refs: string[] }) =>
  taskWrite(planId, taskId, 'refs', { expected_version: expectedVersion, ...refs });
export const verifyTask = (planId: string, taskId: string, expectedVersion: number) =>
  taskWrite(planId, taskId, 'verify', { expected_version: expectedVersion });
export const requestTaskApproval = (planId: string, taskId: string, expectedVersion: number) =>
  taskWrite(planId, taskId, 'request-approval', { expected_version: expectedVersion });
export const settleTask = (planId: string, taskId: string, expectedVersion: number) =>
  taskWrite(planId, taskId, 'settle', { expected_version: expectedVersion });

export const revalidatePlan = (planId: string) =>
  apiFetch<{ invalidated: { task_id: string; reason: string }[]; staled_review_approvals: string[] }>(
    `${base}/plans/${enc(planId)}/revalidate`, { method: 'POST', idempotencyKey: idem() });

export const getGates = (planId: string): Promise<AfGate[]> =>
  apiFetch(`${base}/plans/${enc(planId)}/gates`, { method: 'GET' }, AfGatesSchema).then((r) => r.gates);

export const requestGateApproval = (planId: string, gate: string) =>
  apiFetch<{ approval: { approval_id: string; status: string }; gate: string; evaluation_hash: string }>(
    `${base}/plans/${enc(planId)}/gates/${enc(gate)}/request-approval`, { method: 'POST', idempotencyKey: idem() });

export const getAudit = (planId: string) => apiFetch(`${base}/plans/${enc(planId)}/audit?limit=100`, { method: 'GET' }, AfAuditSchema).then((r) => r.events);

export const getMetrics = (planId: string): Promise<AfMetrics> => apiFetch(`${base}/plans/${enc(planId)}/metrics`, { method: 'GET' }, AfMetricsSchema);

export const listAssurance = (planId: string, kind?: AfAssuranceKind): Promise<AfAssuranceRow[]> =>
  apiFetch(`${base}/plans/${enc(planId)}/assurance${kind ? `?kind=${kind}` : ''}`, { method: 'GET' }, AfAssuranceListSchema).then((r) => r.items);

export const getAssurance = (planId: string, recordId: string): Promise<AfAssuranceRecord> =>
  apiFetch(`${base}/plans/${enc(planId)}/assurance/${enc(recordId)}`, { method: 'GET' }, AfAssuranceRecordSchema);

export const createAssurance = (planId: string, kind: AfAssuranceKind, body: Record<string, unknown>): Promise<AfAssuranceRecord> =>
  apiFetch(`${base}/plans/${enc(planId)}/assurance/${kind}`, { method: 'POST', body: JSON.stringify(body), idempotencyKey: idem() }, AfAssuranceRecordSchema);
