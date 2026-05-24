import { apiFetch } from './client';
import type { Artifact } from '@amc/shared';

export async function getArtifacts(runId: string): Promise<{ data: Artifact[] }> {
  return apiFetch<{ data: Artifact[] }>(`/runs/${runId}/artifacts`, {
    method: 'GET',
  });
}
