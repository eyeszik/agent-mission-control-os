import { expect, test } from '@playwright/test';

// Fictional local project data: this proves queue/UI boundaries, not brand approval.
test('creative workspace queues and cancels real scoped work without inventing verification', async ({ page }) => {
  const projects = await page.request.get('http://127.0.0.1:8000/projects');
  expect(projects.ok()).toBeTruthy();
  if (!(await projects.json()).projects.some((p: {project_id: string}) => p.project_id === 'proj_1')) {
    const created = await page.request.post('http://127.0.0.1:8000/projects', {
      headers: { 'Idempotency-Key': 'fictional-creative-browser-project' },
      data: { project_id: 'proj_1', display_name: 'Fictional Creative Browser Fixture' },
    });
    expect(created.ok()).toBeTruthy();
  }
  await page.goto('/creative');
  await expect(page.getByRole('heading', { name: 'Governed creative rendering' })).toBeVisible();
  await page.getByRole('combobox', { name: 'Project', exact: true }).selectOption('proj_1');
  const engine = page.getByRole('combobox', { name: 'Rendering engine', exact: true });
  await expect(engine.getByRole('option', { name: 'paper_js', exact: true })).toHaveCount(1);
  await expect(engine.getByRole('option', { name: 'svg_js', exact: true })).toHaveCount(1);
  await engine.selectOption('remotion');
  await expect(page.getByRole('button', { name: 'Queue render' })).toBeDisabled();
  await expect(page.getByRole('status')).toContainText('ADAPTER_NOT_IMPLEMENTED');
  await engine.selectOption('paper_js');
  await expect(page.getByRole('button', { name: 'Queue render' })).toBeEnabled();
  const queued = page.waitForResponse(response => response.url().endsWith('/foundry/projects/proj_1/renders') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Queue render' }).click();
  const receipt = await queued;
  expect(receipt.status()).toBe(202);
  const job = await receipt.json();
  expect(job.job_status).toBe('queued');
  expect(job.artifact_status).toBe('pending_verification');
  expect(job.approval_status).toBe('not_requested');
  expect(job.release.allowed).toBe(false);
  const evidence = page.getByRole('region', { name: 'Render evidence' });
  await expect(evidence).toContainText(job.spec_hash);
  await expect(evidence).toContainText('Release is not authorized.');
  await evidence.getByRole('button', { name: 'Cancel queued or active render' }).click();
  await expect(evidence.locator('dd').first()).toHaveText('cancelled');
  await expect(evidence).toContainText('Release is not authorized.');
  expect((await (await page.request.get(`http://127.0.0.1:8000/foundry/projects/proj_1/renders/${job.job_id}`)).json()).artifact_id).toBeNull();
});
