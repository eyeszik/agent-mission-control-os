import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  ArtifactDiffSchema,
  ArtifactMetadataV2Schema,
  ArtifactVersionRecordSchema,
  AssetRightsSchema,
  BrandDriftReportSchema,
  CalendarSchema,
  ContentAtomSchema,
  ContentItemSchema,
  ContentVariantSpecSchema,
  ConversationMessageSchema,
  ConversationThreadSchema,
  GrowthExperimentSchema,
  KnowledgeCapsuleMetaSchema,
  MemoryRecordSchema,
  ProjectEventSchema,
  ProjectManifestSchema,
  ProjectSnapshotSchema,
  ProjectWorkspaceV2Schema,
  ProviderCapabilityProfileSchema,
  PublicationAttemptSchema,
  PublicationReceiptSchema,
  ReproducibilityRecordSchema,
  ScheduleCadenceSchema,
  ScheduledJobSchema,
  ScheduleSlotSchema,
  StorageObjectSchema,
  canTransitionContent,
  memoryAuthorityRank
} from '../src';

// Generated from the real Pydantic models by
// services/langgraph/tests/test_project_os_contracts.py, which fails on drift.
const fixture = JSON.parse(readFileSync(join(__dirname, 'fixtures', 'project-os.json'), 'utf-8'));

const schemas = {
  ProjectWorkspaceV2: ProjectWorkspaceV2Schema,
  ProjectManifest: ProjectManifestSchema,
  ProjectSnapshot: ProjectSnapshotSchema,
  ProjectEvent: ProjectEventSchema,
  StorageObject: StorageObjectSchema,
  ArtifactMetadataV2: ArtifactMetadataV2Schema,
  ArtifactVersionRecord: ArtifactVersionRecordSchema,
  ArtifactDiff: ArtifactDiffSchema,
  AssetRights: AssetRightsSchema,
  ConversationThread: ConversationThreadSchema,
  ConversationMessage: ConversationMessageSchema,
  ContentAtom: ContentAtomSchema,
  ContentVariantSpec: ContentVariantSpecSchema,
  ContentItem: ContentItemSchema,
  Calendar: CalendarSchema,
  ScheduleSlot: ScheduleSlotSchema,
  ScheduledJob: ScheduledJobSchema,
  ScheduleCadence: ScheduleCadenceSchema,
  PublicationAttempt: PublicationAttemptSchema,
  PublicationReceipt: PublicationReceiptSchema,
  MemoryRecord: MemoryRecordSchema,
  KnowledgeCapsuleMeta: KnowledgeCapsuleMetaSchema,
  ProviderCapabilityProfile: ProviderCapabilityProfileSchema,
  GrowthExperiment: GrowthExperimentSchema,
  BrandDriftReport: BrandDriftReportSchema,
  ReproducibilityRecord: ReproducibilityRecordSchema
} as const;

describe('project OS schemas parity with the Python contracts', () => {
  it('covers every model in the backend fixture', () => {
    expect(Object.keys(schemas).sort()).toEqual(Object.keys(fixture).sort());
  });

  for (const [name, schema] of Object.entries(schemas)) {
    it(`parses ${name}`, () => {
      expect(schema.safeParse(fixture[name]).success).toBe(true);
    });

    it(`${name} is strict like Pydantic extra="forbid"`, () => {
      expect(schema.safeParse({ ...fixture[name], unexpected_field: true }).success).toBe(false);
    });
  }

  it('enforces the content lifecycle and memory authority order', () => {
    expect(canTransitionContent('READY', 'SCHEDULED')).toBe(true);
    expect(canTransitionContent('IDEA', 'PUBLISHED')).toBe(false);
    expect(canTransitionContent('ARCHIVED', 'IDEA')).toBe(false);
    expect(memoryAuthorityRank('BRAND_CANON')).toBeGreaterThan(memoryAuthorityRank('WORKING_CONTEXT'));
  });

  it('never accepts an overwrite claim from a drift report', () => {
    expect(BrandDriftReportSchema.safeParse({ ...fixture.BrandDriftReport, autonomous_overwrites: 1 }).success).toBe(false);
  });
});
