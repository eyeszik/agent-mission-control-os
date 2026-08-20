import { apiFetch } from './client';
import type { AgencyRun, CampaignBrief } from '@amc/shared';

export async function createAgencyRun(
  projectId: string,
  brief: CampaignBrief,
  idempotencyKey: string
): Promise<AgencyRun> {
  return apiFetch<AgencyRun>('/agency/runs', {
    method: 'POST',
    body: JSON.stringify({ project_id: projectId, brief }),
    idempotencyKey,
  });
}

export async function getAgencyRun(runId: string): Promise<AgencyRun> {
  return apiFetch<AgencyRun>(`/agency/runs/${runId}`, {
    method: 'GET',
  });
}

export async function resumeAgencyRun(runId: string, idempotencyKey: string): Promise<AgencyRun> {
  return apiFetch<AgencyRun>(`/agency/runs/${runId}/resume`, {
    method: 'POST',
    idempotencyKey,
  });
}
