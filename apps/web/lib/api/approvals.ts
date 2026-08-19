import { apiFetch } from './client';
import type { ApprovalRequest } from '@amc/shared';

export async function getPendingApprovals(tenantId?: string): Promise<ApprovalRequest[]> {
  const query = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : '';
  return apiFetch<ApprovalRequest[]>(`/approvals${query}`, {
    method: 'GET',
  });
}

export async function resolveApproval(
  approvalId: string,
  reviewer: string,
  decision: 'approve' | 'reject',
  idempotencyKey: string
): Promise<{ approval_id: string; status: string; decision: string }> {
  return apiFetch<{ approval_id: string; status: string; decision: string }>(
    `/approvals/${approvalId}/decide`,
    {
      method: 'POST',
      body: JSON.stringify({ reviewer, decision }),
      idempotencyKey,
    }
  );
}
