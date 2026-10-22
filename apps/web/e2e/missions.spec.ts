import { expect, test } from '@playwright/test';

// Mission Council (/missions) against the real local stack, deliberately with
// no model key: the council runs on the deterministic mock model. CI runs one
// operator principal, so this proves what that environment can: idea ->
// LangGraph dispatch -> the timeline streams to the Sentinel gate -> the
// approval modal is keyboard-accessible and the server's refusal of a
// self-approval is shown while the mission stays paused. The two-person
// approve/reject -> resume -> scaffold -> blueprint journey, on all three
// engines, is covered by services/langgraph/tests/test_missions_council.py.

const API = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8000';
const PROJECT = process.env.E2E_PROJECT_ID ?? 'proj_1';

test.use({ colorScheme: 'dark', viewport: { width: 1440, height: 900 } });

test.beforeAll(async ({ request }) => {
  const res = await request.post(`${API}/projects`, {
    headers: { 'Idempotency-Key': `council-e2e-${PROJECT}` },
    data: { display_name: 'Council E2E (fictional)', project_id: PROJECT, slug: `council-e2e-${PROJECT}` },
  });
  expect([201, 409]).toContain(res.status());
});

test('Mission Council: idea, dispatch, live timeline to the gate, accessible approval modal', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));

  await page.goto('/missions');
  await expect(page.getByRole('heading', { name: 'Mission Council', level: 2 })).toBeVisible();
  await page.getByLabel('Project', { exact: true }).selectOption(PROJECT);

  const title = `Council E2E ${Date.now().toString(36)}`;
  await page.getByLabel('Idea title').fill(title);
  await page.getByLabel('What should it do?').fill('Show agent metrics on a dashboard timeline with live status cards.');
  await page.getByRole('button', { name: 'Create idea' }).click();
  await expect(page.getByRole('status').filter({ hasText: `Idea created: ${title}` })).toBeVisible({ timeout: 15_000 });

  const engines = page.getByRole('group', { name: 'Engine' });
  await expect(engines.getByRole('radio', { name: 'LangGraph' })).toBeChecked();
  await page.getByRole('button', { name: 'Dispatch to council' }).click();

  // The seats and the gate come only from persisted events.
  const seats = page.getByRole('list', { name: 'Council seats' });
  await expect(seats.getByRole('listitem', { name: 'George: Done' })).toBeVisible({ timeout: 30_000 });
  await expect(seats.getByRole('listitem', { name: 'Fable/Cipher: Done' })).toBeVisible();
  await expect(seats.getByRole('listitem', { name: 'Arty: Waiting' })).toBeVisible();
  await expect(seats.getByRole('listitem', { name: 'Sentinel gate: Awaiting a reviewer' })).toBeVisible();
  const timeline = page.getByRole('list', { name: 'Mission events' });
  await expect(timeline.getByText('Sentinel gate: approval required')).toBeVisible();
  await expect(timeline.getByText('Security review finished')).toBeVisible();
  await expect(page.getByText('Hash chain verified')).toBeVisible();

  // Keyboard: open the gate, focus moves into the dialog, Escape returns it.
  const review = page.getByRole('button', { name: 'Review gate' });
  await review.focus();
  await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog', { name: 'Sentinel gate: review before Arty builds' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Close' })).toBeFocused();
  await expect(dialog.getByText('workspace.write_scaffold', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  await expect(review).toBeFocused();

  // The single CI principal started this mission; the server refuses its approval.
  await review.click();
  await dialog.getByRole('button', { name: 'Approve and resume' }).click();
  await expect(dialog.getByRole('alert')).toBeVisible({ timeout: 15_000 });
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(seats.getByRole('listitem', { name: 'Sentinel gate: Awaiting a reviewer' })).toBeVisible();
  await expect(page.getByText('Awaiting approval').first()).toBeVisible();

  // Light theme and a phone-width layout keep the session usable.
  await page.getByRole('button', { name: 'Use light theme' }).click();
  await expect(page.locator('[data-amc-theme="light"]')).toHaveCount(1);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(seats).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);

  expect(errors).toEqual([]);
});
