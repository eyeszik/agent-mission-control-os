import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createProject, listProjects, transitionContentItem } from '../lib/api/projects';
import { useProjectStore } from '../lib/stores/projectStore';

const HASH = 'a'.repeat(64);
const project = {
  project_id: 'p1',
  tenant_id: 't1',
  slug: 'acme',
  display_name: 'Acme',
  description: '',
  lifecycle_state: 'ACTIVE',
  brand_id: null,
  brand_name: null,
  workspace_schema_version: 'amc-workspace/v2',
  manifest_hash: HASH,
  created_by: 'u1',
  created_at: '2026-10-01T00:00:00+00:00',
  updated_at: '2026-10-01T00:00:00+00:00',
};

function respond(body: unknown, status = 200) {
  return vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

afterEach(() => vi.unstubAllGlobals());

describe('project API client', () => {
  it('validates project lists against the shared contract', async () => {
    vi.stubGlobal('fetch', respond({ projects: [project] }));
    const result = await listProjects();
    expect(result.projects[0].workspace_schema_version).toBe('amc-workspace/v2');
  });

  it('rejects a project that carries fields the contract does not know', async () => {
    vi.stubGlobal('fetch', respond({ projects: [{ ...project, secret_token: 'x' }] }));
    await expect(listProjects()).rejects.toThrow();
  });

  it('sends an idempotency key when creating a project', async () => {
    const fetchMock = respond({ project, created: true, mirror: { ok: true } }, 201);
    vi.stubGlobal('fetch', fetchMock);
    await createProject({ display_name: 'Acme' });
    const headers = fetchMock.mock.calls[0][1].headers as Headers;
    expect(headers.get('Idempotency-Key')).toBeTruthy();
  });

  it('surfaces a separation-of-duties refusal', async () => {
    vi.stubGlobal('fetch', respond({ detail: 'The principal who started a content item cannot approve it' }, 403));
    await expect(transitionContentItem('p1', 'c1', 'APPROVED', 1)).rejects.toMatchObject({ status: 403 });
  });
});

describe('project store', () => {
  beforeEach(() => useProjectStore.setState({ activeProjectId: null, activeThreadId: null }));

  it('clears the active thread when the project changes', () => {
    const { setActiveProject, setActiveThread } = useProjectStore.getState();
    setActiveProject('p1');
    setActiveThread('th1');
    setActiveProject('p2');
    expect(useProjectStore.getState()).toMatchObject({ activeProjectId: 'p2', activeThreadId: null });
  });

  it('keeps state identity when re-selecting the same project', () => {
    const { setActiveProject } = useProjectStore.getState();
    setActiveProject('p1');
    const before = useProjectStore.getState();
    setActiveProject('p1');
    expect(useProjectStore.getState()).toBe(before);
  });
});
