import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { projectSchema, projectsSchema, type Organization } from '../api';
import { useResource } from '../hooks';
import { ErrorNotice, Loading } from './UI';

const pageSize = 100;

export function useProjectSelection(organization: Organization | undefined) {
  const [params, setParams] = useSearchParams();
  const [pagination, setPagination] = useState({ organizationId: organization?.id, page: 0 });
  const page = pagination.organizationId === organization?.id ? pagination.page : 0;
  const projects = useResource(organization ? `/api/projects?organization_id=${encodeURIComponent(organization.id)}&limit=${pageSize}&offset=${page * pageSize}` : null, projectsSchema);
  const selected = params.get('project');
  const listed = projects.data?.projects.find(item => item.id === selected);
  const linkedProject = useResource(selected && !listed && !projects.loading ? `/api/projects/${encodeURIComponent(selected)}` : null, projectSchema);
  const linked = linkedProject.data?.organization_id === organization?.id ? linkedProject.data : null;
  const project = selected ? listed ?? linked ?? undefined : projects.data?.projects[0];
  const choices = linked && !listed ? [linked, ...(projects.data?.projects ?? [])] : projects.data?.projects ?? [];
  function changePage(next: number) {
    if (project && !selected) {
      const nextParams = new URLSearchParams(params);
      nextParams.set('organization', project.organization_id);
      nextParams.set('project', project.id);
      setParams(nextParams);
    }
    setPagination({ organizationId: organization?.id, page: next });
  }
  return { projects, linkedProject, project, choices, page, changePage,
    hasNext: projects.data?.projects.length === pageSize,
    select: (id: string) => setParams({ organization: organization?.id ?? '', project: id }) };
}
export function ProjectPagination({ selection }: { selection: ReturnType<typeof useProjectSelection> }) {
  if (!selection.page && !selection.hasNext) return null;
  return <nav className="pagination" aria-label="Project pages">
    <button className="button secondary" disabled={!selection.page || selection.projects.loading} onClick={() => selection.changePage(selection.page - 1)}>Previous projects</button>
    <span>Project page {selection.page + 1}</span>
    <button className="button secondary" disabled={!selection.hasNext || selection.projects.loading} onClick={() => selection.changePage(selection.page + 1)}>Next projects</button>
  </nav>;
}
export function ProjectPicker({ selection }: { selection: ReturnType<typeof useProjectSelection> }) {
  return <><ErrorNotice error={selection.projects.error} retry={selection.projects.reload} />
    <ErrorNotice error={selection.linkedProject.error} retry={selection.linkedProject.reload} />
    {selection.projects.loading && <Loading>Loading projects…</Loading>}
    {selection.projects.data?.projects.length === 0 && <p className="notice">{selection.page ? 'No projects on this page. Go back to the previous page.' : 'No projects yet. Create one in the Analyze workspace.'}</p>}
    {!!selection.choices.length && <label className="project-picker">Project<select value={selection.project?.id ?? ''} onChange={e => selection.select(e.target.value)}>{!selection.project && <option value="" disabled>Select an available project</option>}{selection.choices.map(project => <option value={project.id} key={project.id}>{project.name}{project.archived_at ? ' · archived' : ''}</option>)}</select></label>}
    <ProjectPagination selection={selection} />
  </>;
}
