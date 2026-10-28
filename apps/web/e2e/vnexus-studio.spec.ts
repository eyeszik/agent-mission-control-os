import { expect, test } from '@playwright/test';

// VNEXUS studio against the real local stack (CI: one operator principal, no
// self-approval, no model key). It proves what that environment can prove:
// the studio drives the real API, a draft reaches review only through the
// approval route, production refuses without an approved genome, and hosted
// generation is shown as disabled. The approve -> produce path needs a second
// person and is covered by services/langgraph/tests/test_vnexus_*.py.

const API = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8000';
const PROJECT = process.env.E2E_PROJECT_ID ?? 'proj_1';

test.beforeAll(async ({ request }) => {
  const res = await request.post(`${API}/projects`, {
    headers: { 'Idempotency-Key': `vnexus-e2e-${PROJECT}` },
    data: { display_name: 'VNEXUS E2E (fictional)', project_id: PROJECT, slug: `vnexus-e2e-${PROJECT}` },
  });
  expect([201, 409]).toContain(res.status());
});

test('VNEXUS studio: draft to review, honest refusals, keyboard navigation', async ({ page }) => {
  test.setTimeout(240_000);
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  const status = (text: string | RegExp) => page.getByRole('status').filter({ hasText: text }).first();
  const brandName = `E2E Brand ${Date.now().toString(36)}`;

  await page.goto('/mission-control');
  await page.getByRole('button', { name: 'Projects', exact: true }).click();
  await page.locator('section[aria-labelledby="project-workspace-heading"] select').first().selectOption(PROJECT);
  await page.getByRole('button', { name: 'VNEXUS Studio' }).click();

  await page.getByPlaceholder('Display name').fill(brandName);
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(status(`Created ${brandName}`)).toBeVisible({ timeout: 15_000 });
  const brandSelect = page.locator('label', { hasText: /^Brand/ }).locator('select').first();
  await brandSelect.selectOption({ label: brandName });

  // Keyboard: the area list is a tablist with arrow-key navigation.
  await page.getByRole('tab', { name: 'Overview', exact: true }).focus();
  await page.keyboard.press('ArrowDown');
  await expect(page.getByRole('tab', { selected: true })).toHaveText('Brand Genome');

  // Author and submit a draft.
  await expect(status('Loaded')).toBeVisible({ timeout: 15_000 });
  await page.getByRole('button', { name: 'Add value' }).click();
  await page.getByLabel('Key', { exact: true }).last().fill('voice.register');
  await page.getByLabel('Value', { exact: true }).last().fill('plain');
  await page.getByRole('button', { name: 'Save draft' }).click();
  await expect(status('Saved draft v1')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText('Ready to submit')).toBeVisible();
  await page.getByRole('button', { name: 'Submit for approval' }).click();
  await expect(status('Submitted v1')).toBeVisible({ timeout: 15_000 });

  // Governance lists it as waiting; applying a decision nobody made changes nothing.
  await page.getByRole('tab', { name: 'Governance', exact: true }).click();
  await expect(page.getByText('Genome versions in review (1)')).toBeVisible({ timeout: 15_000 });
  await page.getByRole('button', { name: 'Apply decision' }).first().click();
  await expect(page.getByText('Genome versions in review (1)')).toBeVisible();
  await expect(page.getByText('intact', { exact: true })).toBeVisible();

  // Production refuses without an approved genome.
  await page.getByRole('tab', { name: 'Graphic Design', exact: true }).click();
  await page.getByRole('button', { name: 'Render' }).click();
  await expect(page.getByRole('alert').filter({ hasText: /no approved genome/i })).toBeVisible({ timeout: 15_000 });

  // Brand book: decisions are listed; production refuses without an approved genome; a preview renders all 24
  // pages with every gap labelled (no approved genome yet, so nothing is READY).
  await page.getByRole('tab', { name: 'Brand Book', exact: true }).click();
  await page.getByRole('button', { name: 'Open decisions' }).click();
  await expect(status(/open decision\(s\)/)).toBeVisible({ timeout: 15_000 });
  await page.getByLabel('Brand book mode').selectOption('PRODUCTION');
  await page.getByRole('button', { name: 'Build', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: /no approved genome/i })).toBeVisible({ timeout: 15_000 });
  await page.getByLabel('Brand book mode').selectOption('PREVIEW');
  await page.getByRole('button', { name: 'Build', exact: true }).click();
  await expect(status(/Built: 24 rendered/)).toBeVisible({ timeout: 120_000 });
  await expect(page.getByRole('button', { name: /^24 Release/ })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Request approval' })).toBeDisabled();

  // Hosted generation is visibly disabled.
  await page.getByRole('tab', { name: 'Provider Jobs', exact: true }).click();
  await expect(status('Jobs loaded')).toBeVisible({ timeout: 15_000 });
  const hosted = page.getByRole('row', { name: /hosted\.text_to_image/ });
  await expect(hosted).toContainText('DISABLED');
  await expect(hosted).toContainText('PAID_CALLS_NOT_AUTHORIZED');

  expect(errors).toEqual([]);
});
