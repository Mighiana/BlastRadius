import { ArrowRight, GitPullRequest, Terminal, Network, LockKeyhole, GitCompareArrows, FileCheck2, ChevronRight, Globe, Shield, Cpu, KeyRound, Database, Ban, CheckCircle2, AlertCircle, Lock, Check } from 'lucide-react';
import { Link } from 'react-router-dom';

const HOPS = [
  { icon: Globe, name: 'Internet', text: 'Anyone, anywhere' },
  { icon: Shield, name: 'Web SG', text: 'Now allows SSH from 0.0.0.0/0' },
  { icon: Cpu, name: 'EC2 instance', text: 'Becomes reachable' },
  { icon: KeyRound, name: 'IAM role', text: 'Grants s3:GetObject' },
  { icon: Database, name: 'Customer data', text: 'Sensitive bucket reachable', sensitive: true },
];

export default function Landing() {
  return <>
    <section className="hero container">
      <div className="hero-copy"><div className="hero-kicker"><span className="dot" /> TERRAFORM SECURITY ANALYSIS · IN THE PULL REQUEST</div>
        <h1>See what your <span>Terraform change</span> makes reachable.</h1>
        <p>One line in a pull request can open a path to your customer data. BlastRadius shows that path and returns BLOCK CHANGE before merge.</p>
        <div className="button-row"><Link className="button primary large" to="/demo">Try the live demo<ArrowRight size={18} aria-hidden="true" /></Link><Link className="button secondary large" to="/guide#github"><GitPullRequest size={18} aria-hidden="true" />Set up the PR check</Link></div>
        <ul className="hero-assurances"><li><Check size={14} aria-hidden="true" />No cloud credentials</li><li><Check size={14} aria-hidden="true" />No Terraform, providers or repository code executed</li><li><Check size={14} aria-hidden="true" />Works in GitHub Actions and the CLI</li></ul>
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
      <ol className="how-steps">{[
        { icon: GitCompareArrows, title: 'Compare', text: 'Before vs after Terraform' },
        { icon: Network, title: 'Trace', text: 'Internet → your sensitive data' },
        { icon: FileCheck2, title: 'Decide', text: 'BLOCK · REVIEW · NO NEW PATHS' },
      ].map((step, i) => <li className="step-card" key={step.title}><span className="step-number">{i + 1}</span><span className="step-icon"><step.icon size={24} aria-hidden="true" /></span><div><h2>{step.title}</h2><p>{step.text}</p></div></li>)}</ol>
    </section>
    <section className="container section verdicts-section"><h2 className="section-title">One answer on every pull request</h2>
      <div className="verdicts">
        <article className="verdict-card block"><span className="verdict-badge"><Ban size={18} aria-hidden="true" />BLOCK CHANGE</span><p>New path to sensitive data, or a policy violation</p><span className="verdict-mini"><Globe size={13} aria-hidden="true" /><ArrowRight size={12} aria-hidden="true" /><Database size={13} aria-hidden="true" /></span></article>
        <article className="verdict-card review"><span className="verdict-badge"><AlertCircle size={18} aria-hidden="true" />REVIEW REQUIRED</span><p>New exposure or a coverage gap to check</p><span className="verdict-mini"><Terminal size={13} aria-hidden="true" /><span className="qmark">?</span></span></article>
        <article className="verdict-card safe"><span className="verdict-badge"><CheckCircle2 size={18} aria-hidden="true" />NO NEW PATHS</span><p>Nothing new reaches sensitive data</p><span className="verdict-mini"><Lock size={13} aria-hidden="true" /><Check size={13} aria-hidden="true" /></span></article>
      </div>
      <div className="pr-mock" aria-label="Example GitHub pull request check"><div className="pr-mock-row"><span className="pr-avatar"><Shield size={14} aria-hidden="true" /></span><span><strong>BlastRadius</strong> — <span className="danger-text">BLOCK CHANGE</span> · 1 new critical path · <code>aws_security_group.web</code> line 28</span><span className="pr-status fail"><Ban size={12} aria-hidden="true" />Failing</span></div><div className="pr-mock-row ok"><span className="pr-avatar"><GitPullRequest size={14} aria-hidden="true" /></span><span><strong>BlastRadius</strong> — <span className="ok-text">NO NEW PATHS</span> · after restricting SSH to <code>10.0.0.0/24</code></span><span className="pr-status pass"><Check size={12} aria-hidden="true" />Passing</span></div></div>
    </section>
    <section className="value-strip"><div className="container"><span>WORKS WITH</span><strong><Terminal size={19} aria-hidden="true" />Terraform</strong><strong><GitPullRequest size={19} aria-hidden="true" />GitHub Actions</strong><strong><Network size={19} aria-hidden="true" />AWS</strong><strong><FileCheck2 size={19} aria-hidden="true" />SARIF</strong></div></section>
    <section className="container section faq-section"><div className="section-intro"><LockKeyhole size={24} aria-hidden="true" /><p className="eyebrow">CLEAR BOUNDARIES</p><h2>Honest answers.</h2></div>
      <div className="faq">{[
        ['Does NO NEW PATHS mean my infrastructure is secure?', 'No. It means the change adds no new modeled path under the selected model and policy. Existing exposure may remain, and unsupported resources or Terraform constructs can limit coverage. Read the diagnostics before relying on a result.'],
        ['Do you need my AWS credentials?', 'No. BlastRadius analyzes Terraform text and plan JSON. It does not call AWS, execute Terraform providers, deploy resources or verify exploitability.'],
        ['What happens to uploaded data?', 'Public demos use fixed fixtures and persist no analysis. Workspace reports are stored by the backend and may contain source diffs or patches. Avoid uploading secrets. Deleting an analysis removes its stored report; backup retention is the operator’s responsibility. Use the CLI when data must stay local.'],
        ['Does BlastRadius deploy infrastructure?', 'No. It reads supported infrastructure inputs and returns evidence and suggested patches for human review. It never applies Terraform or changes your AWS infrastructure.'],
      ].map(([question, answer]) => <details key={question}><summary>{question}</summary><p>{answer}</p></details>)}</div>
    </section>
    <section className="container section"><div className="final-cta"><h2>See what one line can open.</h2><Link className="button primary large" to="/demo">Try the live demo<ArrowRight size={18} aria-hidden="true" /></Link></div></section>
  </>;
}
