import { expect, test } from '@playwright/test';

test.describe('Agent Mission Control local release smoke', () => {
  test('renders the live Mission Control surface without browser errors', async ({ page }) => {
    const browserErrors: string[] = [];
    page.on('console', (message) => {
      if (message.type() === 'error') browserErrors.push(message.text());
    });
    page.on('pageerror', (error) => browserErrors.push(error.message));

    const response = await page.goto('/mission-control', { waitUntil: 'networkidle' });
    expect(response?.ok()).toBeTruthy();

    await expect(page.getByRole('heading', { name: 'Mission Control' })).toBeVisible();
    await expect(page.getByText('Campaign Terminal', { exact: true })).toBeVisible();
    await expect(page.getByText('Consequential Lifecycle', { exact: true })).toBeVisible();
    await expect(page.getByLabel('Brand name')).toBeVisible();
    await expect(page.getByLabel('Target audience')).toBeVisible();
    await expect(page.getByLabel(/Goals/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Launch Campaign' })).toBeDisabled();

    expect(browserErrors).toEqual([]);
  });

  test('reaches HITL through the real browser/API path with provider absence explicitly degraded', async ({ page }) => {
    const browserErrors: string[] = [];
    page.on('console', (message) => {
      if (message.type() === 'error') browserErrors.push(message.text());
    });
    page.on('pageerror', (error) => browserErrors.push(error.message));

    await page.goto('/mission-control');
    const brandInput = page.getByLabel('Brand name');
    const audienceInput = page.getByLabel('Target audience');
    const goalsInput = page.getByLabel(/Goals/);

    await brandInput.fill('Deterministic Local Test');
    await audienceInput.fill('Local release-gate operators');
    await goalsInput.fill('verify browser path, verify HITL safety');

    const apiResponsePromise = page.waitForResponse(
      (response) => response.url().endsWith('/agency/runs') && response.request().method() === 'POST'
    );

    await page.getByRole('button', { name: 'Launch Campaign' }).click();
    const apiResponse = await apiResponsePromise;

    expect(apiResponse.status()).toBe(201);
    const payload = await apiResponse.json();
    expect(payload.pipeline).toBe('branding_marketing_agency');
    expect(payload.status).toBe('needs_approval');
    expect(payload.degraded).toBe(true);
    expect(payload.pending_approval?.status).toBe('pending');
    expect(payload.pending_approval?.run_id).toBe(payload.run_id);
    expect(payload.campaign_package).toBeTruthy();

    await expect(page.getByText(/Inbox/)).toContainText('(1)');
    await expect(page.getByText('Consequential Lifecycle', { exact: true })).toBeVisible();
    await expect(page.getByText('Lineage Remediation Queue', { exact: true })).toBeVisible();
    await expect(page.getByText('Run Remediation', { exact: true })).toBeVisible();
    const runRemediationSection = page.getByText('Run Remediation', { exact: true }).locator('..');
    await expect(runRemediationSection).toContainText('compile gate');
    await expect(runRemediationSection).toContainText('BLOCKED');
    await expect(runRemediationSection).toContainText(/hook gaps\s*[1-9]/i);
    await expect(brandInput).toHaveValue('');
    await expect(audienceInput).toHaveValue('');
    await expect(goalsInput).toHaveValue('');
    await expect(page.getByRole('button', { name: 'Launch Campaign' })).toBeDisabled();

    expect(browserErrors).toEqual([]);
  });

  test('surfaces stale approval lineage remediation on the real browser/API path', async ({ page }) => {
    await page.goto('/mission-control');
    await page.getByLabel('Brand name').fill('Lineage E2E');
    await page.getByLabel('Target audience').fill('Operators validating stale approval lineage');
    await page.getByLabel(/Goals/).fill('artifact change, stale approval, regenerate');

    const apiResponsePromise = page.waitForResponse(
      (response) => response.url().endsWith('/agency/runs') && response.request().method() === 'POST'
    );
    await page.getByRole('button', { name: 'Launch Campaign' }).click();
    const apiResponse = await apiResponsePromise;
    const payload = await apiResponse.json();
    const runId = payload.run_id as string;

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
