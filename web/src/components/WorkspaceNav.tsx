import { useEffect } from 'react';
import { NavLink, useSearchParams } from 'react-router-dom';
import { canManage } from '../api';
import { useOrganization, useSession } from '../session';

export function WorkspaceNav() {
  const { session } = useSession();
  const { organization, selectOrganization } = useOrganization();
  const [params, setParams] = useSearchParams();
  const requested = params.get('organization');
  useEffect(() => {
    if (requested && session?.organizations.some(org => org.id === requested)) selectOrganization(requested);
  }, [requested, selectOrganization, session]);
  const context = new URLSearchParams();
  if (organization) context.set('organization', organization.id);
  const project = params.get('project');
  if (organization && project) context.set('project', project);
  const search = context.size ? `?${context}` : '';
  return <div className="panel workspace-navigation">
    {requested && !organization && <p className="notice">Workspace unavailable. Choose a workspace you can access.</p>}
    <label>Workspace<select value={organization?.id ?? ''} onChange={event => {
      selectOrganization(event.target.value); setParams({ organization: event.target.value });
    }}>{session?.organizations.map(org => <option value={org.id} key={org.id}>{org.name} · {org.role}</option>)}</select></label>
    <nav aria-label="Workspace navigation">
      <NavLink to={`/dashboard${search}`}>Analyze</NavLink><NavLink to={`/history${search}`}>History</NavLink>
      <NavLink to={`/settings${search}`}>Settings & policy</NavLink><NavLink to={`/integrations${search}`}>GitHub</NavLink>
      {canManage(organization?.role) && <NavLink to={`/team${search}`}>Team</NavLink>}
      <NavLink to={`/billing${search}`}>Usage & plans</NavLink><NavLink to={`/account${search}`}>Account</NavLink>
    </nav>
  </div>;
}
