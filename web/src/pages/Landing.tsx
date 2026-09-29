import { ArrowRight, GitPullRequest, Terminal, Network, LockKeyhole, GitCompareArrows, FileCheck2, ChevronRight, Globe, Shield, Cpu, KeyRound, Database, Ban, CheckCircle2, AlertCircle, Lock, Check } from 'lucide-react';
import { Link } from 'react-router-dom';

const HOPS = [
  { icon: Globe, name: 'Internet', text: 'Anyone, anywhere' },
  { icon: Shield, name: 'Web SG', text: 'Now allows SSH from 0.0.0.0/0' },
  { icon: Cpu, name: 'EC2 instance', text: 'Becomes reachable' },
  { icon: KeyRound, name: 'IAM role', text: 'Grants s3:GetObject' },
  { icon: Database, name: 'Customer data', text: 'Sensitive bucket exposed', sensitive: true },
];

export default function Landing() {
  return <>
    <section className="hero container">
      <div className="hero-copy"><div className="hero-kicker"><span className="dot" /> TERRAFORM SECURITY ANALYSIS · IN THE PULL REQUEST</div>
        <h1>See what your <span>Terraform change</span> makes reachable.</h1>
        <p>Your Terraform diff shows what changed. BlastRadius shows what became reachable, and blocks the merge when a new path leads to sensitive data.</p>
        <div className="button-row"><Link className="button primary large" to="/demo">Try the live demo<ArrowRight size={18} aria-hidden="true" /></Link><Link className="button secondary large" to="/guide"><GitPullRequest size={18} aria-hidden="true" />Add to GitHub</Link></div>
        <ul className="hero-assurances"><li><Check size={14} aria-hidden="true" />No cloud credentials</li><li><Check size={14} aria-hidden="true" />Nothing is executed or deployed</li><li><Check size={14} aria-hidden="true" />Works in GitHub Actions and the CLI</li></ul>
      </div>
      <figure className="product-preview story" aria-label="Example: a one-line Terraform change opens a path from the internet to customer data">
        <div className="preview-top"><span className="preview-brand"><GitCompareArrows size={16} aria-hidden="true" /> main.tf · pull request #42</span><span className="tag">BUNDLED DEMO</span></div>
        <div className="preview-body">
          <div className="code-change"><code><span className="line-number">19</span><span>  resource "aws_security_group" "web" {'{'}</span></code><code><span className="line-number">25</span><span className="muted">    from_port   = 22</span></code><code><span className="line-number">28</span><span className="minus">−   cidr_blocks = ["10.0.0.0/24"]</span></code><code><span className="line-number">28</span><span className="plus">+   cidr_blocks = ["0.0.0.0/0"]</span></code></div>
          <div className="story-compare">
            <div className="story-state safe"><span><CheckCircle2 size={16} aria-hidden="true" />Before</span><strong><Lock size={15} aria-hidden="true" />SSH from 10.0.0.0/24</strong><small>Private network only</small></div>
            <ArrowRight className="story-arrow" size={20} aria-hidden="true" />
            <div className="story-state risky"><span><AlertCircle size={16} aria-hidden="true" />After</span><strong><Globe size={15} aria-hidden="true" />SSH from 0.0.0.0/0</strong><small>Open to the entire internet</small></div>
          </div>
          <p className="story-label">New attack path introduced</p>
          <ol className="story-path">{HOPS.map(hop => <li key={hop.name} className={hop.sensitive ? 'sensitive' : undefined}><span className="story-node"><hop.icon size={22} aria-hidden="true" /></span><strong>{hop.name}</strong><small>{hop.text}</small></li>)}</ol>
          <div className="story-verdict"><strong><Ban size={20} aria-hidden="true" />BLOCK CHANGE</strong><span>A new path to sensitive data was introduced.</span></div>
          <div className="story-footer"><span>Responsible change: <code>10.0.0.0/24 → 0.0.0.0/0</code></span><Link to="/demo">See the real engine result<ChevronRight size={17} aria-hidden="true" /></Link></div>
        </div>
      </figure>
      <p className="hero-caption">A modeled attack path is evidence to review, not proof of exploitability.</p>
    </section>
    <section className="container section steps-section" id="how-it-works">
      <div className="how-steps">{[
        { n: '1', icon: GitCompareArrows, title: 'Compare', text: 'Baseline and candidate Terraform, a plan JSON, or the pull request itself.' },
        { n: '2', icon: Network, title: 'Trace', text: 'Follow new reachability from public entry points to sensitive resources.' },
        { n: '3', icon: FileCheck2, title: 'Decide', text: 'BLOCK, REVIEW or SAFE, with the responsible line and per-hop evidence.' },
      ].map(step => <article className="step-card" key={step.n}><span className="step-number">{step.n}</span><span className="step-icon"><step.icon size={24} aria-hidden="true" /></span><div><h2>{step.title}</h2><p>{step.text}</p></div></article>)}</div>
    </section>
    <section className="value-strip"><div className="container"><span>BUILT FOR THE WAY YOU SHIP</span><strong><Terminal size={19} aria-hidden="true" />Terraform</strong><strong><GitPullRequest size={19} aria-hidden="true" />GitHub Actions</strong><strong><Network size={19} aria-hidden="true" />AWS infrastructure</strong><strong><FileCheck2 size={19} aria-hidden="true" />SARIF reports</strong></div></section>
    <section className="container section why-section"><div className="section-intro"><p className="eyebrow">WHY NOT JUST READ THE DIFF?</p><h2>The diff says what changed.<br />It never says what that connects.</h2></div>
      <div className="why-grid">
        <article><span className="eyebrow">TERRAFORM DIFF</span><div className="code-change"><code><span className="line-number">28</span><span className="minus">− cidr_blocks = ["10.0.0.0/24"]</span></code><code><span className="line-number">28</span><span className="plus">+ cidr_blocks = ["0.0.0.0/0"]</span></code></div><p><strong>What changed?</strong> One CIDR.</p></article>
        <article className="why-answer"><span className="eyebrow">BLASTRADIUS</span><p className="why-path">Internet <ArrowRight size={14} aria-hidden="true" /> Web SG <ArrowRight size={14} aria-hidden="true" /> EC2 <ArrowRight size={14} aria-hidden="true" /> IAM role <ArrowRight size={14} aria-hidden="true" /> Customer data</p><p><strong>What became reachable?</strong> A sensitive S3 bucket, from anywhere on the internet, through an instance role that never appeared in the diff.</p></article>
      </div>
    </section>
    <section className="container section"><div className="section-intro"><p className="eyebrow">SMALL CHANGES. CONNECTED CONSEQUENCES.</p><h2>Review the path, not just the finding.</h2></div>
      <div className="use-cases"><article><span className="tag">NETWORK</span><h3>An open port is only the beginning.</h3><p>Understand which instance, role and sensitive bucket sit behind an ingress change.</p></article><article><span className="tag">IDENTITY</span><h3>Permissions change the destination.</h3><p>See how a broader IAM grant connects an exposed workload to additional data.</p></article><article><span className="tag">STORAGE</span><h3>Public access changes the boundary.</h3><p>Catch direct public exposure of storage marked sensitive in Terraform.</p></article></div>
    </section>
    <section className="container section workflow-section"><div><p className="eyebrow">WHERE REVIEW ALREADY HAPPENS</p><h2>Your pull request.<br />With the missing context.</h2><p>Run the CLI locally or use GitHub Actions for a security check and one updated PR comment. JSON, Markdown and SARIF exports keep the evidence portable.</p><Link to="/guide" className="text-link">Read the quick start<ArrowRight size={17} aria-hidden="true" /></Link></div>
      <div className="terminal"><div className="terminal-title"><Terminal size={16} aria-hidden="true" />LOCAL CLI</div><pre><code>{'python -m blastradius.cli \\\n  --before examples/safe \\\n  --after examples/vulnerable \\\n  --format pr'}</code></pre><p><span className="danger-text">BLOCK CHANGE</span> · exit 1</p><small>Uses the same Python analysis engine as this demo.</small></div>
    </section>
    <section className="container section faq-section"><div className="section-intro"><LockKeyhole size={24} aria-hidden="true" /><p className="eyebrow">CLEAR BOUNDARIES</p><h2>Security decisions deserve honest answers.</h2></div>
      <div className="faq">{[
        ['Does SAFE mean my infrastructure is secure?', 'No. No new modeled blocking findings detected describes a result under the selected model and policy. Existing exposure may remain. Unsupported resources, policy conditions and Terraform constructs can limit coverage. Read diagnostics before relying on a result.'],
        ['Do you need my AWS credentials?', 'No. BlastRadius analyzes Terraform text and plan JSON. It does not call AWS, execute Terraform providers, deploy resources or verify exploitability.'],
        ['What happens to uploaded data?', 'Public demos use fixed fixtures and persist no analysis. Workspace reports are stored by the backend and may contain source diffs or patches. Avoid uploading secrets. Deleting an analysis removes its stored report; backup retention is the operator’s responsibility. Use the CLI when data must stay local.'],
        ['Does BlastRadius deploy infrastructure?', 'No. It reads supported infrastructure inputs and returns evidence and suggested patches for human review. It never applies Terraform or changes your AWS infrastructure.'],
        ['Can I connect a GitHub repository here?', 'The GitHub App requires configured provider credentials and an operator-verified installation mapped to your workspace. Owners and admins can connect verified repositories. The integration page shows actual status; installation alone does not establish a connection. GitHub Actions is also available.'],
        ['What counts as an analysis?', 'Each job accepted for processing counts toward the monthly UTC quota, even if it later fails. Rejected requests and public demos do not count. Deleting a report does not refund usage.'],
        ['Can I pay for a subscription?', 'Payments are disabled during the commercial beta. Free is available through configured sign-in. Pro, Team and Enterprise have proposed pricing and require an operator grant. There is no self-service upgrade or checkout.'],
        ['Can I run GitHub Actions without a SaaS account?', 'Yes. The documented CLI and Actions workflow run in your environment without a BlastRadius SaaS account. They do not automatically upload reports into workspace history.'],
      ].map(([question, answer]) => <details key={question}><summary>{question}</summary><p>{answer}</p></details>)}</div>
    </section>
    <section className="container section"><div className="final-cta"><p className="eyebrow">KNOW BEFORE YOU MERGE</p><h2>See what one line can open.</h2><p>Three real scenarios. Every connection explained.</p><Link className="button primary large" to="/demo">Try the live demo<ArrowRight size={18} aria-hidden="true" /></Link></div></section>
  </>;
}
