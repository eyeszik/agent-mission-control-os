import {
  OutboxReplayResponseSchema,
  RecoveryActionResponseSchema,
  RoleOSManifestSchema,
  RunRemediationResponseSchema,
  TrustSnapshotSchema,
  type OutboxReplayResponse,
  type RecoveryActionResponse,
  type RoleOSManifest,
  type RunRemediationResponse,
  type TrustSnapshot,
} from '@amc/shared';
import { apiFetch } from './client';

export async function getRoleOSManifest(): Promise<RoleOSManifest> {
  return apiFetch('/runtime/role-os', { method: 'GET' }, RoleOSManifestSchema);
}

export async function getProjectTrust(projectId: string): Promise<TrustSnapshot> {
  return apiFetch(`/runtime/projects/${projectId}/trust`, { method: 'GET' }, TrustSnapshotSchema);
}

export async function resolveRecoveryCase(
  projectId: string,
  recoveryId: string,
  status: 'RECONCILED' | 'COMPENSATED' | 'ESCALATED',
  idempotencyKey: string,
  runId?: string
): Promise<RecoveryActionResponse> {
  return apiFetch(
    `/runtime/projects/${projectId}/trust/recovery/${recoveryId}/resolve`,
    {
      method: 'POST',
      body: JSON.stringify({ status, run_id: runId }),
      idempotencyKey,
    },
    RecoveryActionResponseSchema
  );
}

export async function replayOutboxMessage(
  projectId: string,
  messageId: string,
  idempotencyKey: string,
  runId?: string
): Promise<OutboxReplayResponse> {
  return apiFetch(
    `/runtime/projects/${projectId}/trust/outbox/${messageId}/replay`,
    {
      method: 'POST',
      body: JSON.stringify({ run_id: runId }),
      idempotencyKey,
    },
    OutboxReplayResponseSchema
  );
}

export async function retryBlockedRun(
  runId: string,
  recoveryId: string,
  idempotencyKey: string
): Promise<RunRemediationResponse> {
  return apiFetch(
    `/runtime/runs/${runId}/remediation/retry`,
    {
      method: 'POST',
      body: JSON.stringify({ recovery_id: recoveryId }),
      idempotencyKey,
    },
    RunRemediationResponseSchema
  );
}

export async function compensateAmbiguousRun(
  runId: string,
  recoveryId: string,
  idempotencyKey: string
): Promise<RunRemediationResponse> {
  return apiFetch(
    `/runtime/runs/${runId}/remediation/compensate`,
    {
      method: 'POST',
      body: JSON.stringify({ recovery_id: recoveryId }),
      idempotencyKey,
    },
    RunRemediationResponseSchema
  );
}

export async function regenerateRunApproval(
  runId: string,
  approvalId: string | undefined,
  idempotencyKey: string
): Promise<RunRemediationResponse> {
  return apiFetch(
    `/runtime/runs/${runId}/remediation/regenerate-approval`,
    {
      method: 'POST',
      body: JSON.stringify({ approval_id: approvalId }),
      idempotencyKey,
    },
    RunRemediationResponseSchema
  );
}
