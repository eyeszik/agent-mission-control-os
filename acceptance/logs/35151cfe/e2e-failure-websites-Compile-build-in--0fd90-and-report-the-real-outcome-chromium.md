# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: websites.spec.ts >> Compile, build in the sandbox, and report the real outcome
- Location: e2e/websites.spec.ts:48:1

# Error details

```
Error: expect(locator).toBeEnabled() failed

Locator:  getByRole('button', { name: 'Open approval queue' })
Expected: enabled
Received: disabled
Timeout:  10000ms

Call log:
  - Expect "toBeEnabled" getByRole('button', { name: 'Open approval queue' }) with timeout 10000ms
  - waiting for getByRole('button', { name: 'Open approval queue' })
    24 × locator resolved to <button disabled type="button" class="inline-flex min-h-9 items-center justify-center gap-2 rounded-md px-3 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 bg-surface text-fg-strong border border-line-strong hover:bg-surface-raised focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-focus focus-visible:ring-offset-1 focus-visible:ring-offset-canvas ">Open approval queue</button>
       - unexpected value "disabled"

```

```yaml
- button "Open approval queue" [disabled]
```

# Test source

```ts
  1  | import AxeBuilder from '@axe-core/playwright';
  2  | import { readFileSync } from 'node:fs';
  3  | import { join } from 'node:path';
  4  | import { expect, test, type Page } from '@playwright/test';
  5  | 
  6  | // Website Production (UCPO) in the Agency shell against the real local stack: a brief is
  7  | // compiled into a project, the sandboxed build runs through one durable tick, and the view
  8  | // reports the real outcome. On a host without the sandbox the build must say
  9  | // BLOCKED_ISOLATION instead of pretending; both outcomes are asserted honestly. Approval by
  10 | // a second person and staleness are covered by services/langgraph/tests/test_ucpo_build.py.
  11 | 
  12 | const API = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8000';
  13 | const PROJECT = process.env.E2E_PROJECT_ID ?? 'proj_1';
  14 | const BRIEF = JSON.parse(readFileSync(join(__dirname, '..', '..', '..', 'sample_ucpo_website.json'), 'utf-8'));
  15 | const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
  16 | 
  17 | test.use({ colorScheme: 'dark', viewport: { width: 1440, height: 900 } });
  18 | test.describe.configure({ mode: 'serial' });
  19 | 
  20 | async function expectNoAxeViolations(page: Page, state: string) {
  21 |   const { violations } = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  22 |   expect(violations.map((v) => `${v.id} ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`), state).toEqual([]);
  23 | }
  24 | 
  25 | async function openWebsites(page: Page, { phone = false } = {}) {
  26 |   await page.goto('/agency');
  27 |   await page.getByLabel('Project', { exact: true }).selectOption(PROJECT);
  28 |   if (phone) await page.getByRole('button', { name: 'Open navigation' }).click();
  29 |   await page.getByRole('button', { name: 'Website Production' }).first().click();
  30 | }
  31 | 
  32 | test.beforeAll(async ({ request }) => {
  33 |   const res = await request.post(`${API}/projects`, {
  34 |     headers: { 'Idempotency-Key': `ucpo-e2e-${PROJECT}` },
  35 |     data: { display_name: 'UCPO E2E (fictional)', project_id: PROJECT, slug: `ucpo-e2e-${PROJECT}` },
  36 |   });
  37 |   expect([201, 409]).toContain(res.status());
  38 | });
  39 | 
  40 | test('Brief intake explains disabled actions and passes axe', async ({ page }) => {
  41 |   await openWebsites(page);
  42 |   await expect(page.getByRole('heading', { name: 'Brief intake' })).toBeVisible({ timeout: 15_000 });
  43 |   await expect(page.getByRole('button', { name: 'Compile site' })).toBeDisabled();
  44 |   await expect(page.getByText('Enter a lowercase site id (letters, digits, hyphens).')).toBeVisible();
  45 |   await expectNoAxeViolations(page, 'empty brief intake');
  46 | });
  47 | 
  48 | test('Compile, build in the sandbox, and report the real outcome', async ({ page }) => {
  49 |   // Four real Chromium renders plus a two-step stale-edit sequence; measured at
  50 |   // roughly 100s on a fast machine and over 240s on a loaded shared runner, so the
  51 |   // budget is explicit rather than accidentally at the default.
  52 |   test.setTimeout(420_000);
  53 |   const errors: string[] = [];
  54 |   page.on('pageerror', (e) => errors.push(String(e)));
  55 |   await openWebsites(page);
  56 |   await page.getByLabel('Site id').fill('halden-e2e');
  57 |   await page.getByLabel('WebsiteBrief (JSON)').fill(JSON.stringify(BRIEF));
  58 |   await page.getByRole('button', { name: 'Compile site' }).click();
  59 |   await expect(page.getByRole('heading', { name: 'Site halden-e2e' })).toBeVisible({ timeout: 30_000 });
  60 |   await expect(page.getByText('unresolved until rendered')).toBeVisible();
  61 |   await expectNoAxeViolations(page, 'compiled site');
  62 | 
  63 |   await page.getByRole('button', { name: 'Build and verify in sandbox' }).click();
  64 |   const evidence = page.getByRole('heading', { name: 'Browser evidence' });
  65 |   const blocked = page.getByText(/BLOCKED_ISOLATION/).first();
  66 |   await expect(evidence.or(blocked)).toBeVisible({ timeout: 200_000 });
  67 |   if (await evidence.isVisible()) {
  68 |     await expect(page.getByText(/Eligible for approval/)).toBeVisible();
> 69 |     await expect(page.getByRole('button', { name: 'Open approval queue' })).toBeEnabled();
     |                                                                             ^ Error: expect(locator).toBeEnabled() failed
  70 |   } else {
  71 |     await expect(page.getByRole('button', { name: 'Open approval queue' })).toBeDisabled();
  72 |   }
  73 |   await expect(page.getByRole('button', { name: 'Build and verify in sandbox' })).toBeDisabled();
  74 |   await page.getByRole('button', { name: 'Trace' }).click();
  75 |   await expect(page.getByText('"ir": [')).toBeVisible();
  76 |   await expectNoAxeViolations(page, 'after build');
  77 |   expect(errors).toEqual([]);
  78 | });
  79 | 
  80 | test('Holds its layout at phone width', async ({ page }) => {
  81 |   await page.setViewportSize({ width: 375, height: 800 });
  82 |   await openWebsites(page, { phone: true });
  83 |   await expect(page.getByRole('heading', { name: 'Brief intake' })).toBeVisible({ timeout: 15_000 });
  84 |   const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  85 |   expect(overflow).toBeLessThanOrEqual(1);
  86 | });
  87 | 
```