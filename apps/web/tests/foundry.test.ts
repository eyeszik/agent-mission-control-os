import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  DELIVERABLES,
  ZOOM_MAX,
  ZOOM_MIN,
  clampZoom,
  directionWeights,
  isPreviewable,
  proofTone,
  runFoundryMission,
} from '../lib/api/foundry';

describe('foundry client helpers', () => {
  it('clamps zoom and survives garbage input', () => {
    expect(clampZoom(10)).toBe(ZOOM_MAX);
    expect(clampZoom(0)).toBe(ZOOM_MIN);
    expect(clampZoom(Number.NaN)).toBe(1);
    expect(clampZoom(1.234)).toBe(1.23);
  });

  it('builds normalised grammar weights', () => {
    expect(directionWeights('swiss_editorial', null, 0.4)).toEqual({ swiss_editorial: 1 });
    expect(directionWeights('swiss_editorial', 'swiss_editorial', 0.4)).toEqual({ swiss_editorial: 1 });
    expect(directionWeights('swiss_editorial', 'art_deco', 0.3)).toEqual({ swiss_editorial: 0.7, art_deco: 0.3 });
    expect(directionWeights('a', 'b', 5)).toEqual({ a: 0.1, b: 0.9 });
  });

  it('never presents an unverified proof as good', () => {
    expect(proofTone('VERIFIED')).toBe('ok');
    expect(proofTone('OUTPUT_OBSERVED')).toBe('bad');
    expect(proofTone('SPECIFIED')).toBe('warn');
  });

  it('classifies previews by MIME type', () => {
    expect(isPreviewable('image/svg+xml')).toBe('image');
    expect(isPreviewable('video/mp4')).toBe('video');
    expect(isPreviewable('text/html')).toBe('html');
    expect(isPreviewable('application/json')).toBe('text');
    expect(DELIVERABLES.filter((d) => d.heavy).map((d) => d.id)).toEqual(['product_scene', 'motion']);
  });
});

describe('runFoundryMission', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('always includes the genome, sends an idempotency key and rejects a drifted response', async () => {
    const calls: RequestInit[] = [];
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
      calls.push(init);
      return new Response(JSON.stringify({ unexpected: true }), { status: 201 });
    }));
    const brief = {
      organization: 'Halden & Fen', offering: '', business_objective: '', target_audience: '', desired_action: '',
      deliverable_types: ['poster' as const], visual_direction: { swiss_editorial: 1 }, generation_intensity: 'balanced' as const,
      render_quality: 'draft' as const, reference_assets: [],
    };
    await expect(runFoundryMission('prj-1', brief)).rejects.toThrow(/mission: missing/);
    const body = JSON.parse(String(calls[0].body));
    expect(body.brief.deliverable_types).toEqual(['genome', 'poster']);
    expect(new Headers(calls[0].headers).get('Idempotency-Key')).toBeTruthy();
  });
});
