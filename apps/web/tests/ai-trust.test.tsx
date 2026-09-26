import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { AITrustEnvelope } from '../components/mission-control/AITrustEnvelope';
import { summarizeProvenance } from '../lib/ai/provenance';

const NOW = '2026-09-26T12:00:00+00:00';

function entry(task: string, mode: string, provider: string | null = null, model: string | null = null) {
  return {
    task,
    mode: mode as 'PROVIDER_SUCCESS',
    provider,
    model,
    schema_version: 'v1',
    prompt_version: 'v1',
    prompt_hash: 'h',
    attempts: 1,
    started_at: NOW,
    completed_at: NOW,
    fallback_used: mode !== 'PROVIDER_SUCCESS',
    error_class: null,
  };
}

describe('summarizeProvenance', () => {
  it('reports known provider output as AI-generated with the reported provider/model', () => {
    const summary = summarizeProvenance(
      [entry('brand_strategy', 'PROVIDER_SUCCESS', 'openai', 'gpt-4o-mini'), entry('copywriting', 'PROVIDER_SUCCESS', 'openai', 'gpt-4o-mini')],
      { pendingApproval: true }
    );
    expect(summary.involvement).toBe('AI_GENERATED');
    expect(summary.label).toBe('AI-generated');
    expect(summary.providers).toEqual(['openai / gpt-4o-mini']);
    expect(summary.reviewStatus).toBe('Awaiting human approval');
  });

  it('never infers provenance the backend did not report', () => {
    for (const input of [undefined, []]) {
      const summary = summarizeProvenance(input, { pendingApproval: false });
      expect(summary.involvement).toBe('UNKNOWN');
      expect(summary.label).toBe('AI involvement not reported');
      expect(summary.providers).toEqual([]);
    }
    const partial = summarizeProvenance([entry('x', 'PROVIDER_SUCCESS', 'openai', null), entry('y', 'PROVIDER_SUCCESS')], {
      pendingApproval: false,
    });
    expect(partial.providers).toEqual(['openai / model not disclosed', 'Provider not disclosed']);
  });

  it('labels degraded fallback output as not AI output', () => {
    const summary = summarizeProvenance([entry('brand_strategy', 'FALLBACK_DEGRADED'), entry('design_brief', 'PROVIDER_FAILED')], {
      pendingApproval: false,
    });
    expect(summary.involvement).toBe('FALLBACK_TEMPLATE');
    expect(summary.label).toBe('Fallback template — not AI output');
    expect(summary.tone).toBe('degraded');
    expect(summary.stages).toContain('design_brief: provider call failed; fallback used');
  });

  it('reports mixed runs as partial, counting stages', () => {
    const summary = summarizeProvenance([entry('a', 'PROVIDER_SUCCESS', 'p', 'm'), entry('b', 'FALLBACK_DEGRADED')], {
      pendingApproval: false,
    });
    expect(summary.label).toBe('Partially AI-generated (1 of 2 stages)');
  });

  it('never produces a numeric confidence', () => {
    const summary = summarizeProvenance([entry('a', 'PROVIDER_SUCCESS', 'p', 'm')], { pendingApproval: false });
    expect(summary.confidence).toBe('Confidence not measured');
  });
});

describe('AITrustEnvelope', () => {
  const summary = summarizeProvenance([entry('a', 'FALLBACK_DEGRADED'), entry('b', 'PROVIDER_SUCCESS', 'p', 'm')], {
    pendingApproval: true,
  });

  it('renders exactly one provenance scope even when nested', () => {
    const markup = renderToStaticMarkup(
      <AITrustEnvelope summary={summary}>
        <AITrustEnvelope summary={summary}>
          <p>response body</p>
        </AITrustEnvelope>
      </AITrustEnvelope>
    );
    expect(markup.match(/aria-label="AI provenance"/g)).toHaveLength(1);
    expect(markup).toContain('response body');
  });

  it('shows no fabricated confidence and states meaning in text, not color alone', () => {
    const markup = renderToStaticMarkup(<AITrustEnvelope summary={summary} />);
    expect(markup).not.toMatch(/\d+\s*%/);
    expect(markup).toContain('Confidence not measured');
    expect(markup).toContain('Partially AI-generated');
    expect(markup).toMatch(/<svg[^>]*aria-hidden="true"/);
  });

  it('uses a native, keyboard-operable disclosure with a visible focus ring', () => {
    const markup = renderToStaticMarkup(<AITrustEnvelope summary={summary} />);
    expect(markup).toContain('<details');
    expect(markup).toContain('<summary');
    expect(markup).toContain('focus-visible:ring-focus');
  });

  it('wraps on narrow layouts and has no motion', () => {
    const markup = renderToStaticMarkup(<AITrustEnvelope summary={summary} />);
    expect(markup).toContain('flex-wrap');
    expect(markup).toContain('break-words');
    expect(markup).not.toMatch(/animate-|transition/);
  });

  it('styles only through token classes', () => {
    const markup = renderToStaticMarkup(<AITrustEnvelope summary={summary} />);
    expect(markup).toContain('border-ai-trust-border');
    expect(markup).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(/i);
  });
});
