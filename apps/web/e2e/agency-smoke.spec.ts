import { expect, test, type Page } from '@playwright/test';

async function hydrateMissionControl(
  page: Page,
  run: { run_id: string; project_id?: string; status: string; proof?: unknown },
  pendingApproval?: Record<string, unknown> | null,
) {
  await page.waitForFunction(() => Boolean(window.__amcRunStore && window.__amcApprovalStore));
  await page.evaluate(({ nextRun, nextApproval, nextRunId }) => {
    window.__amcRunStore?.getState().upsertRun({
      id: nextRun.run_id,
      tenant_id: 'tenant_1',
      project_id: nextRun.project_id ?? 'proj_1',
      status: nextRun.status === 'needs_approval' ? 'needs_approval' : 'running',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      metadata: { proof: nextRun.proof ?? null },
    });
    window.__amcRunStore?.getState().setActiveRun(nextRunId);
    if (nextApproval?.approval_id) {
      window.__amcApprovalStore?.getState().upsertApproval(nextApproval as any);
    }
  }, { nextRun: run, nextApproval: pendingApproval ?? null, nextRunId: run.run_id });
  await page.waitForFunction(
    (nextRunId) => window.__amcRunStore?.getState().activeRunId === nextRunId,
    run.run_id,
  );
}

test.describe('Agent Mission Control local release smoke', () => {
  test('renders the live Mission Control surface without browser errors', async ({ page }) => {
    await page.goto('/mission-control', { waitUntil: 'networkidle' });

    await expect(page.getByRole('heading', { name: 'Mission Control' })).toBeVisible();
    await expect(page.getByText('Campaign Terminal', { exact: true })).toBeVisible();
    await expect(page.getByText('Consequential Lifecycle', { exact: true })).toBeVisible();
    await expect(page.getByLabel('Brand name')).toBeVisible();
    await expect(page.getByLabel('Target audience')).toBeVisible();
    await expect(page.getByLabel(/Goals/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Compile Idea Workspace' })).toBeDisabled();
  });

  test('reaches HITL through the real browser/API path with provider absence explicitly degraded', async ({ page }) => {
    const apiResponse = await page.request.post('http://127.0.0.1:8000/agency/runs', {
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'e2e-hitl-degraded' },
      data: {
        project_id: 'proj_1',
        brief: {
          brand_name: 'Deterministic Local Test',
          target_audience: 'Local release-gate operators',
          goals: ['verify browser path', 'verify HITL safety'],
          channels: [],
          constraints: [],
        },
      },
    });
    expect(apiResponse.status()).toBe(201);
    const payload = await apiResponse.json();
    expect(payload.pipeline).toBe('branding_marketing_agency');
    expect(payload.status).toBe('needs_approval');
    expect(payload.degraded).toBe(true);
    expect(payload.pending_approval?.status).toBe('pending');
    expect(payload.pending_approval?.run_id).toBe(payload.run_id);
    expect(payload.campaign_package).toBeTruthy();

    await page.goto('/mission-control');
    await hydrateMissionControl(page, payload, payload.pending_approval ?? null);
    await expect(page.getByText('Consequential Lifecycle', { exact: true })).toBeVisible();
    await expect(page.getByText('Lineage Remediation Queue', { exact: true })).toBeVisible();
    await expect(page.getByText('Run Remediation', { exact: true })).toBeVisible();
    await expect(page.getByTestId('mc-compile-blocked-banner')).toBeVisible();
    await expect(page.getByTestId('mc-release-btn')).toBeVisible();
    await expect(page.getByTestId('mc-release-btn')).toBeDisabled();
    const runRemediationSection = page.getByText('Run Remediation', { exact: true }).locator('..');
    await expect(runRemediationSection).toContainText('compile gate');
    await expect(runRemediationSection).toContainText('BLOCKED');
    await expect(runRemediationSection).toContainText(/hook gaps\s*[1-9]/i);
    await expect(page.getByRole('button', { name: 'Compile Idea Workspace' })).toBeDisabled();
  });

  test('surfaces stale approval lineage remediation on the real browser/API path', async ({ page }) => {
    const apiResponse = await page.request.post('http://127.0.0.1:8000/agency/runs', {
      headers: { 'Content-Type': 'application/json', 'Idempotency-Key': 'e2e-lineage-remediation' },
      data: {
        project_id: 'proj_1',
        brief: {
          brand_name: 'Lineage E2E',
          target_audience: 'Operators validating stale approval lineage',
          goals: ['artifact change', 'stale approval', 'regenerate'],
          channels: [],
          constraints: [],
        },
      },
    });
    expect(apiResponse.status()).toBe(201);
    const payload = await apiResponse.json();
    const runId = payload.run_id as string;

    await page.goto('/mission-control');
    await hydrateMissionControl(page, payload, payload.pending_approval ?? null);
    await expect(page.getByRole('button', { name: 'Simulate protected artifact change' })).toBeVisible();
    await page.getByRole('button', { name: 'Simulate protected artifact change' }).click();
    const runRemediationSection = page.getByText('Run Remediation', { exact: true }).locator('..');
    await expect(runRemediationSection).toContainText('compile gate');
    await expect(runRemediationSection).toContainText('BLOCKED');
    await expect(page.getByText('Lineage Remediation Queue', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Regenerate approval' }).first()).toBeVisible();
    await page.getByRole('button', { name: 'Regenerate approval' }).first().click();
    await expect(page.getByText(/resolved queue/i)).toBeVisible();
  });
});
