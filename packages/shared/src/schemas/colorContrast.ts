// Mirrors services/langgraph/agency/artifacts/color_contrast.py. Same formula,
// same thresholds -- if these two drift, BrandCoreSchema's distinguishability
// check would pass or fail differently in the browser than in the backend
// that actually persists the artifact.
//
// WCAG 2.2 SC 1.4.11 exempts logotypes from contrast requirements ("Text
// that is part of a logo or brand name has no minimum contrast requirement").
// These utilities are not wired into LogoLockupSchema for that reason.

export const HEX_COLOR_RE = /^#[0-9A-Fa-f]{6}$/;

function srgbChannelToLinear(channel255: number): number {
  const c = channel255 / 255;
  if (c <= 0.03928) {
    return c / 12.92;
  }
  return ((c + 0.055) / 1.055) ** 2.4;
}

export function relativeLuminance(hexColor: string): number {
  if (!HEX_COLOR_RE.test(hexColor)) {
    throw new Error(`'${hexColor}' is not a 6-digit hex color (e.g. '#1a2b4c')`);
  }
  const value = hexColor.slice(1);
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return (
    0.2126 * srgbChannelToLinear(r) +
    0.7152 * srgbChannelToLinear(g) +
    0.0722 * srgbChannelToLinear(b)
  );
}

export function contrastRatio(hexA: string, hexB: string): number {
  const luminanceA = relativeLuminance(hexA);
  const luminanceB = relativeLuminance(hexB);
  const lighter = Math.max(luminanceA, luminanceB);
  const darker = Math.min(luminanceA, luminanceB);
  return (lighter + 0.05) / (darker + 0.05);
}

export function meetsWcagAA(ratio: number, largeText = false): boolean {
  return ratio >= (largeText ? 3.0 : 4.5);
}

export function meetsWcagNonText(ratio: number): boolean {
  return ratio >= 3.0;
}
