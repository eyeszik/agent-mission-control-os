import { describe, it, expect, beforeEach } from 'vitest';
import { useNodeStatusStore } from '../lib/stores/nodeStatusStore';
import { useApprovalStore } from '../lib/stores/approvalStore';
import { useArtifactStore } from '../lib/stores/artifactStore';
import type { ApprovalRequest, Artifact } from '@amc/shared';

describe('Zustand State Stores', () => {
  describe('Node Status Store', () => {
    beforeEach(() => {
      useNodeStatusStore.setState({ statuses: {} });
    });

    it('should initialize with empty statuses', () => {
      expect(useNodeStatusStore.getState().statuses).toEqual({});
    });

    it('should update status for a specific run and node without mutating others', () => {
      const { updateNodeStatus } = useNodeStatusStore.getState();
      updateNodeStatus('run-a', 'brief_intake', 'completed');
      updateNodeStatus('run-a', 'brand_strategy', 'running');
      updateNodeStatus('run-b', 'brief_intake', 'failed');

      const { statuses } = useNodeStatusStore.getState();
      expect(statuses['run-a']).toEqual({ brief_intake: 'completed', brand_strategy: 'running' });
      expect(statuses['run-b']).toEqual({ brief_intake: 'failed' });

      updateNodeStatus('run-a', 'brand_strategy', 'completed');
      expect(useNodeStatusStore.getState().statuses['run-b']).toEqual({ brief_intake: 'failed' });
    });
  });
});


describe('Approval store regressions', () => {
  const approval = (approvalId: string): ApprovalRequest => ({
    approval_id: approvalId,
    run_id: 'run-1',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    reason: 'Manual review required',
    confidence: null,
    status: 'pending',
    reviewer: null,
    decision: null,
    created_at: '2026-01-01T00:00:00.000Z',
    decided_at: null,
  });

  beforeEach(() => {
    useApprovalStore.setState({ approvals: {} });
  });

  it('keys approvals by approval_id, not a legacy id field', () => {
    const first = approval('00000000-0000-4000-8000-000000000001');
    useApprovalStore.getState().upsertApproval(first);
    expect(useApprovalStore.getState().approvals[first.approval_id]).toEqual(first);
    expect(Object.keys(useApprovalStore.getState().approvals)).toEqual([first.approval_id]);
  });

  it('updates existing approvals without duplicating them', () => {
    const first = approval('00000000-0000-4000-8000-000000000002');
    useApprovalStore.getState().upsertApproval(first);
    useApprovalStore.getState().upsertApproval({ ...first, status: 'resolved', decision: 'approve' });
    expect(Object.keys(useApprovalStore.getState().approvals)).toHaveLength(1);
    expect(useApprovalStore.getState().approvals[first.approval_id].status).toBe('resolved');
  });

  it('removes only the requested approval', () => {
    const first = approval('00000000-0000-4000-8000-000000000003');
    const second = approval('00000000-0000-4000-8000-000000000004');
    useApprovalStore.getState().setApprovals([first, second]);
    useApprovalStore.getState().removeApproval(first.approval_id);
    expect(useApprovalStore.getState().approvals[first.approval_id]).toBeUndefined();
    expect(useApprovalStore.getState().approvals[second.approval_id]).toEqual(second);
  });

  it('setApprovals updates matching records and preserves unrelated approvals', () => {
    const first = approval('00000000-0000-4000-8000-000000000005');
    const second = approval('00000000-0000-4000-8000-000000000006');
    useApprovalStore.getState().upsertApproval(first);
    useApprovalStore.getState().setApprovals([second, { ...first, status: 'stale' }]);
    expect(useApprovalStore.getState().approvals[first.approval_id].status).toBe('stale');
    expect(useApprovalStore.getState().approvals[second.approval_id]).toEqual(second);
  });
});

describe('Artifact store regressions', () => {
  const artifact = (id: string): Artifact => ({
    id,
    run_id: '00000000-0000-4000-8000-000000000100',
    node_id: 'design_brief',
    type: 'document',
    content: 'Example deliverable',
    created_at: '2026-01-01T00:00:00.000Z',
  });

  beforeEach(() => {
    useArtifactStore.setState({ artifacts: {}, selectedArtifactId: null });
  });

  it('does not duplicate an artifact with the same id within a run', () => {
    const item = artifact('00000000-0000-4000-8000-000000000101');
    useArtifactStore.getState().addArtifact('run-a', item);
    const before = useArtifactStore.getState().artifacts;
    useArtifactStore.getState().addArtifact('run-a', item);
    expect(useArtifactStore.getState().artifacts['run-a']).toEqual([item]);
    expect(useArtifactStore.getState().artifacts).toBe(before);
  });

  it('keeps artifacts isolated by run and maintains independent selection', () => {
    const first = artifact('00000000-0000-4000-8000-000000000102');
    const second = artifact('00000000-0000-4000-8000-000000000103');
    useArtifactStore.getState().addArtifact('run-a', first);
    useArtifactStore.getState().addArtifact('run-b', second);
    useArtifactStore.getState().setSelectedArtifact(first.id);
    expect(useArtifactStore.getState().artifacts['run-a']).toEqual([first]);
    expect(useArtifactStore.getState().artifacts['run-b']).toEqual([second]);
    expect(useArtifactStore.getState().selectedArtifactId).toBe(first.id);
    useArtifactStore.getState().setSelectedArtifact(null);
    expect(useArtifactStore.getState().selectedArtifactId).toBeNull();
  });
});
