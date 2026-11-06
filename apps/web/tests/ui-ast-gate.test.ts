import { describe, expect, it } from 'vitest';
import { scanSource } from '../scripts/verify-ui-ast.mjs';

const scan = (source: string, file = 'components/Example.tsx'): string[] => scanSource(file, source);

describe('ui-ast gate', () => {
  it('rejects visual inline styles and raw colors in style objects', () => {
    expect(scan('export const A = () => <div style={{ color: "red" }} />;')).toHaveLength(1);
    expect(scan('export const B = () => <div style={{ width: "#ffffff" }} />;')).toHaveLength(1);
  });

  it('allows non-visual inline layout values', () => {
    expect(scan('export const C = ({ w }: { w: number }) => <div style={{ width: w }} />;')).toEqual([]);
  });

  it('rejects arbitrary color classes but not arbitrary sizes', () => {
    expect(scan('export const D = () => <div className="bg-[#ff0000] p-2" />;')).toHaveLength(1);
    expect(scan('export const E = () => <div className={`text-[rgb(1,2,3)]`} />;')).toHaveLength(1);
    expect(scan('export const F = () => <div className="text-[10px] max-w-[1920px]" />;')).toEqual([]);
  });

  it('allows only AITrustEnvelope to render the AI provenance root', () => {
    const root = 'export const G = () => <section aria-label="AI provenance" />;';
    expect(scan(root)).toHaveLength(1);
    expect(scan(root, 'components/mission-control/AITrustEnvelope.tsx')).toEqual([]);
  });

  it('honours the greppable amc-allow-hex escape hatch', () => {
    expect(scan('export const H = () => <div style={{ color: "red" }} />; // amc-allow-hex')).toEqual([]);
  });
});
