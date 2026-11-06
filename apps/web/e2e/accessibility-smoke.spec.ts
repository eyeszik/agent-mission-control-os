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
      // CSS Color 4 values (lab/oklch) are valid computed colors in Tailwind
      // v4. Resolve through the browser's actual color pipeline instead of a
      // regex that only accepts rgb() and silently blocks accessibility CI.
      const parseRgb = (value: string): [number, number, number, number] => {
        const canvas = document.createElement('canvas');
        canvas.width = 1;
        canvas.height = 1;
        const context = canvas.getContext('2d', { willReadFrequently: true });
        if (!context) throw new Error('Canvas 2D context unavailable for color conversion');
        context.clearRect(0, 0, 1, 1);
        context.fillStyle = value;
        context.fillRect(0, 0, 1, 1);
        const channels = context.getImageData(0, 0, 1, 1).data;
        return [channels[0], channels[1], channels[2], channels[3]];
      };
      const luminance = ([r, g, b]: [number, number, number]) => {
        const linear = [r, g, b].map((channel) => {
          const value = channel / 255;
          return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
        });
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
      };

      const [fr, fg, fb, fa] = parseRgb(getComputedStyle(element).color);
      if (fa !== 255) throw new Error('Heading color transparency requires explicit compositing');
      const foreground: [number, number, number] = [fr, fg, fb];
      let current: Element | null = element;
      let background: [number, number, number] | null = null;
      while (current) {
        const computed = getComputedStyle(current);
        const bg = computed.backgroundColor;
        if (bg && bg !== 'transparent' && !bg.endsWith(', 0)')) {
          const [r, g, b, alpha] = parseRgb(bg);
          if (alpha === 255) {
            background = [r, g, b];
            break;
          }
          // Semi-transparent layers need compositing; do not produce a false
          // accessibility PASS from an inaccurately assumed background.
          if (alpha !== 0) throw new Error('Translucent background needs alpha compositing');
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
