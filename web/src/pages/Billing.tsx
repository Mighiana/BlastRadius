import { Link } from 'react-router-dom';
import { Check, Minus } from 'lucide-react';
import { plansSchema, usageSchema } from '../api';
import { useResource } from '../hooks';
import { useOrganization, useSession } from '../session';
import { AuthGate } from '../components/AuthGate';
import { WorkspaceNav } from '../components/WorkspaceNav';
import { Empty, ErrorNotice, Loading, PageHeading } from '../components/UI';
import { UsageSummary } from './Workspace';

const values: Record<string, string> = {
  free: 'Evaluate a first Terraform workflow with stored evidence.',
  pro: 'Review changes across several repositories with longer history.',
  team: 'Share review workflows, organization policy and audit visibility.',
  enterprise: 'Everything in Team, plus configurable limits.',
};
const plural = (n: number, word: string) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`;

export function PlanCards() {
  const catalog = useResource('/api/plans', plansSchema);
  const { session, originMismatch } = useSession();
  return <>
    <ErrorNotice error={catalog.error} retry={catalog.reload} />
    {catalog.loading && <Loading>Loading plan catalog…</Loading>}
    <div className="pricing-grid">{catalog.data?.plans.map(plan => <article className={`price-card ${plan.code === 'pro' ? 'featured' : ''}`} key={plan.code}>
      <span className="eyebrow">{plan.code}</span>
      <h2>{plan.monthly_price_usd === null ? 'Custom' : `$${plan.monthly_price_usd}`}<small>{plan.code === 'free' ? 'Free plan' : plan.monthly_price_usd === null ? 'Contact the operator' : 'Proposed / month · USD'}</small></h2>
      <p>{values[plan.code]}</p>
      <ul>{(plan.configurable ? [
        { text: 'Everything in Team', ok: true },
        { text: `Configurable limits (defaults: ${plan.limits.analyses_per_month.toLocaleString()} analyses, ${plural(plan.limits.projects, 'project')}, ${plural(plan.limits.members, 'member')}, ${plan.limits.retention_days} days)`, ok: true },
        { text: 'Deployment and scale discussed with the operator', ok: true },
      ] : [
        { text: `${plan.limits.analyses_per_month.toLocaleString()} analyses / month`, ok: true },
        { text: plural(plan.limits.projects, 'project'), ok: true }, { text: `${plural(plan.limits.members, 'workspace member')}`, ok: true },
        { text: `${plan.limits.retention_days} days of evidence retention`, ok: true }, { text: 'JSON & Markdown reports', ok: true },
        plan.features.sarif ? { text: 'SARIF exports', ok: true } : { text: 'No SARIF exports (Pro and above)', ok: false },
        ...(plan.features.advanced_policy ? [{ text: 'Project policy controls', ok: true }] : []),
        ...(plan.features.team ? [{ text: 'Team roles & invitations', ok: true }] : []),
        ...(plan.features.organization_policy ? [{ text: 'Workspace policy', ok: true }] : []),
        ...(plan.features.audit ? [{ text: 'Audit visibility', ok: true }] : []),
      ]).map(item => <li key={item.text} className={item.ok ? undefined : 'limitation'}>{item.ok ? <Check size={17} aria-hidden="true" /> : <Minus size={17} aria-hidden="true" />}{item.text}</li>)}</ul>
      {plan.assignment === 'signup' ? originMismatch && session ? <a className="button primary" href={`${new URL(session.auth.public_url).origin}/dashboard`}>Get started at configured origin</a> : <Link className="button primary" to="/dashboard">Get started</Link>
        : <Link className={`button ${plan.code === 'pro' ? 'primary' : 'secondary'}`} to="/beta">Request early access</Link>}
    </article>)}</div>
    {catalog.data && <p className="pricing-footnote">Paid plans are operator-granted beta entitlements: self-service checkout is coming later, and a beta request does not guarantee access. Prices are proposed.</p>}
  </>;
}
function Usage() {
  const { organization: org } = useOrganization();
  const usage = useResource(org ? `/api/organizations/${encodeURIComponent(org.id)}/usage` : null, usageSchema);
  return <><WorkspaceNav />
    {!org ? <Empty title="No workspace yet"><Link to="/dashboard">Create a workspace</Link></Empty> : <section className="panel billing-summary">
      <div className="panel-heading"><h2>{org.name} · {usage.data?.plan ?? org.plan}</h2><button className="button secondary" onClick={usage.reload}>Refresh usage</button></div>
      <ErrorNotice error={usage.error} retry={usage.reload} />
      {usage.loading && <Loading>Loading usage…</Loading>}
      {usage.data && <><UsageSummary organization={{ ...org, usage: usage.data }} />
        <dl className="facts"><div><dt>Projects</dt><dd>{usage.data.projects} / {usage.data.limits.projects}</dd></div><div><dt>Members</dt><dd>{usage.data.members} / {usage.data.limits.members}</dd></div><div><dt>Pending invitations</dt><dd>{usage.data.pending_invitations}</dd></div><div><dt>Report exports this month</dt><dd>{usage.data.exports}</dd></div><div><dt>Evidence retention</dt><dd>{usage.data.limits.retention_days} days</dd></div><div><dt>SARIF</dt><dd>{usage.data.features.sarif ? 'Available' : 'Requires Pro or above'}</dd></div></dl>
        <p>Expired evidence becomes unavailable at read time. Physical cleanup and backup retention are operator responsibilities. Deleting an analysis does not refund usage.</p>
      </>}
      <p className="notice">Payments are disabled. Paid plans are operator-granted beta entitlements; no subscription or charge is created here.</p>
    </section>}</>;
}
export function Pricing() {
  return <div className="container page"><PageHeading eyebrow="COMMERCIAL BETA" title="A plan for every review.">Start on Free. Paid plans are granted by the operator during the beta.</PageHeading><PlanCards />
    <section className="panel pricing-note"><h2>Before you start</h2><div className="faq">{[
      ['What counts as an analysis?', 'A job accepted for processing counts toward the monthly UTC quota, including a job that later fails. Rejected submissions and public demos do not count.'],
      ['Do I need AWS credentials?', 'No. Bring baseline and candidate Terraform files, or a Terraform plan JSON generated in your trusted environment. Static analysis does not require AWS access.'],
      ['Does BlastRadius deploy or execute anything?', 'It does not deploy infrastructure, run Terraform or providers, or execute candidate repository scripts. Suggested patches require human review.'],
      ['What does NO NEW PATHS mean?', 'The change adds no new modeled path to sensitive data under the selected model and policy. It is not proof that infrastructure is secure: existing exposure and coverage gaps may remain.'],
      ['Can I use GitHub Actions without the SaaS?', 'Yes. Use the documented CLI and Actions workflow in your own environment. A SaaS account and GitHub App installation are not required; CI results do not automatically enter workspace history.'],
      ['How long are results retained?', 'The server catalog above is authoritative. Reports become unavailable after the current plan’s retention window. Operators manage physical cleanup and backups; deleting a report does not erase copies already exported.'],
      ['What does private beta mean?', 'The product is still being evaluated with Terraform teams. Proposed paid prices are subject to validation, payments are disabled, and beta interest does not create an account, promise an invitation or send email.'],
    ].map(([question, answer]) => <details key={question}><summary>{question}</summary><p>{answer}</p></details>)}</div></section>
  </div>;
}
export default function Billing() {
  return <div className="container page"><PageHeading eyebrow="USAGE & PLANS" title="Know your limits.">Workspace usage, evidence retention and beta entitlements.</PageHeading><AuthGate><Usage /></AuthGate><PlanCards /></div>;
}
