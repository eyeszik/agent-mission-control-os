import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  // Single attempt by design: the release gate is stateful and retries would mask failures.
  // Note what this does and does not mean. A retry re-runs the whole journey against
  // state the first attempt already changed, so it hides real defects -- that is why
  // there are none. A per-test timeout is a different thing: it is a budget, and the
  // three render journeys do several real Chromium renders each. Budgets are raised
  // individually where measured, never by adding retries.
  retries: 0,
  workers: 1,
  reporter: process.env.CI
    ? [
        ['line'],
        ['html', { outputFolder: 'playwright-report', open: 'never' }],
        // Relative to outputDir, which is test-results by default, so this lands at
        // apps/web/test-results/junit.xml. Naming the directory again here wrote it
        // to test-results/test-results/junit.xml, where the failure-annotation step
        // and the artifact upload both looked and found nothing.
        ['junit', { outputFile: 'junit.xml' }],
      ]
    : 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:3000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
