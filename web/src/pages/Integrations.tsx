import { useState } from 'react';
import { Link } from 'react-router-dom';
import { canManage, githubConfigSchema, githubProjectSchema, installationsSchema, jobError, mutate, safeGitHubUrl, type Organization, type Project } from '../api';
import { useAction, useResource } from '../hooks';
import { useOrganization } from '../session';
import { AuthGate } from '../components/AuthGate';
import { WorkspaceNav } from '../components/WorkspaceNav';
import { ProjectPicker, useProjectSelection } from '../components/ProjectPicker';
import { ErrorNotice, Loading, PageHeading } from '../components/UI';

function ProjectConnection({ project, org, available, installations }: {
  project: Project; org: Organization; available: boolean; installations: { id: number; account_login: string; status: string }[];
}) {
  const url = `/api/projects/${encodeURIComponent(project.id)}/github`;
  const status = useResource(url, githubProjectSchema);
  const [installation, setInstallation] = useState('');
  const [repository, setRepository] = useState('');
  const [confirm, setConfirm] = useState(false);
  const action = useAction();
  const connection = status.data?.connection;
  const run = status.data?.latest_run;
  const repositoryUrl = connection && /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(connection.full_name) ? `https://github.com/${connection.full_name}` : null;
  return <section className="panel"><div className="panel-heading"><h2>Project connection</h2><button className="button secondary" onClick={status.reload}>Refresh connection</button></div>
    <ErrorNotice error={status.error} retry={status.reload} /><ErrorNotice error={action.error} />
    {status.loading && <Loading>Loading connection…</Loading>}{action.notice && <p role="status">{action.notice}</p>}
    {status.data && <>{connection ? <><p><strong>{connection.full_name}</strong> · <span className="tag">{connection.status}</span></p><p>Verified installation {connection.installation_id} · repository {connection.repository_id}</p></> : <p>No repository connected to this project.</p>}
      {run ? <><h3>Latest retained PR run</h3><dl className="facts"><div><dt>PR</dt><dd>#{run.pull_number}</dd></div><div><dt>Publication state</dt><dd>{run.status}</dd></div><div><dt>Base</dt><dd><code>{run.base_ref} · {run.base_sha}</code></dd></div><div><dt>Head</dt><dd><code>{run.head_ref} · {run.head_sha}</code></dd></div></dl>
        {run.error && <p className="notice">{jobError(run.error)}</p>}
        <div className="button-row">{run.analysis_id && <Link className="button secondary" to={`/dashboard?project=${encodeURIComponent(project.id)}&analysis=${encodeURIComponent(run.analysis_id)}`}>Open analysis</Link>}
          {repositoryUrl && <a className="button secondary" href={`${repositoryUrl}/pull/${run.pull_number}`} target="_blank" rel="noreferrer">Open pull request</a>}
          {repositoryUrl && run.check_id && <a className="button secondary" href={`${repositoryUrl}/runs/${run.check_id}`} target="_blank" rel="noreferrer">Open check</a>}
        </div></> : <p className="muted">No retained PR runs. This does not verify webhook delivery or check publication.</p>}
    </>}
    {canManage(org.role) && available && !project.archived_at && connection?.status !== 'active' && <form className="inline-form" onSubmit={event => {
      event.preventDefault(); void action.run(async () => {
        if (!Number.isSafeInteger(Number(repository)) || Number(repository) <= 0) throw new Error('Enter a positive numeric repository ID.');
        await mutate(url, 'PUT', { installation_id: Number(installation), repository_id: Number(repository) }); status.reload();
      }, 'Connection request accepted. The refreshed server status is shown above.');
    }}><label>Verified installation<select required value={installation} onChange={e => setInstallation(e.target.value)}><option value="">Select an installation</option>{installations.filter(item => item.status === 'active').map(item => <option value={item.id} key={item.id}>{item.account_login} · {item.id}</option>)}</select></label><label>Numeric repository ID<input required inputMode="numeric" pattern="[0-9]+" value={repository} onChange={e => setRepository(e.target.value)} /></label><button className="button primary" disabled={action.busy || !installation}>Connect verified repository</button><p className="muted">Ask the operator for the stable repository ID. The server independently verifies access through this installation. No repository discovery endpoint is available.</p></form>}
    {canManage(org.role) && connection && connection.status !== 'disconnected' && (confirm ? <div className="notice confirm-delete"><span>Disconnect future PR analysis? Retained workspace reports remain available. This does not uninstall the GitHub App.</span><button className="button danger" disabled={action.busy} onClick={() => { void action.run(async () => { await mutate(url, 'DELETE'); setConfirm(false); status.reload(); }, 'Project disconnected.'); }}>Confirm disconnect</button><button className="button secondary" onClick={() => setConfirm(false)}>Cancel</button></div> : <button className="button secondary" onClick={() => setConfirm(true)}>Disconnect project</button>)}
    {!canManage(org.role) && <p className="notice">Only owners and admins can connect or disconnect projects.</p>}
    {project.archived_at && <p className="notice">Restore this project in settings before connecting it.</p>}
  </section>;
}
function IntegrationContent() {
  const config = useResource('/api/github/config', githubConfigSchema);
  const { organization: org } = useOrganization();
  const installations = useResource(org ? `/api/organizations/${encodeURIComponent(org.id)}/github/installations` : null, installationsSchema);
  const selection = useProjectSelection(org);
  let installUrl: string | null = null;
  try { if (config.data?.installation_url) installUrl = safeGitHubUrl(config.data.installation_url); } catch { /* Invalid provider links are not rendered. */ }
  return <><WorkspaceNav /><div className="report-stack"><section className="panel"><h2>GitHub App setup</h2>
    <ErrorNotice error={config.error} retry={config.reload} />{config.loading && <Loading>Checking GitHub configuration…</Loading>}
    {config.data && <><p className="notice">{config.data.available ? 'Operator registration required. Installing the App alone does not connect this workspace.' : 'GitHub is unavailable: the operator has not configured usable GitHub App credentials.'}</p>
      <p>Configuration reason: <code>{config.data.reason}</code></p><ol className="guide-steps"><li>The operator configures App credentials and a webhook secret.</li><li>A GitHub account admin installs the App for selected repositories.</li><li>The operator independently verifies account authorization and registers the installation to this workspace.</li><li>A workspace owner or admin connects the verified repository and configures the check as required in GitHub.</li></ol>
      {installUrl && config.data.available && <a className="button secondary" href={installUrl} target="_blank" rel="noreferrer">Open GitHub App installation</a>}
      <h3>Required permissions</h3><ul className="findings">{Object.entries(config.data.permissions).map(([permission, value]) => <li key={permission}><code>{permission}</code>: {value}</li>)}</ul>
      <p>The App reads bounded Terraform snapshots and can publish checks and PR comments. It does not execute contributor workflows, scripts or Terraform providers.</p>
    </>}
  </section><section className="panel"><h2>Registered installations</h2><ErrorNotice error={installations.error} retry={installations.reload} />{installations.loading && <Loading>Loading installations…</Loading>}{installations.data?.installations.map(item => <p key={item.id}>{item.account_login} · {item.id} · <strong>{item.status}</strong> · verified {new Date(item.verified_at * 1000).toLocaleDateString()}</p>)}{installations.data?.installations.length === 0 && <p>No verified installations are registered to this workspace. Ask the deployment operator to complete registration.</p>}</section>
    <ProjectPicker selection={selection} />
    {org && selection.project && <ProjectConnection key={selection.project.id} org={org} project={selection.project} available={config.data?.available ?? false} installations={installations.data?.installations ?? []} />}
  </div></>;
}
export default function Integrations() {
  return <div className="container page"><PageHeading eyebrow="INTEGRATIONS" title="Connect the review to the pull request.">Verified installation mappings, repository status and retained PR evidence.</PageHeading><AuthGate><IntegrationContent /></AuthGate></div>;
}
