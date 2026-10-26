import {
  UcpoBuildTickSchema,
  UcpoCapabilitiesSchema,
  UcpoCompileResponseSchema,
  UcpoSiteListSchema,
  UcpoSiteViewSchema,
  UcpoTraceSchema,
  type UcpoCapabilities,
  type UcpoCompileResponse,
  type UcpoSiteView,
  type UcpoTrace,
  type UcpoWebsiteBrief,
} from '@amc/shared';
import { apiFetch } from './client';

// Website production line API (/ucpo). Responses are validated with the shared Zod twins.
// Compiling carries an Idempotency-Key; building runs one sandboxed durable tick. Nothing here deploys.

const idem = () => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);
const enc = encodeURIComponent;
const site = (projectId: string, siteId: string) => `/ucpo/projects/${enc(projectId)}/sites/${enc(siteId)}`;

export const getUcpoCapabilities = (): Promise<UcpoCapabilities> =>
  apiFetch('/ucpo/capabilities', { method: 'GET' }, UcpoCapabilitiesSchema);

export const listSites = (projectId: string) =>
  apiFetch(`/ucpo/projects/${enc(projectId)}/sites`, { method: 'GET' }, UcpoSiteListSchema).then((r) => r.sites);

export const compileSite = (projectId: string, siteId: string, brief: UcpoWebsiteBrief | unknown): Promise<UcpoCompileResponse> =>
  apiFetch(`/ucpo/projects/${enc(projectId)}/sites`, {
    method: 'POST', headers: { 'Idempotency-Key': idem() }, body: JSON.stringify({ site_id: siteId, brief }),
  }, UcpoCompileResponseSchema);

export const getSite = (projectId: string, siteId: string): Promise<UcpoSiteView> =>
  apiFetch(site(projectId, siteId), { method: 'GET' }, UcpoSiteViewSchema);

export const buildSite = (projectId: string, siteId: string) =>
  apiFetch(`${site(projectId, siteId)}/build`, { method: 'POST' }, UcpoBuildTickSchema);

export const traceRequirement = (projectId: string, siteId: string, reqId: string): Promise<UcpoTrace> =>
  apiFetch(`${site(projectId, siteId)}/trace/${enc(reqId)}`, { method: 'GET' }, UcpoTraceSchema);
