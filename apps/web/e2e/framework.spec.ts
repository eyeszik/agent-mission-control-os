import { expect, test } from '@playwright/test';

// Agency Operating Framework (/framework) against the real local stack. CI runs
// one operator principal, so this proves what that environment can: the
// 295-task catalog is added to a fresh project with nothing marked done,
// modules and tasks are navigable, applicability and work moves persist, a
// task cannot reach review without refs, an unresolvable ref is refused,
// verification outside review is refused, KPIs stay Not measured without
// inputs, the five assurance kinds are keyboard-navigable, the audit trail
// records each write, and the layout holds at phone width. Second-person verification, approval, gates and the
// three archetype engagements are covered by
// services/langgraph/tests/test_agency_framework*.py.

const API = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8000';
// The local principal reaches only AMC_LOCAL_PROJECT_IDS. A plan is unique per
// project, so like the other specs this one needs a fresh database.
const PROJECT = process.env.E2E_PROJECT_ID ?? 'proj_1';

test.use({ colorScheme: 'dark', viewport: { width: 1440, height: 900 } });
test.describe.configure({ mode: 'serial' });

test.beforeAll(async ({ request }) => {
  const res = await request.post(`${API}/projects`, {
    headers: { 'Idempotency-Key': `framework-e2e-${PROJECT}` },
    data: { display_name: 'Framework E2E (fictional)', project_id: PROJECT, slug: `framework-e2e-${PROJECT}` },
  });
  expect([201, 409]).toContain(res.status());
  const plans = await (await request.get(`${API}/agency-framework/plans`, { params: { project_id: PROJECT } })).json();
  expect(plans.items, `${PROJECT} already has a framework plan: run this spec on a fresh database`).toEqual([]);
});

test('Operating Framework: catalog, applicability, refused review and refs, assurance, audit', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  const status = (text: string | RegExp) => page.getByRole('status').filter({ hasText: text }).first();

  await page.goto('/framework');
  await page.getByLabel('Project', { exact: true }).selectOption(PROJECT);
  await expect(page.getByRole('heading', { name: 'Start the agency operating framework' })).toBeVisible({ timeout: 15_000 });
  await page.getByLabel('Engagement type').selectOption('B2C_PHYSICAL_PRODUCT');
  await page.getByLabel('Engagement scope').fill('Fictional DTC tea brand: discovery and positioning only');
  await page.getByRole('button', { name: 'Add 295-task framework' }).click();

  await expect(page.getByRole('heading', { name: 'Agency operating framework' })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('295 defined · 0 applicable · 0 not applicable · 295 not assessed')).toBeVisible();
  await expect(page.getByText('0 verified · 0 approved · 0 blocked or invalidated')).toBeVisible();

  // Modules: all 24 are listed; selecting one changes the task list.
  const modules = page.getByRole('navigation', { name: 'Modules' });
  await expect(modules.getByRole('button')).toHaveCount(24);
  await modules.getByRole('button', { name: /^AGM-05 / }).click();
  await expect(page.getByRole('list', { name: 'Tasks in AGM-05' })).toBeVisible();
  await modules.getByRole('button', { name: /^AGM-01 / }).click();
  const tasks = page.getByRole('list', { name: 'Tasks in AGM-01' });
  await tasks.getByRole('button', { name: /AGM-01-001/ }).click();

  // Inspector: applicability, then the allowed manual moves.
  const inspector = page.locator('section[aria-labelledby="task-inspector-title"]');
  await expect(inspector.getByText('From the supplied checklist')).toBeVisible();
  await inspector.getByLabel('Decision', { exact: true }).selectOption('REQUIRED');
  await inspector.getByLabel('Reason', { exact: true }).fill('Discovery interview is in scope');
  await inspector.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(inspector.getByText(/Current: Required — Discovery interview is in scope/)).toBeVisible({ timeout: 15_000 });
  await inspector.getByRole('button', { name: 'Mark ready' }).click();
  await inspector.getByRole('button', { name: 'Start work' }).click();
  await expect(inspector.getByRole('button', { name: 'Submit for review' })).toBeVisible({ timeout: 15_000 });

  // No refs: the server refuses review and the task stays active.
  await inspector.getByRole('button', { name: 'Submit for review' }).click();
  await expect(inspector.getByRole('alert')).toBeVisible({ timeout: 15_000 });
  await expect(inspector.getByRole('button', { name: 'Submit for review' })).toBeVisible();

  // A ref that does not resolve in this project is refused before it is attached.
  await inspector.getByLabel(/^Evidence/).fill('knowledge:does-not-exist');
  await inspector.getByRole('button', { name: 'Save references' }).click();
  await expect(inspector.getByRole('alert')).toBeVisible({ timeout: 15_000 });

  // Gates: five, in order; discovery still has unassessed tasks, so it claims no verdict.
  await page.getByRole('tab', { name: 'Gates' }).click();
  const gates = page.getByRole('list', { name: 'Stage gates' });
  await expect(gates.getByRole('listitem')).toHaveCount(5);
  await expect(gates.getByRole('listitem', { name: 'Discovery gate: Not assessed' })).toBeVisible();

  // KPIs: nothing recorded, so nothing is measured.
  await page.getByRole('tab', { name: 'KPIs' }).click();
  const kpis = page.getByRole('table');
  await expect(kpis.getByRole('row')).toHaveCount(14);
  await expect(kpis.getByRole('cell', { name: 'Not measured' })).toHaveCount(13);

  // Assurance: arrow keys move between the five kinds; malformed input is refused client-side.
  await page.getByRole('tab', { name: 'Assurance' }).click();
  const kinds = page.getByRole('tablist', { name: 'Assurance record kinds' });
  await kinds.getByRole('tab', { name: 'Meaning' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(kinds.getByRole('tab', { name: 'Mutation' })).toBeFocused();
  await expect(kinds.getByRole('tab', { name: 'Mutation' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByText('No Mutation records')).toBeVisible();
  await page.getByLabel('New Mutation record (JSON)').fill('{ not json');
  await page.getByRole('button', { name: 'Record Mutation' }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'The record is not valid JSON' })).toBeVisible();
  // Valid JSON naming an artifact that does not exist is refused by the server.
  await page.getByLabel('New Mutation record (JSON)').fill(JSON.stringify({
    task_ids: ['AGM-01-001'], base_ref: 'artifact:missing@v1', mutation_class: 'CLAIM_CHANGE',
    find: 'a', replace: 'b', expected_findings: ['CLAIM_CHANGED'], test_fixture_ref: 'fixture:e2e',
  }));
  await page.getByRole('button', { name: 'Record Mutation' }).click();
  await expect(page.getByRole('alert').first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText('No Mutation records')).toBeVisible();

  // Audit: every write above appended one event.
  await page.getByRole('tab', { name: 'Audit' }).click();
  const events = page.getByRole('list', { name: 'Plan events' });
  await expect(events.getByText('plan instantiated')).toBeVisible({ timeout: 15_000 });
  await expect(events.getByText('applicability')).toBeVisible();
  await expect(events.getByText('transition').first()).toBeVisible();

  // Main tabs are keyboard-navigable too.
  await page.getByRole('tab', { name: 'Audit' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab', { name: 'Tasks' })).toBeFocused();

  // Persistence: a reload shows the same plan, not a fresh instantiation form.
  await page.reload();
  await page.getByLabel('Project', { exact: true }).selectOption(PROJECT);
  await expect(page.getByText('295 defined · 1 applicable · 0 not applicable · 294 not assessed')).toBeVisible({ timeout: 30_000 });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('heading', { name: 'Agency operating framework' })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
});

test('Operating Framework: the API refuses to verify work that is not in review', async ({ request }) => {
  const plans = await (await request.get(`${API}/agency-framework/plans`, { params: { project_id: PROJECT } })).json();
  const planId = plans.items[0].plan_id;
  const detail = await (await request.get(`${API}/agency-framework/plans/${planId}/tasks/AGM-01-001`)).json();
  expect(detail.instance.state).toBe('ACTIVE');
  const verify = await request.post(`${API}/agency-framework/plans/${planId}/tasks/AGM-01-001/verify`, {
    headers: { 'Idempotency-Key': `fw-e2e-${PROJECT}-verify` }, data: { expected_version: detail.instance.version },
  });
  expect(verify.status()).toBe(409);
  expect((await verify.json()).error.code).toBeTruthy();
  const after = await (await request.get(`${API}/agency-framework/plans/${planId}/tasks/AGM-01-001`)).json();
  expect(after.instance.state).toBe('ACTIVE');
  expect(after.instance.version).toBe(detail.instance.version);
});
