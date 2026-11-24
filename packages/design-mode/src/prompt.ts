/**
 * Twin of `agency/design/prompt_compiler.py`: one prompt line per resolved
 * dimension, so each dimension is described by exactly one style. Text only:
 * it never invokes a provider or writes an asset.
 */
import { pySorted } from '@amc/kernel';
import { pyCapitalize } from './python';
import { STYLE_DIMENSIONS } from './registry';

const BASELINE =
  'Maintain a disciplined hierarchy, strong readability, and brand-safe execution; ' +
  'avoid decorative noise, unreadable typography, and low-contrast composition.';

/** A brief as Python reads it (`brief.get(key)`); `null` is Python `None`. */
export type DesignBrief = Readonly<Record<string, string | null | undefined>>;

export interface PromptToken {
  readonly token?: string | null;
  readonly value?: string | null;
  readonly dimension?: string | null;
}

/** The slice of a composition the prompt reads (Python passes a dict). */
export interface PromptComposition {
  readonly resolved_tokens?: readonly PromptToken[];
  readonly production_notes?: readonly string[];
  readonly conflicts?: readonly string[];
}

function briefLine(brief: DesignBrief): string {
  const objective = brief['objective'] || 'Create a premium visual concept';
  const audience = brief['audience'] || 'the target audience';
  const format = brief['format'] || 'campaign visuals';
  return `Objective: ${objective}. Audience: ${audience}. Output format: ${format}.`;
}

type Grouped = Map<string, Map<string, string[]>>;

function groupTokens(tokens: readonly PromptToken[]): Grouped {
  const grouped: Grouped = new Map();
  for (const token of tokens) {
    const value = token.value ?? '';
    if (!value) continue;
    const dimension = token.dimension || 'style';
    const owner = token.token || '';
    const owners = grouped.get(dimension) ?? new Map<string, string[]>();
    grouped.set(dimension, owners);
    const values = owners.get(owner) ?? [];
    owners.set(owner, values);
    if (!values.includes(value)) values.push(value);
  }
  return grouped;
}

function dimensionSections(tokens: readonly PromptToken[]): string[] {
  const grouped = groupTokens(tokens);
  const known = [...STYLE_DIMENSIONS, 'style'].filter((d) => grouped.has(d));
  const ordered = [...known, ...pySorted([...grouped.keys()].filter((d) => !known.includes(d)))];
  const sections: string[] = [];
  for (const dimension of ordered) {
    const label = dimension === 'imagery' ? 'Identity' : pyCapitalize(dimension);
    for (const [owner, values] of grouped.get(dimension) ?? []) {
      sections.push(`${owner ? `${label} (${owner})` : label}: ${values.join(', ')}`);
    }
  }
  return sections;
}

/** Brief + per-dimension style system + production notes -> prompt text. */
export function compileDesignPrompt(brief: DesignBrief | null | undefined, composed: PromptComposition): string {
  const sections = dimensionSections(composed.resolved_tokens ?? []);
  const parts = [briefLine(brief ?? {})];
  parts.push(sections.length > 0 ? `Style system — ${sections.join('; ')}.` : 'Style system: a coherent premium design system.');
  const notes = (composed.production_notes ?? []).filter((note) => note);
  if (notes.length > 0) parts.push(`Production: ${notes.join('; ')}.`);
  parts.push(BASELINE);
  const conflicts = (composed.conflicts ?? []).filter((conflict) => conflict);
  if (conflicts.length > 0) {
    parts.push(`BLOCKED — resolve style conflicts before generation: ${conflicts.join('; ')}.`);
  }
  return parts.join(' ');
}

/** Python `compile_negative_prompt`: truthy tokens, first occurrence kept. */
export function compileNegativePrompt(negativeTokens: readonly string[]): string {
  return [...new Set(negativeTokens.filter((token) => token))].join(', ');
}
