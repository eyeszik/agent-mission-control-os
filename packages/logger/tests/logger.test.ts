import { describe, expect, it } from 'vitest';
import { REDACTED, createLogger, parseLogLevel, type LogSink } from '../src/index';

function capture() {
  const lines: Array<{ level: string; args: unknown[] }> = [];
  const sink = Object.fromEntries(
    (['debug', 'info', 'warn', 'error'] as const).map((level) => [level, (...args: unknown[]) => lines.push({ level, args })]),
  ) as unknown as LogSink;
  return { lines, sink };
}

describe('@amc/logger', () => {
  it('filters below the configured level', () => {
    const { lines, sink } = capture();
    const logger = createLogger({ level: 'warn', sink });
    logger.debug('d');
    logger.info('i');
    logger.warn('w');
    logger.error('e');
    expect(lines.map((l) => l.level)).toEqual(['warn', 'error']);
  });

  it('prefixes the name, merges child bindings and redacts secrets', () => {
    const { lines, sink } = capture();
    const logger = createLogger({ name: 'web', sink }).child({ run_id: 'r1' });
    logger.info('sent', { authorization: 'Bearer abc', nested: { api_key: 'k', ok: 1 }, err: new Error('boom') });
    expect(lines[0]?.args).toEqual([
      '[web] sent',
      { run_id: 'r1', authorization: REDACTED, nested: { api_key: REDACTED, ok: 1 }, err: { name: 'Error', message: 'boom' } },
    ]);
  });

  it('parses levels leniently', () => {
    expect(parseLogLevel('WARNING')).toBe('warn');
    expect(parseLogLevel(' debug ')).toBe('debug');
    expect(parseLogLevel('verbose')).toBe('info');
    expect(parseLogLevel(undefined, 'error')).toBe('error');
  });
});
