import { AislError } from '../lib/errors.js';

/** Injectable fetch so connectors are testable without a live merchant API. */
export type FetchLike = typeof globalThis.fetch;

export interface HttpOptions {
  fetchImpl: FetchLike;
  timeoutMs: number;
}

export interface JsonRequest {
  url: string;
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  headers?: Record<string, string>;
  body?: unknown;
  /** Connector name used in the error code, e.g. `shopify_storefront`. */
  source: string;
}

export async function requestJson<T>(request: JsonRequest, options: HttpOptions): Promise<T> {
  const { fetchImpl, timeoutMs } = options;
  const headers: Record<string, string> = { accept: 'application/json', ...request.headers };
  if (request.body !== undefined) {
    headers['content-type'] = headers['content-type'] ?? 'application/json';
  }

  let response: Response;
  try {
    response = await fetchImpl(request.url, {
      method: request.method ?? 'GET',
      headers,
      body: request.body === undefined ? undefined : JSON.stringify(request.body),
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    const aborted = error instanceof Error && (error.name === 'TimeoutError' || error.name === 'AbortError');
    throw new AislError({
      statusCode: 504,
      type: aborted ? 'service_unavailable' : 'processing_error',
      code: `${request.source}_unreachable`,
      message: aborted
        ? `${request.source} did not respond within ${timeoutMs}ms`
        : `${request.source} request failed: ${error instanceof Error ? error.message : String(error)}`,
      cause: error,
    });
  }

  const text = await response.text();
  if (!response.ok) {
    throw AislError.upstream(
      `${request.source}_http_${response.status}`,
      `${request.source} responded ${response.status}: ${truncate(text, 400)}`,
    );
  }

  if (text.length === 0) {
    return undefined as T;
  }

  try {
    return JSON.parse(text) as T;
  } catch (error) {
    throw AislError.upstream(`${request.source}_invalid_json`, `${request.source} returned malformed JSON`, error);
  }
}

function truncate(value: string, max: number): string {
  return value.length <= max ? value : `${value.slice(0, max)}...`;
}
