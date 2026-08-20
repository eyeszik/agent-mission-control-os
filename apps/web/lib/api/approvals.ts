import { apiFetch } from './client';
import type { ApprovalRequest } from '@amc/shared';

export async function getPendingApprovals(): Promise<ApprovalRequest[]> {
  return apiFetch<ApprovalRequest[]>('/approvals', {
    method: 'GET',
  });
}

export async function resolveApproval(
  approvalId: string,
  decision: 'approve' | 'reject',
  idempotencyKey: string
): Promise<{
  approval_id: string;
  status: string;
  decision: string;
  reviewer: string;
  decided_at: string;
}> {
  return apiFetch(
    `/approvals/${approvalId}/decide`,
    {
      method: 'POST',
      body: JSON.stringify({ decision }),
      idempotencyKey,
    }
  );
}
