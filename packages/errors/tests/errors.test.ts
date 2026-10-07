import { describe, expect, it } from 'vitest';
import {
  AMCError,
  ConflictError,
  ForbiddenError,
  NotFoundError,
  UnauthorizedError,
  ValidationError,
  ensureValid,
  errorFromResponse,
  isAMCError,
  toErrorEnvelope,
} from '../src/index';

describe('@amc/errors', () => {
  it('assigns stable codes and statuses', () => {
    const cases: Array<[AMCError, string, number]> = [
      [new ValidationError(), 'VALIDATION_FAILED', 422],
      [new UnauthorizedError(), 'UNAUTHORIZED', 401],
      [new ForbiddenError(), 'FORBIDDEN', 403],
      [new NotFoundError(), 'NOT_FOUND', 404],
      [new ConflictError(), 'CONFLICT', 409],
    ];
    for (const [error, code, status] of cases) {
      expect(error).toBeInstanceOf(AMCError);
      expect(error).toBeInstanceOf(Error);
      expect([error.code, error.status]).toEqual([code, status]);
      expect(error.name).toBe(error.constructor.name);
    }
  });

  it('renders an envelope that keeps FastAPI-style detail', () => {
    const envelope = new NotFoundError('Run not found', { details: { run_id: 'r1' } }).toEnvelope();
    expect(envelope).toEqual({
      detail: 'Run not found',
      error: { code: 'NOT_FOUND', message: 'Run not found', status: 404, details: { run_id: 'r1' } },
    });
  });

  it('never leaks a non-AMC error message', () => {
    const envelope = toErrorEnvelope(new Error('db password=hunter2'));
    expect(envelope.error).toEqual({ code: 'INTERNAL', message: 'Internal error', status: 500 });
  });

  it('recognises branded errors and validates conditions', () => {
    expect(isAMCError(new ConflictError())).toBe(true);
    expect(isAMCError(new Error('x'))).toBe(false);
    expect(isAMCError(null)).toBe(false);
    expect(() => ensureValid(false, 'bad input', { field: 'name' })).toThrow(ValidationError);
    expect(() => ensureValid(true, 'fine')).not.toThrow();
  });

  it('maps response bodies to typed errors', () => {
    const fastapi = errorFromResponse(404, { detail: 'Run not found' });
    expect(fastapi).toBeInstanceOf(NotFoundError);
    expect(fastapi.message).toBe('Run not found');
    const envelope = errorFromResponse(409, { detail: 'x', error: { code: 'STALE', message: 'Stale approval', status: 409 } });
    expect(envelope).toBeInstanceOf(ConflictError);
    expect([envelope.code, envelope.message]).toEqual(['STALE', 'Stale approval']);
    const other = errorFromResponse(503, {}, 'Service Unavailable');
    expect([other.code, other.status, other.message]).toEqual(['UNKNOWN', 503, 'Service Unavailable']);
  });
});
