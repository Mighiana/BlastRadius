import { useState } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { z } from 'zod';
import { ArrowRight, Check, CreditCard, RefreshCw } from 'lucide-react';
import { billingSchema, request, safeBillingUrl } from '../api';
import { useResource } from '../hooks';
import { useSession } from '../session';
import { AuthGate } from '../components/AuthGate';
import { ErrorNotice, Loading, PageHeading } from '../components/UI';
import { UsageSummary } from './Workspace';

export const plans = [
  { id: 'free', name: 'Free', count: '20', projects: '3', members: '1', description: 'Start with your next infrastructure change.' },
  { id: 'pro', name: 'Pro', count: '500', projects: '20', members: '5', description: 'Make change review part of your workflow.' },
  { id: 'team', name: 'Team', count: '5,000', projects: '100', members: '25', description: 'Bring infrastructure and security together.' },
] as const;
function PlanCards({ checkout, busy = false }: { checkout?: (plan: 'pro' | 'team') => void; busy?: boolean }) {
  return <div className="pricing-grid">{plans.map(plan => <article className={`price-card ${plan.id === 'pro' ? 'featured' : ''}`} key={plan.id}>
    <span className="eyebrow">{plan.name}</span><h2>{plan.id === 'free' ? 'Free' : 'Test mode'}<small>{plan.id !== 'free' && 'Pricing set by operator in Stripe sandbox'}</small></h2><p>{plan.description}</p>
    <ul>{[`${plan.count} analyses / month`, `${plan.projects} projects`, `${plan.members} workspace ${plan.members === '1' ? 'member' : 'members'}`, 'Evidence, remediation & exports'].map(text => <li key={text}><Check size={17} aria-hidden="true" />{text}</li>)}</ul>
    {checkout && plan.id !== 'free' ? <button className={`button ${plan.id === 'pro' ? 'primary' : 'secondary'}`} disabled={busy} onClick={() => checkout(plan.id as 'pro' | 'team')}>Start {plan.name} test checkout<ArrowRight size={16} aria-hidden="true" /></button> : <Link className={`button ${plan.id === 'pro' ? 'primary' : 'secondary'}`} to={plan.id === 'free' ? '/dashboard' : '/billing'}>{plan.id === 'free' ? 'Open workspace' : 'View test billing'}<ArrowRight size={16} aria-hidden="true" /></Link>}
  </article>)}</div>;
}
function BillingContent() {
  const { session, refresh } = useSession();
  const [params] = useSearchParams();
  const [selected, setSelected] = useState(params.get('organization') ?? '');
  const org = session?.organizations.find(o => o.id === selected) ?? session?.organizations[0];
  const billing = useResource(org?.role === 'owner' ? `/api/organizations/${encodeURIComponent(org.id)}/billing` : null, billingSchema);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  async function redirect(action: 'checkout' | 'portal', plan?: 'pro' | 'team') {
    if (!org || busy) return;
    setBusy(true); setError(null);
    try {
      const data = await request(`/api/organizations/${encodeURIComponent(org.id)}/billing/${action}`, z.object({ url: z.string() }),
        { method: 'POST', ...(plan ? { body: JSON.stringify({ plan }) } : {}) });
      window.location.assign(safeBillingUrl(data.url));
    } catch (err) { setError(err instanceof Error ? err : new Error('Could not open test billing.')); setBusy(false); }
  }
  return <>
    <div className="panel billing-summary"><div className="panel-heading"><label>Workspace<select value={org?.id} onChange={e => { setSelected(e.target.value); setError(null); }}>{session?.organizations.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}</select></label><button className="button secondary" onClick={() => { billing.reload(); void refresh(); }}><RefreshCw size={16} aria-hidden="true" />Refresh status</button></div>
      {org && <UsageSummary organization={org} />}
      <ErrorNotice error={billing.error} retry={billing.reload} /><ErrorNotice error={error} />
      {billing.loading && <Loading>Loading subscription…</Loading>}
      {org?.role !== 'owner' && <p>Only workspace owners can manage billing. Your usage is shown above.</p>}
      {billing.data && <><div className="subscription-status"><span className="tag">TEST MODE ONLY</span><strong>{billing.data.plan} plan</strong><span>Subscription: {billing.data.subscription_status}</span></div>
        {!billing.data.enabled ? <div className="notice">Stripe test billing is not configured. Your Free workspace and public demos work without payment credentials.</div>
          : <><p>Checkout uses Stripe test mode. No real payments. Subscription status changes only after a verified provider webhook; the return URL does not confirm payment.</p><button className="button secondary" disabled={busy || billing.data.subscription_status === 'none'} onClick={() => { void redirect('portal'); }}><CreditCard size={16} aria-hidden="true" />Open test billing portal</button></>}
      </>}
      {params.get('checkout') && <div className="notice">Returned from test checkout. Refresh status to check webhook-confirmed entitlements. A successful redirect alone does not change your plan.</div>}
    </div>
    <PlanCards busy={busy} checkout={billing.data?.enabled && ['none', 'canceled', 'incomplete_expired'].includes(billing.data.subscription_status) ? plan => { void redirect('checkout', plan); } : undefined} />
  </>;
}
export default function Billing({ publicPage = false }: { publicPage?: boolean }) {
  return <div className="container page"><PageHeading eyebrow="PLANS & USAGE" title="Start small. Review with your team.">Every plan includes the same engine and evidence. Limits scale with your workspace.</PageHeading>
    <div className="notice pricing-notice">Billing is test mode only. Paid plans are a sandbox integration, not a live commercial offer. No live payments or production SLA.</div>
    {publicPage ? <PlanCards /> : <AuthGate><BillingContent /></AuthGate>}
    <p className="footnote">Usage is enforced per workspace. Failed accepted analyses count toward monthly usage; deletion does not refund quota. Downgrades retain existing reports.</p>
  </div>;
}
