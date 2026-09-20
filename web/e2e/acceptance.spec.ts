import { readFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { test, expect, type Page } from '@playwright/test';
import { reportSchema, sessionSchema } from '../src/api';

const widths = [320, 375, 430, 768, 1024, 1440, 1920];
const pageHeadings = {
  'Product demo': 'A small diff. A new way in.',
  Pricing: 'A plan for every review.',
  Documentation: 'From Terraform to an informed decision.',
  'Get started': 'Know what this change opens.',
};
async function contained(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const controls = await page.locator('button,input:not([type="hidden"]),select,summary,nav a,.text-link,.workspace-usage a,.brand,.preview-metrics>a').evaluateAll(elements =>
    elements.filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden').map(el => ({
      label: el.getAttribute('aria-label') ?? el.textContent ?? el.tagName,
      height: el.getBoundingClientRect().height,
      width: el.getBoundingClientRect().width,
    })),
  );
  for (const control of controls) {
    expect(Number(control.height.toFixed(2)), control.label).toBeGreaterThanOrEqual(44);
    expect(Number(control.width.toFixed(2)), control.label).toBeGreaterThanOrEqual(44);
  }
  for (const card of await page.locator('.panel, .metric, .scenario, .price-card').all()) {
    const box = await card.boundingBox();
    if (box) { expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width + 1); }
  }
  for (const graph of await page.getByTestId('attack-graph').all()) {
    const box = await graph.boundingBox();
    expect(box).not.toBeNull();
    if (box) { expect(box.x).toBeGreaterThanOrEqual(0); expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width + 1); }
    expect(await graph.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  }
}
async function navigate(page: Page, name: keyof typeof pageHeadings) {
  if (page.viewportSize()!.width < 768) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name, exact: true }).click();
  await expect(page.getByRole('heading', { level: 1, name: pageHeadings[name], exact: true })).toBeVisible();
}
async function exports(page: Page, prefix: string, sarif = true) {
  for (const [label, suffix] of [['JSON', 'json'], ['MARKDOWN', 'md'], ['SARIF', 'sarif']]) {
    const button = page.getByRole('button', { name: label, exact: true });
    if (label === 'SARIF' && !sarif) { await expect(button).toBeDisabled(); continue; }
    expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    const downloaded = page.waitForEvent('download');
    await button.click();
    const artifact = await downloaded;
    expect(artifact.suggestedFilename()).toBe(`${prefix}.${suffix}`);
    const content = await readFile((await artifact.path())!, 'utf8');
    if (suffix === 'md') expect(content).toContain('BlastRadius');
    else if (suffix === 'sarif') expect(JSON.parse(content).version).toBe('2.1.0');
    else expect(reportSchema.parse(JSON.parse(content)).schema_version).toBe(1);
  }
}
async function assignPlan(organizationId: string, plan: 'pro' | 'team') {
  const root = fileURLToPath(new URL('../../', import.meta.url));
  const database = await readFile(new URL('../.e2e/current-database', import.meta.url), 'utf8');
  if (!database.startsWith(`sqlite:///${root}web/.e2e/run-`) || !database.endsWith('/test.db')) throw new Error('Refusing to grant a plan outside the isolated E2E database');
  execFileSync(`${root}.venv/bin/python`, ['-m', 'blastradius.server.admin', 'assign-plan', organizationId, plan], {
    cwd: root, env: { ...process.env, BR_ENV: 'test', BR_ADMIN_ENABLED: 'true', BR_DATABASE_URL: database, BR_PUBLIC_URL: 'http://127.0.0.1:5173' },
  });
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
      await navigate(page, 'Product demo');
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
      await exports(page, 'blastradius-demo');
      await navigate(page, 'Pricing'); await contained(page);
      await expect(page.getByRole('button', { name: 'Coming soon' })).toHaveCount(3);
      for (const route of ['/security', '/privacy', '/terms']) {
        await page.goto(route);
        await expect(page.getByText('LEGAL REVIEW REQUIRED BEFORE COMMERCIAL LAUNCH')).toBeVisible();
        await contained(page);
      }
      await navigate(page, 'Documentation'); await contained(page);
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
      await page.goto('/');
      await navigate(page, 'Get started');
      await page.getByRole('button', { name: 'Create local demo workspace' }).click();
      await expect(page.getByLabel('Project name')).toBeVisible();
      await page.getByText('Create another workspace', { exact: true }).click();
      await page.getByLabel('Workspace name').fill(`Review workspace ${width}`);
      await page.getByRole('button', { name: 'Create workspace', exact: true }).click();
      await expect(page.getByRole('combobox', { name: 'Workspace', exact: true }).locator('option:checked')).toHaveText(`Review workspace ${width} · owner`);
      await contained(page);
      await page.getByLabel('Project name').fill(`Production / terraform-${'long-resource-name-'.repeat(6)}`.slice(0, 100));
      await page.getByRole('button', { name: 'Create project', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Analyze change' })).toBeVisible();
      await page.getByLabel('Baseline Terraform files').setInputFiles(new URL('../../examples/safe/main.tf', import.meta.url).pathname);
      await page.getByLabel('Candidate Terraform files').setInputFiles(new URL('../../examples/vulnerable/main.tf', import.meta.url).pathname);
      await page.getByLabel('Baseline label').fill('baseline-with-a-long-resource-name'.repeat(3));
      await page.getByRole('button', { name: 'Analyze change' }).click();
      await expect(page.getByLabel('Analysis decision').getByText('BLOCK CHANGE', { exact: true })).toBeVisible();
      await expect(page.getByLabel('Selected analysis')).toBeFocused();
      await expect(page.getByLabel('Analysis decision')).toBeInViewport();
      await expect(page.getByLabel('Responsible change')).toBeInViewport();
      if (width >= 1024) await expect(page.getByTestId('attack-graph')).toBeInViewport();
      await contained(page);
      await page.getByRole('link', { name: 'Review remediation', exact: true }).click();
      await page.getByText('Inspect supported patch', { exact: true }).click();
      const patchDownload = page.waitForEvent('download');
      await page.getByRole('button', { name: 'Download patch' }).click();
      expect((await patchDownload).suggestedFilename()).toBe('blastradius.patch');
      await page.getByRole('link', { name: 'Edit inputs or run another analysis' }).click();
      await page.getByLabel('Candidate Terraform files').setInputFiles(new URL('../../examples/safe/main.tf', import.meta.url).pathname);
      await page.getByLabel('Candidate label').fill('remediated-candidate');
      await page.getByRole('button', { name: 'Analyze change' }).click();
      await expect(page.getByLabel('Analysis decision').getByText('SAFE TO MERGE', { exact: true })).toBeVisible();
      await contained(page);
      await exports(page, 'blastradius', false);
      await expect(page.getByText(/Saved SARIF exports require/)).toBeVisible();
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
      const workspaceNav = page.getByRole('navigation', { name: 'Workspace navigation' });
      await workspaceNav.getByRole('link', { name: 'Settings & policy' }).click();
      await expect(page.getByLabel('Project name')).toBeVisible();
      await page.getByRole('textbox', { name: 'Description', exact: true }).fill(`Saved project metadata at ${width}px`);
      const savedProject = page.waitForResponse(response => response.request().method() === 'PATCH' && new URL(response.url()).pathname.startsWith('/api/projects/'));
      await page.getByRole('button', { name: 'Save project', exact: true }).click();
      expect((await savedProject).ok()).toBe(true);
      await expect(page.getByText('Project saved.', { exact: true })).toBeVisible();
      await page.reload();
      await expect(page.getByRole('combobox', { name: 'Workspace', exact: true }).locator('option:checked')).toHaveText(`Review workspace ${width} · owner`);
      await expect(page.getByRole('textbox', { name: 'Description', exact: true })).toHaveValue(`Saved project metadata at ${width}px`);
      await expect(page.getByRole('button', { name: 'Save policy', exact: true })).toHaveCount(0);
      await contained(page);
      await page.getByRole('button', { name: 'Archive project', exact: true }).click();
      await page.getByRole('button', { name: 'Confirm archive', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Restore project', exact: true })).toBeVisible();
      await workspaceNav.getByRole('link', { name: 'Analyze', exact: true }).click();
      await expect(page.getByText(/This project is archived/)).toBeVisible();
      await expect(page.getByRole('button', { name: 'Analyze change' })).toHaveCount(0);
      await workspaceNav.getByRole('link', { name: 'Settings & policy' }).click();
      await page.getByRole('button', { name: 'Restore project', exact: true }).click();
      await page.getByRole('button', { name: 'Confirm restore', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Archive project', exact: true })).toBeVisible();
      await workspaceNav.getByRole('link', { name: 'History', exact: true }).click();
      await page.getByRole('combobox', { name: 'Status', exact: true }).selectOption('succeeded');
      await page.getByRole('combobox', { name: 'Decision', exact: true }).selectOption('SAFE TO MERGE');
      await page.getByRole('combobox', { name: 'Input type', exact: true }).selectOption('hcl');
      await page.getByRole('button', { name: 'Apply filters' }).click();
      await expect(page.getByText('Page 1 · 1 results')).toBeVisible();
      await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeDisabled();
      await contained(page);
      await workspaceNav.getByRole('link', { name: 'Team', exact: true }).click();
      await expect(page.getByText(/Invitations and role changes require Team/)).toBeVisible();
      await expect(page.getByRole('button', { name: 'Create invitation' })).toHaveCount(0);
      await contained(page);
      await workspaceNav.getByRole('link', { name: 'GitHub', exact: true }).click();
      await expect(page.getByText(/GitHub is unavailable/)).toBeVisible();
      await contained(page);
      await workspaceNav.getByRole('link', { name: 'Account', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Sign out this session' })).toBeVisible();
      await contained(page);
      await workspaceNav.getByRole('link', { name: 'Usage & plans' }).click();
      await expect(page.getByText('Payments are disabled.', { exact: false })).toBeVisible();
      await expect(page.getByRole('progressbar', { name: 'Monthly analysis usage' })).toHaveAttribute('value', '3');
      await contained(page);
      if (width < 768) await page.getByRole('button', { name: 'Open navigation' }).click();
      await page.getByRole('button', { name: 'Sign out', exact: true }).click();
      await expect(page).toHaveURL('/');
      await page.goto('/history');
      await expect(page.getByRole('button', { name: 'Create local demo workspace' })).toBeVisible();
    });
  });
}
test('alternate origin offers an actionable configuration message instead of a broken login CTA', async ({ page }) => {
  await page.goto('http://localhost:5173/dashboard');
  await expect(page.getByRole('heading', { name: 'Workspace unavailable at this address' })).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('BR_PUBLIC_URL');
  await expect(page.getByRole('button', { name: 'Create local demo workspace' })).toHaveCount(0);
  await page.getByRole('link', { name: 'Try the public demo', exact: true }).click();
  await expect(page.getByLabel('Analysis decision')).toBeVisible();
});
test('operator-granted Pro exports and Team policies/invitations use real workspace APIs', async ({ page }) => {
  await page.goto('/dashboard');
  await page.getByRole('button', { name: 'Create local demo workspace' }).click();
  await page.getByLabel('Project name').fill('Beta entitlements');
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Analyze change' })).toBeVisible();
  const identity = sessionSchema.parse(await (await page.request.get('/api/me')).json());
  const org = identity.organizations[0];
  if (!org) throw new Error('Demo onboarding did not return a workspace');
  await assignPlan(org.id, 'pro');
  await page.reload();
  await page.getByRole('button', { name: 'Plan JSON', exact: true }).click();
  await page.getByLabel('Plan JSON', { exact: true }).fill(await readFile(new URL('../../examples/plans/ssh_open_plan.json', import.meta.url), 'utf8'));
  await page.getByRole('button', { name: 'Analyze change' }).click();
  await expect(page.getByLabel('Analysis decision').getByText('BLOCK CHANGE', { exact: true })).toBeVisible();
  await exports(page, 'blastradius');
  await assignPlan(org.id, 'team');
  await page.reload();
  const navigation = page.getByRole('navigation', { name: 'Workspace navigation' });
  await navigation.getByRole('link', { name: 'Settings & policy' }).click();
  const projectPolicy = page.locator('section.panel').filter({ has: page.getByRole('heading', { name: 'Project policy', exact: true }) });
  await projectPolicy.getByLabel('Minimum security score (blank for no threshold)').fill('80');
  await projectPolicy.getByRole('button', { name: 'Save policy', exact: true }).click();
  await expect(projectPolicy.getByText(/Stored version 1/)).toBeVisible();
  await contained(page);
  await navigation.getByRole('link', { name: 'Team', exact: true }).click();
  await page.getByLabel('Invite email').fill('reviewer@example.test');
  await page.getByLabel('Invitation role').selectOption('viewer');
  await page.getByRole('button', { name: 'Create invitation' }).click();
  const link = await page.getByLabel('One-time invitation link').inputValue();
  expect(new URL(link).hash).toMatch(/^#token=[A-Za-z0-9_-]{43}$/);
  await page.getByRole('button', { name: 'Dismiss link' }).click();
  await page.getByRole('button', { name: 'Revoke invitation', exact: true }).click();
  await expect(page.getByText(/viewer · Revoked/)).toBeVisible();
  await expect(page.getByText(/Ownership protection/)).toBeVisible();
  await contained(page);
  await page.goto(link);
  await expect(page.getByText('Demo identities cannot accept invitations.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Accept invitation' })).toBeDisabled();
  await expect(page).not.toHaveURL(/#token=/);
});
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
