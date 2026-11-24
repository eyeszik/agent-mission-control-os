/**
 * Twin of `agency/design/compatibility.py`. Blocking: declared incompatibility
 * (either direction) or a disabled style. Warnings: deprecated/experimental
 * styles, undeclared dimension overlap, and brief text matching `unsuitable_for`.
 */
import { compareCodePoints, pySorted } from '@amc/kernel';
import { pyStrip } from './python';
import { getStyle, type StyleDefinition, type StyleLibrary } from './registry';

export interface CompatibilityReport {
  readonly conflicts: string[];
  readonly warnings: string[];
  readonly blocking: boolean;
}

export interface CompatibilityOptions {
  readonly briefText?: string;
  /** `false` skips declared-dimension overlap warnings (the composer reports actual contention). */
  readonly dimensionOverlap?: boolean;
  readonly library: StyleLibrary;
}

function statusFindings(styles: readonly StyleDefinition[], conflicts: string[], warnings: string[]): void {
  for (const style of styles) {
    if (style.status === 'disabled') {
      conflicts.push(`'${style.name}' (${style.id}) is disabled and cannot be composed`);
    } else if (style.status === 'deprecated' || style.status === 'experimental') {
      warnings.push(`'${style.name}' (${style.id}) is ${style.status}`);
    }
  }
}

function pairKey(left: StyleDefinition, right: StyleDefinition): string {
  return [left.id, right.id].sort(compareCodePoints).join('\u0000');
}

function overlapWarning(left: StyleDefinition, right: StyleDefinition): string | null {
  const declared = left.compatible_with.includes(right.id) || right.compatible_with.includes(left.id);
  const shared = pySorted(new Set(left.design_dimensions.filter((d) => right.design_dimensions.includes(d))));
  if (shared.length === 0 || declared) return null;
  return (
    `'${left.name}' and '${right.name}' both shape ${shared.join(', ')} without a declared ` +
    'compatibility; assign those dimensions explicitly'
  );
}

function pairFindings(left: StyleDefinition, right: StyleDefinition, overlap: boolean, out: CompatibilityReport): void {
  if (right.incompatible_with.includes(left.id) || left.incompatible_with.includes(right.id)) {
    out.conflicts.push(`'${left.name}' (${left.id}) is incompatible with '${right.name}' (${right.id})`);
    return;
  }
  const warning = overlap ? overlapWarning(left, right) : null;
  if (warning !== null) out.warnings.push(warning);
}

function briefFindings(styles: readonly StyleDefinition[], briefText: string, warnings: string[]): void {
  const lowered = briefText.toLowerCase();
  if (!pyStrip(lowered)) return;
  for (const style of styles) {
    for (const phrase of style.unsuitable_for) {
      if (phrase && lowered.includes(phrase.toLowerCase())) {
        warnings.push(`'${style.name}' is marked unsuitable for '${phrase}'`);
      }
    }
  }
}

/** Python `analyze_style_compatibility`; the library is an explicit input. */
export function analyzeStyleCompatibility(styleIds: readonly string[], options: CompatibilityOptions): CompatibilityReport {
  const styles = styleIds.map((id) => getStyle(id, options.library));
  const report: CompatibilityReport = { conflicts: [], warnings: [], blocking: false };
  statusFindings(styles, report.conflicts, report.warnings);
  const seen = new Set<string>();
  styles.forEach((left, index) => {
    for (const right of styles.slice(index + 1)) {
      const key = pairKey(left, right);
      if (seen.has(key)) continue;
      seen.add(key);
      pairFindings(left, right, options.dimensionOverlap ?? true, report);
    }
  });
  briefFindings(styles, options.briefText ?? '', report.warnings);
  return { ...report, blocking: report.conflicts.length > 0 };
}
