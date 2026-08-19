import type { RunEvent } from '@amc/shared';
import { EventEmitter } from '../events/bus';

/**
 * Handles Server-Sent Events for live run status updates.
 */
export class SSEClient {
  private eventSource: EventSource | null = null;

  constructor(private runId: string, private bus: EventEmitter) {}

  connect() {
    if (this.eventSource) return;

    const base = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';
    this.eventSource = new EventSource(`${base}/runs/${this.runId}/events`);

    this.eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as RunEvent;
        this.bus.emit('run_event_received', data);
      } catch (err) {
        console.error('Failed to parse SSE message', err);
      }
    };

    this.eventSource.onerror = () => {
      console.warn('SSE connection lost, attempting reconnect...');
      // Reconnect logic would be scaffolded here via backoff
    };
  }

  disconnect() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }
}
