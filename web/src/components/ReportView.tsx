import { useState } from 'react';
import { ArrowRight, Download, GitBranch, ShieldAlert, ShieldCheck, ShieldQuestion } from 'lucide-react';
import { download, exportReport, type Report } from '../api';
import { Decision, ErrorNotice } from './UI';
import { Graph } from './Graph';

export function ReportView({ report, jobId }: { report: Report; jobId?: string }) {
  const [side, setSide] = useState<'before' | 'after'>('after');
  const [error, setError] = useState<Error | null>(null);
  const [exporting, setExporting] = useState(false);
  const sarifAvailable = !!report.reports.sarif;
  if (report.analysis_complete === false && report.decision === 'SAFE TO MERGE') {
    return <ErrorNotice error={new Error('The analysis result is inconsistent. Submit a new analysis.')} />;
  }
  async function exportAs(format: 'json' | 'markdown' | 'sarif') {
    if (format === 'sarif' && !sarifAvailable) return;
    setError(null); setExporting(true);
    try {
      if (jobId) await exportReport(jobId, format);
      else download(format === 'markdown' ? report.reports.markdown : JSON.stringify(format === 'sarif' ? report.reports.sarif : report, null, 2),
        `blastradius-demo.${format === 'markdown' ? 'md' : format}`, format === 'markdown' ? 'text/markdown' : 'application/json');
    } catch (err) { setError(err instanceof Error ? err : new Error('Export failed.')); }
    finally { setExporting(false); }
  }
  return <div className="report-stack">
    <section className={`verdict-panel ${report.decision === 'BLOCK CHANGE' ? 'blocked' : ''}`} aria-label="Analysis decision">
      <div><Decision decision={report.decision} /><h2>{report.headline}</h2>
        <p>{report.decision === 'BLOCK CHANGE' ? 'Review the new exposure, supporting evidence and remediation before merging.' : report.decision === 'SAFE TO MERGE' ? 'No new modeled blocking findings detected. No new modeled critical paths does not prove safety. Review evidence and coverage before merging.' : 'Review nonblocking findings and coverage before merging. This decision does not prove safety.'}</p></div>
      <div className="verdict-mark">{report.decision === 'BLOCK CHANGE' ? <ShieldAlert size={40} aria-hidden="true" /> : report.decision === 'SAFE TO MERGE' ? <ShieldCheck size={40} aria-hidden="true" /> : <ShieldQuestion size={40} aria-hidden="true" />}</div>
    </section>
    {report.analysis_complete === false && <div role="alert" className="notice error">Analysis incomplete. Counts are lower bounds within the modeled coverage. Resolve the coverage diagnostics before treating this change as safe.</div>}
    <div className="metrics">
      <div className="metric score"><span>Security score</span><div><span>{report.score.before}</span><ArrowRight size={20} aria-hidden="true" /><strong>{report.score.after}<small>/100</small></strong></div>
        <small><span className={report.score.delta < 0 ? 'danger-text' : ''}>{report.score.delta > 0 ? '+' : ''}{report.score.delta} points</span> · Heuristic · not a risk probability</small></div>
      <div className="metric"><span>New critical paths</span><strong className={report.new_critical_paths.length ? 'danger-text' : ''}>{report.new_critical_paths.length}</strong><small>{report.new_attack_paths.length} total new paths · {report.removed_critical_paths.length} critical removed</small></div>
      <div className="metric"><span>New sensitive reachability</span><strong className={report.newly_reachable_sensitive.length ? 'danger-text' : ''}>{report.newly_reachable_sensitive.length}</strong><small>Newly reachable sensitive resources</small></div>
      <div className="metric"><span>New exposed resources</span><strong>{report.newly_exposed.length}</strong><small>{report.before.risk_level} → {report.after.risk_level}</small></div>
    </div>
    <section className="panel change-summary" aria-label="Responsible change">
      <div><p className="eyebrow">WHAT CAUSED IT?</p><h2><GitBranch size={18} aria-hidden="true" />Responsible change</h2>
        <p>{report.demo?.stage === 'safe' ? 'Baseline configuration — no candidate change yet.' : report.responsible_change || 'Review the modeled changes and relationship evidence below.'}</p></div>
      <nav className="button-row" aria-label="Report sections"><a className="button secondary" href="#remediation">Review remediation</a><a className="button secondary" href="#report-export">Export</a></nav>
    </section>
    <section className="panel graph-panel">
      <div className="panel-heading"><div><p className="eyebrow">FOLLOW THE CONNECTIONS</p><h2>One change. A different attack surface.</h2></div>
        <div className="segmented" role="group" aria-label="Graph snapshot">
          <button aria-pressed={side === 'before'} onClick={() => setSide('before')}>Before</button>
          <button aria-pressed={side === 'after'} onClick={() => setSide('after')}>After</button>
        </div>
      </div>
      <p className="snapshot-label">{side === 'before' ? 'Baseline' : 'Candidate'}: <code>{report[side].label}</code> · {report[side].risk_level}</p>
      <Graph key={`${side}-${report.demo?.stage ?? jobId}`} snapshot={report[side]} />
    </section>
    <div className="report-columns">
      <section className="panel"><p className="eyebrow">WHAT CHANGED?</p><div className="panel-heading"><h2>Source changes</h2></div>
        {report.responsible_changes.map(change => <details key={change.file}>
          <summary>{change.file}</summary><pre className="diff"><code>{change.diff}</code></pre>
        </details>)}
        {!report.responsible_changes.length && <p className="muted">No HCL source changes to display. For plan inputs, review modeled changes and relationship evidence.</p>}
      </section>
      <section className="panel"><h2>What became reachable</h2>
        <h3>Sensitive resources</h3>
        {report.newly_reachable_sensitive.length ? <ul className="resource-list">{report.newly_reachable_sensitive.map(id => <li key={id}><code>{id}</code></li>)}</ul> : <p className="muted">No newly reachable sensitive resources.</p>}
        <h3>Decision evidence</h3>
        <p className="muted">Why it matters: follow the modeled relationships and findings below. Reachability is evidence to review, not proof of successful exploitation.</p>
        <ul className="findings">{report.findings.map((finding, index) => <li key={index}><strong>{finding.label}</strong><p>{finding.detail}</p></li>)}</ul>
      </section>
    </div>
    <section className="panel" id="remediation"><p className="eyebrow">HOW CAN I FIX IT?</p><h2>Review the remediation</h2>
      <p className="muted">Proposed Terraform edits require review. Downloads do not change your infrastructure.</p>
      {report.demo?.remediation_kind === 'reviewed_fixture' && <div className="notice">{report.demo.note}</div>}
      {report.remediation.recommendations.map((item, i) => <details className="recommendation" key={`${item.resource}-${i}`}>
        <summary>{item.title}</summary><p>{item.detail}</p><code>{item.resource}</code>
        <div className="code-pair"><div><h3>Current</h3><pre><code>{item.current}</code></pre></div><div><h3>Recommended</h3><pre><code>{item.recommended}</code></pre></div></div>
      </details>)}
      {!report.remediation.recommendations.length && <p>No remediation recommendations for this snapshot.</p>}
      {report.remediation.can_autofix && <details><summary>Inspect supported patch</summary><pre><code>{report.remediation.diff}</code></pre>
        <button className="button secondary" onClick={() => download(report.remediation.diff, 'blastradius.patch', 'text/plain')}><Download size={16} aria-hidden="true" />Download patch</button>
        <p className="muted">Merge the patch into your candidate files and submit another analysis to verify the result.</p>
      </details>}
    </section>
    <section className="panel"><h2>Coverage & scoring</h2>
      <h3>Recommended next step</h3><p>{report.decision === 'BLOCK CHANGE' ? 'Review the responsible change and supporting paths, validate suggested edits, then upload the updated candidate for another comparison.' : 'Review existing exposure and coverage gaps with your team before deciding to merge. If you change the candidate, run a new comparison.'} Export evidence when you need a record for the review.</p>
      {report.limitations.map(text => <p key={text}>{text}</p>)}
      <details open={report.analysis_complete === false}><summary>Coverage diagnostics ({report.diagnostics.length})</summary><ul className="findings">{report.diagnostics.map((d, i) => <li key={i}><strong>{d.code}</strong><p>{d.message}</p>{d.phase && <p>{d.phase}: <code>{d.resource}</code>{d.attribute && ` · ${d.attribute}`}{d.source_file && ` · ${d.source_file}`}</p>}</li>)}</ul></details>
      <details><summary>How the heuristic score was calculated</summary><div className="code-pair">{(['before', 'after'] as const).map(key => <div key={key}><h3>{key === 'before' ? 'Before' : 'After'}: {report[key].score}/100</h3><ul className="findings">{report[key].score_breakdown.map(item => <li key={item.finding}>{item.finding}: {item.points} points ({item.count})</li>)}</ul>{!report[key].score_breakdown.length && <p>No score penalties in this model.</p>}</div>)}</div><p className="muted">Scores start at 100 and subtract capped findings. The score is not a calibrated measure of real-world risk.</p></details>
    </section>
    <section className="panel export-panel" id="report-export"><div><p className="eyebrow">TAKE THE EVIDENCE WITH YOU</p><h2>Export this analysis</h2></div>
      <div className="button-row">{(['json', 'markdown', 'sarif'] as const).map(format =>
        <button className="button secondary" key={format} disabled={exporting || (format === 'sarif' && !sarifAvailable)} aria-describedby={format === 'sarif' && !sarifAvailable ? 'sarif-restriction' : undefined} onClick={() => { void exportAs(format); }}><Download size={16} aria-hidden="true" />{format.toUpperCase()}</button>)}</div>
      {!sarifAvailable && <p className="notice" id="sarif-restriction">Saved SARIF exports require an operator-granted Pro, Team or Enterprise plan. JSON and Markdown are available on Free. Public demo SARIF remains available.</p>}
      <ErrorNotice error={error} />
    </section>
  </div>;
}
