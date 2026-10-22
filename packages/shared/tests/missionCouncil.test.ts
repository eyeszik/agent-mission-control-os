import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  BlueprintSchema,
  CheckpointsSchema,
  EnginesResponseSchema,
  IdeaDetailSchema,
  IdeaPageSchema,
  IdeaSchema,
  MissionPageSchema,
  MissionSchema,
  TimelineSchema,
  ToolAuditSchema,
  ToolAuditListSchema,
  ToolsResponseSchema,
} from '../src/schemas/missionCouncil';

// Recorded from the real API by services/langgraph/tests/test_council_contracts.py.
const fixture = JSON.parse(readFileSync(join(__dirname, 'fixtures', 'mission-council.json'), 'utf-8'));

describe('Mission council Zod twins parse real backend responses', () => {
  const cases: [string, { parse: (v: unknown) => unknown }, unknown][] = [
    ['engines', EnginesResponseSchema, fixture.engines],
    ['tools', ToolsResponseSchema, fixture.tools],
    ['idea', IdeaSchema, fixture.idea],
    ['idea page', IdeaPageSchema, fixture.idea_page],
    ['idea detail', IdeaDetailSchema, fixture.idea_detail],
    ['paused mission', MissionSchema, fixture.mission_paused],
    ['completed mission', MissionSchema, fixture.mission_completed],
    ['mission page', MissionPageSchema, fixture.mission_page],
    ['timeline', TimelineSchema, fixture.timeline],
    ['checkpoints', CheckpointsSchema, fixture.checkpoints],
    ['blueprint', BlueprintSchema, fixture.blueprint],
  ];
  for (const [name, schema, value] of cases) {
    it(`parses the ${name}`, () => expect(() => schema.parse(value)).not.toThrow());
  }

  it('parses every tool audit row', () => {
    for (const row of fixture.tool_audits.items) expect(() => ToolAuditSchema.parse(row)).not.toThrow();
    expect(ToolAuditListSchema.parse(fixture.tool_audits).items.length).toBe(fixture.tool_audits.items.length);
  });

  it('records a paused gate and a completed, approved mission', () => {
    const paused = MissionSchema.parse(fixture.mission_paused);
    const done = MissionSchema.parse(fixture.mission_completed);
    expect(paused.status).toBe('needs_approval');
    expect(paused.approval?.status).toBe('pending');
    expect(done.status).toBe('completed');
    expect(done.decision?.decision).toBe('approve');
  });

  it('rejects an unknown engine or status', () => {
    expect(() => MissionSchema.parse({ ...fixture.mission_completed, engine: 'swarm' })).toThrow();
    expect(() => MissionSchema.parse({ ...fixture.mission_completed, status: 'resumed_and_completed' })).toThrow();
  });
});
