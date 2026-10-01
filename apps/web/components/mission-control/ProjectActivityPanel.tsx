"use client";

import { useCallback, useEffect, useState } from 'react';
import type { ConversationMessage, ConversationThread, ProjectEvent } from '@amc/shared';
import { createThread, listMessages, listProjectEvents, listThreads, postMessage } from '../../lib/api/projects';
import { useProjectStore } from '../../lib/stores/projectStore';

const EVENT_TONE: Partial<Record<ProjectEvent['event_type'], string>> = {
  APPROVED: 'text-emerald-300',
  VERIFIED: 'text-emerald-300',
  PUBLISHED: 'text-emerald-300',
  QA_BLOCKED: 'text-amber-300',
  APPROVAL_REQUIRED: 'text-amber-300',
  RECOVERING: 'text-amber-300',
  FAILED: 'text-rose-300',
  REJECTED: 'text-rose-300',
};

function MessageCard({ message }: { message: ConversationMessage }) {
  return (
    <li className="text-xs border border-zinc-800/60 rounded-md p-2 flex flex-col gap-1">
      <div className="flex justify-between gap-2 text-zinc-500">
        <span>{message.author}</span>
        <span className="font-mono">{message.activity_type}</span>
      </div>
      <p className="text-zinc-200 whitespace-pre-wrap">{message.body}</p>
      {message.artifact_refs.length > 0 && (
        <ul className="flex flex-wrap gap-1">
          {message.artifact_refs.map((ref) => (
            <li key={`${ref.version_ref}-${ref.relation}`} className="px-1.5 py-0.5 rounded border border-zinc-700 font-mono text-zinc-300">
              {ref.relation}: {ref.version_ref}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function EventRow({ event }: { event: ProjectEvent }) {
  return (
    <li className="flex gap-2 text-xs font-mono">
      <span className="text-zinc-600 w-8 text-right">{event.sequence}</span>
      <span className={EVENT_TONE[event.event_type] ?? 'text-zinc-300'}>{event.event_type}</span>
      <span className="text-zinc-500 truncate">{event.subject_ref ?? ''}</span>
    </li>
  );
}

export function ProjectActivityPanel() {
  const projectId = useProjectStore((state) => state.activeProjectId);
  const threadId = useProjectStore((state) => state.activeThreadId);
  const setThread = useProjectStore((state) => state.setActiveThread);
  const [threads, setThreads] = useState<ConversationThread[]>([]);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [events, setEvents] = useState<ProjectEvent[]>([]);
  const [draft, setDraft] = useState('');
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!projectId) return;
    try {
      const [threadList, eventList] = await Promise.all([listThreads(projectId), listProjectEvents(projectId)]);
      setThreads(threadList.threads);
      setEvents(eventList.events);
      if (threadId) setMessages((await listMessages(projectId, threadId)).messages);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load activity');
    }
  }, [projectId, threadId]);

  useEffect(() => {
    setThreads([]);
    setMessages([]);
    setEvents([]);
    void refresh();
  }, [refresh]);

  if (!projectId) {
    return <section className="bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-3 text-xs text-zinc-500">Select a project to see its conversations and activity.</section>;
  }

  const onNewThread = async () => {
    try {
      const created = await createThread(projectId, `Thread ${threads.length + 1}`);
      setThread(created.thread.thread_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create thread');
    }
  };

  const onSend = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!threadId || !draft.trim()) return;
    try {
      await postMessage(projectId, threadId, draft.trim());
      setDraft('');
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not send message');
    }
  };

  return (
    <section aria-labelledby="project-activity-heading" className="bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-3 flex flex-col gap-3 min-h-0">
      <div className="flex items-center justify-between">
        <h2 id="project-activity-heading" className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Project Activity</h2>
        <button type="button" onClick={onNewThread} className="text-xs px-2 py-0.5 rounded border border-zinc-700 text-zinc-300 hover:text-zinc-100">New thread</button>
      </div>
      {error && <p role="alert" className="text-xs text-rose-300">{error}</p>}
      <div role="tablist" aria-label="Conversation threads" className="flex flex-wrap gap-1">
        {threads.map((thread) => (
          <button
            key={thread.thread_id}
            role="tab"
            type="button"
            aria-selected={thread.thread_id === threadId}
            onClick={() => setThread(thread.thread_id)}
            className={`text-xs px-2 py-0.5 rounded ${thread.thread_id === threadId ? 'bg-zinc-100 text-zinc-900' : 'text-zinc-400 border border-zinc-800'}`}
          >
            {thread.title}
          </button>
        ))}
      </div>
      {threadId && (
        <>
          <ul className="flex flex-col gap-2 overflow-auto max-h-56">{messages.map((message) => <MessageCard key={message.message_id} message={message} />)}</ul>
          <form onSubmit={onSend} className="flex gap-2">
            <label htmlFor="project-message" className="sr-only">Message</label>
            <input id="project-message" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Message this project…"
              className="flex-1 min-w-0 bg-zinc-950 border border-zinc-800 rounded-md px-2 py-1 text-sm text-zinc-100" />
            <button type="submit" disabled={!draft.trim()} className="text-xs px-2.5 py-1 rounded-md bg-zinc-100 text-zinc-900 disabled:opacity-50">Send</button>
          </form>
        </>
      )}
      <div className="min-h-0">
        <p className="text-xs text-zinc-500 mb-1">Activity stream</p>
        <ol className="flex flex-col gap-0.5 overflow-auto max-h-48">{events.map((event) => <EventRow key={event.event_id} event={event} />)}</ol>
      </div>
    </section>
  );
}
