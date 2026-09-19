import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { canManage, mutate, type Organization, type Project } from '../api';
import { useAction } from '../hooks';
import { useOrganization, useSession } from '../session';
import { AuthGate } from '../components/AuthGate';
import { WorkspaceNav } from '../components/WorkspaceNav';
import { ProjectPicker, useProjectSelection } from '../components/ProjectPicker';
import { PolicyEditor } from '../components/PolicyEditor';
import { ErrorNotice, PageHeading } from '../components/UI';

function WorkspaceSettings({ organization }: { organization: Organization }) {
  const [name, setName] = useState(organization.name);
  const { refresh } = useSession();
  const action = useAction();
  return <section className="panel"><h2>Workspace settings</h2><form className="inline-form" onSubmit={e => {
    e.preventDefault(); void action.run(async () => { await mutate(`/api/organizations/${encodeURIComponent(organization.id)}`, 'PATCH', { name: name.trim() }); await refresh(); }, 'Workspace saved.');
  }}><label>Workspace name<input required maxLength={100} value={name} disabled={!canManage(organization.role)} onChange={e => setName(e.target.value)} /></label>
    {canManage(organization.role) && <button className="button primary" disabled={action.busy}>Save workspace</button>}</form>
    <ErrorNotice error={action.error} />{action.notice && <p role="status">{action.notice}</p>}
    <p className="muted">Your role: {organization.role}. Owners and admins manage settings; developers run analyses; viewers read and export evidence.</p>
  </section>;
}
function ProjectSettings({ project, editable, reload }: { project: Project; editable: boolean; reload: () => void }) {
  const [values, setValues] = useState({
    name: project.name, description: project.description, repository: project.repository, repository_provider: project.repository_provider,
    default_branch: project.default_branch, environment: project.environment, terraform_root: project.terraform_root, archived: !!project.archived_at,
  });
  const [archiveConfirmation, setArchiveConfirmation] = useState(false);
  const action = useAction();
  const { refresh } = useSession();
  function save(event: FormEvent) {
    event.preventDefault();
    void action.run(async () => { await mutate(`/api/projects/${encodeURIComponent(project.id)}`, 'PATCH', values); reload(); await refresh(); }, 'Project saved.');
  }
  return <section className="panel"><h2>Project settings</h2><form className="settings-form" onSubmit={save}>
    <fieldset disabled={!editable || action.busy}><legend>Infrastructure metadata</legend><div className="form-grid">
      <label>Project name<input required maxLength={100} value={values.name} onChange={e => setValues({ ...values, name: e.target.value })} /></label>
      <label>Environment<input maxLength={100} value={values.environment} onChange={e => setValues({ ...values, environment: e.target.value })} /></label>
      <label>Repository (owner/name)<input maxLength={255} pattern="([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?" value={values.repository} onChange={e => setValues({ ...values, repository: e.target.value })} /></label>
      <label>Repository provider<select value={values.repository_provider} onChange={e => setValues({ ...values, repository_provider: e.target.value === 'github' ? 'github' : 'manual' })}><option value="manual">Manual uploads</option><option value="github">GitHub</option></select></label>
      <label>Default branch<input required maxLength={120} value={values.default_branch} onChange={e => setValues({ ...values, default_branch: e.target.value })} /></label>
      <label>Terraform root<input required maxLength={255} value={values.terraform_root} onChange={e => setValues({ ...values, terraform_root: e.target.value })} /></label>
    </div><label>Description<textarea maxLength={2000} rows={3} value={values.description} onChange={e => setValues({ ...values, description: e.target.value })} /></label>
      {editable && <button className="button primary">Save project</button>}
    </fieldset>
  </form><p className="muted">Metadata does not connect a repository. Use <Link to={`/integrations?organization=${encodeURIComponent(project.organization_id)}&project=${encodeURIComponent(project.id)}`}>GitHub integration</Link> for verified connection status. Terraform root must be repository-relative.</p>
    <ErrorNotice error={action.error} />{action.notice && <p role="status">{action.notice}</p>}
    <p>{project.archived_at ? 'Archived: new analyses are disabled. Existing evidence remains subject to retention.' : 'Archiving stops new analyses while keeping retained history.'}</p>
    {editable && (archiveConfirmation ? <div className="notice confirm-delete"><span>{project.archived_at ? 'Restore this project?' : 'Archive this project? Unsaved metadata will not be changed.'}</span>
      <button className="button danger" disabled={action.busy} onClick={() => { void action.run(async () => {
        await mutate(`/api/projects/${encodeURIComponent(project.id)}`, 'PATCH', {
          name: project.name, description: project.description, repository: project.repository, repository_provider: project.repository_provider,
          default_branch: project.default_branch, environment: project.environment, terraform_root: project.terraform_root, archived: !project.archived_at,
        }); setArchiveConfirmation(false); reload(); await refresh();
      }); }}>Confirm {project.archived_at ? 'restore' : 'archive'}</button><button className="button secondary" onClick={() => setArchiveConfirmation(false)}>Cancel</button></div>
      : <button className="button secondary" onClick={() => setArchiveConfirmation(true)}>{project.archived_at ? 'Restore project' : 'Archive project'}</button>)}
  </section>;
}
function SettingsContent() {
  const { organization } = useOrganization();
  const selection = useProjectSelection(organization);
  const [policyRevision, setPolicyRevision] = useState(0);
  return <><WorkspaceNav />{organization ? <div className="report-stack">
    <WorkspaceSettings key={organization.id} organization={organization} />
    <PolicyEditor key={`org-${organization.id}`} organization={organization} onChange={() => setPolicyRevision(value => value + 1)} />
    <ProjectPicker selection={selection} />
    {selection.project && <><ProjectSettings key={`${selection.project.id}-${selection.project.updated_at}`} project={selection.project} editable={canManage(organization.role)} reload={selection.projects.reload} /><PolicyEditor key={`${selection.project.id}-${policyRevision}`} organization={organization} projectId={selection.project.id} /></>}
  </div> : <p className="notice">Create a workspace to manage settings.</p>}</>;
}
export default function Settings() {
  return <div className="container page"><PageHeading eyebrow="SETTINGS" title="Define the review context.">Workspace metadata, project lifecycle and trusted policy.</PageHeading><AuthGate><SettingsContent /></AuthGate></div>;
}
