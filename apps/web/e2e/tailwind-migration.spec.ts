import { test, expect } from '@playwright/test';

test('Tailwind v4 emits semantic tokens and preserves migrated v3 sizes', async ({ page }) => {
  await page.goto('/agency');
  const result = await page.evaluate(() => {
    const sample = document.createElement('div');
    sample.className = 'bg-surface text-fg rounded-sm blur-xs';
    const reference = document.createElement('div');
    reference.style.backgroundColor = 'var(--amc-semantic-color-surface)';
    reference.style.color = 'var(--amc-semantic-color-foreground)';
    document.body.append(sample, reference);
    const actual = getComputedStyle(sample);
    const expected = getComputedStyle(reference);
    const result = {
      background: actual.backgroundColor, expectedBackground: expected.backgroundColor,
      color: actual.color, expectedColor: expected.color,
      radius: actual.borderRadius, filter: actual.filter,
    };
    sample.remove();
    reference.remove();
    return result;
  });
  expect(result.background).not.toBe('rgba(0, 0, 0, 0)');
  expect(result.background).toBe(result.expectedBackground);
  expect(result.color).toBe(result.expectedColor);
  expect(result.radius).toBe('4px');
  expect(result.filter).toBe('blur(4px)');
});
