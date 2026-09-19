import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { SessionProvider } from '../session';
import type { Session } from '../api';
import { session } from '../test/fixtures';
import Workspace from './Workspace';

const viewer: Session = {
  ...session, authenticated: true, user: { id: 'reader', name: 'Read Only', email: '' },
  organizations: [{ id: 'org', name: 'Example', role: 'viewer', plan: 'free', usage: {
    period: '2026-09', plan: 'free', analyses: 1, limits: { analyses_per_month: 20, projects: 3, members: 1 },
  } }],
};
const project = { id: 'project', organization_id: 'org', name: 'Infrastructure', created_at: 1 };
const queued = {
  id: 'job', project_id: 'project', organization_id: 'org', base_label: 'before', candidate_label: 'after',
  created_at: 1, started_at: null, completed_at: null, status: 'queued', error: null, result: null,
};
function mount(route = '/dashboard') {
  return render(<MemoryRouter initialEntries={[route]}><SessionProvider><Workspace /></SessionProvider></MemoryRouter>);
}
describe('workspace roles and polling', () => {
  it('keeps a viewer read-only instead of presenting unusable mutation controls', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(
      url === '/api/me' ? viewer : url.startsWith('/api/projects?') ? { projects: [project] } : { analyses: [queued] },
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
          : url.startsWith('/api/projects/') ? { analyses: [queued] }
            : ++polls === 1 ? queued : { ...queued, status: 'failed', error: '/home/operator/private/job.py Traceback' };
      return new Response(JSON.stringify(body));
    }));
    mount('/dashboard?project=project&analysis=job');
    expect(await screen.findByText(/Queued — waiting/)).toBeVisible();
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('The analysis could not be completed.'), { timeout: 3000 });
    expect(polls).toBe(2);
    expect(screen.queryByLabelText('Analysis decision')).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('Traceback');
  });
});
