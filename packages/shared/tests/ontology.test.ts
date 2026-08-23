import { describe, it, expect } from 'vitest';
import {
  AGENCY_ARTIFACT_TYPES,
  ARTIFACT_TYPE_OWNER,
  DEPARTMENTS,
  DepartmentSchema,
  ONTOLOGY_VERSION,
  OntologySnapshotSchema,
  owningDepartment
} from '../src/schemas/ontology';
import {
  ARTIFACT_CLIENT_VISIBLE,
  ARTIFACT_TRANSITIONS,
  ArtifactStateSchema,
  ENGAGEMENT_TRANSITIONS,
  LIFECYCLE_VERSION,
  WORKSTREAM_TRANSITIONS,
  isDegradedProvenance
} from '../src/schemas/lifecycle';

describe('N1 department ontology', () => {
  it('rejects a department outside the closed vocabulary', () => {
    expect(DepartmentSchema.safeParse('growth').success).toBe(true);
    expect(DepartmentSchema.safeParse('marketing').success).toBe(false);
  });

  it('assigns exactly one owning department to every artifact type', () => {
    for (const artifactType of AGENCY_ARTIFACT_TYPES) {
      const owner = owningDepartment(artifactType);
      expect(DEPARTMENTS).toContain(owner);
    }
    expect(Object.keys(ARTIFACT_TYPE_OWNER).sort()).toEqual([...AGENCY_ARTIFACT_TYPES].sort());
  });

  it('validates a well-formed ontology snapshot', () => {
    const snapshot = {
      ontology_version: ONTOLOGY_VERSION,
      departments: [
        {
          department: 'copy',
          mandate: 'Write channel-ready language.',
          capabilities: ['copywriting'],
          owned_artifact_types: ['copy_variant'],
          release_reviewers: ['quality']
        }
      ]
    };
    expect(OntologySnapshotSchema.safeParse(snapshot).success).toBe(true);
  });

  it('rejects a snapshot carrying a different ontology version', () => {
    const result = OntologySnapshotSchema.safeParse({
      ontology_version: 'amc-agency-ontology/n1-v0',
      departments: []
    });
    expect(result.success).toBe(false);
  });
});

describe('N2 lifecycle matrices', () => {
  it('pins the lifecycle contract version', () => {
    expect(LIFECYCLE_VERSION).toBe('amc-agency-lifecycle/n2-v1');
  });

  it('declares transitions for every declared state', () => {
    for (const matrix of [ENGAGEMENT_TRANSITIONS, WORKSTREAM_TRANSITIONS, ARTIFACT_TRANSITIONS]) {
      for (const [state, targets] of Object.entries(matrix)) {
        expect(Array.isArray(targets), `${state} has no target list`).toBe(true);
        for (const target of targets) {
          expect(Object.keys(matrix)).toContain(target);
        }
      }
    }
  });

  it('keeps terminal artifact states terminal', () => {
    expect(ARTIFACT_TRANSITIONS.archived).toEqual([]);
  });

  it('does not allow a draft artifact to reach a client-visible state directly', () => {
    for (const visible of ARTIFACT_CLIENT_VISIBLE) {
      expect(ARTIFACT_TRANSITIONS.draft).not.toContain(visible);
    }
  });

  it('rejects an unknown artifact state', () => {
    expect(ArtifactStateSchema.safeParse('released').success).toBe(true);
    expect(ArtifactStateSchema.safeParse('shipped').success).toBe(false);
  });

  it('flags degraded provenance', () => {
    expect(isDegradedProvenance('FALLBACK_DEGRADED')).toBe(true);
    expect(isDegradedProvenance('PROVIDER_SUCCESS')).toBe(false);
    expect(isDegradedProvenance(null)).toBe(false);
    expect(isDegradedProvenance(undefined)).toBe(false);
  });
});
