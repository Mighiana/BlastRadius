import { type ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { account, organization, project, session } from '../test/fixtures';
import { SessionProvider } from '../session';
import { Pricing } from './Billing';
import Billing from './Billing';
import Integrations from './Integrations';
import Trust from './Trust';

const catalog = { payments_enabled: false, mode: 'commercial_beta', plans: [
  { code: 'free', monthly_price_usd: 0, price_status: 'free', assignment: 'signup', configurable: false, limits: organization.usage.limits, features: organization.usage.features },
  ...(['pro', 'team', 'enterprise'] as const).map(code => ({ code, monthly_price_usd: code === 'pro' ? 49 : code === 'team' ? 149 : null, price_status: 'proposed', assignment: 'operator_beta', configurable: code === 'enterprise', limits: { ...organization.usage.limits, analyses_per_month: 777, retention_days: 123 }, features: { ...organization.usage.features, sarif: true } })),
] };
function mount(children: ReactNode) {
  return render(<MemoryRouter><SessionProvider>{children}</SessionProvider></MemoryRouter>);
}
describe('API-backed plans and retention', () => {
  it('uses catalog values, keeps paid actions disabled and makes Free onboarding reachable', async () => {
    const fetcher = vi.fn(async (url: string) => new Response(JSON.stringify(url === '/api/me' ? session : catalog)));
    vi.stubGlobal('fetch', fetcher);
    mount(<Pricing />);
    await screen.findByText('enterprise', { exact: true });
    expect(screen.getAllByText('777 analyses / month')).toHaveLength(3);
    expect(screen.getAllByText('123 days of evidence retention')).toHaveLength(3);
    expect(screen.getByRole('link', { name: 'Get started' })).toHaveAttribute('href', '/dashboard');
    for (const button of screen.getAllByRole('button', { name: 'Coming soon' })) expect(button).toBeDisabled();
    expect(screen.queryByText('Project policy controls')).not.toBeInTheDocument();
    expect(fetcher.mock.calls.every(([url]) => url === '/api/me' || url === '/api/plans')).toBe(true);
  });
  it('reads current usage rather than hardcoding session limits', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(url === '/api/me' ? account : url === '/api/plans' ? catalog : { ...organization.usage, analyses: 12, exports: 4, limits: { ...organization.usage.limits, retention_days: 17 } }))));
    mount(<Billing />);
    expect(await screen.findByText('17 days')).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'Monthly analysis usage' })).toHaveAttribute('value', '12');
    expect(screen.getByText(/Payments are disabled/)).toBeInTheDocument();
  });
});

describe('GitHub connection status', () => {
  const configuration = { configured: false, available: false, mode: 'operator_registration', self_service: false, app_slug: null, installation_url: null, reason: 'github_not_configured', permissions: { contents: 'read', metadata: 'read', checks: 'write', pull_requests: 'write' } };
  it('renders the actual unavailable reason and operator guidance without a fake installation', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(url === '/api/me' ? account : url === '/api/github/config' ? configuration : url.includes('/installations') ? { installations: [] } : url.includes('/github') ? { connection: null, latest_run: null } : { projects: [project] }))));
    mount(<Integrations />);
    expect(await screen.findByText(/GitHub is unavailable/)).toBeInTheDocument();
    await screen.findByText('No repository connected to this project.');
    expect(screen.getByText('github_not_configured')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Open GitHub App installation' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Connect verified repository' })).not.toBeInTheDocument();
  });
  it('links only returned PR/check identities and confirms disconnect without uninstalling', async () => {
    let disconnected = false;
    const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
      if (options?.method === 'DELETE') disconnected = true;
      return new Response(JSON.stringify(url === '/api/me' ? account : url === '/api/github/config' ? { ...configuration, configured: true, available: true, app_slug: 'blastradius', installation_url: 'https://github.com/apps/blastradius/installations/new', reason: 'operator_registration_required' }
        : url.includes('/installations') ? { installations: [{ id: 12, account_id: 13, account_login: 'example', status: 'active', verified_at: 1 }] }
          : url.includes('/github') ? { connection: { id: 'connection', installation_id: 12, repository_id: 42, full_name: 'example/repo', status: disconnected ? 'disconnected' : 'active', created_at: 1 }, latest_run: { id: 'run', analysis_id: 'analysis', pull_number: 9, base_sha: 'a'.repeat(40), head_sha: 'b'.repeat(40), base_ref: 'main', head_ref: 'feature', head_repository_id: 42, status: 'published', error: null, check_id: 123 } }
            : { projects: [project] }));
    });
    vi.stubGlobal('fetch', fetcher);
    mount(<Integrations />);
    expect(await screen.findByRole('link', { name: 'Open pull request' })).toHaveAttribute('href', 'https://github.com/example/repo/pull/9');
    expect(screen.getByRole('link', { name: 'Open check' })).toHaveAttribute('href', 'https://github.com/example/repo/runs/123');
    expect(screen.getByRole('link', { name: 'Open analysis' })).toHaveAttribute('href', '/dashboard?project=project&analysis=analysis');
    await userEvent.click(screen.getByRole('button', { name: 'Disconnect project' }));
    expect(fetcher.mock.calls.some(([, options]) => options?.method === 'DELETE')).toBe(false);
    await userEvent.click(screen.getByRole('button', { name: 'Confirm disconnect' }));
    await screen.findByText('disconnected', { exact: true });
    expect(fetcher).toHaveBeenCalledWith('/api/projects/project/github', expect.objectContaining({ method: 'DELETE' }));
  });
  it('sends only registered installation and numeric repository IDs for a connection', async () => {
    const fetcher = vi.fn(async (url: string) => new Response(JSON.stringify(url === '/api/me' ? account : url === '/api/github/config' ? { ...configuration, configured: true, available: true } : url.includes('/installations') ? { installations: [{ id: 12, account_id: 13, account_login: 'example', status: 'active', verified_at: 1 }] } : url.includes('/github') ? { connection: null, latest_run: null } : { projects: [project] })));
    vi.stubGlobal('fetch', fetcher);
    mount(<Integrations />);
    await userEvent.selectOptions(await screen.findByLabelText('Verified installation'), '12');
    await userEvent.type(screen.getByLabelText('Numeric repository ID'), '42');
    await userEvent.click(screen.getByRole('button', { name: 'Connect verified repository' }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith('/api/projects/project/github', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ installation_id: 12, repository_id: 42 }) })));
    await screen.findByText('No repository connected to this project.');
  });
});

describe('trust templates', () => {
  it.each(['security', 'privacy', 'terms'] as const)('marks %s for legal review with functional navigation', kind => {
    render(<MemoryRouter><Trust kind={kind} /></MemoryRouter>);
    expect(screen.getByText('LEGAL REVIEW REQUIRED BEFORE COMMERCIAL LAUNCH')).toBeVisible();
    const navigation = screen.getByRole('navigation', { name: 'Trust pages' });
    expect(within(navigation).getByRole('link', { name: 'Security' })).toHaveAttribute('href', '/security');
    expect(within(navigation).getByRole('link', { name: 'Privacy' })).toHaveAttribute('href', '/privacy');
    expect(within(navigation).getByRole('link', { name: 'Terms' })).toHaveAttribute('href', '/terms');
  });
});
