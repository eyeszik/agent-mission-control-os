import { RunEventSchema, type RunEvent } from '@amc/shared';
import { ensureAccessToken } from '../auth/supabase';
import { readSession } from '../auth/session';
import { EventEmitter } from '../events/bus';
import { getAppConfig, usesSupabaseAuth } from '../config';
import { getLogger } from '../logger';

const MAX_RECONNECT_ATTEMPTS = 6;
const BASE_RECONNECT_MS = 500;

/**
 * Cursor-aware SSE client. Every payload is runtime-validated before it enters
 * application state. The server remains the canonical source of replay order.
 */
export class SSEClient {
  private streamController: AbortController | null = null;
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
    if (this.streamController || this.stopped) return;
    void this.openStream();
  }

  private async openStream() {
    const controller = new AbortController();
    this.streamController = controller;
    const config = getAppConfig();
    const base = config.apiBaseUrl;
    const cursor = encodeURIComponent(String(this.lastSequence));
    const headers = new Headers({ Accept: 'text/event-stream' });

    try {
      if (usesSupabaseAuth(config)) {
        const token = await ensureAccessToken();
        if (!token) throw new Error('Authentication required for event stream');
        headers.set('Authorization', `Bearer ${token}`);
        const tenantId = readSession()?.tenant_id;
        if (tenantId) headers.set('X-AMC-Tenant', tenantId);
      }

      const response = await fetch(`${base}/runs/${this.runId}/events?follow=true&cursor=${cursor}`, {
        method: 'GET',
        headers,
        signal: controller.signal,
        cache: 'no-store',
      });
      if (!response.ok || !response.body) {
        throw new Error(`Event stream request failed (${response.status})`);
      }

      this.reconnectAttempts = 0;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let dataLines: string[] = [];

      while (!this.stopped) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        while (true) {
          const newlineIndex = buffer.indexOf('\n');
          if (newlineIndex === -1) break;
          const rawLine = buffer.slice(0, newlineIndex);
          buffer = buffer.slice(newlineIndex + 1);
          const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;

          if (!line) {
            if (dataLines.length > 0) {
              this.handleMessage(dataLines.join('\n'));
              dataLines = [];
            }
            continue;
          }

          if (line.startsWith(':')) continue;
          if (line.startsWith('data:')) {
            dataLines.push(line.slice(5).trimStart());
          }
        }
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        getLogger().error('SSE stream failed', { run_id: this.runId, err });
        this.scheduleReconnect();
      }
    } finally {
      if (this.streamController === controller) this.streamController = null;
    }
  }

  private handleMessage(payload: string) {
    try {
      const decoded: unknown = JSON.parse(payload);
      const parsed = RunEventSchema.safeParse(decoded);
      if (!parsed.success) {
        getLogger().error('Rejected invalid SSE payload', { run_id: this.runId, issues: parsed.error.flatten() });
        return;
      }
      const data: RunEvent = parsed.data;
      if (data.sequence <= this.lastSequence) return;
      this.persistSequence(data.sequence);
      this.bus.emit('run_event_received', data);
    } catch (err) {
      getLogger().error('Failed to parse SSE message', { run_id: this.runId, err });
    }
  }

  private scheduleReconnect() {
    if (this.stopped || this.reconnectTimer) return;
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      getLogger().error('SSE reconnect limit reached', { run_id: this.runId });
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
    if (this.streamController) {
      this.streamController.abort();
      this.streamController = null;
    }
  }
}
