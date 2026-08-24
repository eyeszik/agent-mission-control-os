import { RoleOSManifestSchema, TrustSnapshotSchema, type RoleOSManifest, type TrustSnapshot } from '@amc/shared';
import { apiFetch } from './client';

export async function getRoleOSManifest(): Promise<RoleOSManifest> {
  return apiFetch('/runtime/role-os', { method: 'GET' }, RoleOSManifestSchema);
}

export async function getProjectTrust(projectId: string): Promise<TrustSnapshot> {
  return apiFetch(`/runtime/projects/${projectId}/trust`, { method: 'GET' }, TrustSnapshotSchema);
}
