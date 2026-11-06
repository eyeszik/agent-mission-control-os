import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { TimelineSchema, type TimelineEvent } from '@amc/shared';
import { deriveCouncil, describeEvent, fromStream, mergeEvents } from '../lib/missions/council';

// A real completed mission timeline recorded from the backend.
const fixture = JSON.parse(
  readFileSync(join(__dirname, '..', '..', '..', 'packages', 'shared', 'tests', 'fixtures', 'mission-council.json'), 'utf-8'),
);
const recorded: TimelineEvent[] = TimelineSchema.parse(fixture.timeline).events;

describe('mission council timeline view-model', () => {
  it('derives seat and gate state from a real completed mission', () => {
    const view = deriveCouncil(recorded);
    expect(view.seats).toEqual({ george: 'done', fable: 'done', arty: 'done' });
    expect(view.gate).toBe('approved');
    expect(view.terminal).toBe('completed');
    expect(view.lastSequence).toBe(recorded[recorded.length - 1].sequence);
  });

  it('shows a seat running only after its SEAT_STARTED event, and the gate pending at the pause', () => {
    const upToGate = recorded.slice(0, recorded.findIndex((e) => e.event_type === 'APPROVAL_REQUIRED') + 1);
    const view = deriveCouncil(upToGate);
    expect(view.seats).toEqual({ george: 'done', fable: 'done', arty: 'waiting' });
    expect(view.gate).toBe('pending');
    expect(view.terminal).toBeNull();
  });

  it('stays synchronized when the REST page and the live stream overlap or arrive out of order', () => {
    const half = Math.floor(recorded.length / 2);
    const fromRest = recorded.slice(0, half + 2);
    const fromStreamOutOfOrder = [...recorded.slice(half)].reverse();
    const merged = mergeEvents(mergeEvents([], fromRest), fromStreamOutOfOrder);
    expect(merged.map((e) => e.sequence)).toEqual(recorded.map((e) => e.sequence));
    expect(mergeEvents(merged, recorded)).toBe(merged); // no change, same reference: no re-render
  });

  it('converts a stream event into a timeline entry', () => {
    const e = fromStream({ event_id: 'e', run_id: 'r', sequence: 3, schema_version: 'run-event-v2', event_type: 'MISSION_FAILED',
      node_id: null, observed_at: '2026-10-22T00:00:00+00:00', safe_payload: { code: 'SEAT_TIMEOUT' } });
    expect(e.payload).toEqual({ code: 'SEAT_TIMEOUT' });
    expect(describeEvent(e)).toMatchObject({ title: 'Mission failed', detail: 'SEAT_TIMEOUT', tone: 'danger' });
  });

  it('marks Arty skipped on rejection and the reviewer decision in the text', () => {
    const rejected: TimelineEvent[] = [
      { sequence: 0, event_type: 'SEAT_STARTED', node_id: 'george', observed_at: 't', payload: {} },
      { sequence: 1, event_type: 'SEAT_COMPLETED', node_id: 'george', observed_at: 't', payload: { summary: 'plan' } },
      { sequence: 2, event_type: 'APPROVAL_REQUIRED', node_id: 'sentinel_gate', observed_at: 't', payload: {} },
      { sequence: 3, event_type: 'APPROVAL_APPLIED', node_id: 'sentinel_gate', observed_at: 't', payload: { decision: 'reject', reason: 'REJECTED_BY_REVIEWER' } },
      { sequence: 4, event_type: 'MISSION_REJECTED', node_id: null, observed_at: 't', payload: { reason: 'REJECTED_BY_REVIEWER' } },
    ];
    const view = deriveCouncil(rejected);
    expect(view.seats.arty).toBe('skipped');
    expect(view.gate).toBe('rejected');
    expect(describeEvent(rejected[3]).detail).toContain('reject');
  });
});
