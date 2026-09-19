import { StrictMode, type ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import type { Organization, Policy, Session } from '../api';
import { SessionProvider } from '../session';
import { account, organization, project, queued } from '../test/fixtures';
import { PolicyEditor } from '../components/PolicyEditor';
import Account from './Account';
import Settings from './Settings';
import Team from './Team';
import Invitation from './Invitation';
import Workspace from './Workspace';

const policy: Policy = { version: 1, gate: { block_new_critical_paths: true, block_new_sensitive_exposure: true, block_public_admin_ports: true }, allowed: { public_https: true }, thresholds: { minimum_security_score: null } };
const teamOrg: Organization = { ...organization, plan: 'team', usage: { ...organization.usage, plan: 'team', features: { ...organization.usage.features, team: true, advanced_policy: true, organization_policy: true } } };
function mockApi(identity: Session, handler: (url: string, options?: RequestInit) => unknown) {
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => new Response(JSON.stringify(url === '/api/me' ? identity : handler(url, options)), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}
function mount(children: ReactNode, route = '/settings') {
  return render(<StrictMode><MemoryRouter initialEntries={[route]}><SessionProvider>{children}</SessionProvider></MemoryRouter></StrictMode>);
}
afterEach(() => { window.history.replaceState(null, '', '/'); });

describe('account sessions', () => {
  it('revokes a selected session without exposing token material', async () => {
    let revoked = false;
    const fetcher = mockApi(account, (url, options) => {
      if (options?.method === 'DELETE') { revoked = true; return {}; }
      if (url === '/api/account/sessions') return { sessions: [{ id: 'current', created_at: null, expires_at: 9999999999, current: true }, ...(!revoked ? [{ id: 'other', created_at: 1, expires_at: 9999999999, current: false }] : [])] };
      throw Error(`Unexpected route ${url}`);
    });
    mount(<Account />, '/account');
    await userEvent.click(await screen.findByRole('button', { name: 'Revoke session' }));
    await waitFor(() => expect(screen.queryByText('Another session')).not.toBeInTheDocument());
    expect(fetcher).toHaveBeenCalledWith('/api/account/sessions/other', expect.objectContaining({ method: 'DELETE' }));
    expect(screen.getByText('owner@example.test')).toBeInTheDocument();
    expect(screen.getByText('before session tracking was added', { exact: false })).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('token_hash');
  });
  it('requires confirmation before revoking all sessions and refreshes identity', async () => {
    const fetcher = mockApi(account, () => ({ sessions: [] }));
    mount(<Account />, '/account');
    await userEvent.click(await screen.findByRole('button', { name: 'Sign out everywhere' }));
    expect(fetcher.mock.calls.some(([, options]) => options?.method === 'DELETE')).toBe(false);
    await userEvent.click(screen.getByRole('button', { name: 'Confirm sign out everywhere' }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith('/api/account/sessions', expect.objectContaining({ method: 'DELETE' })));
    expect(fetcher.mock.calls.filter(([url]) => url === '/api/me').length).toBeGreaterThan(1);
  });
});

describe('policy role and plan gates', () => {
  it.each([
    ['Free owner', organization, 'project'],
    ['Team developer', { ...teamOrg, role: 'developer' as const }, 'project'],
    ['Team viewer', { ...teamOrg, role: 'viewer' as const }, 'project'],
    ['Pro workspace', { ...teamOrg, usage: { ...teamOrg.usage, features: { ...teamOrg.usage.features, organization_policy: false } } }, undefined],
  ])('keeps %s read-only', async (_label, org, projectId) => {
    mockApi(account, () => ({ policy, version: 3 }));
    render(<PolicyEditor organization={org} projectId={projectId} />);
    expect(await screen.findByRole('checkbox', { name: 'Block new critical paths' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Save policy' })).not.toBeInTheDocument();
  });
  it('submits exact trusted policy fields and preserves inherited values', async () => {
    const inherited = { ...policy, thresholds: { minimum_security_score: 70 } };
    const fetcher = mockApi(account, () => ({ policy: null, version: 0, effective: { source: 'organization', version: 4, rules: inherited } }));
    render(<PolicyEditor organization={teamOrg} projectId="project" />);
    const threshold = await screen.findByLabelText('Minimum security score (blank for no threshold)');
    expect(threshold).toHaveValue(70);
    await userEvent.clear(threshold); await userEvent.type(threshold, '80');
    await userEvent.click(screen.getByRole('button', { name: 'Save policy' }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith('/api/projects/project/policy', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ ...policy, thresholds: { minimum_security_score: 80 } }) })));
  });
  it('requires confirmation before removing a policy override', async () => {
    const fetcher = mockApi(account, () => ({ policy, version: 3 }));
    render(<PolicyEditor organization={teamOrg} projectId="project" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Remove policy override' }));
    expect(fetcher.mock.calls.some(([, options]) => options?.method === 'DELETE')).toBe(false);
    await userEvent.click(screen.getByRole('button', { name: 'Confirm remove override' }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith('/api/projects/project/policy', expect.objectContaining({ method: 'DELETE' })));
  });
});

describe('project lifecycle', () => {
  it('keeps workspace and project context in navigation, selection and fresh page loads', async () => {
    const secondOrg = { ...organization, id: 'second-org', name: 'Second workspace' };
    const firstProject = { ...project, id: 'second-project', organization_id: secondOrg.id, name: 'First project in second workspace' };
    const secondProject = { ...firstProject, id: 'third-project', name: 'Selected project' };
    const fetcher = mockApi({ ...account, organizations: [organization, secondOrg] }, url => {
      if (url.startsWith('/api/projects?')) return { projects: [firstProject, secondProject] };
      return { policy: null, version: 0 };
    });
    const view = mount(<Settings />, '/settings?organization=second-org&project=third-project');
    expect(await screen.findByLabelText('Project name')).toHaveValue('Selected project');
    expect(screen.getByRole('combobox', { name: 'Workspace' })).toHaveValue(secondOrg.id);
    for (const link of within(screen.getByRole('navigation', { name: 'Workspace navigation' })).getAllByRole('link')) {
      expect(link.getAttribute('href')).toContain('?organization=second-org&project=third-project');
    }
    expect(screen.getByRole('link', { name: 'GitHub integration' })).toHaveAttribute('href', '/integrations?organization=second-org&project=third-project');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Project' }), firstProject.id);
    expect(await screen.findByLabelText('Project name')).toHaveValue(firstProject.name);
    const location = screen.getByRole('link', { name: 'Settings & policy' }).getAttribute('href')!;
    view.unmount();
    mount(<Settings />, location);
    expect(await screen.findByLabelText('Project name')).toHaveValue(firstProject.name);
    await userEvent.click(screen.getByRole('button', { name: 'Save project' }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith('/api/projects/second-project', expect.objectContaining({ method: 'PATCH' })));
    expect(fetcher.mock.calls.filter(([url]) => url.startsWith('/api/projects?')).every(([url]) => url.includes('organization_id=second-org'))).toBe(true);
  });
  it('does not substitute another workspace or project for an unavailable explicit selection', async () => {
    mockApi(account, url => url.startsWith('/api/projects?') ? { projects: [project] } : { policy: null, version: 0 });
    const view = mount(<Settings />, '/settings?organization=unavailable');
    expect(await screen.findByText('Workspace unavailable. Choose a workspace you can access.')).toBeVisible();
    expect(screen.queryByRole('button', { name: /Save workspace|Save project/ })).not.toBeInTheDocument();
    view.unmount();
    mount(<Settings />, '/settings?organization=org&project=unavailable');
    expect(await screen.findByRole('option', { name: 'Select an available project' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save project' })).not.toBeInTheDocument();
  });
  it('refreshes inherited rules after saving workspace policy without losing project edits', async () => {
    let threshold = 70;
    mockApi({ ...account, organizations: [teamOrg] }, (url, options) => {
      if (url.startsWith('/api/projects?')) return { projects: [project] };
      if (options?.method === 'PUT') threshold = 80;
      const rules = { ...policy, thresholds: { minimum_security_score: threshold } };
      return url.startsWith('/api/organizations/') ? { policy: rules, version: threshold } : { policy: null, version: 0, effective: { source: 'organization', version: threshold, rules } };
    });
    mount(<Settings />);
    const name = await screen.findByLabelText('Project name');
    await userEvent.clear(name); await userEvent.type(name, 'Unsaved name');
    const orgPolicy = screen.getByRole('heading', { name: 'Workspace policy' }).closest('section')!;
    const projectPolicy = screen.getByRole('heading', { name: 'Project policy' }).closest('section')!;
    const input = within(orgPolicy).getByLabelText('Minimum security score (blank for no threshold)');
    await userEvent.clear(input); await userEvent.type(input, '80');
    await userEvent.click(within(orgPolicy).getByRole('button', { name: 'Save policy' }));
    await waitFor(() => expect(within(screen.getByRole('heading', { name: 'Project policy' }).closest('section')!).getByLabelText('Minimum security score (blank for no threshold)')).toHaveValue(80));
    expect(name).toHaveValue('Unsaved name');
    expect(projectPolicy).not.toBeInTheDocument();
  });
  it('archives with the complete metadata payload and offers restoration', async () => {
    let archived = false;
    const fetcher = mockApi(account, (url, options) => {
      if (url.startsWith('/api/projects?')) return { projects: [{ ...project, archived_at: archived ? 100 : null }] };
      if (url.endsWith('/policy')) return { policy: null, version: 0 };
      if (options?.method === 'PATCH') { archived = true; return {}; }
      throw Error(`Unexpected route ${url}`);
    });
    mount(<Settings />);
    await userEvent.click(await screen.findByRole('button', { name: 'Archive project' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirm archive' }));
    await screen.findByRole('button', { name: 'Restore project' });
    expect(fetcher).toHaveBeenCalledWith('/api/projects/project', expect.objectContaining({
      method: 'PATCH', body: JSON.stringify({ name: project.name, description: '', repository: '', repository_provider: 'manual', default_branch: 'main', environment: '', terraform_root: '.', archived: true }),
    }));
  });
  it('hides analysis submission for an archived project while retaining history', async () => {
    mockApi(account, url => url.startsWith('/api/projects?') ? { projects: [{ ...project, archived_at: 100 }] } : { analyses: [], total: 0, limit: 50, offset: 0 });
    mount(<Workspace />, '/dashboard');
    await screen.findByText(/This project is archived/);
    expect(screen.queryByRole('button', { name: 'Analyze change' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Analysis history' })).toBeInTheDocument();
  });
  it('lets developers analyze but not create projects or manage members', async () => {
    mockApi({ ...account, organizations: [{ ...organization, role: 'developer' }] }, url => url.startsWith('/api/projects?') ? { projects: [project] } : { analyses: [], total: 0, limit: 50, offset: 0 });
    mount(<Workspace />, '/dashboard');
    expect(await screen.findByRole('button', { name: 'Analyze change' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Create project' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Team' })).not.toBeInTheDocument();
  });
});

describe('history queries', () => {
  it('sends supported filters and paginates using total even when a page is short', async () => {
    const fetcher = mockApi(account, url => url.startsWith('/api/projects?') ? { projects: [project] } : { analyses: [queued], total: 75, limit: 50, offset: new URL(url, 'http://test').searchParams.get('offset') === '50' ? 50 : 0 });
    mount(<Workspace />, '/history');
    const next = await screen.findByRole('button', { name: 'Next' });
    await waitFor(() => expect(next).toBeEnabled());
    await userEvent.selectOptions(screen.getByLabelText('Status'), 'succeeded');
    await userEvent.selectOptions(screen.getByLabelText('Decision'), 'REVIEW REQUIRED');
    await userEvent.selectOptions(screen.getByLabelText('Input type'), 'plan');
    await userEvent.type(screen.getByLabelText('Candidate branch'), 'feature/network');
    fireEvent.change(screen.getByLabelText('Since (local time)'), { target: { value: '2026-09-01T00:00' } });
    await userEvent.click(screen.getByRole('button', { name: 'Apply filters' }));
    await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes('input_type=plan') && url.includes('decision=REVIEW+REQUIRED') && url.includes('branch=feature%2Fnetwork') && url.includes('since='))).toBe(true));
    await waitFor(() => expect(next).toBeEnabled());
    await userEvent.click(next);
    await waitFor(() => expect(screen.getByText('Page 2 · 75 results')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    expect(fetcher.mock.calls.some(([url]) => url.includes('offset=50') && url.includes('status=succeeded'))).toBe(true);
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }));
    await waitFor(() => expect(screen.getByText('Page 1 · 75 results')).toBeInTheDocument());
  });
  it('disables Next on a full final page using total rather than page length', async () => {
    mockApi(account, url => url.startsWith('/api/projects?') ? { projects: [project] } : { analyses: Array.from({ length: 50 }, (_, i) => ({ ...queued, id: `job-${i}` })), total: 50, limit: 50, offset: 0 });
    mount(<Workspace />, '/history');
    await screen.findByText('Page 1 · 50 results');
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  });
});

describe('team management', () => {
  const members = [{ user_id: 'owner', name: 'Owner', email: 'owner@example.test', role: 'owner' }, { user_id: 'reader', name: 'Reader', email: 'reader@example.test', role: 'viewer' }];
  it('protects the last owner and sends role changes for other members', async () => {
    const fetcher = mockApi({ ...account, organizations: [teamOrg] }, url => url.endsWith('/members') ? { members } : url.includes('/invitations?') ? { invitations: [] } : {});
    mount(<Team />, '/team');
    expect(await screen.findByLabelText('Role for Owner')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Remove Owner' })).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('Role for Reader'), 'developer');
    await userEvent.click(within(screen.getByLabelText('Role for Reader').closest('article')!).getByRole('button', { name: 'Save role' }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith('/api/organizations/org/members/reader', expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ role: 'developer' }) })));
  });
  it('displays the manual delivery URL only after creation and can dismiss it', async () => {
    const token = 'x'.repeat(43);
    const invitation = { id: 'invite', organization_id: 'org', email: 'invited@example.test', role: 'viewer', created_at: 1, expires_at: 9999999999, revoked_at: null, accepted_at: null };
    const fetcher = mockApi({ ...account, organizations: [teamOrg] }, (url, options) => url.endsWith('/members') ? { members } : options?.method === 'POST' ? { ...invitation, invitation_url: `${window.location.origin}/invitations/accept#token=${token}`, delivery: 'manual' } : { invitations: [] });
    mount(<Team />, '/team');
    await userEvent.type(await screen.findByLabelText('Invite email'), 'invited@example.test');
    await userEvent.selectOptions(screen.getByLabelText('Invitation role'), 'viewer');
    await userEvent.click(screen.getByRole('button', { name: 'Create invitation' }));
    expect(await screen.findByLabelText('One-time invitation link')).toHaveValue(`${window.location.origin}/invitations/accept#token=${token}`);
    expect(fetcher).toHaveBeenCalledWith('/api/organizations/org/invitations', expect.objectContaining({ method: 'POST', body: JSON.stringify({ email: 'invited@example.test', role: 'viewer' }) }));
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss link' }));
    expect(screen.queryByLabelText('One-time invitation link')).not.toBeInTheDocument();
    expect(localStorage.length + sessionStorage.length).toBe(0);
  });
  it('keeps Free member visibility but gates invitation and role creation', async () => {
    mockApi(account, url => url.endsWith('/members') ? { members } : { invitations: [] });
    mount(<Team />, '/team');
    expect(await screen.findByLabelText('Role for Reader')).toBeDisabled();
    expect(screen.queryByLabelText('Invite email')).not.toBeInTheDocument();
  });
  it('does not request manager APIs for a viewer', async () => {
    const fetcher = mockApi({ ...account, organizations: [{ ...organization, role: 'viewer' }] }, () => { throw Error('Manager API must not be requested'); });
    mount(<Team />, '/team');
    await screen.findByText('Member management is available to workspace owners and admins.');
    expect(fetcher.mock.calls.every(([url]) => url === '/api/me')).toBe(true);
  });
});

describe('invitation acceptance', () => {
  const oidc: Session = { ...account, auth: { ...account.auth, mode: 'oidc' } };
  it('clears the fragment in StrictMode and sends the secret only in the POST body', async () => {
    const token = 'x'.repeat(43);
    window.history.replaceState(null, '', `/invitations/accept#token=${token}`);
    const fetcher = mockApi(oidc, () => ({ organization_id: 'org', role: 'viewer' }));
    mount(<Invitation />, '/invitations/accept');
    const accept = await screen.findByRole('button', { name: 'Accept invitation' });
    expect(window.location.hash).toBe('');
    await userEvent.click(accept);
    expect(await screen.findByRole('heading', { name: 'Invitation accepted' })).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledWith('/api/invitations/accept', expect.objectContaining({ method: 'POST', body: JSON.stringify({ token }) }));
    expect(fetcher.mock.calls.every(([url]) => !url.includes(token))).toBe(true);
    expect(localStorage.length + sessionStorage.length).toBe(0);
  });
  it.each([
    ['malformed token', oidc, 'bad'],
    ['demo identity', account, 'x'.repeat(43)],
    ['unverified email', { ...oidc, user: { ...account.user!, email_verified: false } }, 'x'.repeat(43)],
  ])('rejects %s without a POST', async (_label, identity, token) => {
    window.history.replaceState(null, '', `/invitations/accept#token=${token}`);
    const fetcher = mockApi(identity, () => ({}));
    mount(<Invitation />, '/invitations/accept');
    expect(await screen.findByRole('button', { name: 'Accept invitation' })).toBeDisabled();
    expect(window.location.hash).toBe('');
    expect(fetcher.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
  });
});
