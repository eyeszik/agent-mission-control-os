"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import {
  BarChart3, Bell, FolderKanban, LayoutDashboard, Menu, Moon, Package, Palette, Plug, Search, Settings, ShieldCheck, Sun,
  Users, Workflow, X,
} from 'lucide-react';
import { listProjects } from '../../lib/api/projects';
import { getAttention, getMe, listActions } from '../../lib/api/agencyOs';
import { useAgencyStore, type AgencySection } from '../../lib/stores/agencyStore';
import { Badge, Button, focusRing, useLoad } from './ui';
import { Inspector } from './Inspector';
import { OverviewView } from './views/OverviewView';
import { ClientsView } from './views/ClientsView';
import { ProjectsView } from './views/ProjectsView';
import { MissionsView } from './views/MissionsView';
import { StudioView } from './views/StudioView';
import { ApprovalsView } from './views/ApprovalsView';
import { DeliverablesView } from './views/DeliverablesView';
import { AnalyticsView } from './views/AnalyticsView';
import { IntegrationsView } from './views/IntegrationsView';
import { SettingsView } from './views/SettingsView';

const NAV: { id: AgencySection; label: string; Icon: typeof LayoutDashboard }[] = [
  { id: 'overview', label: 'Overview', Icon: LayoutDashboard },
  { id: 'clients', label: 'Clients', Icon: Users },
  { id: 'projects', label: 'Projects', Icon: FolderKanban },
  { id: 'missions', label: 'Missions', Icon: Workflow },
  { id: 'studio', label: 'Creative Studio', Icon: Palette },
  { id: 'approvals', label: 'Approvals', Icon: ShieldCheck },
  { id: 'deliverables', label: 'Deliverables', Icon: Package },
  { id: 'analytics', label: 'Analytics', Icon: BarChart3 },
  { id: 'integrations', label: 'Integrations', Icon: Plug },
  { id: 'settings', label: 'Settings', Icon: Settings },
];

type Theme = 'light' | 'dark' | 'system';
const THEME_KEY = 'amc.agency.theme';

function readTheme(): Theme {
  try {
    const v = window.localStorage.getItem(THEME_KEY);
    return v === 'light' || v === 'dark' || v === 'system' ? v : 'system';
  } catch {
    return 'system';
  }
}

function useResolvedTheme(theme: Theme): 'light' | 'dark' {
  const [systemLight, setSystemLight] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: light)');
    setSystemLight(mq.matches);
    const on = (e: MediaQueryListEvent) => setSystemLight(e.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  return theme === 'system' ? (systemLight ? 'light' : 'dark') : theme;
}

function View({ section }: { section: AgencySection }) {
  switch (section) {
    case 'overview': return <OverviewView />;
    case 'clients': return <ClientsView />;
    case 'projects': return <ProjectsView />;
    case 'missions': return <MissionsView />;
    case 'studio': return <StudioView />;
    case 'approvals': return <ApprovalsView />;
    case 'deliverables': return <DeliverablesView />;
    case 'analytics': return <AnalyticsView />;
    case 'integrations': return <IntegrationsView />;
    case 'settings': return <SettingsView />;
  }
}

function NavList({ onPick }: { onPick?: () => void }) {
  const section = useAgencyStore((s) => s.section);
  const setSection = useAgencyStore((s) => s.setSection);
  return (
    <ul className="flex flex-col gap-1">
      {NAV.map(({ id, label, Icon }) => (
        <li key={id}>
          <button type="button" aria-current={section === id ? 'page' : undefined}
            onClick={() => { setSection(id); onPick?.(); }}
            className={`flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm ${focusRing} ${section === id ? 'bg-surface-raised font-medium text-fg-strong' : 'text-fg hover:bg-surface-raised hover:text-fg-strong'}`}>
            <Icon aria-hidden="true" size={16} />
            {label}
          </button>
        </li>
      ))}
    </ul>
  );
}

interface Command { id: string; label: string; hint: string; run: () => void }

function CommandPalette({ commands }: { commands: Command[] }) {
  const open = useAgencyStore((s) => s.paletteOpen);
  const setOpen = useAgencyStore((s) => s.setPaletteOpen);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (q ? commands.filter((c) => `${c.label} ${c.hint}`.toLowerCase().includes(q)) : commands).slice(0, 12);
  }, [commands, query]);
  useEffect(() => { if (open) { setQuery(''); setActive(0); setTimeout(() => input.current?.focus(), 0); } }, [open]);
  if (!open) return null;
  const pick = (c: Command | undefined) => { if (c) { setOpen(false); c.run(); } };
  const onKey = (e: ReactKeyboardEvent) => {
    if (e.key === 'Escape') { e.preventDefault(); setOpen(false); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, shown.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); pick(shown[active]); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-[12vh]">
      <div aria-hidden="true" className="absolute inset-0 bg-canvas opacity-80" onClick={() => setOpen(false)} />
      <div role="dialog" aria-modal="true" aria-label="Command palette" onKeyDown={onKey}
        className="relative w-full max-w-lg rounded-lg border border-line-strong bg-surface p-2 shadow-lg">
        <label htmlFor="palette-input" className="sr-only">Search commands, sections, clients and projects</label>
        <input id="palette-input" ref={input} value={query} onChange={(e) => { setQuery(e.target.value); setActive(0); }}
          placeholder="Search sections, clients, projects…" role="combobox" aria-expanded="true" aria-controls="palette-list"
          aria-activedescendant={shown[active] ? `cmd-${shown[active].id}` : undefined}
          className={`w-full rounded-md border border-line bg-canvas px-3 py-2 text-sm text-fg-strong ${focusRing}`} />
        <ul id="palette-list" role="listbox" className="mt-2 max-h-80 overflow-auto">
          {shown.length === 0 && <li className="px-3 py-2 text-sm text-fg">No matches</li>}
          {shown.map((c, i) => (
            <li key={c.id} id={`cmd-${c.id}`} role="option" aria-selected={i === active}
              onMouseEnter={() => setActive(i)} onClick={() => pick(c)}
              className={`flex cursor-pointer items-center justify-between gap-2 rounded-md px-3 py-2 text-sm ${i === active ? 'bg-surface-raised text-fg-strong' : 'text-fg'}`}>
              <span>{c.label}</span><span className="text-xs text-fg">{c.hint}</span>
            </li>
          ))}
        </ul>
        <p className="px-3 pt-2 text-xs text-fg">↑↓ to move · Enter to open · Esc to close</p>
      </div>
    </div>
  );
}

export function AgencyShell() {
  const [theme, setTheme] = useState<Theme>('system');
  const [online, setOnline] = useState(true);
  useEffect(() => { setTheme(readTheme()); }, []);
  useEffect(() => {
    const on = () => setOnline(navigator.onLine);
    on();
    window.addEventListener('online', on);
    window.addEventListener('offline', on);
    return () => { window.removeEventListener('online', on); window.removeEventListener('offline', on); };
  }, []);
  const resolved = useResolvedTheme(theme);
  const chooseTheme = useCallback((next: Theme) => {
    setTheme(next);
    try { window.localStorage.setItem(THEME_KEY, next); } catch { /* storage unavailable: theme still applies for this visit */ }
  }, []);

  const section = useAgencyStore((s) => s.section);
  const setSection = useAgencyStore((s) => s.setSection);
  const projectId = useAgencyStore((s) => s.projectId);
  const setProject = useAgencyStore((s) => s.setProject);
  const navOpen = useAgencyStore((s) => s.navOpen);
  const setNavOpen = useAgencyStore((s) => s.setNavOpen);
  const setPaletteOpen = useAgencyStore((s) => s.setPaletteOpen);
  const inspected = useAgencyStore((s) => s.inspected);

  const me = useLoad(getMe, []);
  const projects = useLoad(listProjects, []);
  const attention = useLoad(getAttention, []);
  const actions = useLoad(() => listActions(), []);

  const projectList = useMemo(() => projects.data?.projects ?? [], [projects.data]);
  useEffect(() => {
    if (!projectId && projectList.length > 0) setProject(projectList[0].project_id);
  }, [projectId, projectList, setProject]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPaletteOpen(true); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setPaletteOpen]);

  // ⚡ Bolt: Precompute derived metrics in a single pass with zero allocation instead of multiple .filter().length
  const { running, unsure } = useMemo(() => {
    let r = 0, u = 0;
    for (const a of actions.data ?? []) {
      if (a.state === 'DISPATCHING' || a.state === 'OBSERVING' || a.state === 'RECONCILING') r++;
      else if (a.state === 'UNKNOWN' || a.state === 'NEEDS_HUMAN') u++;
    }
    return { running: r, unsure: u };
  }, [actions.data]);
  const pending = attention.data?.length ?? 0;

  const commands: Command[] = useMemo(() => [
    ...NAV.map((n) => ({ id: `nav-${n.id}`, label: n.label, hint: 'Section', run: () => setSection(n.id) })),
    ...projectList.map((p) => ({ id: `prj-${p.project_id}`, label: p.display_name, hint: 'Project', run: () => { setProject(p.project_id); setSection('projects'); } })),
    { id: 'new-mission', label: 'New mission from a brief', hint: 'Missions', run: () => setSection('missions') },
    { id: 'new-client', label: 'Add a client', hint: 'Clients', run: () => setSection('clients') },
    { id: 'theme', label: `Switch to ${resolved === 'dark' ? 'light' : 'dark'} theme`, hint: 'Appearance', run: () => chooseTheme(resolved === 'dark' ? 'light' : 'dark') },
  ], [projectList, setSection, setProject, resolved, chooseTheme]);

  return (
    <div data-amc-theme={resolved === 'light' ? 'light' : undefined} className="min-h-[100dvh] bg-canvas text-fg">
      <a href="#agency-main" className={`sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:text-fg-strong ${focusRing}`}>
        Skip to content
      </a>
      <div className="flex min-h-[100dvh]">
        <aside className="hidden w-60 shrink-0 flex-col gap-6 border-r border-line bg-surface p-4 lg:flex" aria-label="Primary">
          <div>
            <p className="text-sm font-semibold text-fg-strong">Agency OS</p>
            <p className="text-xs text-fg">Mission Control</p>
          </div>
          <nav aria-label="Sections"><NavList /></nav>
          <p className="mt-auto text-xs text-fg">External actions: <span className="font-medium text-status-info">disabled</span>. Sandbox only.</p>
        </aside>

        {navOpen && (
          <div className="fixed inset-0 z-40 flex flex-col bg-canvas p-4 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
            <div className="mb-4 flex items-center justify-between">
              <p className="text-sm font-semibold text-fg-strong">Agency OS</p>
              <Button variant="ghost" aria-label="Close navigation" onClick={() => setNavOpen(false)}><X aria-hidden="true" size={18} /></Button>
            </div>
            <nav aria-label="Sections"><NavList onPick={() => setNavOpen(false)} /></nav>
          </div>
        )}

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex flex-wrap items-center gap-2 border-b border-line bg-canvas px-4 py-3 sm:px-6">
            <Button variant="ghost" className="lg:hidden" aria-label="Open navigation" onClick={() => setNavOpen(true)}>
              <Menu aria-hidden="true" size={18} />
            </Button>
            <div className="flex min-w-0 items-center gap-2">
              <label htmlFor="agency-project" className="text-xs text-fg">Project</label>
              <select id="agency-project" value={projectId ?? ''} onChange={(e) => setProject(e.target.value || null)}
                className={`max-w-[14rem] rounded-md border border-line-strong bg-surface px-2 py-1.5 text-sm text-fg-strong ${focusRing}`}>
                {projectList.length === 0 && <option value="">No projects yet</option>}
                {projectList.map((p) => <option key={p.project_id} value={p.project_id}>{p.display_name}</option>)}
              </select>
            </div>
            <Button variant="secondary" onClick={() => setPaletteOpen(true)} aria-keyshortcuts="Control+K Meta+K" className="ml-auto sm:ml-2">
              <Search aria-hidden="true" size={16} /><span className="hidden sm:inline">Search</span><kbd className="hidden text-xs text-fg sm:inline">⌘K</kbd>
            </Button>
            <div className="flex items-center gap-2 sm:ml-auto">
              <span role="status" aria-live="polite" className="hidden text-xs text-fg md:inline">
                {running} running · {unsure} need checking
              </span>
              <Button variant="ghost" aria-label={`Attention queue: ${pending} item${pending === 1 ? '' : 's'}`} onClick={() => setSection('overview')}>
                <Bell aria-hidden="true" size={16} /><span className="text-sm">{pending}</span>
              </Button>
              <Button variant="ghost" aria-label={`Use ${resolved === 'dark' ? 'light' : 'dark'} theme`} onClick={() => chooseTheme(resolved === 'dark' ? 'light' : 'dark')}>
                {resolved === 'dark' ? <Sun aria-hidden="true" size={16} /> : <Moon aria-hidden="true" size={16} />}
              </Button>
              {me.data && (
                <span className="hidden items-center gap-2 text-xs text-fg sm:flex" title={`Tenant ${me.data.tenant_id}`}>
                  <span className="text-fg-strong">{me.data.user_id}</span><Badge label={me.data.role} tone="neutral" />
                </span>
              )}
            </div>
          </header>
          {!online && (
            <div role="alert" className="border-b border-status-warning px-4 py-2 text-sm text-status-warning sm:px-6">
              You are offline. Nothing can be sent until the connection returns; nothing was lost.
            </div>
          )}
          <div className="flex min-w-0 flex-1">
            <main id="agency-main" tabIndex={-1} className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8">
              <h1 className="sr-only">{NAV.find((n) => n.id === section)?.label}</h1>
              <View section={section} />
            </main>
            {inspected && <Inspector />}
          </div>
        </div>
      </div>
      <CommandPalette commands={commands} />
    </div>
  );
}
