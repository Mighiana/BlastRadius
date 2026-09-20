import { useState, type FormEvent } from 'react';
import { canManage, mutate, policyResponseSchema, type Organization, type Policy } from '../api';
import { useAction, useResource } from '../hooks';
import { ErrorNotice, Loading } from './UI';

const explicitPolicy: Policy = {
  version: 1, gate: { block_new_critical_paths: true, block_new_sensitive_exposure: true, block_public_admin_ports: true },
  allowed: { public_https: true }, thresholds: { minimum_security_score: null },
};
function PolicyForm({ url, initial, editable, reload }: { url: string; initial: Policy; editable: boolean; reload: () => void }) {
  const [policy, setPolicy] = useState(initial);
  const [confirmClear, setConfirmClear] = useState(false);
  const action = useAction();
  function save(event: FormEvent) {
    event.preventDefault();
    void action.run(async () => { await mutate(url, 'PUT', policy); reload(); }, 'Policy saved.');
  }
  return <form className="settings-form" onSubmit={save}>
    <fieldset disabled={!editable || action.busy}><legend>Trusted policy rules</legend>
      {([
        ['block_new_critical_paths', 'Block new critical paths'],
        ['block_new_sensitive_exposure', 'Block new sensitive exposure'],
        ['block_public_admin_ports', 'Block public admin ports'],
      ] as const).map(([key, label]) => <label className="check-field" key={key}><input type="checkbox" checked={policy.gate[key]} onChange={e => setPolicy({ ...policy, gate: { ...policy.gate, [key]: e.target.checked } })} />{label}</label>)}
      <label className="check-field"><input type="checkbox" checked={policy.allowed.public_https} onChange={e => setPolicy({ ...policy, allowed: { public_https: e.target.checked } })} />Allow public HTTPS (never exempts critical paths)</label>
      <label>Minimum security score (blank for no threshold)<input type="number" min={0} max={100} step={1} value={policy.thresholds.minimum_security_score ?? ''} onChange={e => setPolicy({ ...policy, thresholds: { minimum_security_score: e.target.value === '' ? null : Number(e.target.value) } })} /></label>
      {editable && <button className="button primary">Save policy</button>}
    </fieldset>
    <ErrorNotice error={action.error} />{action.notice && <p role="status">{action.notice}</p>}
    {editable && (confirmClear ? <div className="notice confirm-delete"><span>Remove this override for future analyses? Existing analysis snapshots remain unchanged.</span><button type="button" className="button danger" disabled={action.busy} onClick={() => { void action.run(async () => { await mutate(url, 'DELETE'); setConfirmClear(false); reload(); }); }}>Confirm remove override</button><button type="button" className="button secondary" onClick={() => setConfirmClear(false)}>Cancel</button></div> : <button type="button" className="button secondary" onClick={() => setConfirmClear(true)}>Remove policy override</button>)}
  </form>;
}
export function PolicyEditor({ organization, projectId, onChange }: { organization: Organization; projectId?: string; onChange?: () => void }) {
  const url = projectId ? `/api/projects/${encodeURIComponent(projectId)}/policy` : `/api/organizations/${encodeURIComponent(organization.id)}/policy`;
  const policy = useResource(url, policyResponseSchema);
  const entitled = projectId ? organization.usage.features.advanced_policy : organization.usage.features.organization_policy;
  const editable = canManage(organization.role) && entitled;
  return <section className="panel"><h2>{projectId ? 'Project' : 'Workspace'} policy</h2>
    <p>Only owners and admins can update trusted policy. Project overrides take precedence over workspace policy. Each accepted analysis retains its own policy snapshot.</p>
    {!entitled && <p className="notice">{projectId ? 'Project policies require Pro, Team or Enterprise.' : 'Workspace policies require Team or Enterprise.'} Paid plans require an operator grant.</p>}
    {!canManage(organization.role) && <p className="notice">Your role can inspect policy, but cannot edit it.</p>}
    <ErrorNotice error={policy.error} retry={policy.reload} />{policy.loading && <Loading>Loading policy…</Loading>}
    {policy.data && <><p className="tag">Stored version {policy.data.version}{policy.data.effective ? ` · Effective: ${policy.data.effective.source} v${policy.data.effective.version}` : ''}</p>
      {!policy.data.policy && <p className="muted">No saved override. {policy.data.effective?.rules ? 'Showing inherited rules.' : 'The form is an explicit policy draft, not a claim about implicit engine defaults. Save to apply it.'}</p>}
      <PolicyForm key={`${url}-${policy.data.version}`} url={url} initial={policy.data.policy ?? policy.data.effective?.rules ?? explicitPolicy} editable={editable} reload={() => { policy.reload(); onChange?.(); }} />
    </>}
  </section>;
}
