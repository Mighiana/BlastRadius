import { ArrowRight, GitPullRequest, Terminal, Network, LockKeyhole, GitCompareArrows, FileCheck2, ChevronRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { reportSchema } from '../api';
import { useResource } from '../hooks';
import { Decision, ErrorNotice, Loading } from '../components/UI';
import { Graph } from '../components/Graph';

export default function Landing() {
  const preview = useResource('/api/demo/public_ssh?stage=risky', reportSchema);
  return <>
    <section className="hero container">
      <div className="hero-copy"><div className="hero-kicker"><span className="dot" /> SECURITY IN THE PULL REQUEST</div>
        <h1>Your Terraform diff shows what changed.<br /><span>BlastRadius shows what became reachable.</span></h1>
        <p>See the path from a one-line infrastructure change to your sensitive data. Catch new exposure before it reaches production.</p>
        <div className="button-row"><Link className="button primary large" to="/demo">Explore the live demo<ArrowRight size={18} aria-hidden="true" /></Link><Link className="button secondary large" to="/guide"><GitPullRequest size={18} aria-hidden="true" />Add to your workflow</Link></div>
        <div className="hero-assurances"><span>No AWS credentials</span><span>No infrastructure changes</span><span>Open source</span></div>
      </div>
      <div className="product-preview">
        <div className="preview-top"><span className="preview-brand"><GitCompareArrows size={16} aria-hidden="true" /> Infrastructure change review</span><span className="tag">LIVE ENGINE RESULT</span></div>
        <div className="preview-body">
          <div className="preview-title"><div><span className="eyebrow">DEMO / PUBLIC SSH EXPOSURE</span><h2>One line opens the entire path.</h2></div>{preview.data && <Decision decision={preview.data.decision} />}</div>
          <div className="code-change"><code><span className="line-number">28</span><span className="minus">− cidr_blocks = ["10.0.0.0/24"]</span></code><code><span className="line-number">28</span><span className="plus">+ cidr_blocks = ["0.0.0.0/0"]</span></code></div>
          {preview.loading && <Loading>Loading a real engine comparison…</Loading>}
          <ErrorNotice error={preview.error} retry={preview.reload} />
          {preview.data && <><Graph snapshot={preview.data.after} compact />
            <div className="preview-metrics"><div><strong>{preview.data.new_critical_paths.length}</strong><span>new critical path</span></div><div><strong>{preview.data.newly_reachable_sensitive.length}</strong><span>sensitive resource reached</span></div><div><strong>{preview.data.score.before} <ArrowRight size={18} aria-hidden="true" /> {preview.data.score.after}</strong><span>heuristic security score / 100</span></div>
              <Link to="/demo">Inspect the evidence<ChevronRight size={17} aria-hidden="true" /></Link></div>
          </>}
        </div>
      </div>
      <p className="hero-caption">A modeled attack path is evidence to review, not proof of exploitability.</p>
    </section>
    <section className="value-strip"><div className="container"><span>BUILT FOR THE WAY YOU SHIP</span><strong><Terminal size={19} aria-hidden="true" />Terraform</strong><strong><GitPullRequest size={19} aria-hidden="true" />GitHub Actions</strong><strong><Network size={19} aria-hidden="true" />AWS infrastructure</strong><strong><FileCheck2 size={19} aria-hidden="true" />SARIF reports</strong></div></section>
    <section className="container section" id="how-it-works"><div className="section-intro"><p className="eyebrow">FROM DIFF TO DECISION</p><h2>Understand the change.<br />Follow the consequences.</h2><p>A port, a role, and a bucket can look harmless in isolation. See what they connect when a pull request brings them together.</p></div>
      <div className="feature-grid">{[
        { n: '01', icon: GitCompareArrows, title: 'Compare your infrastructure', text: 'Start with baseline and candidate Terraform files, a plan JSON, or a GitHub pull request in your own CI.' },
        { n: '02', icon: Network, title: 'Trace what became reachable', text: 'Compare directed attack graphs. Follow public entry points, compute identities, permissions and sensitive storage.' },
        { n: '03', icon: FileCheck2, title: 'Make an informed merge decision', text: 'Get BLOCK, REVIEW or SAFE with the responsible change, per-hop evidence and specific remediation guidance.' },
      ].map(item => <article className="feature-card" key={item.n}><span className="feature-number">{item.n}</span><item.icon size={26} aria-hidden="true" /><h3>{item.title}</h3><p>{item.text}</p></article>)}</div>
    </section>
    <section className="container section"><div className="section-intro"><p className="eyebrow">SMALL CHANGES. CONNECTED CONSEQUENCES.</p><h2>Review the path, not just the finding.</h2></div>
      <div className="use-cases"><article><span className="tag">NETWORK</span><h3>An open port is only the beginning.</h3><p>Understand which instance, role and sensitive bucket sit behind an ingress change.</p></article><article><span className="tag">IDENTITY</span><h3>Permissions change the destination.</h3><p>See how a broader IAM grant connects an exposed workload to additional data.</p></article><article><span className="tag">STORAGE</span><h3>Public access changes the boundary.</h3><p>Catch direct public exposure of storage marked sensitive in Terraform.</p></article></div>
    </section>
    <section className="container section workflow-section"><div><p className="eyebrow">WHERE REVIEW ALREADY HAPPENS</p><h2>Your pull request.<br />With the missing context.</h2><p>Run the CLI locally or use GitHub Actions for a security check and one updated PR comment. JSON, Markdown and SARIF exports keep the evidence portable.</p><Link to="/guide" className="text-link">Read the quick start<ArrowRight size={17} aria-hidden="true" /></Link></div>
      <div className="terminal"><div className="terminal-title"><Terminal size={16} aria-hidden="true" />LOCAL CLI</div><pre><code>{'python -m blastradius.cli \\\n  --before examples/safe \\\n  --after examples/vulnerable \\\n  --format pr'}</code></pre><p><span className="danger-text">BLOCK CHANGE</span> · exit 1</p><small>Uses the same Python analysis engine as this demo.</small></div>
    </section>
    <section className="container section faq-section"><div className="section-intro"><LockKeyhole size={24} aria-hidden="true" /><p className="eyebrow">CLEAR BOUNDARIES</p><h2>Security decisions deserve honest answers.</h2></div>
      <div className="faq">{[
        ['Does SAFE mean my infrastructure is secure?', 'No. It means no new modeled critical attack paths were detected under the selected model and policy. Existing exposure may remain. Unsupported resources, policy conditions and Terraform constructs can limit coverage. Read diagnostics before relying on a result.'],
        ['Do you need my AWS credentials?', 'No. BlastRadius analyzes Terraform text and plan JSON. It does not call AWS, execute Terraform providers, deploy resources or verify exploitability.'],
        ['What happens to uploaded data?', 'Public demos use fixed fixtures and persist no analysis. Workspace reports are stored by the backend and may contain source diffs or patches. Avoid uploading secrets. Deleting an analysis removes its stored report; backup retention is the operator’s responsibility. Use the CLI when data must stay local.'],
        ['Does BlastRadius deploy infrastructure?', 'No. It reads supported infrastructure inputs and returns evidence and suggested patches for human review. It never applies Terraform or changes your AWS infrastructure.'],
        ['Can I connect a GitHub repository here?', 'The GitHub App requires configured provider credentials and an operator-verified installation mapped to your workspace. Owners and admins can connect verified repositories. The integration page shows actual status; installation alone does not establish a connection. GitHub Actions is also available.'],
        ['What counts as an analysis?', 'Each job accepted for processing counts toward the monthly UTC quota, even if it later fails. Rejected requests and public demos do not count. Deleting a report does not refund usage.'],
        ['Can I pay for a subscription?', 'Payments are disabled during the commercial beta. Free is available through configured sign-in. Pro, Team and Enterprise have proposed pricing and require an operator grant. There is no self-service upgrade or checkout.'],
      ].map(([question, answer]) => <details key={question}><summary>{question}</summary><p>{answer}</p></details>)}</div>
    </section>
    <section className="container section"><div className="final-cta"><p className="eyebrow">KNOW BEFORE YOU MERGE</p><h2>See what one line can open.</h2><p>Three real scenarios. Every connection explained.</p><Link className="button primary large" to="/demo">Explore the live demo<ArrowRight size={18} aria-hidden="true" /></Link></div></section>
  </>;
}
