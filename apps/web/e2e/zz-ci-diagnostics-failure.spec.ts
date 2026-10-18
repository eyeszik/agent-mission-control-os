// Temporary branch-only proof; removed after the failure artifact is inspected.
import { test, expect } from '@playwright/test';

test('synthetic failure verifies browser diagnostics and retained artifacts', async ({ page, request }) => {
  await page.goto('/mission-control');
  await expect(page.getByRole('heading', { name: 'Mission Control' })).toBeVisible();
  const response = await request.get('http://127.0.0.1:8000/health?diagnostic_marker=SYNTHETIC_DIAGNOSTIC_MARKER&GH_TOKEN=synthetic-do-not-upload');
  expect(response.ok()).toBe(true);
  expect(true, 'Intentional branch-only failure to validate CI diagnostics').toBe(false);
});
