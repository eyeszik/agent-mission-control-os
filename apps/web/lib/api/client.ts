export class ServiceError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
    this.name = 'ServiceError';
  }
}

interface FetchOptions extends RequestInit {
  idempotencyKey?: string;
}

export interface RuntimeSchema<T> {
  parse(input: unknown): T;
}

export async function apiFetch<T>(
  endpoint: string,
  options: FetchOptions = {},
  schema?: RuntimeSchema<T>
): Promise<T> {
  const headers = new Headers(options.headers || {});
  headers.set('Content-Type', 'application/json');

  if (options.idempotencyKey) {
    headers.set('Idempotency-Key', options.idempotencyKey);
  }

  const base = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';
  const url = `${base}${endpoint}`;
  const response = await fetch(url, { ...options, headers });

  if (!response.ok) {
    let errorData: Record<string, unknown> = {};
    try {
      errorData = (await response.json()) as Record<string, unknown>;
    } catch {
      errorData = {};
    }
    const detail = typeof errorData.detail === 'string' ? errorData.detail : undefined;
    const message = typeof errorData.message === 'string' ? errorData.message : undefined;
    const code = typeof errorData.code === 'string' ? errorData.code : 'UNKNOWN';
    throw new ServiceError(response.status, code, detail || message || response.statusText || 'API request failed');
  }

  const data: unknown = await response.json();
  if (schema) return schema.parse(data);
  return data as T;
}
