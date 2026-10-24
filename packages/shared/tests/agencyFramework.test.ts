import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  AfApplicabilityResultSchema,
  AfAssuranceListSchema,
  AfAssuranceRecordSchema,
  AfAuditSchema,
  AfCatalogSchema,
  AfGatesSchema,
  AfMetricsSchema,
  AfPlanListSchema,
  AfPlanViewSchema,
  AfTaskDefinitionSchema,
  AfTaskDetailSchema,
  AfTaskListSchema,
} from '../src/schemas/agencyFramework';

// Recorded from the real API by services/langgraph/tests/test_agency_framework_contracts.py.
const fixture = JSON.parse(readFileSync(join(__dirname, 'fixtures', 'agency-framework.json'), 'utf-8'));

describe('Agency framework Zod twins parse real backend responses', () => {
  const cases: [string, { parse: (v: unknown) => unknown }, unknown][] = [
    ['catalog', AfCatalogSchema, fixture.catalog],
    ['plan view', AfPlanViewSchema, fixture.plan_view],
    ['plan list', AfPlanListSchema, fixture.plan_list],
    ['task list', AfTaskListSchema, fixture.task_list],
    ['task detail', AfTaskDetailSchema, fixture.task_detail],
    ['applicability result', AfApplicabilityResultSchema, fixture.applicability],
    ['gates', AfGatesSchema, fixture.gates],
    ['audit', AfAuditSchema, fixture.audit],
    ['metrics', AfMetricsSchema, fixture.metrics],
    ['assurance list', AfAssuranceListSchema, fixture.assurance_list],
    ['assurance record', AfAssuranceRecordSchema, fixture.assurance_record],
  ];
  for (const [name, schema, value] of cases) {
    it(`parses the ${name}`, () => expect(() => schema.parse(value)).not.toThrow());
  }

  it('parses catalog task definitions', () => {
    for (const t of fixture.catalog_tasks.tasks) expect(() => AfTaskDefinitionSchema.parse(t)).not.toThrow();
  });

  it('records the 24-module, 295-task catalog and an honest plan', () => {
    const catalog = AfCatalogSchema.parse(fixture.catalog);
    expect(catalog.module_count).toBe(24);
    expect(catalog.task_count).toBe(295);
    expect(catalog.modules).toHaveLength(24);
    const view = AfPlanViewSchema.parse(fixture.plan_view);
    expect(view.progress.overall.defined).toBe(295);
    expect(view.readiness.release_eligible).toBe(false);
    expect(view.readiness.externally_executed).toBe(false);
    const detail = AfTaskDetailSchema.parse(fixture.task_detail);
    expect(detail.instance.state).toBe('APPROVED');
    expect(detail.instance.verification?.result).toBe('PASSED');
  });

  it('keeps unknown KPIs as NOT_MEASURED and synthetic ones labelled', () => {
    const metrics = AfMetricsSchema.parse(fixture.metrics);
    expect(metrics.metrics.some((m) => m.value === 'NOT_MEASURED')).toBe(true);
    const rate = metrics.metrics.find((m) => m.metric_id === 'acquisition.conversion_rate');
    expect(rate?.origin).toBe('SYNTHETIC');
  });
});
