import { apiFetch } from './client';
import type { ApprovalRequest } from '@amc/shared';

export async function getPendingApprovals(): Promise<{ data: ApprovalRequest[] }> {
  return apiFetch<{ data: ApprovalRequest[] }>('/approvals', {
    method: 'GET',
  });
}

export async function resolveApproval(approvalId: string, action: string, idempotencyKey: string): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(`/approvals/${approvalId}/resolve`, {
    method: 'POST',
    body: JSON.stringify({ action }),
    idempotencyKey,
  });
}
