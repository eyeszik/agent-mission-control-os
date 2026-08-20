import {
  ApprovalDecisionResponseSchema,
  ApprovalListSchema,
  type ApprovalDecisionResponse,
  type ApprovalRequest,
} from '@amc/shared';
import { apiFetch } from './client';

export async function getPendingApprovals(): Promise<ApprovalRequest[]> {
  return apiFetch('/approvals', { method: 'GET' }, ApprovalListSchema);
}

export async function resolveApproval(
  approvalId: string,
  decision: 'approve' | 'reject',
  idempotencyKey: string
): Promise<ApprovalDecisionResponse> {
  return apiFetch(
    `/approvals/${approvalId}/decide`,
    {
      method: 'POST',
      body: JSON.stringify({ decision }),
      idempotencyKey,
    },
    ApprovalDecisionResponseSchema
  );
}
