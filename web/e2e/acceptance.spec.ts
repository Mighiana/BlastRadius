import { readFile } from 'node:fs/promises';
import { test, expect, type Page } from '@playwright/test';
import { reportSchema } from '../src/api';

const widths = [320, 375, 768, 1024, 1440];
async function contained(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  for (const graph of await page.getByTestId('attack-graph').all()) {
    const box = await graph.boundingBox();
    expect(box).not.toBeNull();
    if (box) { expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width + 1); }
    expect(await graph.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  }
}
for (const width of widths) {
  test.describe(`${width}px responsive acceptance`, () => {
    test.use({ viewport: { width, height: 940 } });
    test('landing, real three-scenario loop, evidence, exports and navigation', async ({ page }) => {
      const failures: string[] = [];
      page.on('pageerror', error => failures.push(error.message));
      await page.goto('/');
      await expect(page.getByRole('heading', { level: 1 })).toHaveText('Your Terraform diff shows what changed.BlastRadius shows what became reachable.');
      await expect(page.locator('.product-preview').getByText('BLOCK CHANGE', { exact: true })).toBeVisible();
      await contained(page);
      await page.getByRole('link', { name: 'Explore the live demo' }).first().click();
      await expect(page.getByRole('group', { name: 'Demo scenario' }).getByRole('button')).toHaveCount(3);
      for (const scenario of ['Public SSH exposure', 'Overly broad IAM permission', 'Public sensitive S3 bucket']) {
        await page.getByRole('group', { name: 'Demo scenario' }).getByRole('button', { name: new RegExp(scenario) }).click();
        await expect(page.getByLabel('Analysis decision').getByText('SAFE TO MERGE', { exact: true })).toBeVisible();
        await page.getByRole('button', { name: 'Simulate risky change' }).click();
        await expect(page.getByLabel('Analysis decision').getByText('BLOCK CHANGE', { exact: true })).toBeVisible();
        await contained(page);
        const evidence = page.locator('.evidence-item').first().locator('summary');
        await evidence.focus(); await page.keyboard.press('Enter');
        await expect(page.locator('.evidence-item').first()).toHaveAttribute('open', '');
        await expect(page.locator('.evidence-body').first()).toBeVisible();
        await contained(page);
        await page.getByRole('button', { name: 'Before', exact: true }).click();
        await contained(page);
        await page.getByRole('button', { name: 'After', exact: true }).click();
        const remediatedResponse = page.waitForResponse(response => response.url().includes('/api/demo/') && response.url().endsWith('stage=remediated') && response.ok());
        if (scenario === 'Overly broad IAM permission') await page.getByRole('button', { name: 'Restore least-privilege fixture' }).click();
        else await page.getByRole('button', { name: 'Remediate & re-analyze' }).click();
        const remediated = reportSchema.parse(await (await remediatedResponse).json());
        await expect(page.getByLabel('Analysis decision').getByText(remediated.decision, { exact: true })).toBeVisible();
        expect(remediated.after.reachable_sensitive).toHaveLength(0);
        expect(remediated.new_critical_paths).toHaveLength(0);
        await contained(page);
      }
      const downloaded = page.waitForEvent('download');
      await page.getByRole('button', { name: 'JSON', exact: true }).click();
      expect((await downloaded).suggestedFilename()).toBe('blastradius-demo.json');
      await page.goto('/pricing'); await contained(page);
      await page.goto('/guide'); await contained(page);
      if (width < 768) {
        await page.getByRole('button', { name: 'Open navigation' }).click();
        await expect(page.getByRole('navigation', { name: 'Main navigation' })).toBeVisible();
        await contained(page);
        await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Get started' }).click();
        await expect(page.getByRole('button', { name: 'Open navigation' })).toHaveAttribute('aria-expanded', 'false');
      }
      expect(failures).toEqual([]);
    });
    test('local workspace HCL and plan jobs, history, deletion, usage and logout', async ({ page }) => {
      await page.goto('/dashboard');
      await page.getByRole('button', { name: 'Create local demo workspace' }).click();
      await expect(page.getByLabel('Project name')).toBeVisible();
      await page.getByLabel('Project name').fill(`Production / terraform-${'long-resource-name-'.repeat(6)}`.slice(0, 100));
      await page.getByRole('button', { name: 'Create project', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Analyze change' })).toBeVisible();
      await page.getByLabel('Baseline Terraform files').setInputFiles(new URL('../../examples/safe/main.tf', import.meta.url).pathname);
      await page.getByLabel('Candidate Terraform files').setInputFiles(new URL('../../examples/vulnerable/main.tf', import.meta.url).pathname);
      await page.getByLabel('Baseline label').fill('baseline-with-a-long-resource-name'.repeat(3));
      await page.getByRole('button', { name: 'Analyze change' }).click();
      await expect(page.getByLabel('Analysis decision').getByText('BLOCK CHANGE', { exact: true })).toBeVisible();
      await contained(page);
      const download = page.waitForEvent('download');
      await page.getByRole('button', { name: 'SARIF', exact: true }).click();
      expect((await download).suggestedFilename()).toBe('blastradius.sarif');
      await page.getByRole('button', { name: 'Plan JSON', exact: true }).click();
      const plan = await readFile(new URL('../../examples/plans/ssh_open_plan.json', import.meta.url), 'utf8');
      await page.getByLabel('Plan JSON', { exact: true }).fill(plan);
      await page.getByLabel('Baseline label').fill('plan-before');
      await page.getByLabel('Candidate label').fill('plan-after');
      await page.getByRole('button', { name: 'Analyze change' }).click();
      await expect(page.getByRole('heading', { name: 'plan-before plan-after' })).toBeVisible();
      await expect(page.getByLabel('Analysis decision').getByText('BLOCK CHANGE', { exact: true })).toBeVisible();
      await contained(page);
      await page.getByRole('button', { name: 'Delete analysis plan-before to plan-after' }).click();
      await page.getByRole('button', { name: 'Confirm delete' }).click();
      await expect(page.getByRole('button', { name: 'Delete analysis plan-before to plan-after' })).toHaveCount(0);
      await page.getByRole('button', { name: /baseline-with-a-long-resource-name.*candidate/ }).first().click();
      await expect(page.getByLabel('Analysis decision')).toBeVisible();
      await page.getByRole('link', { name: 'Usage & billing' }).click();
      await expect(page.getByText('Stripe test billing is not configured.', { exact: false })).toBeVisible();
      await expect(page.getByRole('progressbar', { name: 'Monthly analysis usage' })).toHaveAttribute('value', '2');
      await contained(page);
      if (width < 768) await page.getByRole('button', { name: 'Open navigation' }).click();
      await page.getByRole('button', { name: 'Sign out', exact: true }).click();
      await expect(page).toHaveURL('/');
      await page.goto('/history');
      await expect(page.getByRole('button', { name: 'Create local demo workspace' })).toBeVisible();
    });
  });
}
test('invalid input is actionable and never looks like a SAFE result', async ({ page }) => {
  await page.goto('/dashboard');
  await page.getByRole('button', { name: 'Create local demo workspace' }).click();
  await page.getByLabel('Project name').fill('Invalid input regression');
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  await page.getByRole('button', { name: 'Plan JSON', exact: true }).click();
  await page.getByLabel('Plan JSON', { exact: true }).fill('{"unrecognized":true}');
  await page.getByRole('button', { name: 'Analyze change' }).click();
  await expect(page.getByRole('alert')).toContainText('Terraform show -json plan');
  await expect(page.getByLabel('Analysis decision')).toHaveCount(0);
  await page.getByLabel('Plan JSON', { exact: true }).fill('{"resource_changes":[{"invalid":"shape"}]}');
  await page.getByRole('button', { name: 'Analyze change' }).click();
  await expect(page.getByRole('alert')).toContainText('Invalid Terraform plan structure');
  await page.getByRole('button', { name: 'HCL files', exact: true }).click();
  await page.getByLabel('Baseline Terraform files').setInputFiles(new URL('../../examples/safe/main.tf', import.meta.url).pathname);
  await page.getByLabel('Candidate Terraform files').setInputFiles({ name: 'broken.tf', mimeType: 'text/plain', buffer: Buffer.from('resource "aws_s3_bucket" "broken" {') });
  await page.getByRole('button', { name: 'Analyze change' }).click();
  await expect(page.getByLabel('Selected analysis').getByRole('alert')).toBeVisible();
  await expect(page.getByLabel('Analysis decision')).toHaveCount(0);
  await expect(page.locator('body')).not.toContainText('Traceback');
});
test('required IAM remediation ends in SAFE', async ({ request }) => {
  const response = await request.get('/api/demo/broad_iam?stage=remediated');
  expect(response.ok()).toBe(true);
  const report = reportSchema.parse(await response.json());
  expect(report.decision).toBe('SAFE TO MERGE');
});
