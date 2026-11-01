import { expect, test } from '@playwright/test';

const API = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8000';
const PROJECT = process.env.E2E_PROJECT_ID ?? 'proj_1';
const base = `${API}/innovation/projects/${encodeURIComponent(PROJECT)}/runs`;

test.beforeEach(async ({ request }) => {
  const response = await request.post(`${API}/projects`, {
    headers: { 'Idempotency-Key': `innovation-capabilities-project-${PROJECT}` },
    data: { display_name: 'UNBOUND capability fixtures', project_id: PROJECT, slug: `innovation-capabilities-${PROJECT}` },
  });
  expect([201, 409]).toContain(response.status());
});

test('mobile workbench reads actual lexical receipts without relabeling fixture inputs', async ({ page, request }) => {
  const created = await request.post(base, { headers: { 'Idempotency-Key': crypto.randomUUID() }, data: { objective: 'Fictional local audit of library discovery mechanisms', provider: 'simulated' } });
  expect(created.status()).toBe(201);
  const initial = await created.json();
  const completed = await request.post(`${base}/${initial.run.run_id}/tick`, { data: { expected_version: initial.version } });
  expect(completed.status()).toBe(200);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/mission-control?mode=innovation&innovation_project=${PROJECT}&innovation_run=${initial.run.run_id}`);
  const capability = page.getByRole('complementary', { name: 'Innovation capability records' });
  await capability.getByRole('button', { name: 'Run local lexical experiment' }).click();
  const measured = capability.getByLabel('Actual local computation receipt');
  await expect(measured.getByText(/ACTUAL LOCAL COMPUTATION/)).toBeVisible();
  await expect(measured.getByText(/SIMULATED_OFFLINE_FIXTURE/)).toBeVisible();
  await expect(measured.getByText(/Canonical permits: 1; execution receipts: 1; matched observations: 1/)).toBeVisible();
  await expect(measured.getByText(/Preregistered decision: SUPPORTED/)).toBeVisible();
  await expect(capability.getByText(/C7 hosted mobile HTTPS: NOT_VERIFIED/)).toBeVisible();
  await page.reload();
  await expect(measured.getByText(/Persisted receipt reloaded/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
});

test('mobile live brief prepares a scoped blocked intent without calling a provider', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/mission-control?mode=innovation&innovation_project=${PROJECT}`);
  const foundry = page.locator('section[aria-labelledby="innovation-title"]');
  await foundry.getByLabel('Innovation objective').fill('Fictional live-generation brief for accessible neighborhood repair');
  await foundry.getByLabel('Generation source').selectOption('live');
  await foundry.getByRole('button', { name: 'Save live-generation brief' }).click();
  await expect(foundry.getByRole('button', { name: 'Advance simulation' })).toBeDisabled();
  const capability = foundry.getByRole('complementary', { name: 'Innovation capability records' });
  await capability.getByRole('button', { name: 'Prepare live generation intent' }).click();
  await expect(capability.getByLabel('Provider generation intent')).toBeVisible();
  await expect(capability.getByLabel('Generation blockers')).not.toBeEmpty();
  await expect(capability.getByRole('button', { name: 'Advance approved generation' })).toBeDisabled();
  await expect(capability.getByText(/C1 live generation: NOT_VERIFIED/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
});
