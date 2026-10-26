import { expect, test } from '@playwright/test';

// Agency OS (/agency) against the real local stack. CI runs one operator
// principal with no model key and no budget policy, so this proves what that
// environment can: the ten-section shell, a client linked to a project, a plan
// preview that executes nothing, an external effect that is refused (not
// queued) at the default autonomy, autonomy raising reserved for owners,
// honest live/measurement states, keyboard navigation, theming and mobile
// layout. The multi-person approve -> sandbox dispatch -> export journey is
// covered by services/langgraph/tests/test_ace12_*.py.

const API = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8000';
const PROJECT = process.env.E2E_PROJECT_ID ?? 'proj_1';
const SECTIONS = ['Overview', 'Clients', 'Projects', 'Missions', 'Creative Studio', 'Approvals', 'Deliverables', 'Analytics', 'Integrations', 'Settings'];

// The primary Sections sidebar is lg-only (>=1024px); Playwright's default
// Desktop Chrome viewport is 1280x720 today, but a stable explicit viewport
// prevents browser/device preset changes from collapsing the navigation.
test.use({ colorScheme: 'dark', viewport: { width: 1440, height: 900 } });

test.beforeAll(async ({ request }) => {
  const res = await request.post(`${API}/projects`, {
    headers: { 'Idempotency-Key': `agency-e2e-${PROJECT}` },
    data: { display_name: 'Agency E2E (fictional)', project_id: PROJECT, slug: `agency-e2e-${PROJECT}` },
  });
  expect([201, 409]).toContain(res.status());
});

test('Agency OS: shell, client, plan preview, refused external effect, honest states', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  const nav = page.getByRole('navigation', { name: 'Sections' });
  const go = (label: string) => nav.getByRole('button', { name: label, exact: true }).click();
  const status = (text: string | RegExp) => page.getByRole('status').filter({ hasText: text }).first();

  await page.goto('/agency');
  for (const name of SECTIONS) await expect(nav.getByRole('button', { name, exact: true })).toBeVisible();
  await page.getByLabel('Project', { exact: true }).selectOption(PROJECT);

  const client = `E2E Client ${Date.now().toString(36)} (fictional)`;
  await go('Clients');
  await page.getByLabel('Client name').fill(client);
  await page.getByRole('button', { name: 'Add client' }).click();
  await expect(status(`Added ${client}`)).toBeVisible({ timeout: 15_000 });
  await page.getByRole('button', { name: 'Link selected project' }).click();
  await expect(status('Linked the selected project')).toBeVisible({ timeout: 15_000 });

  await go('Missions');
  await page.getByLabel('Brief').fill('Create an SVG logo mark for the spring collection.');
  await page.getByRole('button', { name: 'Preview plan' }).click();
  await expect(status(/^Plan: /)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('PREVIEW: nothing was executed')).toBeVisible();

  // Default autonomy is DRAFT: a publication is refused at preview, not queued.
  await page.getByLabel('Action', { exact: true }).selectOption('sandbox.cms.publish_page');
  await page.getByRole('button', { name: 'Preview effect' }).click();
  await expect(status('Would be blocked')).toBeVisible({ timeout: 15_000 });

  await go('Settings');
  await expect(page.getByText('Raising needs an owner or admin.').first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole('radio', { name: /Request approval/ })).toBeDisabled();

  await go('Integrations');
  await expect(page.getByText('Live external execution:')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText('No source definition').first()).toBeVisible();

  // Keyboard: the command palette reaches any section.
  await page.keyboard.press('Control+K');
  const palette = page.getByRole('dialog', { name: 'Command palette' });
  const search = palette.getByRole('combobox');
  // Opening the dialog schedules input focus; visibility alone is not readiness.
  await expect(search).toBeFocused();
  await search.fill('analytics');
  await expect(palette.getByRole('option', { name: 'Analytics Section', exact: true })).toHaveAttribute('aria-selected', 'true');
  await search.press('Enter');
  await expect(page.getByText('Counts of stored records')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText('Not measured').first()).toBeVisible();

  await page.getByRole('button', { name: 'Use light theme' }).click();
  await expect(page.locator('[data-amc-theme="light"]')).toHaveCount(1);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('dialog', { name: 'Navigation' }).getByRole('button', { name: 'Missions', exact: true }).click();
  await expect(page.getByLabel('Brief')).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);

  expect(errors).toEqual([]);
});
