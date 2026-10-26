import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { AfPlanViewSchema } from '@amc/shared';
import { MANUAL_TRANSITIONS, parseRefs, ratioLabel, ratioPercent } from '../lib/framework/view';

const CONTRACTS = readFileSync(
  join(__dirname, '..', '..', '..', 'services', 'langgraph', 'agency', 'operating_framework', 'contracts.py'), 'utf-8');
const fixture = JSON.parse(readFileSync(
  join(__dirname, '..', '..', '..', 'packages', 'shared', 'tests', 'fixtures', 'agency-framework.json'), 'utf-8'));

function pythonTransitions(): Record<string, string[]> {
  const block = CONTRACTS.slice(CONTRACTS.indexOf('MANUAL_TRANSITIONS'), CONTRACTS.indexOf('# What a task must carry'));
  const out: Record<string, string[]> = {};
  for (const line of block.split('\n')) {
    const m = line.match(/TaskState\.([A-Z_]+)\.value: \((.*)\),/);
    if (m) out[m[1]] = [...m[2].matchAll(/TaskState\.([A-Z_]+)\.value/g)].map((x) => x[1]);
  }
  return out;
}

describe('agency framework view helpers', () => {
  it('offers exactly the manual transitions the server accepts', () => {
    expect(MANUAL_TRANSITIONS).toEqual(pythonTransitions());
  });

  it('never offers VERIFIED, APPROVED or INVALIDATED as a manual move', () => {
    for (const targets of Object.values(MANUAL_TRANSITIONS)) {
      expect(targets).not.toContain('VERIFIED');
      expect(targets).not.toContain('APPROVED');
      expect(targets).not.toContain('INVALIDATED');
    }
  });

  it('says Not measured instead of 0% or 100% when nothing is required', () => {
    const view = AfPlanViewSchema.parse(fixture.plan_view);
    const growth = view.progress.stage_gates['05_GROWTH'];
    expect(growth.required_verified_ratio).toBe('NOT_MEASURED');
    expect(ratioPercent(growth)).toBeNull();
    expect(ratioLabel(growth)).toMatch(/^Not measured/);
    const discovery = view.progress.stage_gates['01_DISCOVERY'];
    expect(ratioLabel(discovery)).toBe(`${discovery.required_verified} of ${discovery.required} required verified`);
  });

  it('parses one ref per line', () => {
    expect(parseRefs(' knowledge:a \n\nartifact:b@v1\n')).toEqual(['knowledge:a', 'artifact:b@v1']);
  });
});
