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
  return <div className="panel workspace-navigation">
    <label>Workspace<select value={organization?.id ?? ''} onChange={event => {
      selectOrganization(event.target.value); setParams({ organization: event.target.value });
    }}>{session?.organizations.map(org => <option value={org.id} key={org.id}>{org.name} · {org.role}</option>)}</select></label>
    <nav aria-label="Workspace navigation">
      <NavLink to="/dashboard">Analyze</NavLink><NavLink to="/history">History</NavLink>
      <NavLink to="/settings">Settings & policy</NavLink><NavLink to="/integrations">GitHub</NavLink>
      {canManage(organization?.role) && <NavLink to="/team">Team</NavLink>}
      <NavLink to="/billing">Usage & plans</NavLink><NavLink to="/account">Account</NavLink>
    </nav>
  </div>;
}
