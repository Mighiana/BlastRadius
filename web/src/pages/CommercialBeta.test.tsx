import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import App from '../App';
import { ApiError, type Session } from '../api';
import { betaInputSchema, feedbackInputSchema } from '../beta-api';
import { eventNames, operatorSchemas } from '../operator-api';
import { SessionProvider } from '../session';
import { account, organization, project, queued, session, safe } from '../test/fixtures';
import { AnalysisFeedback } from '../components/AnalysisFeedback';
import { ReportView } from '../components/ReportView';
import BetaInterest from './BetaInterest';
import Operator from './Operator';
import { Pricing } from './Billing';
import Workspace from './Workspace';

const privacy = { version: '2026-09-20', retention_days: 90, notice: 'Operator review only. No email is sent. Do not include infrastructure or secrets.' };
const lead = { name: 'Tester', email: 'tester@example.test', privacy_version: privacy.version, privacy_consent: true };
const feedback = { id: 'feedback', analysis_id: 'analysis', project_id: 'project', organization_id: 'org', user_id: 'owner', useful: false, message: 'More context', created_at: 1, updated_at: 2 };
const operator: Session = { ...account, capabilities: { platform_admin: true } };
const events = { retention_days: 90, max_records: 100000, counts: Object.fromEntries(eventNames.map(name => [name, 0])), active_workspaces: 0 };
const catalog = { payments_enabled: false, mode: 'commercial_beta', plans: [
  { code: 'pro', monthly_price_usd: 49, price_status: 'proposed', assignment: 'operator_beta', configurable: false, limits: organization.usage.limits, features: organization.usage.features },
] };
function json(body: unknown, status = 200) { return new Response(JSON.stringify(body), { status }); }
function mount(children: ReactNode, path = '/beta') {
  return render(<MemoryRouter initialEntries={[path]}><SessionProvider>{children}</SessionProvider></MemoryRouter>);
}
function betaFetch(mutation: () => Promise<Response> = async () => json({ status: 'stored', message: 'Saved' }, 201), current = session) {
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url === '/api/me') return json(current);
    if (url === '/api/beta-interest/privacy') return json(privacy);
    if (url === '/api/beta-interest' && options?.method === 'POST') return mutation();
    throw new Error(`Unexpected test URL: ${url}`);
  });
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}
async function fillLead() {
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save beta interest' })).toBeEnabled());
  await userEvent.type(screen.getByLabelText(/Name \(required/), 'Tester');
  await userEvent.type(screen.getByLabelText('Email (required)'), 'tester@example.test');
  await userEvent.click(screen.getByRole('checkbox'));
}
function feedbackFetch(mutation: () => Promise<Response>, initial: typeof feedback | null = null, current = account) {
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url === '/api/me') return json(current);
    if (url === '/api/analyses/analysis/feedback') return options?.method === 'PUT' ? mutation() : json({ feedback: initial });
    throw new Error(`Unexpected test URL: ${url}`);
  });
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}
async function openFeedback() {
  await userEvent.click(await screen.findByRole('button', { name: 'Give feedback' }));
  await screen.findByRole('radio', { name: 'Yes' });
}

describe('beta-interest contract and privacy', () => {
  it('requires explicit consent, uses the fetched notice, persists once with CSRF and sends only allowed fields', async () => {
    const fetcher = betaFetch();
    mount(<BetaInterest />);
    expect(await screen.findByText(privacy.notice)).toBeVisible();
    expect(screen.getByRole('checkbox')).not.toBeChecked();
    await userEvent.click(screen.getByRole('button', { name: 'Save beta interest' }));
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0);
    await fillLead();
    await userEvent.click(screen.getByRole('button', { name: 'Save beta interest' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Your beta interest has been saved.');
    expect(screen.getByText(/does not guarantee access or send an email/)).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Save beta interest' })).not.toBeInTheDocument();
    const mutations = fetcher.mock.calls.filter(([, init]) => init?.method === 'POST');
    expect(mutations).toHaveLength(1);
    const init = mutations[0]![1]!;
    expect(JSON.parse(String(init.body))).toEqual({ ...lead, company: '', role: '', team_size: null, repository_count: null, primary_cloud: null, source_control: null, problem: '' });
    expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('test-csrf');
    expect(new Headers(init.headers).has('Origin')).toBe(false);
    expect(init).toMatchObject({ credentials: 'same-origin', cache: 'no-store' });
  });
  it.each([
    { privacy_consent: false }, { name: '' }, { email: 'not-an-email' }, { team_size: 0 },
    { repository_count: -1 }, { team_size: 1.1 }, { company: 'x'.repeat(121) },
    { role: 'a\tb' }, { problem: 'x'.repeat(1001) }, { terraform: 'private source' },
  ])('rejects invalid or extra fields %j', changes => {
    expect(betaInputSchema.safeParse({ ...lead, ...changes }).success).toBe(false);
  });
  it('validates a programmatic submission without falsely saying the server may have stored it', async () => {
    const fetcher = betaFetch();
    mount(<BetaInterest />);
    await screen.findByText(privacy.notice);
    fireEvent.submit(screen.getByRole('button', { name: 'Save beta interest' }).closest('form')!);
    expect(screen.getByRole('alert')).toHaveTextContent('Check your name, email, consent');
    expect(screen.queryByText(/may already have been saved/)).not.toBeInTheDocument();
    expect(fetcher.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
  });
  it.each([
    [403, 'csrf_required'], [403, 'invalid_origin'], [429, 'rate_limit_exceeded'],
    [413, 'body_too_large'], [422, 'invalid_request'], [503, 'submission_storage_full'],
  ] as const)('announces %s %s and never retries a mutation', async (status, code) => {
    const fetcher = betaFetch(async () => json({ detail: code }, status));
    mount(<BetaInterest />);
    await fillLead();
    await userEvent.click(screen.getByRole('button', { name: 'Save beta interest' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(new ApiError(status, code, null).message);
    expect(screen.queryByText('Your beta interest has been saved.')).not.toBeInTheDocument();
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
    if (code === 'csrf_required') await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url === '/api/me')).toHaveLength(2));
  });
  it('leaves ambiguous network failures for a deliberate retry', async () => {
    const fetcher = betaFetch(async () => { throw new TypeError('Network offline'); });
    mount(<BetaInterest />);
    await fillLead();
    await userEvent.click(screen.getByRole('button', { name: 'Save beta interest' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot reach the API');
    expect(screen.getByText(/may already have been saved/)).toBeVisible();
    expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(1);
  });
  it('blocks mutation without session bootstrap or a fetched privacy notice', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'unavailable' }, 503)));
    mount(<BetaInterest />);
    await screen.findAllByRole('alert');
    expect(screen.getByRole('button', { name: 'Save beta interest' })).toBeDisabled();
    expect(screen.getByRole('checkbox')).not.toBeChecked();
    expect(screen.getAllByRole('button', { name: 'Try again' }).every(button => button.getAttribute('type') === 'button')).toBe(true);
  });
  it('blocks a mismatched configured origin', async () => {
    const fetcher = betaFetch(undefined, { ...session, auth: { ...session.auth, public_url: 'https://other.example.test' } });
    mount(<BetaInterest />);
    expect(await screen.findByRole('alert')).toHaveTextContent(new ApiError(403, 'invalid_origin', null).message);
    expect(screen.getByRole('button', { name: 'Save beta interest' })).toBeDisabled();
    expect(fetcher.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);
  });
  it('keeps proposed paid pricing server-sourced and directs interest to the real form', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => json(url === '/api/me' ? session : catalog)));
    mount(<Pricing />);
    expect(await screen.findByRole('link', { name: 'Request early access' })).toHaveAttribute('href', '/beta');
    expect(screen.getByRole('heading', { name: /\$49/ })).toBeVisible();
    await userEvent.click(screen.getByText('Can I use GitHub Actions without the SaaS?'));
    expect(screen.getByText(/SaaS account and GitHub App installation are not required/)).toBeVisible();
  });
});

describe('authenticated analysis feedback', () => {
  it('does not read feedback for an anonymous user', async () => {
    const fetcher = feedbackFetch(async () => json({ feedback }), null, session);
    mount(<AnalysisFeedback analysisId="analysis" />);
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole('region', { name: 'Analysis feedback' })).not.toBeInTheDocument();
  });
  it('reads on request and allows a viewer to persist exactly usefulness and bounded text', async () => {
    const fetcher = feedbackFetch(async () => json({ feedback }), null, { ...account, organizations: [{ ...organization, role: 'viewer' }] });
    mount(<AnalysisFeedback analysisId="analysis" />);
    await screen.findByRole('button', { name: 'Give feedback' });
    expect(fetcher.mock.calls).toHaveLength(1);
    await openFeedback();
    expect(screen.getByRole('button', { name: 'Save feedback' })).toBeDisabled();
    await userEvent.click(screen.getByRole('radio', { name: 'No' }));
    await userEvent.type(screen.getByRole('textbox'), 'More context');
    await userEvent.click(screen.getByRole('button', { name: 'Save feedback' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Your feedback has been saved.');
    const init = fetcher.mock.calls.find(([, options]) => options?.method === 'PUT')![1]!;
    expect(JSON.parse(String(init.body))).toEqual({ useful: false, message: 'More context' });
    expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('test-csrf');
    expect(screen.getByRole('textbox')).toHaveAttribute('maxlength', '1000');
  });
  it('loads saved feedback for editing and clears saved status when it changes', async () => {
    feedbackFetch(async () => json({ feedback: { ...feedback, useful: true, message: '' } }), feedback);
    mount(<AnalysisFeedback analysisId="analysis" />);
    await openFeedback();
    expect(screen.getByRole('radio', { name: 'No' })).toBeChecked();
    expect(screen.getByRole('textbox')).toHaveValue('More context');
    await userEvent.click(screen.getByRole('radio', { name: 'Yes' }));
    await userEvent.clear(screen.getByRole('textbox'));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Save feedback' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Your feedback has been saved.');
  });
  it.each([[404, 'not_found'], [403, 'invalid_origin'], [403, 'csrf_required'], [409, 'analysis_not_terminal'], [409, 'feedback_expired']] as const)('does not claim success after %s %s', async (status, code) => {
    feedbackFetch(async () => json({ detail: code }, status));
    mount(<AnalysisFeedback analysisId="analysis" />);
    await openFeedback();
    await userEvent.click(screen.getByRole('radio', { name: 'Yes' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save feedback' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(new ApiError(status, code, null).message);
    expect(screen.queryByText('Your feedback has been saved.')).not.toBeInTheDocument();
    expect(screen.queryByText('SAFE TO MERGE')).not.toBeInTheDocument();
  });
  it('hides form data for foreign or expired analysis IDs', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url === '/api/me' ? json(account) : json({ detail: 'not_found' }, 404)));
    mount(<AnalysisFeedback analysisId="foreign" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Give feedback' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('This item is unavailable');
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });
  it('rejects tenant metadata, oversized notes and nonboolean votes', () => {
    expect(feedbackInputSchema.safeParse({ useful: true, message: '', user_id: 'another-user' }).success).toBe(false);
    expect(feedbackInputSchema.safeParse({ useful: true, message: 'a'.repeat(1001) }).success).toBe(false);
    expect(feedbackInputSchema.safeParse({ useful: 'yes', message: '' }).success).toBe(false);
    expect(feedbackInputSchema.parse({ useful: false, message: ' one\ntwo ' })).toEqual({ useful: false, message: 'one\ntwo' });
  });
  it.each(['queued', 'running', 'succeeded', 'failed'] as const)('offers feedback only for terminal analysis state: %s', async status => {
    const job = { ...queued, status, result: status === 'succeeded' ? safe : null };
    const fetcher = vi.fn(async (url: string) => json(url === '/api/me' ? account
      : url === '/api/projects/project' ? project : url.startsWith('/api/projects?') ? { projects: [project] }
        : url.startsWith('/api/projects/project/analyses') ? { analyses: [job], total: 1, limit: 50, offset: 0 } : job));
    vi.stubGlobal('fetch', fetcher);
    mount(<Workspace />, '/dashboard?project=project&analysis=job');
    const selected = await screen.findByLabelText('Selected analysis');
    await within(selected).findByRole('heading', { name: 'before after' });
    if (status === 'succeeded' || status === 'failed') expect(within(selected).getByRole('button', { name: 'Give feedback' })).toBeVisible();
    else expect(within(selected).queryByRole('button', { name: 'Give feedback' })).not.toBeInTheDocument();
    expect(fetcher.mock.calls.some(([url]) => url.endsWith('/feedback'))).toBe(false);
  });
});

describe('platform operator access and bounded inspection', () => {
  it.each([undefined, { platform_admin: false }])('hides navigation and does not request admin data without capability %j', async capabilities => {
    vi.stubGlobal('scrollTo', vi.fn());
    const fetcher = vi.fn(async () => json({ ...account, capabilities }));
    vi.stubGlobal('fetch', fetcher);
    mount(<App />, '/operator');
    expect(await screen.findByRole('alert')).toHaveTextContent('Platform operator');
    expect(screen.queryByRole('link', { name: 'Operator' })).not.toBeInTheDocument();
    expect(fetcher.mock.calls).toHaveLength(1);
  });
  it.each([401, 403, 404])('respects a backend %s despite a previously granted capability', async status => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url === '/api/me' ? json(operator) : json({ detail: status === 403 ? 'platform_admin_required' : 'not_found' }, status)));
    mount(<Operator />);
    expect(await screen.findByRole('alert')).toBeVisible();
    expect(screen.queryByText('Active workspaces')).not.toBeInTheDocument();
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
  });
  it('uses bounded pages, strips nonwhitelisted content and clears old records on access denial', async () => {
    let denied = false;
    const fetcher = vi.fn(async (url: string) => {
      if (url === '/api/me') return json(operator);
      if (url === '/api/admin/events') return json(events);
      if (denied) return json({ detail: 'platform_admin_required' }, 403);
      if (url === '/api/admin/users?limit=25&offset=0') return json({ items: [{ id: 'first', created_at: 1, email_verified: true, source: 'PRIVATE TERRAFORM', email: 'private@example.test' }], limit: 25, offset: 0, next_offset: 25 });
      return json({ items: [{ id: 'second', created_at: 2, email_verified: false }], limit: 25, offset: 25, next_offset: null });
    });
    vi.stubGlobal('fetch', fetcher);
    mount(<Operator />);
    await userEvent.selectOptions(await screen.findByLabelText('Operator view'), 'users');
    expect(await screen.findByText('first')).toBeVisible();
    expect(screen.queryByText(/PRIVATE TERRAFORM|private@example.test/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Previous records' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Next records' }));
    expect(await screen.findByText('second')).toBeVisible();
    expect(screen.queryByText('first')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next records' })).toBeDisabled();
    denied = true;
    await userEvent.click(screen.getByRole('button', { name: 'Previous records' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Platform operator');
    expect(screen.queryByText('second')).not.toBeInTheDocument();
    expect(fetcher.mock.calls.some(([url]) => url === '/api/admin/users?limit=25&offset=25')).toBe(true);
  });
  it('renders aggregate objects directly and separates escaped private review from ordinary data', async () => {
    const privateText = '<img src=x onerror=alert(1)>';
    vi.stubGlobal('fetch', vi.fn(async (url: string) => json(url === '/api/me' ? operator : url === '/api/admin/events' ? events : url === '/api/admin/plans' ? catalog : {
      items: [{ ...feedback, message: privateText }], limit: 25, offset: 0, next_offset: null,
    })));
    const { container } = mount(<Operator />);
    expect(await screen.findByText('Active workspaces')).toBeVisible();
    expect(screen.getByText(/not a durable accounting ledger/)).toBeVisible();
    await userEvent.selectOptions(screen.getByLabelText('Operator view'), 'plans');
    expect(await screen.findByRole('heading', { name: 'pro' })).toBeVisible();
    expect(screen.queryByRole('button', { name: /Next records/ })).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('Operator view'), 'feedback');
    expect(await screen.findByText(privateText)).toBeVisible();
    expect(screen.getByText(/Private operator review/)).toBeVisible();
    expect(container.querySelector('img,script')).toBeNull();
  });
  it('resets pagination when page size changes and shows an accessible empty page', async () => {
    const fetcher = vi.fn(async (url: string) => json(url === '/api/me' ? operator : url === '/api/admin/events' ? events : { items: [], limit: url.includes('limit=100') ? 100 : 25, offset: 0, next_offset: null }));
    vi.stubGlobal('fetch', fetcher);
    mount(<Operator />);
    await userEvent.selectOptions(await screen.findByLabelText('Operator view'), 'beta-requests');
    await screen.findByText('No records on this page');
    await userEvent.selectOptions(screen.getByLabelText('Records per page'), '100');
    expect(await screen.findByText('No records on this page')).toBeVisible();
    expect(fetcher.mock.calls.some(([url]) => url === '/api/admin/beta-requests?limit=100&offset=0')).toBe(true);
    expect(screen.getByRole('button', { name: 'Next records' })).toBeDisabled();
  });
  it('accepts only the ordinary row contract and reduces unknown failure details to a fixed category', () => {
    const result = operatorSchemas.failures.parse({ items: [{ id: 'failure', organization_id: 'org', project_id: 'project', status: 'failed', error: 'private traceback', created_at: 1, completed_at: null, terraform: 'private source' }], limit: 25, offset: 0, next_offset: null });
    expect(result.items[0]?.error).toBe('analysis_failed');
    expect(result.items[0]).not.toHaveProperty('terraform');
    expect(operatorSchemas.users.safeParse({ items: [], limit: 101, offset: 0, next_offset: null }).success).toBe(false);
  });
  it('shows authorized operator navigation but never gives a self-upgrade control', async () => {
    vi.stubGlobal('scrollTo', vi.fn());
    vi.stubGlobal('fetch', vi.fn(async (url: string) => json(url === '/api/me' ? operator : events)));
    mount(<App />, '/operator');
    expect(await screen.findByRole('link', { name: 'Operator' })).toHaveAttribute('href', '/operator');
    expect(screen.queryByRole('button', { name: /upgrade|assign|delete/i })).not.toBeInTheDocument();
  });
});

it('preserves the machine SAFE decision while explaining the bounded result and next step', () => {
  render(<ReportView report={safe} />);
  expect(within(screen.getByLabelText('Analysis decision')).getByText(/No new modeled blocking findings detected\./)).toBeVisible();
  expect(screen.getByText('SAFE TO MERGE')).toBeVisible();
  expect(screen.getByRole('heading', { name: 'Recommended next step' })).toBeVisible();
});
