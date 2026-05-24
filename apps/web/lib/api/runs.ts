import { apiFetch } from './client';
import type { AgentRun } from '@amc/shared';

export async function createRun(projectId: string, tenantId: string, inputData: Record<string, unknown>, idempotencyKey: string): Promise<AgentRun> {
  return apiFetch<AgentRun>('/runs', {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId, tenant_id: tenantId, input_data: inputData }),
    idempotencyKey,
  });
}

export async function getRun(runId: string): Promise<AgentRun> {
  return apiFetch<AgentRun>(`/runs/${runId}`, {
    method: 'GET',
  });
}
