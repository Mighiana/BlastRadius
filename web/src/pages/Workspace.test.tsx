import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { SessionProvider } from '../session';
import type { Session } from '../api';
import { account, project, queued, session } from '../test/fixtures';
import Workspace from './Workspace';

const viewer: Session = {
  ...account, organizations: account.organizations.map(org => ({ ...org, role: 'viewer' })),
};
function mount(route = '/dashboard') {
  return render(<MemoryRouter initialEntries={[route]}><SessionProvider><Workspace /></SessionProvider></MemoryRouter>);
}
describe('workspace roles and polling', () => {
  it.each([session, viewer])('does not offer unusable onboarding or writes on an untrusted origin ($authenticated)', async current => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      ...current, auth: { ...current.auth, public_url: 'https://configured.example' },
    }))));
    mount();
    expect(await screen.findByRole('heading', { name: 'Workspace unavailable at this address' })).toBeVisible();
    expect(screen.getByRole('alert')).toHaveTextContent('BR_PUBLIC_URL');
    expect(screen.queryByRole('button', { name: /Create.*workspace|Create project|Analyze change/ })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Try the public demo' })).toHaveAttribute('href', '/demo');
  });
  it('selects the created workspace and scopes the first project to it', async () => {
    const user = userEvent.setup();
    const owner = { ...viewer, organizations: [{ ...viewer.organizations[0]!, role: 'owner' as const }] };
    const created = { ...owner.organizations[0]!, id: 'new-org', name: 'New workspace' };
    let current = owner;
    const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
      if (url === '/api/organizations') {
        current = { ...owner, organizations: [...owner.organizations, created] };
        return new Response(JSON.stringify(created));
      }
      const body = url === '/api/me' ? current
        : url === '/api/projects' ? { ...project, organization_id: 'new-org' }
          : url.startsWith('/api/projects?') ? { projects: [] } : url === '/api/projects/project' ? { ...project, organization_id: 'new-org' } : { analyses: [], total: 0, limit: 50, offset: 0 };
      return new Response(JSON.stringify(body), { status: options?.method === 'POST' ? 201 : 200 });
    });
    vi.stubGlobal('fetch', fetcher);
    mount();
    await user.click(await screen.findByText('Create another workspace'));
    await user.type(screen.getByLabelText('Workspace name'), 'New workspace');
    await user.click(screen.getByRole('button', { name: 'Create workspace' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Workspace “New workspace” created');
    expect(screen.getByLabelText('Workspace', { exact: true })).toHaveValue('new-org');
    await user.type(screen.getByLabelText('Project name'), 'Infrastructure');
    await user.click(screen.getByRole('button', { name: 'Create project' }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith('/api/projects', expect.objectContaining({
      body: JSON.stringify({ organization_id: 'new-org', name: 'Infrastructure' }),
    })));
  });
  it('keeps a viewer read-only instead of presenting unusable mutation controls', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(
      url === '/api/me' ? viewer : url.startsWith('/api/projects?') ? { projects: [project] } : { analyses: [queued], total: 1, limit: 50, offset: 0 },
    ))));
    mount();
    expect(await screen.findByText(/Viewer access/)).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Create project' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Analyze change' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Delete analysis/ })).not.toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /before → after/ })).toBeEnabled();
  });
  it('polls queued jobs to a sanitized failure without inventing a report', async () => {
    let polls = 0;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      const body = url === '/api/me' ? viewer
        : url.startsWith('/api/projects?') ? { projects: [project] }
          : url === '/api/projects/project' ? project : url.startsWith('/api/projects/') ? { analyses: [queued], total: 1, limit: 50, offset: 0 }
            : ++polls === 1 ? queued : { ...queued, status: 'failed', error: '/home/operator/private/job.py Traceback' };
      return new Response(JSON.stringify(body));
    }));
    mount('/dashboard?project=project&analysis=job');
    expect(await screen.findByText(/Queued — waiting/)).toBeVisible();
    const selected = screen.getByLabelText('Selected analysis');
    expect(selected).toHaveFocus();
    expect(selected.compareDocumentPosition(screen.getByRole('heading', { name: 'Analysis history' })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('The analysis could not be completed.'), { timeout: 3000 });
    expect(polls).toBe(2);
    expect(screen.queryByLabelText('Analysis decision')).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('Traceback');
  });
  it.each(['queued', 'running'])('removes stale %s progress when saving the outcome is unavailable', async status => {
    let polls = 0;
    let historyReads = 0;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/api/analyses/job' && ++polls > 1) {
        return new Response(JSON.stringify({ detail: 'analysis_persistence_failed' }), { status: 503 });
      }
      if (url.startsWith('/api/projects/project/analyses')) {
        historyReads++;
        if (polls > 1) return new Response(JSON.stringify({ detail: 'analysis_persistence_failed' }), { status: 503 });
        return new Response(JSON.stringify({ analyses: [{ ...queued, status }], total: 1, limit: 50, offset: 0 }));
      }
      const body = url === '/api/me' ? viewer
        : url.startsWith('/api/projects?') ? { projects: [project] }
          : url === '/api/projects/project' ? project : { ...queued, status };
      return new Response(JSON.stringify(body));
    }));
    mount('/dashboard?project=project&analysis=job');
    expect(await screen.findByText(status === 'queued' ? /Queued — waiting/ : /Analyzing Terraform/)).toBeVisible();
    await waitFor(() => {
      expect(screen.getAllByRole('alert')[0]).toHaveTextContent('Analysis incomplete:');
      expect(historyReads).toBeGreaterThan(1);
    }, { timeout: 3000 });
    expect(screen.queryByText(/Queued — waiting|Analyzing Terraform/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Analysis decision')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /before → after/ })).not.toBeInTheDocument();
    expect(polls).toBe(2);
  });
});
