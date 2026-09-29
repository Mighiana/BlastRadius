import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Check, Copy, ExternalLink, GitPullRequest, Terminal, UploadCloud } from 'lucide-react';
import { PageHeading } from '../components/UI';

const repository = 'https://github.com/Mighiana/BlastRadius';
const installCommand = 'python -m venv .venv\nsource .venv/bin/activate\npython -m pip install .';
const compareCommand = 'python -m blastradius.cli \\\n  --before examples/safe \\\n  --after examples/vulnerable \\\n  --format pr';
const planCommand = 'terraform show -json your-plan.tfplan > plan.json\npython -m blastradius.cli --plan plan.json --format sarif';

export function CodeBlock({ code, label }: { code: string; label: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setState('copied');
    } catch {
      setState('failed');
    }
    window.setTimeout(() => setState('idle'), 1800);
  };
  return <div className="code-block">
    <pre><code>{code}</code></pre>
    <button type="button" className="copy-button" onClick={copy} aria-label={`Copy ${label}`}>
      {state === 'copied' ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}
      {state === 'copied' ? 'Copied' : state === 'failed' ? 'Select & copy' : 'Copy'}
    </button>
  </div>;
}

export default function Guide() {
  return <div className="container page guide"><PageHeading eyebrow="QUICK START" title="Three ways to run it.">Pick one. Each gives the same decision on the same Terraform change.</PageHeading>
    <div className="guide-grid"><aside className="panel guide-nav"><span className="guide-nav-label">Ways to run</span><a href="#cli">Local CLI</a><a href="#github">Pull request check</a><a href="#workspace">Workspace upload</a><span className="guide-nav-label">Reference</span><a href="#model">What the model covers</a><a href="#privacy">Data handling</a></aside><div className="report-stack">
      <section className="panel" id="cli"><span className="eyebrow guide-kind"><Terminal size={14} aria-hidden="true" />LOCAL CLI · SOURCE STAYS ON YOUR MACHINE</span><h2>Local CLI</h2>
        <p className="muted">Python 3.11+ and Git, from a reviewed checkout of this repository.</p>
        <CodeBlock code={installCommand} label="install commands" />
        <p>Compare two Terraform directories:</p>
        <CodeBlock code={compareCommand} label="compare command" />
        <p>Or analyze a plan generated in your trusted environment:</p>
        <CodeBlock code={planCommand} label="plan command" />
        <table className="exit-codes" aria-label="CLI exit codes"><thead><tr><th>Exit code</th><th>Meaning</th></tr></thead><tbody>
          <tr><td><code>0</code></td><td><span className="decision safe">NO NEW PATHS</span> or REVIEW — passes the gate</td></tr>
          <tr><td><code>1</code></td><td><span className="decision block">BLOCK CHANGE</span> — new path to sensitive data</td></tr>
          <tr><td><code>2</code></td><td>Invalid input or usage</td></tr>
        </tbody></table>
        <p className="muted">Add <code>--fail-on-review</code> to make REVIEW exit 1 too.</p></section>
      <section className="panel" id="github"><span className="eyebrow guide-kind"><GitPullRequest size={14} aria-hidden="true" />PULL REQUEST CHECK · GITHUB ACTIONS</span><h2>Pull request check</h2>
        <p>The reviewed Actions workflow installs a pinned analyzer, compares base and head, posts one bot comment and a check.</p>
        <ul className="guide-points"><li>Copy the consumer workflow into your repository.</li><li>Point it at your Terraform root from trusted base configuration.</li><li>Use the <code>pull_request</code> event with minimal permissions; candidate providers and scripts never run.</li><li>Require the check before merging.</li></ul>
        <div className="button-row"><a className="button primary" href={`${repository}#github-actions`} target="_blank" rel="noreferrer">Actions workflow<ExternalLink size={16} aria-hidden="true" /></a><Link className="button secondary" to="/integrations">GitHub App (operator-enabled)</Link></div>
        <p className="muted">The GitHub App additionally stores PR analyses in a workspace. It needs operator-configured credentials and a verified installation before a repository can be connected.</p></section>
      <section className="panel" id="workspace"><span className="eyebrow guide-kind"><UploadCloud size={14} aria-hidden="true" />WORKSPACE UPLOAD · STORED EVIDENCE</span><h2>Workspace upload</h2>
        <ul className="guide-points"><li>Sign in and create a project.</li><li>Upload baseline and candidate <code>.tf</code> files, or one <code>terraform show -json</code> plan.</li><li>Open the report: decision, path, evidence, remediation.</li><li>Fix, re-upload, export JSON / Markdown / SARIF.</li></ul>
        <Link to="/dashboard" className="button primary">Open workspace<ArrowRight size={16} aria-hidden="true" /></Link>
        <p className="muted">No repository connection required. Uploads are read as data; nothing is executed.</p></section>
      <section className="panel" id="model"><span className="eyebrow">REFERENCE</span><h2>What the model covers</h2>
        <p>A static graph from supported Terraform relationships: public ingress → compute → assumed roles → storage tagged sensitive.</p>
        <ul className="guide-points"><li>Coverage is bounded: modules, unresolved values and IAM conditions can lower accuracy. Every report lists its coverage gaps.</li><li>The decision judges the <em>change</em>. NO NEW PATHS can coexist with exposure that already existed.</li><li>The 0–100 score is a capped heuristic for comparison, not a probability of compromise.</li></ul>
        <Link to="/demo" className="text-link">Inspect a real example<ArrowRight size={16} aria-hidden="true" /></Link></section>
      <section className="panel" id="privacy"><span className="eyebrow">REFERENCE</span><h2>Data handling</h2>
        <ul className="guide-points"><li>Public demos use fixed fixtures.</li><li>Workspace uploads are processed by your configured backend; reports can retain source diffs and patched Terraform. Keep secrets out of uploads.</li><li>Credentials live in backend-managed HttpOnly cookies, never in browser storage.</li><li>Deleting a history entry removes the stored analysis; it does not refund quota or erase backups. Evidence expires per plan: Free 7 days, Pro 90, Team 365, Enterprise configurable.</li></ul>
        <div className="link-row"><Link to="/security" className="text-link">Security and limitations<ArrowRight size={16} aria-hidden="true" /></Link><Link to="/privacy" className="text-link">Privacy and retention<ArrowRight size={16} aria-hidden="true" /></Link></div></section>
    </div></div>
  </div>;
}
