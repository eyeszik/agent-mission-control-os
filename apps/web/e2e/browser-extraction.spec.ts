import { expect, test } from '@playwright/test';

test('local Obscura extracts supplied HTML and shows persisted proof', async ({ page, request }) => {
  test.skip(process.env.E2E_OBSCURA_ENABLED !== '1', 'Requires explicitly enabled, verified local container runtime');
  const api = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8100';
  const project = 'obscura-preview-fixture';
  const created = await request.post(`${api}/projects`, { headers: { 'Idempotency-Key': 'obscura-preview-project' }, data: { project_id: project, slug: project, display_name: 'Obscura activation fixture' } });
  expect([201, 409]).toContain(created.status());
  await page.goto('/agency');
  await page.getByLabel('Project', { exact: true }).selectOption(project);
  await page.getByRole('button', { name: 'Integrations', exact: true }).first().click();
  await expect(page.getByText('Local extraction enabled', { exact: true })).toBeVisible();
  await page.getByLabel('Source reference', { exact: true }).fill('fixture:browser-activation');
  await page.getByLabel('Supplied HTML', { exact: true }).fill('<h1>Obscura browser fixture</h1>');
  await page.getByRole('button', { name: 'Extract supplied HTML', exact: true }).click();
  await expect(page.getByText(/SUCCEEDED ·/)).toBeVisible({ timeout: 30000 });
  await expect(page.getByText('# Obscura browser fixture', { exact: true })).toBeVisible();
  await page.getByText('Persisted proof summary', { exact: true }).click();
  await expect(page.getByText(/"execution_count": 1/)).toBeVisible();
});

test('public HTTPS extraction produces retrieved evidence and persisted proof', async ({ page, request }) => {
  test.skip(process.env.E2E_OBSCURA_PUBLIC !== '1', 'Explicit live public-web validation only');
  const api = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8100';
  const project = 'obscura-preview-fixture';
  const created = await request.post(`${api}/projects`, { headers: { 'Idempotency-Key': 'obscura-preview-project' }, data: { project_id: project, slug: project, display_name: 'Obscura activation fixture' } });
  expect([201, 409]).toContain(created.status());
  await page.goto('/agency');
  await page.getByLabel('Project', { exact: true }).selectOption(project);
  await page.getByRole('button', { name: 'Integrations', exact: true }).first().click();
  await page.getByLabel('Public HTTPS URL').fill('https://example.com');
  const response = page.waitForResponse(r => r.url().endsWith(`/browser/projects/${project}/extractions`) && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Browse and extract URL', exact: true }).click();
  const data = await (await response).json();
  expect(data.status).toBe('SUCCEEDED');
  expect(data.content.source_status).toBe('RETRIEVED');
  expect(data.content.retrieval.final_url).toBe('https://example.com');
  await expect(page.getByText(/SUCCEEDED ·/)).toBeVisible();
  await expect(page.getByText(/This domain is for use in documentation examples/)).toBeVisible();
  await page.getByText('Persisted proof summary', { exact: true }).click();
  await expect(page.getByText(/"matched_observation_count": 1/)).toBeVisible();
});
