import { BrowserCapabilities, ExtractionResult } from '@amc/shared';
import { apiFetch } from './client';
const base = (project: string) => `/browser/projects/${encodeURIComponent(project)}`;
export const browserCapabilities = (project: string) => apiFetch(`${base(project)}/capabilities`, {}, BrowserCapabilities);
export const extractHtml = (project: string, html: string, source_ref: string) => apiFetch(`${base(project)}/extractions`, { method: 'POST', body: JSON.stringify({ html, source_ref }) }, ExtractionResult);

export const extractUrl = (project: string, url: string) => apiFetch(`${base(project)}/extractions`, { method: 'POST', idempotencyKey: crypto.randomUUID(), body: JSON.stringify({ url, source_ref: url }) }, ExtractionResult);
