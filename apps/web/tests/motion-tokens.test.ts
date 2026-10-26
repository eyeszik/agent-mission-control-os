import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { MOTION, revealVariants, staggerVariants } from '../lib/design/motion';

const tokens = JSON.parse(readFileSync(join(__dirname, '..', 'tokens', 'amc.tokens.json'), 'utf8'));

// Follow '{a.b.c}' aliases down to the literal DTCG value.
function resolve(path: string): unknown {
  const node = path.split('.').reduce((n: any, key) => n[key], tokens);
  const value = node.$value;
  const alias = typeof value === 'string' ? /^\{(.+)\}$/.exec(value) : null;
  return alias ? resolve(alias[1]) : value;
}

const seconds = (path: string) => {
  const v = resolve(path) as { value: number; unit: string };
  return v.unit === 'ms' ? v.value / 1000 : v.value;
};

describe('Framer Motion values mirror the DTCG motion tokens', () => {
  it('matches durations', () => {
    expect(MOTION.hover).toBe(seconds('semantic.motion.duration.hover'));
    expect(MOTION.reveal).toBe(seconds('semantic.motion.duration.reveal'));
    expect(MOTION.stagger).toBe(seconds('semantic.motion.duration.stagger'));
  });

  it('matches easings and the reveal offset', () => {
    expect([...MOTION.standard]).toEqual(resolve('semantic.motion.easing.standard'));
    expect([...MOTION.emphasized]).toEqual(resolve('semantic.motion.easing.emphasized'));
    expect(MOTION.revealOffset).toBe((resolve('semantic.motion.offset.reveal') as { value: number }).value);
  });

  it('reveals with opacity and offset, and staggers by the token interval', () => {
    expect(revealVariants.hidden).toEqual({ opacity: 0, y: MOTION.revealOffset });
    expect((staggerVariants.visible as any).transition.staggerChildren).toBe(MOTION.stagger);
  });
});
