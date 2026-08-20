import { AgencyRunSchema, type AgencyRun, type CampaignBrief } from '@amc/shared';
import { apiFetch } from './client';

export async function createAgencyRun(
  projectId: string,
  brief: CampaignBrief,
  idempotencyKey: string
): Promise<AgencyRun> {
  return apiFetch(
    '/agency/runs',
    {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, brief }),
      idempotencyKey,
    },
    AgencyRunSchema
  );
}

export async function getAgencyRun(runId: string): Promise<AgencyRun> {
  return apiFetch(`/agency/runs/${runId}`, { method: 'GET' }, AgencyRunSchema);
}

export async function resumeAgencyRun(runId: string, idempotencyKey: string): Promise<AgencyRun> {
  return apiFetch(
    `/agency/runs/${runId}/resume`,
    { method: 'POST', idempotencyKey },
    AgencyRunSchema
  );
}
