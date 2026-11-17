'use client';
import { useState } from 'react';
import { browserCapabilities, extractHtml, extractUrl } from '../../../lib/api/browser';
import { Button, Card, ErrorNote, Field, inputClass, useLoad } from '../ui';

export function BrowserPanel({ projectId }: { projectId: string }) {
  const capability = useLoad(() => browserCapabilities(projectId), [projectId]);
  const [url, setUrl] = useState('');
  const [html, setHtml] = useState('');
  const [source, setSource] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Awaited<ReturnType<typeof extractHtml>> | null>(null);
  return <Card title="Obscura local extraction" description="Extract supplied HTML or an enabled public HTTPS page. Page text remains untrusted. External scripts, images and subpages are not loaded; use Chromium for compatibility-critical browsing.">
    <p role="status">{capability.loading ? 'Checking availability…' : capability.data?.enabled ? 'Local extraction enabled' : 'Local extraction disabled'}</p>
    {capability.error && <ErrorNote error={capability.error} />}
    {capability.data?.public_browsing && <>
      <Field label="Public HTTPS URL" htmlFor="browser-url"><input id="browser-url" type="url" className={inputClass} value={url} maxLength={2048} onChange={e => setUrl(e.target.value)} /></Field>
      <Button disabled={busy || !url.trim()} onClick={async () => {
        setBusy(true); setError(null); setResult(null);
        try { setResult(await extractUrl(projectId, url)); }
        catch (e) { setError(e instanceof Error ? e.message : 'Retrieval failed'); }
        finally { setBusy(false); }
      }}>Browse and extract URL</Button>
    </>}
    <Field label="Source reference" htmlFor="browser-source"><input id="browser-source" className={inputClass} value={source} maxLength={300} onChange={e => setSource(e.target.value)} /></Field>
    <Field label="Supplied HTML" htmlFor="browser-html"><textarea id="browser-html" className={inputClass} value={html} maxLength={262144} onChange={e => setHtml(e.target.value)} /></Field>
    <Button disabled={busy || !capability.data?.enabled || !source.trim() || !html.trim()} onClick={async () => {
      setBusy(true); setError(null); setResult(null);
      try { setResult(await extractHtml(projectId, html, source)); }
      catch (e) { setError(e instanceof Error ? e.message : 'Extraction failed'); }
      finally { setBusy(false); }
    }}>{busy ? 'Extracting…' : 'Extract supplied HTML'}</Button>
    {error && <ErrorNote error={error} />}
    {result && <div aria-live="polite"><p>{result.status} · {result.run_id}{result.replayed ? ' · Replayed receipt' : ''}</p><p>{result.reasons.join("; ")}</p><pre className="whitespace-pre-wrap break-words">{result.content?.markdown}</pre><details><summary>Persisted proof summary</summary><pre className="whitespace-pre-wrap break-words">{JSON.stringify(result.proof, null, 2)}</pre></details></div>}
  </Card>;
}
