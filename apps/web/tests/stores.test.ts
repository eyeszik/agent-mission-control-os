import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useApprovalStore } from '../lib/stores/approvalStore';
import { useArtifactStore } from '../lib/stores/artifactStore';

// We mock React hooks usage for now since we're just checking that the store acts independently.

describe('Zustand Stores', () => {
  beforeEach(() => {
    // Reset stores if necessary
    useApprovalStore.setState({ approvals: {} });
    useArtifactStore.setState({ artifacts: {}, selectedArtifactId: null });
  });

  it('useApprovalStore adds and removes approvals', () => {
    const store = useApprovalStore.getState();
    store.upsertApproval({
      id: 'test-1',
      description: 'Test approval',
      action_type: 'test',
      status: 'pending'
    });

    expect(useApprovalStore.getState().approvals['test-1']).toBeDefined();

    useApprovalStore.getState().removeApproval('test-1');
    expect(useApprovalStore.getState().approvals['test-1']).toBeUndefined();
  });
});
