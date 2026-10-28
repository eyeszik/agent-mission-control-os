import AxeBuilder from '@axe-core/playwright';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

// Visual Compiler (ACE x AVIC) in the Agency shell against the real local stack: a brief is
// compiled into a project, rendered by the API host's isolated Chromium and evaluated; an edit
// made against a version someone else has since changed is refused (409) and the latest version
// is loaded; a valid edit is applied; approval is requested. On a host where the renderer is
// unavailable the view must say so instead of pretending; both outcomes are asserted honestly.
// The second-person approval and local release are covered by services/langgraph/tests/test_avic_api.py.

const API = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8000';
const PROJECT = process.env.E2E_PROJECT_ID ?? 'proj_1';
const SAMPLE = JSON.parse(readFileSync(join(__dirname, '..', '..', '..', 'sample_avic_request.json'), 'utf-8'));
const ASSET = SAMPLE.requirement.asset_id as string;
const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

test.use({ colorScheme: 'dark', viewport: { width: 1440, height: 900 } });
test.describe.configure({ mode: 'serial' });

async function expectNoAxeViolations(page: Page, state: string) {
  const { violations } = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  expect(violations.map((v) => `${v.id} ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`), state).toEqual([]);
}

async function openVisuals(page: Page, { phone = false } = {}) {
  await page.goto('/agency');
  await page.getByLabel('Project', { exact: true }).selectOption(PROJECT);
  if (phone) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('button', { name: 'Visual Compiler' }).first().click();
}

test.beforeAll(async ({ request }) => {
  const res = await request.post(`${API}/projects`, {
    headers: { 'Idempotency-Key': `avic-e2e-${PROJECT}` },
    data: { display_name: 'AVIC E2E (fictional)', project_id: PROJECT, slug: `avic-e2e-${PROJECT}` },
  });
  expect([201, 409]).toContain(res.status());
});

test('Compile intake explains disabled actions and passes axe', async ({ page }) => {
  await openVisuals(page);
  await expect(page.getByRole('heading', { name: 'Compile a visual' })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole('button', { name: 'Compile', exact: true })).toBeDisabled();
  await expect(page.getByText(/Paste an AssetRequirement JSON/)).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Capabilities' })).toBeVisible();
  await expectNoAxeViolations(page, 'empty intake');
});

test('Compile, refuse a stale edit, apply a current one, request approval', async ({ page, request }) => {
  test.setTimeout(240_000);
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await openVisuals(page);
  await page.getByLabel('AssetRequirement (JSON)').fill(JSON.stringify(SAMPLE.requirement));
  const unavailable = page.getByText(/Renderer unavailable on the API host/);
  const compile = page.getByRole('button', { name: 'Compile', exact: true });
  await expect(compile.or(unavailable).first()).toBeVisible();
  if (await unavailable.isVisible()) {
    await expect(compile).toBeDisabled();
    return;
  }
  await compile.click();
  await expect(page.getByRole('heading', { name: `Asset ${ASSET}` })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole('img', { name: new RegExp(`Rendered preview of ${ASSET}`) })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole('heading', { name: 'Independent evaluation' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Recompile from scene' })).toBeDisabled();
  await expectNoAxeViolations(page, 'compiled asset');

  // Someone else changes the asset after this page loaded it.
  const base = `${API}/avic/projects/${PROJECT}/assets/${ASSET}`;
  const view = await (await request.get(base)).json();
  const other = await request.post(`${base}/edits`, {
    headers: { 'Idempotency-Key': `avic-e2e-other-${Date.now()}` },
    data: { op: 'recolor', args: { object_id: 'motif-ring-inner', palette_key: 'fog', field: 'stroke' }, base_svg_sha256: view.svg_sha256 },
  });
  expect(other.status()).toBe(200);

  await page.getByLabel('Object').selectOption('motif-ring-inner');
  await page.getByLabel('Palette colour').selectOption('paper');
  await page.getByLabel('Paint').selectOption('stroke');
  await page.getByRole('button', { name: 'Apply edit' }).click();
  await expect(page.getByText(/changed after you opened it/)).toBeVisible({ timeout: 30_000 });

  await page.getByRole('button', { name: 'Apply edit' }).click();
  await expect(page.getByText(/Applied: 1 change/)).toBeVisible({ timeout: 60_000 });

  await page.getByRole('button', { name: 'Request approval' }).click();
  await expect(page.getByText(/Approval requested/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole('button', { name: 'Release locally' })).toBeDisabled();
  await expectNoAxeViolations(page, 'after edit and approval request');
  expect(errors).toEqual([]);
});

test('Holds its layout at phone width', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await openVisuals(page, { phone: true });
  await expect(page.getByRole('heading', { name: 'Compile a visual' })).toBeVisible({ timeout: 15_000 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
