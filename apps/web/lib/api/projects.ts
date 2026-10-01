import {
  CalendarViewSchema,
  ContentItemResponseSchema,
  ContentItemsResponseSchema,
  CreatedProjectResponseSchema,
  MessageResponseSchema,
  MessagesResponseSchema,
  PortfolioSchema,
  ProjectArtifactsResponseSchema,
  ProjectDetailResponseSchema,
  ProjectEventsResponseSchema,
  ProjectListResponseSchema,
  ThreadResponseSchema,
  ThreadsResponseSchema,
  WorkspaceViewSchema,
  type ActivityType,
  type ContentState,
} from '@amc/shared';
import { apiFetch } from './client';

// Every project-OS response is validated against the shared contract
// (packages/shared/src/schemas/projectOs.ts), so backend/frontend drift fails
// at the boundary instead of rendering wrong.

function newKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

const project = (projectId: string) => `/projects/${encodeURIComponent(projectId)}`;

export const listProjects = () => apiFetch('/projects', { method: 'GET' }, ProjectListResponseSchema);

export const getProject = (projectId: string) => apiFetch(project(projectId), { method: 'GET' }, ProjectDetailResponseSchema);

export function createProject(input: { display_name: string; description?: string; brand_name?: string }) {
  return apiFetch('/projects', { method: 'POST', body: JSON.stringify(input), idempotencyKey: newKey() }, CreatedProjectResponseSchema);
}

export const listProjectEvents = (projectId: string, after = 0) =>
  apiFetch(`${project(projectId)}/events?after=${after}`, { method: 'GET' }, ProjectEventsResponseSchema);

export function listProjectArtifacts(projectId: string, filters: { media_type?: string; channel?: string; q?: string } = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const query = params.toString();
  return apiFetch(`${project(projectId)}/artifacts${query ? `?${query}` : ''}`, { method: 'GET' }, ProjectArtifactsResponseSchema);
}

export const getWorkspace = (projectId: string) => apiFetch(`${project(projectId)}/workspace`, { method: 'GET' }, WorkspaceViewSchema);

export const listThreads = (projectId: string) => apiFetch(`${project(projectId)}/threads`, { method: 'GET' }, ThreadsResponseSchema);

export const createThread = (projectId: string, title: string) =>
  apiFetch(`${project(projectId)}/threads`, { method: 'POST', body: JSON.stringify({ title }) }, ThreadResponseSchema);

export const listMessages = (projectId: string, threadId: string) =>
  apiFetch(`${project(projectId)}/threads/${encodeURIComponent(threadId)}/messages`, { method: 'GET' }, MessagesResponseSchema);

export function postMessage(projectId: string, threadId: string, body: string, activityType: ActivityType = 'MESSAGE') {
  return apiFetch(
    `${project(projectId)}/threads/${encodeURIComponent(threadId)}/messages`,
    { method: 'POST', body: JSON.stringify({ body, activity_type: activityType }) },
    MessageResponseSchema,
  );
}

export const listContentItems = (projectId: string) =>
  apiFetch(`${project(projectId)}/content/items`, { method: 'GET' }, ContentItemsResponseSchema);

export function transitionContentItem(projectId: string, itemId: string, target: ContentState, expectedVersion?: number) {
  return apiFetch(
    `${project(projectId)}/content/items/${encodeURIComponent(itemId)}/transition`,
    { method: 'POST', body: JSON.stringify({ target, expected_version: expectedVersion }) },
    ContentItemResponseSchema,
  );
}

export const getCalendar = (projectId: string) => apiFetch(`${project(projectId)}/calendar`, { method: 'GET' }, CalendarViewSchema);

export const getPortfolio = () => apiFetch('/portfolio', { method: 'GET' }, PortfolioSchema);

export type { CalendarView, Portfolio, PortfolioProject, WorkspaceView } from '@amc/shared';
