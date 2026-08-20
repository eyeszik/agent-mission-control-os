import { RunEventSchema, type RunEvent } from '@amc/shared';
import { EventEmitter } from '../events/bus';

const MAX_RECONNECT_ATTEMPTS = 6;
const BASE_RECONNECT_MS = 500;

/**
 * Cursor-aware SSE client. Every payload is runtime-validated before it enters
 * application state. The server remains the canonical source of replay order.
 */
export class SSEClient {
  private eventSource: EventSource | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  private stopped = false;
  private lastSequence = -1;

  constructor(private runId: string, private bus: EventEmitter) {
    if (typeof window !== 'undefined') {
      const stored = window.sessionStorage.getItem(this.storageKey());
      if (stored !== null && Number.isInteger(Number(stored))) {
        this.lastSequence = Number(stored);
      }
    }
  }

  private storageKey() {
    return `amc:sse:${this.runId}:sequence`;
  }

  private persistSequence(sequence: number) {
    this.lastSequence = Math.max(this.lastSequence, sequence);
    if (typeof window !== 'undefined') {
      window.sessionStorage.setItem(this.storageKey(), String(this.lastSequence));
    }
  }

  connect() {
    if (this.eventSource || this.stopped) return;

    const base = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';
    const cursor = encodeURIComponent(String(this.lastSequence));
    const source = new EventSource(`${base}/runs/${this.runId}/events?follow=true&cursor=${cursor}`);
    this.eventSource = source;

    source.onopen = () => {
      this.reconnectAttempts = 0;
    };

    source.onmessage = (event) => {
      try {
        const decoded: unknown = JSON.parse(event.data);
        const parsed = RunEventSchema.safeParse(decoded);
        if (!parsed.success) {
          console.error('Rejected invalid SSE payload', parsed.error.flatten());
          return;
        }
        const data: RunEvent = parsed.data;
        if (data.sequence <= this.lastSequence) return;
        this.persistSequence(data.sequence);
        this.bus.emit('run_event_received', data);
      } catch (err) {
        console.error('Failed to parse SSE message', err);
      }
    };

    source.onerror = () => {
      source.close();
      if (this.eventSource === source) this.eventSource = null;
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect() {
    if (this.stopped || this.reconnectTimer) return;
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      console.error('SSE reconnect limit reached');
      return;
    }
    const exponent = Math.min(this.reconnectAttempts, 5);
    const jitter = Math.floor(Math.random() * 250);
    const delay = BASE_RECONNECT_MS * 2 ** exponent + jitter;
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  disconnect() {
    this.stopped = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }
}
