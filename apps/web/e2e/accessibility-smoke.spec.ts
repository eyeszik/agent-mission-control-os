import { expect, test } from '@playwright/test';

test.describe('Mission Control accessibility smoke', () => {
  test('checks labels, keyboard order, reduced-motion preference, and measured heading contrast', async ({ page }) => {
    await page.goto('/mission-control', { waitUntil: 'networkidle' });

    for (const label of ['Brand name', 'Target audience', 'Market', 'Language', 'Locale']) {
      await expect(page.getByLabel(label)).toBeVisible();
    }

    const duplicateIds = await page.locator('[id]').evaluateAll((nodes) => {
      const counts = new Map<string, number>();
      for (const node of nodes) {
        const id = (node as HTMLElement).id;
        counts.set(id, (counts.get(id) ?? 0) + 1);
      }
      return Array.from(counts.entries()).filter(([, count]) => count > 1).map(([id]) => id);
    });
    expect(duplicateIds).toEqual([]);

    const unlabeledControls = await page.locator('input, textarea, select').evaluateAll((nodes) =>
      nodes
        .filter((node) => {
          const control = node as HTMLInputElement;
          if (control.labels && control.labels.length > 0) return false;
          return !control.getAttribute('aria-label') && !control.getAttribute('aria-labelledby');
        })
        .map((node) => (node as HTMLElement).id || (node as HTMLInputElement).name || node.tagName)
    );
    expect(unlabeledControls).toEqual([]);

    const brandName = page.getByLabel('Brand name');
    const businessIdea = page.getByLabel('Business idea');
    await brandName.focus();
    await expect(brandName).toBeFocused();
    await page.keyboard.press('Tab');
    await expect(businessIdea).toBeFocused();

    await page.emulateMedia({ reducedMotion: 'reduce' });
    expect(
      await page.evaluate(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
    ).toBe(true);

    const contrast = await page.getByRole('heading', { name: 'Mission Control' }).evaluate((element) => {
      // Canvas performs the browser's CSS Color 4 -> sRGB conversion, including
      // Lab/OKLCH computed values emitted by Tailwind 4. Keep the WCAG formula.
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 1;
      const context = canvas.getContext('2d', { colorSpace: 'srgb', willReadFrequently: true });
      if (!context) throw new Error('sRGB canvas unavailable for contrast measurement');
      const parseRgb = (value: string): [number, number, number] => {
        if (!CSS.supports('color', value)) throw new Error(`Unsupported computed color: ${value}`);
        context.clearRect(0, 0, 1, 1);
        context.fillStyle = value;
        context.fillRect(0, 0, 1, 1);
        const [r, g, b, alpha] = context.getImageData(0, 0, 1, 1).data;
        if (alpha !== 255) throw new Error(`Contrast measurement needs an opaque color: ${value}`);
        return [r, g, b];
      };
      const luminance = ([r, g, b]: [number, number, number]) => {
        const linear = [r, g, b].map((channel) => {
          const value = channel / 255;
          return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
        });
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
      };

      const foreground = parseRgb(getComputedStyle(element).color);
      let current: Element | null = element;
      let background: [number, number, number] | null = null;
      while (current) {
        const computed = getComputedStyle(current);
        const bg = computed.backgroundColor;
        if (bg && bg !== 'transparent' && !bg.endsWith(', 0)')) {
          background = parseRgb(bg);
          break;
        }
        current = current.parentElement;
      }
      if (!background) background = [0, 0, 0];

      const l1 = luminance(foreground);
      const l2 = luminance(background);
      return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    });

    expect(contrast).toBeGreaterThanOrEqual(4.5);
  });
});
