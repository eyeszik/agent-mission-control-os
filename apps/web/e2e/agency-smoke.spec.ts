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
    await expect(brandInput).toHaveValue('');
    await expect(audienceInput).toHaveValue('');
    await expect(goalsInput).toHaveValue('');
    await expect(page.getByRole('button', { name: 'Launch Campaign' })).toBeDisabled();

    expect(browserErrors).toEqual([]);
  });
});
