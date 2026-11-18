/**
 * Twin of `agency/project_os/content.py`: one verified fact core, many
 * channel-native derivatives.
 *
 * Derivatives never invent facts: every section is built from atom claims and
 * names the claim ids it used. A derivative that uses an unverified or
 * contradicted claim carries a release blocker; it can be drafted but never
 * scheduled. This is structure, not copywriting: no model is called.
 */
import { z } from 'zod';
import { ClaimSchema, ContentAtomSchema, ContentVariantSpecSchema } from '@amc/shared';
import { compareCodePoints, pySorted } from '@amc/kernel';
import { ContentLineageError } from './errors';
import { canonicalSha256, type PyJson } from './json';
import { CONTENT_KINDS, own, parseEnum } from './vocabulary';
import type { ContentKind } from '@amc/shared';
import { pyStr } from '@amc/kernel';

export type Claim = z.infer<typeof ClaimSchema>;
export type ContentAtom = z.infer<typeof ContentAtomSchema>;
export type ContentVariantSpec = z.infer<typeof ContentVariantSpecSchema>;

export interface FormatRule {
  readonly sections: readonly string[];
  /** `null` = all claims. */
  readonly claims_per_unit: number | null;
  readonly verified_only: boolean;
  readonly constraints: readonly string[];
}

const rule = (
  sections: readonly string[],
  claimsPerUnit: number | null,
  constraints: readonly string[] = [],
  verifiedOnly = false,
): FormatRule => ({ sections, claims_per_unit: claimsPerUnit, verified_only: verifiedOnly, constraints });

/** Channel-native structure per content kind. `{claim}` is expanded once per claim the format uses. */
export const FORMAT_RULES: Readonly<Record<ContentKind, FormatRule>> = {
  article: rule(['headline', 'lede', '{claim}', 'sources'], null),
  email: rule(['subject', 'preheader', '{claim}', 'cta'], 3, ['subject<=60 chars', 'preheader<=100 chars']),
  newsletter: rule(['subject', 'intro', '{claim}', 'sign_off'], null, ['subject<=60 chars']),
  carousel: rule(['cover_slide', '{claim}', 'cta_slide'], 8, ['<=10 slides', 'one claim per slide']),
  social_post: rule(['hook', '{claim}', 'cta'], 1),
  thread: rule(['hook_post', '{claim}', 'closing_post'], 6, ['one claim per post']),
  video_script: rule(['cold_open', '{claim}', 'outro'], 5, ['spoken-word pacing']),
  short_video: rule(['hook_0_3s', '{claim}', 'end_card'], 2, ['<=60s', 'captions burned in']),
  reel: rule(['hook_0_3s', '{claim}', 'end_card'], 2, ['9:16', '<=90s']),
  story: rule(['frame', '{claim}', 'sticker_cta'], 3, ['9:16']),
  podcast_episode: rule(['intro', '{claim}', 'outro'], null),
  faq: rule(['{claim}'], null, ['question + direct answer per claim']),
  landing_section: rule(['heading', '{claim}', 'cta'], 3),
  // Answer engines and paid placements amplify claims: verified evidence only.
  ai_search_answer: rule(['direct_answer', '{claim}', 'citations'], null, ['cite every claim'], true),
  paid_creative: rule(['headline', '{claim}', 'cta'], 1, ['platform ad policy review'], true),
};

export const CHANNEL_LIMITS: Readonly<Record<string, string>> = {
  x: '<=280 chars per post',
  linkedin: '<=3000 chars',
  instagram: 'caption <=2200 chars',
  tiktok: 'caption <=2200 chars',
  youtube: 'title <=100 chars',
  email: 'subject <=60 chars',
  web: 'semantic HTML headings',
};

/** SHA-256 over the atom's title, claims and (sorted) source refs. */
export function atomHash(title: string, claims: readonly Claim[], sourceRefs: readonly string[]): string {
  const payload = {
    title,
    claims: claims.map((claim) => ({
      claim_id: claim.claim_id,
      text: claim.text,
      evidence_refs: claim.evidence_refs,
      verification: claim.verification,
    })),
    source_refs: pySorted(sourceRefs),
  };
  return canonicalSha256(payload as unknown as PyJson);
}

function eligibleClaims(atom: ContentAtom, formatRule: FormatRule): Claim[] {
  let claims = atom.claims.filter((claim) => claim.verification !== 'CONTRADICTED');
  if (formatRule.verified_only) claims = claims.filter((claim) => claim.verification === 'VERIFIED');
  return formatRule.claims_per_unit === null ? claims : claims.slice(0, formatRule.claims_per_unit);
}

function releaseBlockers(used: readonly Claim[]): string[] {
  const blockers = used.length === 0 ? ['NO_ELIGIBLE_CLAIMS'] : [];
  blockers.push(...used.filter((claim) => claim.verification !== 'VERIFIED').map((claim) => `UNVERIFIED_CLAIM:${claim.claim_id}`));
  blockers.push(...used.filter((claim) => claim.evidence_refs.length === 0).map((claim) => `CLAIM_WITHOUT_EVIDENCE:${claim.claim_id}`));
  return blockers;
}

export function deriveVariant(atom: ContentAtom, kind: string, channel: string): ContentVariantSpec {
  const contentKind = parseEnum('ContentKind', CONTENT_KINDS, kind);
  const formatRule = FORMAT_RULES[contentKind];
  const used = eligibleClaims(atom, formatRule);
  const limit = own(CHANNEL_LIMITS, channel);
  return {
    kind: contentKind,
    channel,
    title: `${atom.title} — ${contentKind} for ${channel}`,
    sections: formatRule.sections.flatMap((section) =>
      section === '{claim}' ? used.map((claim) => `claim:${claim.claim_id}`) : [section],
    ),
    claim_refs: used.map((claim) => claim.claim_id),
    constraints: limit === undefined ? [...formatRule.constraints] : [...formatRule.constraints, limit],
    atom_id: atom.atom_id,
    atom_version: atom.version,
    release_blockers: releaseBlockers(used),
  };
}

export function deriveVariants(atom: ContentAtom, targets: Iterable<readonly [string, string]>): ContentVariantSpec[] {
  return Array.from(targets, ([kind, channel]) => deriveVariant(atom, kind, channel));
}

/** A derivative may only cite claims that exist in its source atom version. */
export function assertLineage(atom: ContentAtom, variant: ContentVariantSpec): void {
  if (variant.atom_id !== atom.atom_id || variant.atom_version !== atom.version) {
    throw new ContentLineageError('variant does not derive from this atom version');
  }
  const known = new Set(atom.claims.map((claim) => claim.claim_id));
  const unknown = variant.claim_refs.filter((ref) => !known.has(ref));
  if (unknown.length > 0) {
    throw new ContentLineageError(`variant cites claims missing from the atom: ${pyStr(unknown)}`);
  }
}

export function evidenceFor(atom: ContentAtom, variant: ContentVariantSpec): Record<string, string[]> {
  assertLineage(atom, variant);
  const byId = new Map(atom.claims.map((claim) => [claim.claim_id, claim] as const));
  return Object.fromEntries(variant.claim_refs.map((ref) => [ref, [...(byId.get(ref)?.evidence_refs ?? [])]]));
}

export interface ExhaustionMap {
  readonly atom_id: string;
  readonly claim_usage: Readonly<Record<string, string[]>>;
  readonly unused_claims: string[];
  readonly untapped_formats: string[];
}

/** ContentExhaustionMap: which claims have been used, by which formats. */
export function exhaustionMap(atom: ContentAtom, produced: readonly ContentVariantSpec[]): ExhaustionMap {
  const usage = new Map<string, string[]>(atom.claims.map((claim) => [claim.claim_id, []]));
  for (const variant of produced) {
    for (const ref of variant.claim_refs) usage.get(ref)?.push(`${variant.kind}:${variant.channel}`);
  }
  const producedKinds = new Set(produced.map((variant) => variant.kind));
  return {
    atom_id: atom.atom_id,
    claim_usage: Object.fromEntries(usage),
    unused_claims: [...usage].filter(([, uses]) => uses.length === 0).map(([ref]) => ref).sort(compareCodePoints),
    untapped_formats: CONTENT_KINDS.filter((kind) => !producedKinds.has(kind)),
  };
}
