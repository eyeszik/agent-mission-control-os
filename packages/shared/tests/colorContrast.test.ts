import { describe, it, expect } from 'vitest';
import {
  relativeLuminance,
  contrastRatio,
  meetsWcagAA,
  meetsWcagNonText,
} from '../src/schemas/colorContrast';

describe('colorContrast', () => {
  it('white has luminance 1', () => {
    expect(relativeLuminance('#FFFFFF')).toBeCloseTo(1.0, 9);
  });

  it('black has luminance 0', () => {
    expect(relativeLuminance('#000000')).toBeCloseTo(0.0, 9);
  });

  it('black on white is the textbook 21:1', () => {
    expect(contrastRatio('#000000', '#FFFFFF')).toBeCloseTo(21.0, 9);
  });

  it('contrast is symmetric', () => {
    expect(contrastRatio('#000000', '#FFFFFF')).toBe(contrastRatio('#FFFFFF', '#000000'));
  });

  it('a color against itself is 1:1', () => {
    expect(contrastRatio('#1a2b4c', '#1a2b4c')).toBeCloseTo(1.0, 9);
  });

  it('accepts lowercase and uppercase hex identically', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBe(contrastRatio('#000000', '#FFFFFF'));
  });

  it('rejects non-hex input', () => {
    expect(() => relativeLuminance('blue')).toThrow('not a 6-digit hex color');
  });

  it('rejects short hex shorthand', () => {
    expect(() => relativeLuminance('#fff')).toThrow();
  });

  it('rejects a missing hash', () => {
    expect(() => relativeLuminance('1a2b4c')).toThrow();
  });

  it('normal-text AA threshold is 4.5:1', () => {
    expect(meetsWcagAA(4.5)).toBe(true);
    expect(meetsWcagAA(4.49)).toBe(false);
  });

  it('large-text AA threshold is 3:1', () => {
    expect(meetsWcagAA(3.0, true)).toBe(true);
    expect(meetsWcagAA(2.99, true)).toBe(false);
  });

  it('non-text threshold is 3:1', () => {
    expect(meetsWcagNonText(3.0)).toBe(true);
    expect(meetsWcagNonText(2.99)).toBe(false);
  });

  it('near-identical grays fail normal-text AA', () => {
    expect(meetsWcagAA(contrastRatio('#808080', '#828282'))).toBe(false);
  });
});
