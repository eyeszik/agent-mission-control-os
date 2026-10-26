import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

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
//
// Accessibility: every state is scanned with axe for WCAG 2.0/2.1/2.2 A and AA
// rules (no rule is disabled), and the keyboard, focus, announcement and
// reduced-motion behaviour axe cannot judge is checked directly. Passing this
// does not prove WCAG conformance: see docs/agency-operating-framework.md for
// the criteria that still need a person.

const API = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8000';
// The local principal reaches only AMC_LOCAL_PROJECT_IDS. A plan is unique per
// project, so like the other specs this one needs a fresh database.
const PROJECT = process.env.E2E_PROJECT_ID ?? 'proj_1';

test.use({ colorScheme: 'dark', viewport: { width: 1440, height: 900 } });
test.describe.configure({ mode: 'serial' });

const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

async function expectNoAxeViolations(page: Page, state: string) {
  const { violations } = await new AxeBuilder({ page }).withTags(WCAG_TAGS).analyze();
  const found = violations.map((v) => `${v.id} [${v.impact}] ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`);
  expect(found, `axe violations in: ${state}`).toEqual([]);
}

async function openFramework(page: Page) {
  await page.goto('/framework');
  await page.getByLabel('Project', { exact: true }).selectOption(PROJECT);
}

test.beforeAll(async ({ request }) => {
  const res = await request.post(`${API}/projects`, {
    headers: { 'Idempotency-Key': `framework-e2e-${PROJECT}` },
    data: { display_name: 'Framework E2E (fictional)', project_id: PROJECT, slug: `framework-e2e-${PROJECT}` },
  });
  expect([201, 409]).toContain(res.status());
  const plans = await (await request.get(`${API}/agency-framework/plans`, { params: { project_id: PROJECT } })).json();
  expect(plans.items, `${PROJECT} already has a framework plan: run this spec on a fresh database`).toEqual([]);
});

test('Accessibility: the instantiation form passes axe and works from the keyboard', async ({ page }) => {
  await openFramework(page);
  await expect(page.getByRole('heading', { name: 'Start the agency operating framework' })).toBeVisible({ timeout: 15_000 });
  await expectNoAxeViolations(page, 'instantiation form');
  const type = page.getByLabel('Engagement type');
  await type.focus();
  await page.keyboard.press('Tab');
  await expect(page.getByLabel('Engagement scope')).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: 'Add 295-task framework' })).toBeFocused();
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
  // Valid JSON naming an artifact that does not exist is recorded as an invalid test, never counted as a finding.
  await page.getByLabel('New Mutation record (JSON)').fill(JSON.stringify({
    task_ids: ['AGM-01-001'], base_ref: 'artifact:missing@v1', mutation_class: 'CLAIM_CHANGE',
    find: 'a', replace: 'b', expected_findings: ['CLAIM_CHANGED'], test_fixture_ref: 'fixture:e2e',
  }));
  await page.getByRole('button', { name: 'Record Mutation' }).click();
  await expect(status('Mutation recorded: INVALID_TEST')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole('list', { name: 'Mutation records' }).getByRole('button', { name: /INVALID_TEST/ })).toBeVisible();

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

test('Accessibility: every framework state passes axe; keyboard, focus, announcements and motion hold', async ({ page }) => {
  await openFramework(page);
  await expect(page.getByRole('heading', { name: 'Agency operating framework' })).toBeVisible({ timeout: 30_000 });
  await expectNoAxeViolations(page, 'dashboard, Tasks tab, no task selected');

  // Keyboard only: Tab from the module list to a task, open it with Enter.
  const modules = page.getByRole('navigation', { name: 'Modules' });
  await modules.getByRole('button', { name: /^AGM-01 / }).focus();
  const opener = page.getByRole('list', { name: 'Tasks in AGM-01' }).getByRole('button', { name: /AGM-01-001/ });
  for (let i = 0; i < 40 && !(await opener.evaluate((el) => el === document.activeElement)); i += 1) {
    await page.keyboard.press('Tab');
  }
  await expect(opener).toBeFocused();
  const ring = await opener.evaluate((el) => getComputedStyle(el).boxShadow);
  expect(ring, 'focused control shows a visible focus indicator').not.toBe('none');
  await page.keyboard.press('Enter');
  const inspector = page.locator('section[aria-labelledby="task-inspector-title"]');
  await expect(inspector.getByRole('heading', { level: 3 })).toBeVisible();
  await expectNoAxeViolations(page, 'task inspector open');

  // An error is announced (role=alert) and the form stays usable.
  await inspector.getByLabel(/^Evidence/).fill('knowledge:does-not-exist');
  await inspector.getByRole('button', { name: 'Save references' }).focus();
  await page.keyboard.press('Enter');
  await expect(inspector.getByRole('alert')).toContainText(/./, { timeout: 15_000 });
  await expectNoAxeViolations(page, 'task inspector with an error');

  // Closing the inspector returns focus to the task that opened it.
  await inspector.getByRole('button', { name: 'Close' }).focus();
  await page.keyboard.press('Enter');
  await expect(inspector).toHaveCount(0);
  await expect(opener).toBeFocused();

  for (const tab of ['Gates', 'KPIs', 'Audit']) {
    await page.getByRole('tab', { name: tab }).click();
    await expect(page.getByRole('tabpanel')).toBeVisible();
    await expect(page.getByRole('tabpanel').getByLabel('Loading')).toHaveCount(0, { timeout: 15_000 });
    await expectNoAxeViolations(page, `${tab} tab`);
  }
  await page.getByRole('tab', { name: 'Assurance' }).click();
  const kinds = page.getByRole('tablist', { name: 'Assurance record kinds' });
  for (const kind of ['Meaning', 'Mutation', 'Probe', 'Renewal', 'Review']) {
    await kinds.getByRole('tab', { name: kind }).click();
    // Mutation holds the invalid-test record from the flow above; the others are empty.
    const loaded = kind === 'Mutation' ? page.getByRole('list', { name: 'Mutation records' }) : page.getByText(`No ${kind} records`);
    await expect(loaded).toBeVisible({ timeout: 15_000 });
    await expectNoAxeViolations(page, `assurance ${kind} (${kind === 'Mutation' ? 'one record' : 'empty'})`);
  }
  // A record opened from the list: the detail view is scanned too.
  await kinds.getByRole('tab', { name: 'Mutation' }).click();
  await page.getByRole('list', { name: 'Mutation records' }).getByRole('button').first().click();
  await expect(page.getByText('Integrity verified')).toBeVisible({ timeout: 15_000 });
  await expectNoAxeViolations(page, 'assurance record detail');
  await kinds.getByRole('tab', { name: 'Review' }).click();
  // A review bound to a release candidate that is not in this project is refused and announced.
  await page.getByLabel('New Review record (JSON)').fill(JSON.stringify({ release_candidate_ref: 'release-candidate:missing-run' }));
  await page.getByRole('button', { name: 'Record Review' }).click();
  await expect(page.getByRole('alert').filter({ hasText: /release candidate/i })).toBeVisible({ timeout: 15_000 });
  await expectNoAxeViolations(page, 'assurance Review with a refused candidate');

  // Loading and error states, and reduced motion while loading.
  await page.emulateMedia({ reducedMotion: 'reduce' });
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route('**/agency-framework/plans/*/metrics', async (route) => { await held; await route.continue(); });
  await page.getByRole('tab', { name: 'KPIs' }).click();
  const loading = page.getByRole('tabpanel').getByLabel('Loading');
  await expect(loading).toBeVisible();
  // Motion is keyframe animation or movement; a colour or focus-ring fade on state change is not motion.
  const moving = await page.evaluate(() => {
    const movement = new Set(['transform', 'translate', 'scale', 'rotate', 'top', 'left', 'right', 'bottom', 'all']);
    return document.getAnimations().filter((a) => a.playState === 'running').filter((a) =>
      a instanceof CSSAnimation || (a instanceof CSSTransition && movement.has(a.transitionProperty))).map((a) => {
      const target = (a.effect as KeyframeEffect | null)?.target as Element | null;
      const name = a instanceof CSSAnimation ? a.animationName : (a as CSSTransition).transitionProperty;
      return `${name} on ${target?.tagName.toLowerCase()}.${String(target?.className).slice(0, 60)}`;
    });
  });
  expect(moving, 'no motion under prefers-reduced-motion').toEqual([]);
  await expectNoAxeViolations(page, 'KPIs loading');
  release();
  await expect(loading).toHaveCount(0, { timeout: 15_000 });
  await page.unroute('**/agency-framework/plans/*/metrics');

  await page.route('**/agency-framework/plans/*/audit*', (route) => route.fulfill({
    status: 503, contentType: 'application/json',
    body: JSON.stringify({ detail: 'Audit trail unavailable (simulated)', error: { code: 'UNAVAILABLE', message: 'Audit trail unavailable (simulated)', status: 503 } }),
  }));
  await page.getByRole('tab', { name: 'Audit' }).click();
  const failure = page.getByRole('tabpanel').getByRole('alert');
  await expect(failure).toContainText('unavailable', { timeout: 15_000 });
  await expectNoAxeViolations(page, 'Audit error state');
  await page.unroute('**/agency-framework/plans/*/audit*');
  await failure.getByRole('button', { name: 'Try again' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('list', { name: 'Plan events' })).toBeVisible({ timeout: 15_000 });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('tab', { name: 'Tasks' }).click();
  await expectNoAxeViolations(page, 'Tasks tab at phone width');
});
