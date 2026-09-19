import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import { z } from 'zod';
import { ArrowRight, FolderPlus, RefreshCw, Trash2 } from 'lucide-react';
import { canAnalyze, canManage, historySchema, projectsSchema, jobError, jobSchema, mutate, projectSchema, request, type Job, type Organization } from '../api';
import { useResource } from '../hooks';
import { useOrganization, useSession } from '../session';
import { AnalysisForm } from '../components/AnalysisForm';
import { AuthGate } from '../components/AuthGate';
import { Decision, Empty, ErrorNotice, Loading, PageHeading } from '../components/UI';
import { ReportView } from '../components/ReportView';
import { WorkspaceNav } from '../components/WorkspaceNav';

function JobView({ id, onComplete }: { id: string; onComplete: () => void }) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [retry, setRetry] = useState(0);
  const resultRef = useRef<HTMLElement>(null);
  const status = job?.status;
  useEffect(() => {
    if (!status) return;
    resultRef.current?.focus({ preventScroll: true });
    resultRef.current?.scrollIntoView({ block: 'start' });
  }, [status]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let delay = 1000;
    setJob(null); setError(null);
    async function poll() {
      try {
        const next = await request(`/api/analyses/${encodeURIComponent(id)}`, jobSchema, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setJob(next);
        if (next.status === 'queued' || next.status === 'running') {
          timer = setTimeout(() => { void poll(); }, delay);
          delay = Math.min(delay * 1.5, 5000);
        } else onComplete();
      } catch (err) {
        if (!controller.signal.aborted) setError(err instanceof Error ? err : new Error('Could not read this analysis.'));
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [id, retry, onComplete]);
  return <section ref={resultRef} tabIndex={-1} aria-label="Selected analysis" className="selected-analysis">
    <ErrorNotice error={error} retry={() => setRetry(n => n + 1)} />
    {!job && !error && <Loading>Opening analysis…</Loading>}
    {job && <><div className="analysis-heading"><h2>Analysis result</h2><span className="tag">{job.status}</span></div>
      {(job.status === 'queued' || job.status === 'running') && <Loading>{job.status === 'queued' ? 'Queued — waiting for an available worker…' : 'Analyzing Terraform in an isolated worker…'}</Loading>}
      {job.status === 'failed' && <ErrorNotice error={new Error(jobError(job.error))} />}
      {job.status === 'succeeded' && job.result && <ReportView report={job.result} jobId={id} />}
      <div className="analysis-heading"><h3>{job.base_label} <ArrowRight size={20} aria-hidden="true" /> {job.candidate_label}</h3></div>
      <details className="panel"><summary>Analysis provenance & trusted policy</summary><dl className="facts"><div><dt>Input</dt><dd>{job.input_type ?? 'Not recorded'}</dd></div><div><dt>Base ref / SHA</dt><dd><code>{job.base_ref ?? 'Not recorded'} / {job.base_sha ?? 'Not recorded'}</code></dd></div><div><dt>Candidate ref / SHA</dt><dd><code>{job.candidate_ref ?? 'Not recorded'} / {job.candidate_sha ?? 'Not recorded'}</code></dd></div></dl>{job.policy_snapshot ? <pre><code>{JSON.stringify(job.policy_snapshot, null, 2)}</code></pre> : <p>No policy snapshot was recorded for this analysis.</p>}</details>
    </>}
  </section>;
}

function WorkspaceContent() {
  const { session, refresh } = useSession();
  const location = useLocation();
  const historyOnly = location.pathname === '/history';
  const [params, setParams] = useSearchParams();
  const { organization: org, selectOrganization: setOrgId } = useOrganization();
  const projectId = params.get('project') ?? '';
  const analysisId = params.get('analysis') ?? '';
  const projects = useResource(org ? `/api/projects?organization_id=${encodeURIComponent(org.id)}&limit=100` : null, projectsSchema);
  const linkedProject = useResource(projectId ? `/api/projects/${encodeURIComponent(projectId)}` : null, projectSchema);
  useEffect(() => {
    if (linkedProject.data && session?.organizations.some(item => item.id === linkedProject.data?.organization_id)) setOrgId(linkedProject.data.organization_id);
  }, [linkedProject.data, session, setOrgId]);
  const project = projectId ? projects.data?.projects.find(item => item.id === projectId) : projects.data?.projects[0];
  const [historyLimit, setHistoryLimit] = useState(50);
  const [historyPage, setHistoryPage] = useState(0);
  const [filters, setFilters] = useState({ status: '', decision: '', input_type: '', branch: '', since: '', until: '' });
  const [appliedFilters, setAppliedFilters] = useState('');
  const history = useResource(project ? `/api/projects/${encodeURIComponent(project.id)}/analyses?limit=${historyLimit}&offset=${historyPage * historyLimit}${appliedFilters}` : null, historySchema);
  const reloadHistory = history.reload;
  const [projectName, setProjectName] = useState('');
  const [organizationName, setOrganizationName] = useState('');
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [confirmDelete, setConfirmDelete] = useState('');
  const canWrite = canAnalyze(org?.role);
  useEffect(() => { setHistoryPage(0); setConfirmDelete(''); }, [org?.id]);
  const workspaceLimitReached = (session?.organizations.filter(item => item.role === 'owner').length ?? 0) >= 5;
  const complete = useCallback(() => { reloadHistory(); void refresh(); }, [reloadHistory, refresh]);
  function selectProject(id: string) {
    setParams({ project: id }); setHistoryPage(0); setConfirmDelete('');
  }
  async function createProject(event: FormEvent) {
    event.preventDefault();
    if (!org) return;
    setBusy(true); setError(null);
    try {
      const created = await request('/api/projects', projectSchema, { method: 'POST', body: JSON.stringify({ organization_id: org.id, name: projectName.trim() }) });
      setProjectName(''); projects.reload(); selectProject(created.id); void refresh();
    } catch (err) { setError(err instanceof Error ? err : new Error('Could not create project.')); }
    finally { setBusy(false); }
  }
  async function createOrganization(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const created = await request('/api/organizations', z.object({ id: z.string(), name: z.string() }), { method: 'POST', body: JSON.stringify({ name: organizationName.trim() }) });
      setOrganizationName(''); await refresh();
      setOrgId(created.id); setParams({}); setHistoryPage(0); setConfirmDelete('');
      setNotice(`Workspace “${created.name}” created. Create your first project below.`);
    } catch (err) { setError(err instanceof Error ? err : new Error('Could not create workspace.')); }
    finally { setBusy(false); }
  }
  async function deleteAnalysis(id: string) {
    setBusy(true); setError(null);
    try {
      await mutate(`/api/analyses/${encodeURIComponent(id)}`, 'DELETE');
      if (analysisId === id && project) setParams({ project: project.id });
      setConfirmDelete(''); history.reload();
    } catch (err) { setError(err instanceof Error ? err : new Error('Could not delete analysis.')); }
    finally { setBusy(false); }
  }
  function submitted(job: Job) {
    setParams({ project: job.project_id, analysis: job.id }); history.reload(); void refresh();
  }
  return <>
    <WorkspaceNav />
    <div className="workspace-toolbar panel">
      {org && <div className="workspace-usage"><span className="tag">{org.plan} plan</span><strong>{org.usage.analyses} / {org.usage.limits.analyses_per_month}</strong><span>analyses · {org.usage.period} UTC · {org.usage.limits.retention_days} day retention</span><Link to={`/billing?organization=${encodeURIComponent(org.id)}`}>View workspace usage<ArrowRight size={14} aria-hidden="true" /></Link></div>}
    </div>
    <details className="workspace-create"><summary>Create another workspace</summary>{workspaceLimitReached ? <p className="muted">You already own the maximum of five workspaces. Select an existing workspace above.</p> : <form className="inline-form" onSubmit={event => { void createOrganization(event); }}><label>Workspace name<input required maxLength={100} value={organizationName} onChange={e => setOrganizationName(e.target.value)} /></label><button className="button secondary" disabled={busy}>Create workspace</button></form>}</details>
    {notice && <p role="status" className="notice">{notice}</p>}
    <ErrorNotice error={error} />
    <ErrorNotice error={linkedProject.error} retry={linkedProject.reload} />
    {analysisId && <><JobView key={analysisId} id={analysisId} onComplete={complete} /><p className="analysis-back"><a className="button secondary" href="#analysis-inputs">{historyOnly ? 'Browse analysis history' : canWrite ? 'Edit inputs or run another analysis' : 'Browse projects and history'}<ArrowRight size={16} aria-hidden="true" /></a></p></>}
    <div className="workspace-layout" id="analysis-inputs"><aside className="project-sidebar panel">
      <div className="panel-heading"><h2>Projects</h2><button className="icon-button" aria-label="Refresh projects" onClick={projects.reload}><RefreshCw size={16} aria-hidden="true" /></button></div>
      <p className="muted">Organize comparisons by repository or environment.</p>
      {projects.loading && <Loading>Loading projects…</Loading>}
      <ErrorNotice error={projects.error} retry={projects.reload} />
      <div className="project-list">{projects.data?.projects.map(item => <button key={item.id} aria-pressed={item.id === project?.id} onClick={() => selectProject(item.id)}>{item.name}{item.archived_at ? ' · archived' : ''}<ArrowRight size={15} aria-hidden="true" /></button>)}</div>
      {projects.data?.projects.length === 0 && <p>No projects yet. Create your first to get started.</p>}
      {canManage(org?.role) && org && <form className="project-form" onSubmit={event => { void createProject(event); }}><label>Project name<input placeholder="e.g. payments-production" required maxLength={100} value={projectName} onChange={event => setProjectName(event.target.value)} /></label><button className="button secondary" disabled={busy || org.usage.projects >= org.usage.limits.projects}><FolderPlus size={16} aria-hidden="true" />Create project</button>{org.usage.projects >= org.usage.limits.projects && <p className="notice">Project limit reached. Check usage and ask your operator about beta entitlements.</p>}</form>}
      {org && <p className="footnote">Up to {org.usage.limits.projects} projects · {org.usage.limits.members} members</p>}
    </aside>
      <div className="workspace-main">
        {!project && !projects.loading && <Empty title="Your first comparison starts here"><p>Create a project, then upload baseline and candidate Terraform or a plan JSON.</p><Link className="text-link" to="/demo">See an example in the public demo<ArrowRight size={16} aria-hidden="true" /></Link></Empty>}
        {project && <>
          {project.archived_at && <p className="notice">This project is archived. Retained history remains available. An owner or admin can restore it in settings.</p>}
          {!historyOnly && canWrite && !project.archived_at && <AnalysisForm key={`${org?.id}-${project.id}`} projectId={project.id} onSubmitted={submitted} />}
          {!canWrite && <div className="notice">Viewer access: you can read and export analyses. Ask a workspace owner for write access.</div>}
          <section className="panel history-panel"><div className="panel-heading"><div><p className="eyebrow">{project.name}</p><h2>Analysis history</h2></div><button className="button secondary" onClick={history.reload}><RefreshCw size={15} aria-hidden="true" />Refresh</button></div>
            <form className="history-filters" onSubmit={e => {
              e.preventDefault();
              const query = new URLSearchParams();
              for (const [key, value] of Object.entries(filters)) {
                if (!value) continue;
                query.set(key, key === 'since' || key === 'until' ? String(new Date(value).getTime() / 1000) : value.trim());
              }
              setAppliedFilters(query.size ? `&${query}` : ''); setHistoryPage(0);
            }}><div className="form-grid">
              <label>Status<select value={filters.status} onChange={e => setFilters({ ...filters, status: e.target.value })}><option value="">All statuses</option>{['queued', 'running', 'succeeded', 'failed'].map(value => <option key={value}>{value}</option>)}</select></label>
              <label>Decision<select value={filters.decision} onChange={e => setFilters({ ...filters, decision: e.target.value })}><option value="">All decisions</option>{['SAFE TO MERGE', 'REVIEW REQUIRED', 'BLOCK CHANGE'].map(value => <option key={value}>{value}</option>)}</select></label>
              <label>Input type<select value={filters.input_type} onChange={e => setFilters({ ...filters, input_type: e.target.value })}><option value="">All inputs (including GitHub)</option><option value="hcl">Uploaded HCL</option><option value="plan">Plan JSON</option></select></label>
              <label>Candidate branch<input maxLength={120} value={filters.branch} onChange={e => setFilters({ ...filters, branch: e.target.value })} /></label>
              <label>Since (local time)<input type="datetime-local" value={filters.since} onChange={e => setFilters({ ...filters, since: e.target.value })} /></label>
              <label>Until (local time)<input type="datetime-local" min={filters.since || undefined} value={filters.until} onChange={e => setFilters({ ...filters, until: e.target.value })} /></label>
            </div><div className="button-row"><button className="button secondary">Apply filters</button><button className="button secondary" type="button" onClick={() => { setFilters({ status: '', decision: '', input_type: '', branch: '', since: '', until: '' }); setAppliedFilters(''); setHistoryPage(0); }}>Clear filters</button></div></form>
            <ErrorNotice error={history.error} retry={history.reload} />
            {history.loading && <Loading>Loading history…</Loading>}
            {!history.loading && !history.data?.analyses.length && !history.error && <p className="muted">{appliedFilters ? 'No analyses match these filters on this page.' : 'No analyses on this page. Upload Terraform to run your first comparison.'}</p>}
            <div className="history-list">{history.data?.analyses.map(job => <article key={job.id} className={job.id === analysisId ? 'selected' : ''}>
              <button className="history-open" onClick={() => setParams({ project: project.id, analysis: job.id })}><span><strong>{job.base_label} → {job.candidate_label}</strong><small>{new Date(job.created_at * 1000).toLocaleString()} · {job.input_type ?? 'input not recorded'}{job.candidate_ref && ` · ${job.candidate_ref}`}</small></span>
                {job.summary ? <Decision decision={job.summary.decision} /> : <span className="tag">{job.status}</span>}</button>
              {canWrite && (confirmDelete === job.id ? <div className="confirm-delete"><span>Delete this analysis and report? Usage is not refunded.</span><button className="button danger" disabled={busy} onClick={() => { void deleteAnalysis(job.id); }}>Confirm delete</button><button className="button secondary" onClick={() => setConfirmDelete('')}>Cancel</button></div>
                : <button className="icon-button" disabled={busy} aria-label={`Delete analysis ${job.base_label} to ${job.candidate_label}`} onClick={() => setConfirmDelete(job.id)}><Trash2 size={16} aria-hidden="true" /></button>)}
            </article>)}</div>
            <div className="pagination"><button className="button secondary" disabled={!historyPage || history.loading} onClick={() => setHistoryPage(n => n - 1)}>Previous</button><span>Page {historyPage + 1} · {history.data?.total ?? 0} results</span><button className="button secondary" disabled={history.loading || !history.data || history.data.offset + history.data.limit >= history.data.total} onClick={() => setHistoryPage(n => n + 1)}>Next</button><label className="sr-only" htmlFor="history-count">Analyses per page</label><select id="history-count" value={historyLimit} onChange={e => { setHistoryLimit(Number(e.target.value)); setHistoryPage(0); }}><option value={20}>20 / page</option><option value={50}>50 / page</option></select></div>
          </section>
        </>}
      </div>
    </div>
  </>;
}
export function UsageSummary({ organization }: { organization: Organization }) {
  return <div className="usage-meter"><div><strong>{organization.usage.analyses} / {organization.usage.limits.analyses_per_month}</strong><span>analyses this month</span></div><progress max={organization.usage.limits.analyses_per_month} value={organization.usage.analyses} aria-label="Monthly analysis usage" /><small>Resets monthly in UTC. Accepted jobs count even if they fail.</small></div>;
}
export default function Workspace() {
  const { pathname } = useLocation();
  return <div className="container page"><PageHeading eyebrow="WORKSPACE" title={pathname === '/history' ? 'The evidence, kept together.' : 'Know what this change opens.'}>Compare infrastructure. Trace new paths. Review the evidence.</PageHeading><AuthGate><WorkspaceContent /></AuthGate></div>;
}
