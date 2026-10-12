"use client";

import { Card } from '../ui';

const STUDIOS = [
  { title: 'VNEXUS Studio', body: 'Brand genome, inheritance, knowledge graph, multiverse branches and local production from an approved genome.' },
  { title: 'Creative Foundry', body: 'A plain-language brief to a connected brand family rendered on this host, each piece verified and approval-gated.' },
  { title: 'Design Mode', body: 'Compose a style direction by dimension and attach it to a campaign brief.' },
];

export function StudioView() {
  return (
    <Card id="studio" title="Creative Studio" description="The creative tools live in Mission Control and share the same projects, approvals and evidence.">
      <ul className="grid gap-4 md:grid-cols-3">
        {STUDIOS.map((s) => (
          <li key={s.title} className="flex flex-col gap-2 rounded-md border border-line p-4">
            <p className="text-sm font-semibold text-fg-strong">{s.title}</p>
            <p className="text-sm text-fg">{s.body}</p>
          </li>
        ))}
      </ul>
      <a href="/mission-control" className="text-sm font-medium text-accent underline underline-offset-2">Open Mission Control</a>
      <p className="text-xs text-fg">Image and video generation from hosted models is not connected; those requests report “Tool not connected”.</p>
    </Card>
  );
}
