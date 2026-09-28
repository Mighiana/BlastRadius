import { useState, type ChangeEvent, type FormEvent } from 'react';
import { FileUp, Play, X } from 'lucide-react';
import { z } from 'zod';
import { demoFilesSchema, jobSchema, request, type AnalysisInput, type Job } from '../api';
import { ErrorNotice } from './UI';

export function validateFiles(files: Record<string, string>) {
  const entries = Object.entries(files);
  if (!entries.length) throw new Error('Select at least one Terraform file for each snapshot.');
  if (entries.length > 30) throw new Error('Each snapshot supports up to 30 Terraform files.');
  for (const [name, text] of entries) {
    if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\.tf$/.test(name) || name.includes('..')) {
      throw new Error('Use simple ASCII .tf filenames without directories or consecutive dots.');
    }
    if (text.includes('\0')) throw new Error('Terraform files must not contain NUL bytes.');
  }
}
const planShape = z.object({
  planned_values: z.record(z.string(), z.unknown()).optional(),
  resource_changes: z.array(z.object({
    address: z.string().min(1),
    change: z.object({ actions: z.array(z.string()) }).passthrough(),
  }).passthrough()).optional(),
}).passthrough();
export function validatePlan(text: string): Record<string, unknown> {
  let parsed: unknown;
  try { parsed = JSON.parse(text); } catch { throw new Error('The plan is not valid JSON. Upload output from terraform show -json.'); }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)
    || (!('planned_values' in parsed) && !('resource_changes' in parsed))) {
    throw new Error('Provide a Terraform show -json plan containing planned_values or resource_changes.');
  }
  if (!planShape.safeParse(parsed).success) throw new Error('Invalid Terraform plan structure. Use unmodified terraform show -json output.');
  return parsed as Record<string, unknown>;
}
function FileEditor({ title, files, setFiles, disabled }: {
  title: string; files: Record<string, string>; setFiles: (files: Record<string, string>) => void; disabled: boolean;
}) {
  const [selected, setSelected] = useState('');
  const [error, setError] = useState<Error | null>(null);
  const [reading, setReading] = useState(false);
  const names = Object.keys(files);
  const current = names.includes(selected) ? selected : names[0];
  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const list = Array.from(event.target.files ?? []);
    event.target.value = '';
    if (!list.length) return;
    setError(null); setReading(true);
    try {
      if (list.length > 30 || list.reduce((total, file) => total + file.size, 0) > 1_048_576) throw new Error('Choose up to 30 files totaling less than 1 MiB.');
      if (new Set(list.map(file => file.name)).size !== list.length) throw new Error('Duplicate filenames are not supported.');
      const uploaded = Object.fromEntries(await Promise.all(list.map(async file => [file.name, await file.text()] as const)));
      validateFiles(uploaded);
      setFiles(uploaded); setSelected(list[0]?.name ?? '');
    } catch (err) { setError(err instanceof Error ? err : new Error('Could not read the selected files.')); }
    finally { setReading(false); }
  }
  return <fieldset className="file-editor" disabled={disabled || reading}><legend>{title}</legend>
    <label className="upload"><FileUp size={20} aria-hidden="true" /><span>{reading ? 'Reading files…' : 'Choose .tf files'}<small>Replaces this snapshot · up to 30 files</small></span>
      <input aria-label={`${title} Terraform files`} type="file" multiple accept=".tf" onChange={event => { void upload(event); }} /></label>
    {current && <><div className="file-toolbar"><label>{title} file<select value={current} onChange={e => setSelected(e.target.value)}>{names.map(name => <option key={name}>{name}</option>)}</select></label>
      <button type="button" className="icon-button" aria-label={`Remove ${current} from ${title}`} onClick={() => { const next = { ...files }; delete next[current]; setFiles(next); }}><X size={16} aria-hidden="true" /></button></div>
      <label className="sr-only" htmlFor={`${title}-source`}>{title} HCL</label><textarea id={`${title}-source`} spellCheck={false} value={files[current]} onChange={e => setFiles({ ...files, [current]: e.target.value })} rows={9} />
    </>}
    {!current && <button className="text-button" type="button" onClick={() => setFiles({ 'main.tf': '' })}>Or paste HCL into a new main.tf</button>}
    <ErrorNotice error={error} />
  </fieldset>;
}
export function AnalysisForm({ projectId, onSubmitted }: { projectId: string; onSubmitted: (job: Job) => void }) {
  const [mode, setMode] = useState<'hcl' | 'plan'>('hcl');
  const [before, setBefore] = useState<Record<string, string>>({});
  const [after, setAfter] = useState<Record<string, string>>({});
  const [plan, setPlan] = useState('');
  const [baseLabel, setBaseLabel] = useState('baseline');
  const [candidateLabel, setCandidateLabel] = useState('candidate');
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState(false);
  async function uploadPlan(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setError(null); setReading(true);
    try {
      if (file.size > 1_048_576) throw new Error('The plan must be smaller than 1 MiB.');
      const text = await file.text(); validatePlan(text); setPlan(text);
    } catch (err) { setError(err instanceof Error ? err : new Error('Could not read this plan.')); }
    finally { setReading(false); }
  }
  async function loadExample() {
    setError(null); setReading(true);
    try {
      const example = await request('/api/demo/public_ssh/files', demoFilesSchema);
      setBefore(example.before_files);
      setAfter(example.after_files);
      setBaseLabel('example-baseline');
      setCandidateLabel('example-public-ssh');
      setMode('hcl');
    } catch (err) { setError(err instanceof Error ? err : new Error('Could not load the example.')); }
    finally { setReading(false); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); setError(null); setBusy(true);
    try {
      const labels = { project_id: projectId, base_label: baseLabel.trim(), candidate_label: candidateLabel.trim() };
      let payload: AnalysisInput;
      if (mode === 'hcl') { validateFiles(before); validateFiles(after); payload = { ...labels, before_files: before, after_files: after }; }
      else payload = { ...labels, plan: validatePlan(plan) };
      const body = JSON.stringify(payload);
      if (new TextEncoder().encode(body).length > 1_048_576) throw new Error('The full request exceeds 1 MiB. Use a smaller Terraform scope.');
      const job = await request('/api/analyses', jobSchema, { method: 'POST', body });
      onSubmitted(job);
    } catch (err) { setError(err instanceof Error ? err : new Error('Submission failed.')); }
    finally { setBusy(false); }
  }
  return <form className="panel analysis-form" onSubmit={event => { void submit(event); }}>
    <div className="panel-heading"><div><p className="eyebrow">NEW COMPARISON</p><h2>What are you changing?</h2></div>
      <div className="segmented" role="group" aria-label="Input format">
        <button type="button" disabled={busy} aria-pressed={mode === 'hcl'} onClick={() => { setMode('hcl'); setError(null); }}>HCL files</button>
        <button type="button" disabled={busy} aria-pressed={mode === 'plan'} onClick={() => { setMode('plan'); setError(null); }}>Plan JSON</button>
      </div></div>
    <p className="muted">Source text is analyzed as data. No repository code, Terraform providers or commands are executed. Do not upload secrets.</p>
    <p className="muted">New here? Load the example to see a real BLOCK result, or bring your own baseline and candidate .tf files. No AWS credentials or GitHub connection are required. <button className="text-button" type="button" disabled={busy || reading} onClick={() => { void loadExample(); }}>{reading ? 'Loading example…' : 'Load the example (public SSH change)'}</button></p>
    <p className="muted">Baseline is your current or reference configuration. Candidate is the proposed change. A baseline may already contain exposure.</p>
    <fieldset disabled={busy || reading} className="form-fields">
      <div className="form-grid"><label>Baseline label<input required maxLength={120} value={baseLabel} onChange={e => setBaseLabel(e.target.value)} /></label><label>Candidate label<input required maxLength={120} value={candidateLabel} onChange={e => setCandidateLabel(e.target.value)} /></label></div>
      {mode === 'hcl' ? <div className="form-grid"><FileEditor title="Baseline" files={before} setFiles={setBefore} disabled={busy} /><FileEditor title="Candidate" files={after} setFiles={setAfter} disabled={busy} /></div>
        : <div className="plan-editor"><label className="upload"><FileUp size={20} aria-hidden="true" /><span>Choose Terraform plan JSON<input aria-label="Terraform plan file" type="file" accept=".json" onChange={event => { void uploadPlan(event); }} /></span></label>
          <label htmlFor="terraform-plan">Plan JSON</label><textarea id="terraform-plan" rows={12} spellCheck={false} value={plan} onChange={e => setPlan(e.target.value)} placeholder="Paste terraform show -json output" />
          <p className="muted">The plan contains both prior and proposed state. Source patch generation is unavailable for plan input.</p></div>}
    </fieldset>
    <ErrorNotice error={error} />
    <div className="submit-row"><span className="muted">1 MiB request · 300 resources per snapshot</span><button className="button primary" disabled={busy || reading} type="submit"><Play size={16} aria-hidden="true" />{busy ? 'Submitting…' : 'Analyze change'}</button></div>
  </form>;
}
