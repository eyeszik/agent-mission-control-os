import {
  BlueprintSchema,
  CheckpointsSchema,
  EnginesResponseSchema,
  IdeaDetailSchema,
  IdeaPageSchema,
  IdeaSchema,
  MissionPageSchema,
  MissionSchema,
  TimelineSchema,
  ToolAuditListSchema,
  ToolsResponseSchema,
  type Blueprint,
  type Checkpoints,
  type CouncilEngine,
  type EnginesResponse,
  type Idea,
  type IdeaDetail,
  type IdeaPage,
  type Mission,
  type MissionPage,
  type ToolAudit,
  type ToolsResponse,
} from '@amc/shared';
import { apiFetch } from './client';

// Mission council API (/missions). Every response is runtime-validated with the
// shared Zod twins; writes carry an Idempotency-Key so a retried click is safe.

const idem = () => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);

export const getEngines = (): Promise<EnginesResponse> => apiFetch('/missions/engines', { method: 'GET' }, EnginesResponseSchema);
export const getTools = (): Promise<ToolsResponse> => apiFetch('/missions/tools', { method: 'GET' }, ToolsResponseSchema);

export const listIdeas = (projectId: string): Promise<IdeaPage> =>
  apiFetch(`/missions/ideas?project_id=${encodeURIComponent(projectId)}&limit=50`, { method: 'GET' }, IdeaPageSchema);

export const getIdea = (ideaId: string): Promise<IdeaDetail> =>
  apiFetch(`/missions/ideas/${encodeURIComponent(ideaId)}`, { method: 'GET' }, IdeaDetailSchema);

export const createIdea = (body: { project_id: string; title: string; description: string }): Promise<Idea> =>
  apiFetch('/missions/ideas', { method: 'POST', body: JSON.stringify(body), idempotencyKey: idem() }, IdeaSchema);

export const dispatchMission = (body: { idea_id: string; engine: CouncilEngine; materialize_scaffold: boolean }): Promise<Mission> =>
  apiFetch('/missions/dispatch', { method: 'POST', body: JSON.stringify(body), idempotencyKey: idem() }, MissionSchema);

export const listMissions = (projectId: string): Promise<MissionPage> =>
  apiFetch(`/missions?project_id=${encodeURIComponent(projectId)}&limit=50`, { method: 'GET' }, MissionPageSchema);

export const getMission = (missionId: string): Promise<Mission> =>
  apiFetch(`/missions/${encodeURIComponent(missionId)}`, { method: 'GET' }, MissionSchema);

export const getTimeline = (missionId: string) =>
  apiFetch(`/missions/${encodeURIComponent(missionId)}/timeline?limit=500`, { method: 'GET' }, TimelineSchema);

export const getCheckpoints = (missionId: string): Promise<Checkpoints> =>
  apiFetch(`/missions/${encodeURIComponent(missionId)}/checkpoints`, { method: 'GET' }, CheckpointsSchema);

type MissionAction = 'resume' | 'cancel' | 'retry' | 'recover';
export const missionAction = (missionId: string, action: MissionAction): Promise<Mission> =>
  apiFetch(`/missions/${encodeURIComponent(missionId)}/${action}`, { method: 'POST', idempotencyKey: idem() }, MissionSchema);

export const extractBlueprint = (ideaId: string): Promise<Blueprint> =>
  apiFetch(`/missions/ideas/${encodeURIComponent(ideaId)}/blueprints`, { method: 'POST', idempotencyKey: idem() }, BlueprintSchema);

export const promoteBlueprint = (blueprintId: string): Promise<Blueprint> =>
  apiFetch(`/missions/blueprints/${encodeURIComponent(blueprintId)}/promote`, { method: 'POST', idempotencyKey: idem() }, BlueprintSchema);

export const getToolAudits = (missionId: string): Promise<ToolAudit[]> =>
  apiFetch(`/missions/${encodeURIComponent(missionId)}/tool-audits`, { method: 'GET' }, ToolAuditListSchema).then((r) => r.items);
