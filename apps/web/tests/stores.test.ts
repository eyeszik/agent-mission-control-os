import { describe, it, expect, beforeEach } from 'vitest';
import { useNodeStatusStore } from '../lib/stores/nodeStatusStore';

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
