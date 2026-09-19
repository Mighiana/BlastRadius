import { useSearchParams } from 'react-router-dom';
import { projectsSchema, type Organization } from '../api';
import { useResource } from '../hooks';
import { ErrorNotice, Loading } from './UI';

export function useProjectSelection(organization: Organization | undefined) {
  const [params, setParams] = useSearchParams();
  const projects = useResource(organization ? `/api/projects?organization_id=${encodeURIComponent(organization.id)}&limit=100` : null, projectsSchema);
  const selected = params.get('project');
  const project = projects.data?.projects.find(item => item.id === selected) ?? projects.data?.projects[0];
  return { projects, project, select: (id: string) => setParams({ project: id }) };
}
export function ProjectPicker({ selection }: { selection: ReturnType<typeof useProjectSelection> }) {
  return <><ErrorNotice error={selection.projects.error} retry={selection.projects.reload} />
    {selection.projects.loading && <Loading>Loading projects…</Loading>}
    {selection.projects.data?.projects.length === 0 && <p className="notice">No projects yet. Create one in the Analyze workspace.</p>}
    {!!selection.projects.data?.projects.length && <label className="project-picker">Project<select value={selection.project?.id ?? ''} onChange={e => selection.select(e.target.value)}>{selection.projects.data.projects.map(project => <option value={project.id} key={project.id}>{project.name}{project.archived_at ? ' · archived' : ''}</option>)}</select></label>}
  </>;
}
