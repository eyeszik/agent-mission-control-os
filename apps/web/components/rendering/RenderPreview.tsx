'use client';

import { useEffect, useState } from 'react';
import { fetchFoundryContent } from '../../lib/api/foundry';

export default function RenderPreview({ project, artifact }: { project: string; artifact: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let disposed = false;
    let objectUrl: string | null = null;
    setUrl(null); setError('');
    void fetchFoundryContent(project, artifact).then(({ blob }) => {
      if (disposed) return;
      objectUrl = URL.createObjectURL(blob); setUrl(objectUrl);
    }).catch(() => { if (!disposed) setError('Preview unavailable.'); });
    return () => { disposed = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [project, artifact]);
  if (error) return <p role="alert">{error}</p>;
  if (!url) return <p role="status">Loading persisted artifact…</p>;
  // Image context does not execute SVG scripts; no arbitrary source is injected.
  return <img src={url} alt="Persisted geometric rendering awaiting human review" className="h-auto max-w-full" />;
}
