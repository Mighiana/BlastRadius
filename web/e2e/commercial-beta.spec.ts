import { test, expect, type Page } from '@playwright/test';
import { sessionSchema } from '../src/api';
import { eventNames } from '../src/operator-api';

const widths = [320, 375, 430, 768, 1024, 1440];
async function contained(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const controls = await page.locator('button,input:not([type="hidden"]),textarea,select,summary,.button,.text-link,nav a').evaluateAll(elements =>
    elements.filter(element => element.getClientRects().length && getComputedStyle(element).visibility !== 'hidden')
      .map(element => ({ name: element.getAttribute('aria-label') ?? element.textContent, width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height })),
  );
  for (const control of controls) {
    expect(control.width, control.name ?? '').toBeGreaterThanOrEqual(44);
    expect(control.height, control.name ?? '').toBeGreaterThanOrEqual(44);
  }
}
for (const width of widths) {
  test(`beta consent and optional form layout at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 940 });
    await page.goto('/pricing');
    await page.getByRole('link', { name: 'Request early access' }).first().click();
    await expect(page.getByRole('button', { name: 'Save beta interest' })).toBeEnabled();
    await expect(page.getByRole('checkbox')).not.toBeChecked();
    await page.getByText('Optional workflow details', { exact: true }).click();
    await contained(page);
    await page.getByRole('button', { name: 'Save beta interest' }).click();
    await expect(page.getByText('Your beta interest has been saved.', { exact: true })).toHaveCount(0);
    await expect(page.getByLabel('Name (required, up to 100 characters)')).toBeFocused();
  });
}
test('anonymous beta request commits once, with explicit notice consent and no email promise', async ({ page }) => {
  await page.goto('/beta');
  await expect(page.getByRole('button', { name: 'Save beta interest' })).toBeEnabled();
  await page.getByLabel('Name (required, up to 100 characters)').fill('Local acceptance tester');
  await page.getByLabel('Email (required)').fill('acceptance@example.test');
  await page.getByRole('checkbox').check();
  const saved = page.waitForResponse(response => new URL(response.url()).pathname === '/api/beta-interest' && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Save beta interest' }).click();
  const response = await saved;
  expect(response.status()).toBe(201);
  expect(response.request().postDataJSON().privacy_consent).toBe(true);
  await expect(page.getByRole('status')).toHaveText('Your beta interest has been saved.');
  await expect(page.getByText(/does not guarantee access or send an email/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save beta interest' })).toHaveCount(0);
  expect((await page.request.get('/api/beta-interest')).status()).toBe(405);
});
test('feedback persists on a real completed analysis and a tenant owner cannot inspect operators', async ({ page }) => {
  await page.goto('/dashboard');
  await page.getByRole('button', { name: 'Create local demo workspace' }).click();
  await page.getByLabel('Project name').fill('Feedback acceptance');
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  await page.getByLabel('Baseline Terraform files').setInputFiles(new URL('../../examples/safe/main.tf', import.meta.url).pathname);
  await page.getByLabel('Candidate Terraform files').setInputFiles(new URL('../../examples/vulnerable/main.tf', import.meta.url).pathname);
  await page.getByRole('button', { name: 'Analyze change' }).click();
  await expect(page.getByLabel('Analysis decision').getByText('BLOCK CHANGE', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Give feedback' }).click();
  const panel = page.getByRole('region', { name: 'Analysis feedback' });
  await panel.getByRole('radio', { name: 'Yes', exact: true }).check();
  await panel.getByRole('textbox').fill('Clear local fixture explanation.');
  for (const width of widths) {
    await page.setViewportSize({ width, height: 940 });
    await contained(page);
  }
  const saved = page.waitForResponse(response => response.url().endsWith('/feedback') && response.request().method() === 'PUT');
  await panel.getByRole('button', { name: 'Save feedback' }).click();
  const response = await saved;
  expect(response.status()).toBe(200);
  expect(response.request().postDataJSON()).toEqual({ useful: true, message: 'Clear local fixture explanation.' });
  await expect(panel.getByRole('status')).toHaveText('Your feedback has been saved.');
  await page.reload();
  await page.getByRole('button', { name: 'Give feedback' }).click();
  await expect(panel.getByRole('radio', { name: 'Yes', exact: true })).toBeChecked();
  await expect(panel.getByRole('textbox')).toHaveValue('Clear local fixture explanation.');
  const me = sessionSchema.parse(await (await page.request.get('/api/me')).json());
  const foreign = await page.request.put('/api/analyses/00000000-0000-4000-8000-000000000000/feedback', {
    headers: { 'X-CSRF-Token': me.csrf_token, Origin: 'http://127.0.0.1:5173' }, data: { useful: false, message: '' },
  });
  expect(foreign.status()).toBe(404);
  expect((await page.request.get('/api/admin/events')).status()).toBe(403);
  await page.goto('/operator');
  await expect(page.getByRole('alert')).toContainText('Platform operator access is required');
  await expect(page.getByRole('link', { name: 'Operator', exact: true })).toHaveCount(0);
});
test('CSRF errors do not retry lead submission or show saved state', async ({ page }) => {
  let submissions = 0;
  await page.route('**/api/beta-interest', async route => {
    submissions++;
    await route.fulfill({ status: 403, json: { detail: 'csrf_required' } });
  });
  await page.goto('/beta');
  await expect(page.getByRole('button', { name: 'Save beta interest' })).toBeEnabled();
  await page.getByLabel('Name (required, up to 100 characters)').fill('Local error tester');
  await page.getByLabel('Email (required)').fill('error@example.test');
  await page.getByRole('checkbox').check();
  await page.getByRole('button', { name: 'Save beta interest' }).click();
  await expect(page.getByRole('alert')).toContainText('Your session changed');
  expect(submissions).toBe(1);
  await expect(page.getByText('Your beta interest has been saved.', { exact: true })).toHaveCount(0);
});
test('mocked operator presentation contains long private review text at six widths and clears denied pages', async ({ page }) => {
  await page.route('**/api/me', async route => {
    const response = await route.fetch();
    const me = sessionSchema.parse(await response.json());
    await route.fulfill({ json: { ...me, authenticated: true, user: { id: 'synthetic-operator', name: 'Local fixture', email: 'operator@example.test', email_verified: true, created_at: 1 }, capabilities: { platform_admin: true } } });
  });
  await page.route('**/api/admin/events', route => route.fulfill({ json: { retention_days: 90, max_records: 100000, active_workspaces: 0, counts: Object.fromEntries(eventNames.map(name => [name, 0])) } }));
  const note = `<img src=x onerror=alert(1)>${'long-review-text'.repeat(50)}`;
  await page.route('**/api/admin/feedback?*', route => {
    const offset = new URL(route.request().url()).searchParams.get('offset');
    return offset === '0' ? route.fulfill({ json: { items: [{ id: 'feedback', analysis_id: 'analysis', project_id: 'project', organization_id: 'org', user_id: 'user', useful: false, message: note, created_at: 1, updated_at: 1 }], limit: 25, offset: 0, next_offset: 25 } }) : route.fulfill({ status: 403, json: { detail: 'platform_admin_required' } });
  });
  await page.goto('/operator');
  await page.getByLabel('Operator view').selectOption('feedback');
  await expect(page.getByText(note, { exact: true })).toBeVisible();
  for (const width of widths) {
    await page.setViewportSize({ width, height: 940 });
    await contained(page);
  }
  await expect(page.locator('.operator-panel img')).toHaveCount(0);
  await page.getByRole('button', { name: 'Next records' }).click();
  await expect(page.getByRole('alert')).toContainText('Platform operator access is required');
  await expect(page.getByText(note, { exact: true })).toHaveCount(0);
});
