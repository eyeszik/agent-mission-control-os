/**
 * Typed AMC errors and the JSON error envelope.
 *
 * The envelope matches what the Python backend's `core.errors` handler
 * renders: `{ detail, error: { code, message, status, details? } }`. `detail`
 * is kept so clients written against FastAPI's default `{ detail }` body keep
 * working.
 */

export interface ErrorDetails {
  [key: string]: unknown;
}

export interface ErrorEnvelope {
  detail: string;
  error: {
    code: string;
    message: string;
    status: number;
    details?: ErrorDetails;
  };
}

export interface AMCErrorOptions {
  code?: string;
  status?: number;
  details?: ErrorDetails;
  cause?: unknown;
}

const AMC_ERROR_BRAND = Symbol.for('amc.error');

export class AMCError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details?: ErrorDetails;
  readonly [AMC_ERROR_BRAND] = true;

  constructor(message: string, options: AMCErrorOptions = {}) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = new.target.name;
    this.code = options.code ?? 'AMC_ERROR';
    this.status = options.status ?? 500;
    if (options.details !== undefined) this.details = options.details;
  }

  toEnvelope(): ErrorEnvelope {
    return {
      detail: this.message,
      error: {
        code: this.code,
        message: this.message,
        status: this.status,
        ...(this.details === undefined ? {} : { details: this.details }),
      },
    };
  }
}

type SubclassOptions = Omit<AMCErrorOptions, 'status'>;

export class ValidationError extends AMCError {
  constructor(message = 'Validation failed', options: SubclassOptions = {}) {
    super(message, { code: 'VALIDATION_FAILED', ...options, status: 422 });
  }
}

export class UnauthorizedError extends AMCError {
  constructor(message = 'Authentication required', options: SubclassOptions = {}) {
    super(message, { code: 'UNAUTHORIZED', ...options, status: 401 });
  }
}

export class ForbiddenError extends AMCError {
  constructor(message = 'Forbidden', options: SubclassOptions = {}) {
    super(message, { code: 'FORBIDDEN', ...options, status: 403 });
  }
}

export class NotFoundError extends AMCError {
  constructor(message = 'Not found', options: SubclassOptions = {}) {
    super(message, { code: 'NOT_FOUND', ...options, status: 404 });
  }
}

export class ConflictError extends AMCError {
  constructor(message = 'Conflict', options: SubclassOptions = {}) {
    super(message, { code: 'CONFLICT', ...options, status: 409 });
  }
}

/** True for any AMCError, including one from another copy of this package. */
export function isAMCError(value: unknown): value is AMCError {
  return value instanceof AMCError || (typeof value === 'object' && value !== null && (value as Record<PropertyKey, unknown>)[AMC_ERROR_BRAND] === true);
}

/** Throw a ValidationError unless `condition` holds. */
export function ensureValid(condition: unknown, message: string, details?: ErrorDetails): asserts condition {
  if (!condition) throw new ValidationError(message, details === undefined ? {} : { details });
}

/**
 * Envelope for any thrown value. Non-AMC errors become a generic 500 so an
 * internal message (which may carry secrets or stack detail) never leaks.
 */
export function toErrorEnvelope(error: unknown): ErrorEnvelope {
  if (isAMCError(error)) return error.toEnvelope();
  return new AMCError('Internal error', { code: 'INTERNAL', status: 500 }).toEnvelope();
}

function str(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

/**
 * Build the typed error for an HTTP error response body. Accepts the AMC
 * envelope and FastAPI's plain `{ detail }` / `{ message, code }` bodies.
 */
export function errorFromResponse(status: number, body: unknown, fallbackMessage = 'Request failed'): AMCError {
  const record = typeof body === 'object' && body !== null ? (body as Record<string, unknown>) : {};
  const nested = typeof record.error === 'object' && record.error !== null ? (record.error as Record<string, unknown>) : {};
  const message = str(nested.message) ?? str(record.detail) ?? str(record.message) ?? fallbackMessage;
  const code = str(nested.code) ?? str(record.code);
  const details = typeof nested.details === 'object' && nested.details !== null ? (nested.details as ErrorDetails) : undefined;
  const options = { ...(code === undefined ? {} : { code }), ...(details === undefined ? {} : { details }) };
  switch (status) {
    case 400:
    case 422:
      return new ValidationError(message, options);
    case 401:
      return new UnauthorizedError(message, options);
    case 403:
      return new ForbiddenError(message, options);
    case 404:
      return new NotFoundError(message, options);
    case 409:
      return new ConflictError(message, options);
    default:
      return new AMCError(message, { code: code ?? 'UNKNOWN', status, ...(details === undefined ? {} : { details }) });
  }
}
