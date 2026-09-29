/**
 * Error envelope.
 *
 * Shape mirrors the Agentic Commerce Protocol delegate-payment error object
 * ({ type, code, message, param }) so agent-side clients can parse gateway
 * failures with the same handler they use for upstream ACP calls.
 * Source: https://developers.openai.com/commerce/specs/payment
 */
export type AislErrorType =
  | 'invalid_request'
  | 'rate_limit_exceeded'
  | 'processing_error'
  | 'service_unavailable';

export interface AislErrorBody {
  type: AislErrorType;
  code: string;
  message: string;
  param?: string;
}

export class AislError extends Error {
  readonly statusCode: number;
  readonly type: AislErrorType;
  readonly code: string;
  readonly param: string | undefined;
  /** Non-null when the failure originated in an upstream connector. */
  override readonly cause: unknown;

  constructor(init: {
    statusCode: number;
    type: AislErrorType;
    code: string;
    message: string;
    param?: string;
    cause?: unknown;
  }) {
    super(init.message);
    this.name = 'AislError';
    this.statusCode = init.statusCode;
    this.type = init.type;
    this.code = init.code;
    this.param = init.param;
    this.cause = init.cause;
  }

  toBody(): AislErrorBody {
    const body: AislErrorBody = { type: this.type, code: this.code, message: this.message };
    if (this.param !== undefined) {
      body.param = this.param;
    }
    return body;
  }

  static badRequest(code: string, message: string, param?: string): AislError {
    return new AislError({ statusCode: 400, type: 'invalid_request', code, message, param });
  }

  static unauthorized(code: string, message: string): AislError {
    return new AislError({ statusCode: 401, type: 'invalid_request', code, message });
  }

  static notFound(code: string, message: string, param?: string): AislError {
    return new AislError({ statusCode: 404, type: 'invalid_request', code, message, param });
  }

  static conflict(code: string, message: string): AislError {
    return new AislError({ statusCode: 409, type: 'invalid_request', code, message });
  }

  static rateLimited(message = 'Rate limit exceeded'): AislError {
    return new AislError({ statusCode: 429, type: 'rate_limit_exceeded', code: 'rate_limited', message });
  }

  static upstream(code: string, message: string, cause?: unknown): AislError {
    return new AislError({ statusCode: 502, type: 'processing_error', code, message, cause });
  }

  static internal(code: string, message: string, cause?: unknown): AislError {
    return new AislError({ statusCode: 500, type: 'processing_error', code, message, cause });
  }

  static unavailable(code: string, message: string, cause?: unknown): AislError {
    return new AislError({ statusCode: 503, type: 'service_unavailable', code, message, cause });
  }
}

export function isAislError(value: unknown): value is AislError {
  return value instanceof AislError;
}
