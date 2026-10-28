import {
  BrandBookBuildSchema,
  BrandBookCompileSchema,
  BrandBookCurrentSchema,
  BrandBookGapsSchema,
  BrandBookIntakeSavedSchema,
  BrandBookIntakeSchema,
  BrandBookTemplateSchema,
  type BrandBookBuild,
  type BrandBookCompile,
  type BrandBookCurrent,
  type BrandBookGaps,
  type BrandBookIntake,
  type BrandBookMode,
  type BrandBookTemplate,
} from '@amc/shared';
import { apiFetch, apiFetchBlob } from './client';
import type { ProductionTarget, ScopeTarget } from './vnexus';

// VNEXUS brand book client. Every response is parsed with its Zod twin
// (packages/shared/src/schemas/vnexusBrandbook.ts). The book is a projection of the
// approved genome: approval is decided in the approval queue, release is a local record.

const enc = encodeURIComponent;
const key = () => (typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);
const qs = (t: ProductionTarget, mode?: BrandBookMode) =>
  `scope=${enc(t.scope)}&scope_ref=${enc(t.scope_ref)}&project_id=${enc(t.project_id)}${mode ? `&mode=${enc(mode)}` : ''}`;
const base = (brandId: string) => `/vnexus/brands/${enc(brandId)}/brandbook`;

export const getBookTemplate = (): Promise<BrandBookTemplate> =>
  apiFetch('/vnexus/brandbook/template', { method: 'GET' }, BrandBookTemplateSchema);

export const getBookGaps = (brandId: string, t: ProductionTarget, mode: BrandBookMode): Promise<BrandBookGaps> =>
  apiFetch(`${base(brandId)}/gaps?${qs(t, mode)}`, { method: 'GET' }, BrandBookGapsSchema);

export const compileBook = (brandId: string, t: ProductionTarget, mode: BrandBookMode): Promise<BrandBookCompile> =>
  apiFetch(`${base(brandId)}/compile`, { method: 'POST', body: JSON.stringify({ ...t, mode }) }, BrandBookCompileSchema);

export const buildBook = (brandId: string, t: ProductionTarget, mode: BrandBookMode): Promise<BrandBookBuild> =>
  apiFetch(`${base(brandId)}/builds`, { method: 'POST', idempotencyKey: key(), body: JSON.stringify({ ...t, mode }) }, BrandBookBuildSchema);

export const currentBook = (brandId: string, t: ProductionTarget, mode: BrandBookMode): Promise<BrandBookCurrent> =>
  apiFetch(`${base(brandId)}/builds/current?${qs(t, mode)}`, { method: 'GET' }, BrandBookCurrentSchema);

export const bookPreview = (brandId: string, t: ProductionTarget, mode: BrandBookMode, pageId: string) =>
  apiFetchBlob(`${base(brandId)}/pages/${enc(pageId)}/preview.png?${qs(t, mode)}`);

export const bookHtml = (brandId: string, t: ProductionTarget, mode: BrandBookMode) => apiFetchBlob(`${base(brandId)}/book.html?${qs(t, mode)}`);

export const bookPdf = (brandId: string, t: ProductionTarget) => apiFetchBlob(`${base(brandId)}/book.pdf?${qs(t)}`);

export interface BookApproval { status: 'PENDING' | 'BLOCKED'; approval_id?: string; reasons?: string[] }
export const requestBookApproval = (brandId: string, t: ProductionTarget): Promise<BookApproval> =>
  apiFetch(`${base(brandId)}/approval`, { method: 'POST', body: JSON.stringify(t) });

export interface BookRelease { status: 'RELEASED_LOCAL' | 'BLOCKED'; reasons: string[] }
export const releaseBook = (brandId: string, t: ProductionTarget, approvalId: string): Promise<BookRelease> =>
  apiFetch(`${base(brandId)}/release`, { method: 'POST', body: JSON.stringify({ ...t, approval_id: approvalId }) });

export const getIntake = (brandId: string): Promise<BrandBookIntake> =>
  apiFetch(`${base(brandId)}/intake`, { method: 'GET' }, BrandBookIntakeSchema);

export const saveIntake = (brandId: string, intake: unknown, expectedSha256: string | null) =>
  apiFetch(`${base(brandId)}/intake`, { method: 'PUT', body: JSON.stringify({ intake, expected_sha256: expectedSha256 }) },
    BrandBookIntakeSavedSchema);

export const proposeFromIntake = (brandId: string, t: ScopeTarget) =>
  apiFetch(`${base(brandId)}/intake/propose`, { method: 'POST', body: JSON.stringify(t) });
