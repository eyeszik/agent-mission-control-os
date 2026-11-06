"use client";

import { useCallback, useEffect, useRef, useState } from 'react';
import { CouncilStreamEventSchema, type CouncilStreamEvent, type Mission, type MissionStatus, type TimelineEvent } from '@amc/shared';
import { getMission, getTimeline } from '../api/missions';
import { SSEClient } from '../api/events';
import { EventEmitter } from '../events/bus';
import { fromStream, mergeEvents } from './council';

const TERMINAL: ReadonlySet<MissionStatus> = new Set(['completed', 'rejected', 'failed', 'cancelled']);
// Events after which the mission row (status, gate, results) has changed.
const REFETCH = new Set([
  'MISSION_STARTED', 'SEAT_COMPLETED', 'RISK_ASSESSED', 'APPROVAL_REQUIRED', 'approval_decided', 'MISSION_RESUMING',
  'APPROVAL_APPLIED', 'TOOL_INVOKED', 'MISSION_COMPLETED', 'MISSION_REJECTED', 'MISSION_BLOCKED', 'MISSION_FAILED',
  'MISSION_CANCELLED', 'MISSION_RETRYING', 'MISSION_RECOVERING',
]);

export type StreamState = 'idle' | 'live' | 'ended';

/**
 * One council mission: the row from GET /missions/{id} plus its persisted
 * timeline, kept current by the run's SSE stream while the mission is not
 * terminal. The REST page and the stream are merged by sequence, so a
 * reconnect or an overlap never duplicates or reorders an event.
 */
export function useMissionLive(missionId: string | null) {
  const [mission, setMission] = useState<Mission | null>(null);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [stream, setStream] = useState<StreamState>('idle');
  const refetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const current = useRef(missionId);
  current.current = missionId;

  const refetchMission = useCallback(async () => {
    const id = current.current;
    if (!id) return;
    try {
      const next = await getMission(id);
      if (current.current === id) setMission(next);
    } catch (err) {
      if (current.current === id) setError(err instanceof Error ? err.message : 'Could not load the mission');
    }
  }, []);

  const reload = useCallback(async () => {
    const id = current.current;
    if (!id) return;
    setLoading(true);
    try {
      const [next, timeline] = await Promise.all([getMission(id), getTimeline(id)]);
      if (current.current !== id) return;
      setMission(next);
      setEvents((prev) => mergeEvents(prev, timeline.events));
      setError(null);
    } catch (err) {
      if (current.current === id) setError(err instanceof Error ? err.message : 'Could not load the mission');
    } finally {
      if (current.current === id) setLoading(false);
    }
  }, []);

  useEffect(() => {
    setMission(null);
    setEvents([]);
    setError(null);
    setStream('idle');
    if (missionId) void reload();
  }, [missionId, reload]);

  const live = Boolean(mission && missionId && mission.mission_id === missionId && !TERMINAL.has(mission.status));
  useEffect(() => {
    if (!live || !missionId) return;
    const bus = new EventEmitter();
    const topic = `mission:${missionId}`;
    const onEvent = (event: CouncilStreamEvent) => {
      setEvents((prev) => mergeEvents(prev, [fromStream(event)]));
      if (REFETCH.has(event.event_type)) {
        if (refetchTimer.current) clearTimeout(refetchTimer.current);
        refetchTimer.current = setTimeout(() => { void refetchMission(); }, 150);
      }
    };
    bus.on(topic, onEvent);
    const client = new SSEClient(missionId, bus, { schema: CouncilStreamEventSchema, busEvent: topic });
    client.connect();
    setStream('live');
    return () => {
      client.disconnect();
      bus.off(topic, onEvent);
      if (refetchTimer.current) clearTimeout(refetchTimer.current);
      setStream('ended');
    };
  }, [live, missionId, refetchMission]);

  return { mission, events, error, loading, stream, reload, setMission };
}
