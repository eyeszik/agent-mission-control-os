import AxeBuilder from '@axe-core/playwright';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

// Website Production (UCPO) in the Agency shell against the real local stack: a brief is
// compiled into a project, the sandboxed build runs through one durable tick, and the view
// reports the real outcome. On a host without the sandbox the build must say
// BLOCKED_ISOLATION instead of pretending; both outcomes are asserted honestly. Approval by
// a second person and staleness are covered by services/langgraph/tests/test_ucpo_build.py.

const API = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8000';
const PROJECT = process.env.E2E_PROJECT_ID ?? 'proj_1';
const BRIEF = JSON.parse(readFileSync(join(__dirname, '..', '..', '..', 'sample_ucpo_website.json'), 'utf-8'));
const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

test.use({ colorScheme: 'dark', viewport: { width: 1440, height: 900 } });
test.describe.configure({ mode: 'serial' });

async function expectNoAxeViolations(page: Page, state: string) {
  const { violations } = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  expect(violations.map((v) => `${v.id} ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`), state).toEqual([]);
}

async function openWebsites(page: Page, { phone = false } = {}) {
  await page.goto('/agency');
  await page.getByLabel('Project', { exact: true }).selectOption(PROJECT);
  if (phone) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('button', { name: 'Website Production' }).first().click();
}

test.beforeAll(async ({ request }) => {
  const res = await request.post(`${API}/projects`, {
    headers: { 'Idempotency-Key': `ucpo-e2e-${PROJECT}` },
    data: { display_name: 'UCPO E2E (fictional)', project_id: PROJECT, slug: `ucpo-e2e-${PROJECT}` },
  });
  expect([201, 409]).toContain(res.status());
});

test('Brief intake explains disabled actions and passes axe', async ({ page }) => {
  await openWebsites(page);
  await expect(page.getByRole('heading', { name: 'Brief intake' })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole('button', { name: 'Compile site' })).toBeDisabled();
  await expect(page.getByText('Enter a lowercase site id (letters, digits, hyphens).')).toBeVisible();
  await expectNoAxeViolations(page, 'empty brief intake');
});

test('Compile, build in the sandbox, and report the real outcome', async ({ page }) => {
  test.setTimeout(240_000);
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await openWebsites(page);
  await page.getByLabel('Site id').fill('halden-e2e');
  await page.getByLabel('WebsiteBrief (JSON)').fill(JSON.stringify(BRIEF));
  await page.getByRole('button', { name: 'Compile site' }).click();
  await expect(page.getByRole('heading', { name: 'Site halden-e2e' })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('unresolved until rendered')).toBeVisible();
  await expectNoAxeViolations(page, 'compiled site');

  await page.getByRole('button', { name: 'Build and verify in sandbox' }).click();
  const evidence = page.getByRole('heading', { name: 'Browser evidence' });
  const blocked = page.getByText(/BLOCKED_ISOLATION/).first();
  await expect(evidence.or(blocked)).toBeVisible({ timeout: 200_000 });
  if (await evidence.isVisible()) {
    await expect(page.getByText(/Eligible for approval/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Open approval queue' })).toBeEnabled();
  } else {
    await expect(page.getByRole('button', { name: 'Open approval queue' })).toBeDisabled();
  }
  await expect(page.getByRole('button', { name: 'Build and verify in sandbox' })).toBeDisabled();
  await page.getByRole('button', { name: 'Trace' }).click();
  await expect(page.getByText('"ir": [')).toBeVisible();
  await expectNoAxeViolations(page, 'after build');
  expect(errors).toEqual([]);
});

test('Holds its layout at phone width', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await openWebsites(page, { phone: true });
  await expect(page.getByRole('heading', { name: 'Brief intake' })).toBeVisible({ timeout: 15_000 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
