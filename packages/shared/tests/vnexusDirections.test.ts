import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  CriterionAssessmentSchema,
  DirectionFreezeSchema,
  DirectionGenerateSchema,
  DirectionHandoffSchema,
  DirectionImportSchema,
  DirectionIntentCreatedSchema,
  DirectionIntentListSchema,
  DirectionReconstructionSchema,
  DirectionReviewSchema,
  DirectionRouteRegistrySchema,
  DirectionSelectionSchema,
  DirectionStateSchema,
  VectorReconstructionSchema,
} from '../src/schemas/vnexusDirections';

// Recorded from the real backend by services/langgraph/tests/test_vnexus_directions_contracts.py.
const fixture = JSON.parse(readFileSync(join(__dirname, 'fixtures', 'vnexus-directions.json'), 'utf-8'));

describe('VNEXUS creative-direction Zod twins parse real backend output', () => {
  const cases: [string, { parse: (v: unknown) => unknown }, unknown][] = [
    ['route registry', DirectionRouteRegistrySchema, fixture.routes],
    ['intent', DirectionIntentCreatedSchema, fixture.intent],
    ['blocked generation', DirectionGenerateSchema, fixture.blocked],
    ['local generation', DirectionGenerateSchema, fixture.generated],
    ['import', DirectionImportSchema, fixture.imported],
    ['handoff', DirectionHandoffSchema, fixture.handoff],
    ['compare review', DirectionReviewSchema, fixture.compare],
    ['selection', DirectionSelectionSchema, fixture.selection],
    ['reconstruction', DirectionReconstructionSchema, fixture.reconstruction],
    ['release review', DirectionReviewSchema, fixture.release],
    ['freeze', DirectionFreezeSchema, fixture.freeze],
    ['state', DirectionStateSchema, fixture.state],
    ['intent list', DirectionIntentListSchema, fixture.intents],
  ];
  for (const [name, schema, value] of cases) {
    it(`parses the ${name}`, () => expect(() => schema.parse(value)).not.toThrow());
  }

  it('keeps hosted routes disabled and the manual route offered, not executed', () => {
    const registry = DirectionRouteRegistrySchema.parse(fixture.routes);
    const cf = registry.routes.find((r) => r.route_id === 'cloudflare.workers_ai.text_to_image');
    expect(cf?.health).toBe('DISABLED');
    expect(cf?.price_per_job_minor).toBeNull();
    const blocked = DirectionGenerateSchema.parse(fixture.blocked);
    expect(blocked.status).toBe('BLOCKED');
    expect(blocked.decision.offer).toBe('manual.handoff');
    expect(blocked.candidates).toEqual([]);
  });

  it('separates recommendation, review effects and approval', () => {
    const { session } = DirectionReviewSchema.parse(fixture.compare);
    expect(session.recommendation.verdict).toBe('RECOMMENDED_DIRECTION');
    expect(session.recommendation.note).toMatch(/not an approval/);
    expect(Object.values(session.effects).every((v) => v === false)).toBe(true);
    expect(session.brand_memory.measured_recall).toBe('HUMAN_RECALL_NOT_TESTED');
  });

  it('refuses a fabricated score, a review that acted, and an unmeasured vector pass', () => {
    expect(() => CriterionAssessmentSchema.parse({
      candidate_id: 'c', criterion: 'silhouette', seat: '03', score: 0, status: 'NOT_REVIEWED', reason: '', finding_ids: [], assessors: [],
    })).toThrow();
    const acted = structuredClone(fixture.compare);
    acted.session.effects.approved = true;
    expect(() => DirectionReviewSchema.parse(acted)).toThrow();
    const rec = structuredClone(fixture.reconstruction.reconstruction);
    rec.fidelity = { status: 'NOT_RUN' };
    expect(() => VectorReconstructionSchema.parse(rec)).toThrow();
  });
});
