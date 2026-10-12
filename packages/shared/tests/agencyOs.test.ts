import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  ActionPreviewSchema,
  ActionStateSchema,
  ActionViewSchema,
  AnalyticsSchema,
  AttentionItemSchema,
  CatalogSnapshotSchema,
  ClientSchema,
  DeliverableSchema,
  DeliveryManifestSchema,
  EvidenceSchema,
  LifecycleSchema,
  MissionPreviewSchema,
  MissionSummarySchema,
  RecoveryItemSchema,
} from '../src/schemas/agencyOs';

// Recorded from the real API by services/langgraph/tests/test_ace12_contracts.py.
const fixture = JSON.parse(readFileSync(join(__dirname, 'fixtures', 'ace12.json'), 'utf-8'));

describe('ACE v12 Zod twins parse real backend responses', () => {
  const cases: [string, { parse: (v: unknown) => unknown }, unknown][] = [
    ['catalog', CatalogSnapshotSchema, fixture.catalog],
    ['action preview', ActionPreviewSchema, fixture.action_preview],
    ['action', ActionViewSchema, fixture.action],
    ['evidence', EvidenceSchema, fixture.evidence],
    ['recovery item', RecoveryItemSchema, fixture.recovery_item],
    ['client', ClientSchema, fixture.client],
    ['lifecycle', LifecycleSchema, fixture.lifecycle],
    ['attention item', AttentionItemSchema, fixture.attention_item],
    ['mission preview', MissionPreviewSchema, fixture.mission_preview],
    ['mission', MissionSummarySchema, fixture.mission],
    ['deliverable', DeliverableSchema, fixture.deliverable],
    ['manifest', DeliveryManifestSchema, fixture.manifest],
    ['analytics', AnalyticsSchema, fixture.analytics],
  ];
  it.each(cases)('%s', (_name, schema, value) => {
    expect(() => schema.parse(value)).not.toThrow();
  });

  it('rejects an unexpected field on a strict object (drift fails at the boundary)', () => {
    expect(() => ActionViewSchema.parse({ ...fixture.action, approved_by: 'me' })).toThrow();
  });

  it('records the truthful labels a person sees', () => {
    const action = ActionViewSchema.parse(fixture.action);
    expect(action.state).toBe('COMPLETED');
    expect(action.live_execution).toBe('DISABLED');
    expect(action.outcome?.simulated).toBe(true);
    const manifest = DeliveryManifestSchema.parse(fixture.manifest);
    expect(manifest.delivered_externally).toBe(false);
  });

  it('knows every action state', () => {
    expect(ActionStateSchema.options).toContain('RECONCILING');
    expect(ActionStateSchema.options).toContain('NEEDS_HUMAN');
  });
});
