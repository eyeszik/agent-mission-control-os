"use client";

import { useEffect, useState } from 'react';
import { getPortfolio, type Portfolio, type PortfolioProject } from '../../lib/api/projects';
import { useProjectStore } from '../../lib/stores/projectStore';

function PortfolioRow({ project, onOpen }: { project: PortfolioProject; onOpen: (id: string) => void }) {
  const queue = Object.values(project.publication_queue).reduce((sum, n) => sum + n, 0);
  return (
    <tr className="border-b border-zinc-800/40 last:border-0">
      <th scope="row" className="text-left font-normal py-1.5 pr-2">
        <button type="button" onClick={() => onOpen(project.project_id)} className="text-zinc-100 hover:underline text-left">
          {project.display_name}
        </button>
        {project.brand_name && <span className="block text-zinc-500">{project.brand_name}</span>}
      </th>
      <td className={project.brand_health === 'OK' ? 'text-emerald-300' : 'text-amber-300'}>{project.brand_health}</td>
      <td className="font-mono text-zinc-300">{project.production_queue}</td>
      <td className="font-mono text-zinc-300">{project.approval_queue.content_review + project.approval_queue.run_approvals}</td>
      <td className="font-mono text-zinc-300">{project.upcoming_calendar_14d}</td>
      <td className="font-mono text-zinc-300">{queue}</td>
      <td className={`font-mono ${project.stale_assets ? 'text-amber-300' : 'text-zinc-300'}`}>{project.stale_assets}</td>
      <td className={`font-mono ${project.rights_expiry.expired ? 'text-rose-300' : 'text-zinc-300'}`}>
        {project.rights_expiry.expired}/{project.rights_expiry.expiring_30d}
      </td>
    </tr>
  );
}

export function PortfolioCommandCenter() {
  const setActiveProject = useProjectStore((state) => state.setActiveProject);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getPortfolio()
      .then((value) => !cancelled && setPortfolio(value))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : 'Could not load portfolio'));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section aria-labelledby="portfolio-heading" className="bg-zinc-900/40 border border-zinc-800/60 rounded-xl p-3 flex flex-col gap-2 min-h-0">
      <h2 id="portfolio-heading" className="text-xs font-mono text-zinc-500 uppercase tracking-wider">Portfolio</h2>
      {error && <p role="alert" className="text-xs text-rose-300">{error}</p>}
      {portfolio && portfolio.projects.length === 0 && <p className="text-xs text-zinc-500">No projects yet.</p>}
      {portfolio && portfolio.projects.length > 0 && (
        <div className="overflow-auto">
          <table className="w-full text-xs">
            <caption className="sr-only">Health of every project you can access</caption>
            <thead className="text-zinc-500">
              <tr>
                <th scope="col" className="text-left font-normal">Project</th>
                <th scope="col" className="text-left font-normal">Health</th>
                <th scope="col" className="text-left font-normal">In production</th>
                <th scope="col" className="text-left font-normal">Approvals</th>
                <th scope="col" className="text-left font-normal">Next 14d</th>
                <th scope="col" className="text-left font-normal">Publishing</th>
                <th scope="col" className="text-left font-normal">Stale</th>
                <th scope="col" className="text-left font-normal">Rights exp.</th>
              </tr>
            </thead>
            <tbody>{portfolio.projects.map((project) => <PortfolioRow key={project.project_id} project={project} onOpen={setActiveProject} />)}</tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-zinc-600">Counts only; private memory, conversations and brand canon never cross projects.</p>
    </section>
  );
}
