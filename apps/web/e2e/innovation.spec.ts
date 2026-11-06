import { expect, test } from '@playwright/test';

// Real local API + persisted simulation. No fake approvals or model output.
const API = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8000';
const PROJECT = process.env.E2E_PROJECT_ID ?? 'proj_1';

test('UNBOUND persists a simulated cohort, controls, lineage and experiment drafts at mobile width', async ({ page, request }) => {
  const seed = await request.post(`${API}/projects`, {
    headers: { 'Idempotency-Key': `innovation-e2e-project-${PROJECT}` },
    data: { display_name: 'UNBOUND E2E (fictional)', project_id: PROJECT, slug: `innovation-e2e-${PROJECT}` },
  });
  expect([201, 409]).toContain(seed.status());
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/mission-control?mode=innovation&innovation_project=${encodeURIComponent(PROJECT)}`);
  const foundry = page.locator('section[aria-labelledby="innovation-title"]');
  await expect(foundry.getByRole('heading', { name: 'UNBOUND Innovation Foundry' })).toBeVisible();
  await foundry.getByLabel('Innovation objective').fill('Fictional fixture: help neighborhoods share reusable tools');
  await foundry.getByRole('button', { name: 'Start simulated run' }).click();
  await expect(foundry.getByRole('status').filter({ hasText: 'RECEIVED' })).toBeVisible();
  await foundry.getByRole('button', { name: 'Pause', exact: true }).click();
  await expect(foundry.getByRole('status').filter({ hasText: 'PAUSED' })).toBeVisible();
  await foundry.getByRole('button', { name: 'Resume', exact: true }).click();
  await expect(foundry.getByRole('status').filter({ hasText: 'RECEIVED' })).toBeVisible();
  // Delay only transport: the real backend still executes and persists the tick.
  let releaseTick: () => void = () => undefined;
  let tickArrived: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => { releaseTick = resolve; });
  const arrival = new Promise<void>((resolve) => { tickArrived = resolve; });
  await page.route(/\/innovation\/projects\/[^/]+\/runs\/[^/]+\/tick$/, async (route) => {
    tickArrived(); await gate; await route.continue();
  });
  await foundry.getByRole('button', { name: 'Advance simulation' }).click();
  await arrival;
  await foundry.getByRole('navigation').getByRole('button', { name: 'Runs', exact: true }).click();
  const historyButtons = foundry.getByRole('list').getByRole('button');
  await expect(historyButtons.first()).toBeDisabled();
  releaseTick();
  await expect(foundry.getByRole('status').filter({ hasText: 'COMPLETED' })).toBeVisible();
  await expect(foundry.getByText('35 raw ideas · 5 wildcards · 4 hybrids · 2 meta-hybrids')).toBeVisible();
  await expect(page).toHaveURL(/innovation_run=/);
  await page.reload();
  const views = foundry.getByRole('navigation', { name: 'Innovation Foundry views' });
  await views.getByRole('button', { name: 'Ideas', exact: true }).click();
  await expect(foundry.getByRole('article')).toHaveCount(41);
  await views.getByRole('button', { name: 'Lineage', exact: true }).click();
  await expect(foundry.getByRole('list', { name: 'Concept lineage' }).getByRole('listitem')).not.toHaveCount(0);
  await views.getByRole('button', { name: 'Experiments', exact: true }).click();
  await expect(foundry.getByRole('article')).toHaveCount(5);
  await expect(foundry.getByText(/NOT_RUN · approval NOT_REQUESTED/)).toHaveCount(5);
  await views.getByRole('button', { name: 'Reviews', exact: true }).click();
  await expect(foundry.getByRole('button', { name: 'Approve experiment (unavailable)' })).toBeDisabled();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
});
