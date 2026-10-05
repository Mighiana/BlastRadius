import { ArrowRight, CheckCircle2, CircleHelp, FileCode2, Network, ShieldCheck, TriangleAlert, UserCheck } from 'lucide-react';
import type { Report, Snapshot } from '../api';
import { Decision } from './UI';
import { NodeIcon } from './Graph';
import { coverageGapChips, type Diagnostic } from './diagnostics';

type Path = Report['new_attack_paths'][number];
export type DecisionKind = 'block' | 'safe' | 'review';
export type ChangePair = { file: string; before: string; after: string };

export function decisionKind(decision: string): DecisionKind {
  return decision === 'BLOCK CHANGE' ? 'block' : decision === 'SAFE TO MERGE' ? 'safe' : 'review';
}

/** Pairs removed and added lines of unified diffs; null when the diff is not a small one-to-one edit. */
export function changePairs(changes: Report['responsible_changes'], limit = 4): ChangePair[] | null {
  const pairs: ChangePair[] = [];
  for (const change of changes) {
    const removed: string[] = [];
    const added: string[] = [];
    for (const line of change.diff.split('\n')) {
      if (/^(---|\+\+\+) /.test(line)) continue;
      if (line.startsWith('-')) removed.push(line.slice(1).trim());
      else if (line.startsWith('+')) added.push(line.slice(1).trim());
    }
    if (removed.length !== added.length) return null;
    removed.forEach((before, index) => {
      const after = added[index] ?? '';
      if (before || after) pairs.push({ file: change.file, before, after });
    });
  }
  return pairs.length && pairs.length <= limit ? pairs : null;
}

const WORD = /[\w.\-/:*]/;
/** Splits two lines into a shared prefix, the differing token span of each, and a shared suffix. */
export function splitChange(before: string, after: string) {
  const max = Math.min(before.length, after.length);
  let prefix = 0;
  while (prefix < max && before[prefix] === after[prefix]) prefix++;
  while (prefix > 0 && WORD.test(before[prefix - 1]!)) prefix--;
  let suffix = 0;
  while (suffix < max - prefix && before[before.length - 1 - suffix] === after[after.length - 1 - suffix]) suffix++;
  while (suffix > 0 && WORD.test(before[before.length - suffix]!)) suffix--;
  return {
    prefix: before.slice(0, prefix), suffix: before.slice(before.length - suffix),
    before: before.slice(prefix, before.length - suffix), after: after.slice(prefix, after.length - suffix),
  };
}

export function primaryPath(report: Report): Path | undefined {
  return report.new_critical_paths.find(path => path.reaches_sensitive) ?? report.new_critical_paths[0] ?? report.new_attack_paths[0];
}
function removedPath(report: Report): Path | undefined {
  return report.removed_critical_paths.find(path => path.reaches_sensitive) ?? report.removed_critical_paths[0] ?? report.removed_attack_paths[0];
}
function signed(value: number) { return value > 0 ? `+${value}` : String(value); }
function percent(value: number) { return `${Math.max(0, Math.min(100, value))}%`; }

function ScoreChange({ score }: { score: Report['score'] }) {
  const tone = score.delta < 0 ? 'down' : score.delta > 0 ? 'up' : 'flat';
  return <div className={`score-change ${tone}`} role="group" aria-label={`Heuristic score ${score.before} to ${score.after}, change ${signed(score.delta)}`}>
    <div className="score-values" aria-hidden="true"><span>{score.before}</span><ArrowRight size={18} /><strong>{score.after}</strong><span className="score-delta">{signed(score.delta)}</span></div>
    <div className="score-bars" aria-hidden="true">
      <span><small>Before</small><i><b style={{ width: percent(score.before) }} /></i></span>
      <span className="after"><small>After</small><i><b style={{ width: percent(score.after) }} /></i></span>
    </div>
    <small>Heuristic score · not a risk probability</small>
  </div>;
}

function Metrics({ report, lowerBound }: { report: Report; lowerBound: boolean }) {
  const items: Array<[number, string, string]> = [
    [report.new_critical_paths.length, 'New critical paths', `${report.new_attack_paths.length} total new paths · ${report.removed_critical_paths.length} critical removed`],
    [report.newly_reachable_sensitive.length, 'New sensitive reachability', 'Newly reachable sensitive resources'],
    [report.newly_exposed.length, 'New exposed resources', `${report.before.risk_level} → ${report.after.risk_level}`],
  ];
  return <ul className="hero-metrics" aria-label="Change in the model">
    {items.map(([count, label, detail]) => <li key={label} className={count ? 'hit' : ''}>
      <strong>{lowerBound && <><span aria-hidden="true">≥</span><span className="sr-only">at least </span></>}{count}</strong>
      <span>{label}</span><small>{detail}</small>
    </li>)}
  </ul>;
}

function ChangeValues({ pairs }: { pairs: ChangePair[] }) {
  const shown = pairs.slice(0, 2);
  return <div className="change-values">
    {shown.map((pair, index) => {
      const parts = splitChange(pair.before, pair.after);
      return <p key={`${pair.file}-${index}`}>
        <del><span className="sr-only">Before: </span>{parts.before || pair.before}</del>
        <ArrowRight size={16} aria-hidden="true" />
        <ins><span className="sr-only">After: </span>{parts.after || pair.after}</ins>
      </p>;
    })}
    <small>{shown[0]?.file}{pairs.length > shown.length && ` · +${pairs.length - shown.length} more`}</small>
  </div>;
}

export function ChangeLines({ pairs }: { pairs: ChangePair[] }) {
  return <div className="change-lines">{pairs.map((pair, index) => {
    const parts = splitChange(pair.before, pair.after);
    return <div key={`${pair.file}-${index}`} className="change-line-pair">
      {(index === 0 || pairs[index - 1]?.file !== pair.file) && <small>{pair.file}</small>}
      <code className="line-before"><span className="line-tag">BEFORE</span><span>{parts.prefix}<mark>{parts.before}</mark>{parts.suffix}</span></code>
      <code className="line-after"><span className="line-tag">AFTER</span><span>{parts.prefix}<mark>{parts.after}</mark>{parts.suffix}</span></code>
    </div>;
  })}</div>;
}

function PathStrip({ path, snapshot, newEdges, label, removed = false }: { path: Path; snapshot: Snapshot; newEdges: Set<string>; label: string; removed?: boolean }) {
  const nodeById = new Map(snapshot.graph.nodes.map(node => [node.id, node]));
  return <ol className={`hero-path ${removed ? 'removed' : ''}`} aria-label={label}>
    {path.nodes.map((id, index) => {
      const node = nodeById.get(id);
      const entry = index === 0;
      const sensitive = node?.sensitive === true;
      const next = path.nodes[index + 1];
      const isNew = !removed && next !== undefined && newEdges.has(`${id}->${next}`);
      return <li key={`${id}-${index}`}>
        <div className={`hero-node ${entry ? 'entry' : ''} ${sensitive ? 'sensitive' : ''}`}>
          <NodeIcon type={node?.type ?? id} size={18} />
          <strong>{path.labels[index] ?? node?.name ?? id}</strong>
          {!entry && <code>{id}</code>}
          {entry && <span className="node-tag">Entry</span>}
          {sensitive && <span className="node-tag">Sensitive</span>}
        </div>
        {next !== undefined && <span className={`hero-link ${isNew ? 'new' : ''}`}>
          <ArrowRight size={16} aria-hidden="true" />{isNew && <small>NEW</small>}
        </span>}
      </li>;
    })}
  </ol>;
}

function CoverageFlow({ chips }: { chips: Array<[number, string]> }) {
  return <ol className="coverage-flow" aria-label="Analysis coverage">
    <li><FileCode2 size={18} aria-hidden="true" /><span>Terraform</span></li>
    <li><Network size={18} aria-hidden="true" /><span>Supported relationships modeled</span></li>
    <li className="gap"><CircleHelp size={18} aria-hidden="true" /><span>Unresolved or unsupported</span>
      {chips.length ? <ul>{chips.map(([count, label]) => <li key={label}>{`${count}× ${label}`}</li>)}</ul> : <ul><li>See coverage diagnostics</li></ul>}
    </li>
    <li className="human"><UserCheck size={18} aria-hidden="true" /><span>Human review required</span></li>
  </ol>;
}

const LEAD: Record<DecisionKind, [string, string]> = {
  block: ['The selected policy and model detected a blocking change.', 'Modeled attack path: evidence to review, not proof of exploitability.'],
  safe: ['No new modeled blocking findings detected.', 'This does not prove the infrastructure is secure. Existing exposure and coverage gaps may remain.'],
  review: ['Human review required.', 'Review nonblocking findings and coverage before merging. This decision does not prove safety.'],
};

export function ResultHero({ report, blockingGroups }: { report: Report; blockingGroups: Array<[string, Diagnostic[]]> }) {
  const kind = decisionKind(report.decision);
  const incomplete = report.analysis_complete === false;
  const baseline = report.demo?.stage === 'safe';
  const pairs = baseline ? null : changePairs(report.responsible_changes);
  const newEdges = new Set(report.new_edges.map(edge => `${edge.source}->${edge.target}`));
  const path = kind === 'safe' ? undefined : primaryPath(report);
  const removed = kind === 'safe' ? removedPath(report) : undefined;
  const chips = coverageGapChips(blockingGroups);
  const [lead, caveat] = kind === 'review' && incomplete
    ? ['Analysis coverage incomplete.', 'BlastRadius could not completely evaluate this change. Zero paths here does not mean safe.']
    : LEAD[kind];
  const existing = report.after.attack_paths.length;
  const morePaths = report.new_attack_paths.length - (path ? 1 : 0);
  return <section id="report-verdict" className={`result-hero ${kind}`} aria-label="Analysis decision">
    <div className="hero-top">
      <div className="hero-copy-block">
        <Decision decision={report.decision} />
        <h2>{report.headline}</h2>
        <p className="hero-lead">{lead}</p>
        <p className="hero-caveat">{caveat}</p>
      </div>
      <ScoreChange score={report.score} />
    </div>
    <Metrics report={report} lowerBound={incomplete} />
    {incomplete && <p role="alert" className="hero-lower-bound"><TriangleAlert size={16} aria-hidden="true" />Analysis incomplete. Counts are lower bounds within the modeled coverage. Resolve the coverage diagnostics before treating this change as safe.</p>}
    <div className="hero-story">
      {pairs && <>
        <div className="story-step change"><p className="step-label">What changed</p><ChangeValues pairs={pairs} /></div>
        <ArrowRight className="story-arrow" size={22} aria-hidden="true" />
      </>}
      {path && <div className="story-step opened">
        <p className="step-label">What that opened{morePaths > 0 && <span> · +{morePaths} more new {morePaths === 1 ? 'path' : 'paths'} in the graph</span>}</p>
        <PathStrip path={path} snapshot={report.after} newEdges={newEdges} label="Primary new path" />
      </div>}
      {kind === 'safe' && <div className="story-stack">
        <div className="story-step clear-step">
          <ShieldCheck size={26} aria-hidden="true" />
          <strong>No new modeled blocking path</strong>
          <small>{existing ? `${existing} existing modeled ${existing === 1 ? 'path remains' : 'paths remain'} in the candidate — inspect the graph.` : 'Existing exposure and coverage limitations may remain.'}</small>
        </div>
        {removed && <div className="story-step removed-step">
          <p className="step-label">Before · path removed</p>
          <PathStrip path={removed} snapshot={report.before} newEdges={newEdges} label="Removed path" removed />
          <p className="removed-note"><CheckCircle2 size={16} aria-hidden="true" />Path removed in the candidate</p>
        </div>}
      </div>}
      {kind !== 'safe' && incomplete && <div className="story-step coverage-step"><p className="step-label">Coverage</p><CoverageFlow chips={chips} /></div>}
      {kind === 'review' && !incomplete && !path && <div className="story-step coverage-step"><p className="step-label">Needs a human decision</p>
        <ul className="finding-chips">{report.findings.slice(0, 4).map((finding, index) => <li key={index}>{finding.label}</li>)}</ul>
        {!report.findings.length && <p className="muted">Review the evidence and coverage below.</p>}
      </div>}
    </div>
  </section>;
}
