import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import type { Project } from '../api';
import { SessionProvider } from '../session';
import { account, organization, project } from '../test/fixtures';
import Integrations from './Integrations';
import Settings from './Settings';
import Workspace from './Workspace';

const projects = Array.from({ length: 101 }, (_, index) => ({
  ...project, id: `project-${index}`, name: `Project ${index}`, created_at: 101 - index,
}));
const oldest = projects[100]!;
const otherOrg = { ...organization, id: 'other-org', name: 'Other workspace' };
const otherProject = { ...project, id: 'other-project', organization_id: otherOrg.id, name: 'Other project' };
const routes = ['/dashboard', '/history', '/settings', '/integrations'];

function mockApi(list = projects) {
  let saved: Project | null = null;
  let failPage = false;
  const fetcher = vi.fn(async (path: string, options?: RequestInit) => {
    const url = new URL(path, window.location.origin);
    let body: unknown;
    if (path === '/api/me') body = { ...account, organizations: [
      { ...organization, plan: 'enterprise', usage: { ...organization.usage, limits: { ...organization.usage.limits, projects: 200 } } },
      otherOrg,
    ] };
    else if (url.pathname === '/api/projects') {
      const offset = Number(url.searchParams.get('offset'));
      if (failPage && offset) return new Response(JSON.stringify({ detail: 'unavailable' }), { status: 503 });
      const source = url.searchParams.get('organization_id') === otherOrg.id ? [otherProject] : list;
      body = { projects: source.slice(offset, offset + Number(url.searchParams.get('limit'))) };
    } else if (url.pathname.endsWith('/analyses')) body = { analyses: [], total: 0, limit: 50, offset: 0 };
    else if (path.endsWith('/policy')) body = { policy: null, version: 0 };
    else if (path === '/api/github/config') body = {
      configured: false, available: false, mode: 'operator_registration', self_service: false,
      app_slug: null, installation_url: null, reason: 'github_not_configured', permissions: {},
    };
    else if (path.endsWith('/installations')) body = { installations: [] };
    else if (path.endsWith('/github')) body = { connection: null, latest_run: null };
    else {
      const found = [...list, otherProject].find(item => path === `/api/projects/${item.id}`);
      if (!found) return new Response(JSON.stringify({ detail: 'not_found' }), { status: 404 });
      if (options?.method === 'PATCH') saved = { ...found, description: 'Updated oldest', updated_at: 2 };
      body = saved?.id === found.id ? saved : found;
    }
    return new Response(JSON.stringify(body));
  });
  vi.stubGlobal('fetch', fetcher);
  return { fetcher, failPage: (fail: boolean) => { failPage = fail; } };
}

function mount(route: string) {
  return render(<MemoryRouter initialEntries={[route]}><SessionProvider><Routes>
    <Route path="/dashboard" element={<Workspace />} />
    <Route path="/history" element={<Workspace />} />
    <Route path="/settings" element={<Settings />} />
    <Route path="/integrations" element={<Integrations />} />
  </Routes></SessionProvider></MemoryRouter>);
}

async function expectSelected(route: string, target = oldest) {
  if (route === '/dashboard' || route === '/history') {
    expect(await screen.findByRole('button', { name: target.name })).toHaveAttribute('aria-pressed', 'true');
    await screen.findByRole('heading', { name: 'Analysis history' });
  } else {
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Project' })).toHaveValue(target.id));
    if (route === '/settings') expect(await screen.findByRole('textbox', { name: 'Project name' })).toHaveValue(target.name);
    else await screen.findByRole('heading', { name: 'Project connection' });
  }
}

describe('project pagination and authorized direct links', () => {
  it.each(routes)('selects the 101st project after paging in %s', async route => {
    const { fetcher } = mockApi();
    const user = userEvent.setup();
    mount(`${route}?organization=org`);
    await user.click(await screen.findByRole('button', { name: 'Next projects' }));
    if (route === '/dashboard' || route === '/history') await user.click(await screen.findByRole('button', { name: oldest.name }));
    else await user.selectOptions(await screen.findByRole('combobox', { name: 'Project' }), await screen.findByRole('option', { name: oldest.name }));
    await expectSelected(route);
    expect(fetcher).toHaveBeenCalledWith('/api/projects?organization_id=org&limit=100&offset=100', expect.anything());
    expect(screen.getByRole('button', { name: 'Next projects' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Previous projects' }));
    await expectSelected(route);
  });

  it.each(routes)('restores an off-page direct link without duplicate choices in %s', async route => {
    const { fetcher } = mockApi();
    const view = mount(`${route}?organization=org&project=${oldest.id}`);
    await expectSelected(route);
    expect(fetcher).toHaveBeenCalledWith(`/api/projects/${oldest.id}`, expect.anything());
    view.unmount();
    mount(`${route}?organization=org&project=${oldest.id}`);
    await expectSelected(route);
    await userEvent.click(screen.getByRole('button', { name: 'Next projects' }));
    await waitFor(() => expect(screen.getByText('Project page 2')).toBeVisible());
    await expectSelected(route);
    expect(screen.getAllByRole(route === '/dashboard' || route === '/history' ? 'button' : 'option', { name: oldest.name })).toHaveLength(1);
  });

  it('refreshes an off-page project after saving settings', async () => {
    const { fetcher } = mockApi();
    mount(`/settings?organization=org&project=${oldest.id}`);
    await expectSelected('/settings');
    fireEvent.change(screen.getByRole('textbox', { name: 'Description' }), { target: { value: 'Updated oldest' } });
    await userEvent.click(screen.getByRole('button', { name: 'Save project' }));
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Description' })).toHaveValue('Updated oldest'));
    await waitFor(() => expect(fetcher.mock.calls.filter(([path, options]) => path === `/api/projects/${oldest.id}` && options?.method !== 'PATCH').length).toBeGreaterThan(1));
    expect(await screen.findByText('Project saved.')).toBeVisible();
  });

  it.each(['unavailable', otherProject.id])('does not substitute a project for %s in another or unavailable workspace', async id => {
    mockApi();
    mount(`/settings?organization=org&project=${id}`);
    await screen.findByRole('combobox', { name: 'Project' });
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Project' })).toHaveValue(''));
    expect(screen.queryByRole('button', { name: 'Save project' })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: otherProject.name })).not.toBeInTheDocument();
  });

  it('resets the page and selection when switching workspaces', async () => {
    const { fetcher } = mockApi();
    mount('/settings?organization=org');
    await userEvent.click(await screen.findByRole('button', { name: 'Next projects' }));
    await screen.findByRole('option', { name: oldest.name });
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Workspace' }), otherOrg.id);
    await expectSelected('/settings', otherProject);
    expect(screen.queryByRole('option', { name: oldest.name })).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledWith('/api/projects?organization_id=other-org&limit=100&offset=0', expect.anything());
    expect(fetcher.mock.calls.some(([path]) => path.includes('organization_id=other-org') && path.includes('offset=100'))).toBe(false);
  });

  it('offers recovery from a failed or empty later page without losing the selected project', async () => {
    const api = mockApi(projects.slice(0, 100));
    mount('/settings?organization=org');
    api.failPage(true);
    await userEvent.click(await screen.findByRole('button', { name: 'Next projects' }));
    await screen.findByRole('alert');
    expect(screen.getByRole('button', { name: 'Previous projects' })).toBeEnabled();
    api.failPage(false);
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    await screen.findByText('No projects on this page. Go back to the previous page.');
    await expectSelected('/settings', projects[0]!);
    expect(screen.getByRole('button', { name: 'Next projects' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Previous projects' }));
    await screen.findByRole('option', { name: projects[99]!.name });
  });
});
