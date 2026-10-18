// Temporary branch-only proof; removed after the failure artifact is inspected.
import { appendFileSync } from 'node:fs';
import { test, expect } from '@playwright/test';

test('synthetic failure verifies browser diagnostics and retained artifacts', async ({ page }) => {
  appendFileSync('/tmp/amc-backend.log', '\nSYNTHETIC_DIAGNOSTIC_MARKER GH_TOKEN=synthetic-do-not-upload\n');
  await page.goto('/mission-control');
  await expect(page.getByRole('heading', { name: 'Mission Control' })).toBeVisible();
  expect(true, 'Intentional branch-only failure to validate CI diagnostics').toBe(false);
});
