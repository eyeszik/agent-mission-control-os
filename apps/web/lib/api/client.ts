export class ServiceError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
    this.name = 'ServiceError';
  }
}

interface FetchOptions extends RequestInit {
  // Option to attach idempotency keys transparently
  idempotencyKey?: string;
}

export async function apiFetch<T>(endpoint: string, options: FetchOptions = {}): Promise<T> {
  const headers = new Headers(options.headers || {});
  headers.set('Content-Type', 'application/json');

  if (options.idempotencyKey) {
    headers.set('Idempotency-Key', options.idempotencyKey);
  }

  const base = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';
  const url = `${base}${endpoint}`;

  const response = await fetch(url, { ...options, headers });

  if (!response.ok) {
    let errorData;
    try {
      errorData = await response.json();
    } catch {
      errorData = { message: response.statusText };
    }
    throw new ServiceError(response.status, errorData.code || 'UNKNOWN', errorData.message || 'API request failed');
  }

  return response.json() as Promise<T>;
}
