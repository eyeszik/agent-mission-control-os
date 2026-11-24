import { z } from 'zod';
import { UcpoCompileResponseSchema, UcpoSectionKindSchema } from './ucpo';

// Twin of agency/ucpo/brand_web_contracts.py; fixture recorded from the API.
const key = z.string().regex(/^(?:verbal\.messaging|strategy\.(?:positioning|audience))\.[a-z0-9_]+(?:\.[a-z0-9_]+)*$/);
const slug = z.string().regex(/^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$/);
const hash = z.string().regex(/^[a-f0-9]{64}$/);

export const BrandSectionMappingSchema = z.object({
  kind: UcpoSectionKindSchema, heading_key: key, body_key: key.nullable().default(null),
  label_key: key.nullable().default(null), cta: z.boolean().default(false),
  anchor: z.string().regex(/^[a-z][a-z0-9-]{0,39}$/).nullable().default(null),
  image: z.string().regex(/^[a-z0-9][a-z0-9-]{0,39}$/).nullable().default(null),
}).strict();
export const BrandPageMappingSchema = z.object({
  slug, title_key: key, description_key: key, sections: z.array(BrandSectionMappingSchema).min(1).max(10),
}).strict();
export const BrandImageMappingSchema = z.object({
  asset_id: z.string().regex(/^[a-z0-9][a-z0-9-]{0,39}$/), alt_key: key, motif_seed: z.number().int().min(0).max(10000).default(0),
}).strict();
export const BrandWebsiteMappingSchema = z.object({
  schema_version: z.literal('amc-brand-website-map/v1').default('amc-brand-website-map/v1'),
  organization_key: key.default('verbal.messaging.organization'), tagline_key: key.default('verbal.messaging.tagline'),
  offering_key: key.default('strategy.positioning.statement'), audience_key: key.default('strategy.audience.primary'),
  cta_label_key: key.default('verbal.messaging.cta'),
  cta_target: z.string().regex(/^[a-z0-9-]{1,40}(?:#[a-z0-9-]{1,40})?$/),
  locale: z.string().regex(/^[a-z]{2}(?:-[A-Z]{2})?$/).default('en'),
  pages: z.array(BrandPageMappingSchema).min(1).max(8),
  images: z.array(BrandImageMappingSchema).max(16).default([]),
  seed: z.number().int().min(0).max(2 ** 31 - 1).nullable().default(null),
}).strict().superRefine((mapping, ctx) => {
  if (new Set(mapping.pages.map((p) => p.slug)).size !== mapping.pages.length)
    ctx.addIssue({ code: 'custom', message: 'page slugs must be unique' });
  if (new Set(mapping.images.map((i) => i.asset_id)).size !== mapping.images.length)
    ctx.addIssue({ code: 'custom', message: 'image asset ids must be unique' });
});
export const BrandSiteRequestSchema = z.object({
  site_id: z.string().regex(/^[a-z0-9][a-z0-9-]{0,39}$/), brand_id: z.string().min(1).max(128),
  mapping: BrandWebsiteMappingSchema,
}).strict();
export type BrandSiteRequest = z.infer<typeof BrandSiteRequestSchema>;

const Layer = z.object({
  version_id: z.string(), version: z.number().int().positive(), content_hash: hash, approval_id: z.string(),
  scope: z.string(), scope_ref: z.string(),
}).strict();
export const BrandSiteResponseSchema = z.object({
  site: UcpoCompileResponseSchema,
  brand: z.object({ brand_id: z.string(), resolution_hash: hash, layers: z.array(Layer).min(1),
    keys_used: z.array(z.string()), unmapped_keys: z.array(z.string()), primary_accent: z.enum(['signal_red', 'amber']) }).strict(),
  handoff: z.object({ artifact_id: z.string(), version: z.number().int().positive(), content_hash: hash }).strict(),
  external_effects: z.literal('none'),
}).strict();
export type BrandSiteResponse = z.infer<typeof BrandSiteResponseSchema>;
