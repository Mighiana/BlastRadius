import { Link } from 'react-router-dom';
import { Check } from 'lucide-react';
import { plansSchema, usageSchema } from '../api';
import { useResource } from '../hooks';
import { useOrganization, useSession } from '../session';
import { AuthGate } from '../components/AuthGate';
import { WorkspaceNav } from '../components/WorkspaceNav';
import { Empty, ErrorNotice, Loading, PageHeading } from '../components/UI';
import { UsageSummary } from './Workspace';

export function PlanCards() {
  const catalog = useResource('/api/plans', plansSchema);
  const { session, originMismatch } = useSession();
  return <>
    <ErrorNotice error={catalog.error} retry={catalog.reload} />
    {catalog.loading && <Loading>Loading plan catalog…</Loading>}
    <div className="pricing-grid">{catalog.data?.plans.map(plan => <article className={`price-card ${plan.code === 'pro' ? 'featured' : ''}`} key={plan.code}>
      <span className="eyebrow">{plan.code}</span>
      <h2>{plan.monthly_price_usd === null ? 'Custom' : `$${plan.monthly_price_usd}`}<small>{plan.code === 'free' ? 'Free plan' : plan.monthly_price_usd === null ? 'Contact the operator' : 'Proposed / month · USD'}</small></h2>
      <p>{plan.configurable ? 'Configurable limits. Shown defaults apply until an operator configures your workspace.' : plan.assignment === 'signup' ? 'Start with your next infrastructure change.' : 'Commercial beta · assigned manually by an operator.'}</p>
      <ul>{[
        `${plan.limits.analyses_per_month.toLocaleString()} analyses / month`,
        `${plan.limits.projects} projects`, `${plan.limits.members} workspace ${plan.limits.members === 1 ? 'member' : 'members'}`,
        `${plan.limits.retention_days} days of evidence retention`, 'JSON & Markdown reports',
        ...(plan.features.sarif ? ['SARIF exports'] : ['SARIF requires Pro or above']),
        ...(plan.features.advanced_policy ? ['Project policy controls'] : []),
        ...(plan.features.team ? ['Team roles & invitations'] : []),
        ...(plan.features.organization_policy ? ['Workspace policy'] : []),
        ...(plan.features.audit ? ['Audit visibility'] : []),
      ].map(text => <li key={text}><Check size={17} aria-hidden="true" />{text}</li>)}</ul>
      {plan.assignment === 'signup' ? originMismatch && session ? <a className="button primary" href={`${new URL(session.auth.public_url).origin}/dashboard`}>Get started at configured origin</a> : <Link className="button primary" to="/dashboard">Get started</Link>
        : <><button className="button secondary" disabled>Coming soon</button><p className="footnote">Self-service upgrades and payments are unavailable. Ask your deployment operator about beta access.</p></>}
    </article>)}</div>
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
  return <div className="container page"><PageHeading eyebrow="COMMERCIAL BETA" title="A plan for every review.">Proposed pricing. No payment processing. Start on Free; paid plans require operator-granted beta access.</PageHeading><PlanCards />
    <section className="panel pricing-note"><h2>What counts as an analysis?</h2><p>A job accepted for processing counts toward the monthly UTC quota, including a job that later fails. Rejected submissions do not count. Public demos do not use workspace quota.</p><p>All plans provide static evidence, not proof of security. AWS credentials are not required; BlastRadius does not deploy infrastructure.</p><Link to="/guide">Read the guide</Link></section>
  </div>;
}
export default function Billing() {
  return <div className="container page"><PageHeading eyebrow="USAGE & PLANS" title="Know your limits.">Workspace usage, evidence retention and beta entitlements.</PageHeading><AuthGate><Usage /></AuthGate><PlanCards /></div>;
}
