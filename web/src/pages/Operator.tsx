import { useState } from 'react';
import { ApiError, plansSchema } from '../api';
import { eventSummarySchema, operatorSchemas, type OperatorList } from '../operator-api';
import { useResource } from '../hooks';
import { useSession } from '../session';
import { AuthGate } from '../components/AuthGate';
import { Empty, ErrorNotice, Loading, PageHeading } from '../components/UI';

function Events() {
  const result = useResource('/api/admin/events', eventSummarySchema);
  return <><ErrorNotice error={result.error} retry={result.reload} />{result.loading && <Loading>Loading activity summary…</Loading>}
    {result.data && <><dl className="facts"><div><dt>Active workspaces</dt><dd>{result.data.active_workspaces}</dd></div>{Object.entries(result.data.counts).map(([name, count]) => <div key={name}><dt>{name.replaceAll('_', ' ')}</dt><dd>{count}</dd></div>)}</dl>
      <p>Activity within {result.data.retention_days} days, capped at {result.data.max_records.toLocaleString()} events. Active workspaces have at least one retained event. Oldest events can be evicted at capacity; these counts are not a durable accounting ledger or evidence of willingness to pay.</p></>}
  </>;
}
function Plans() {
  const result = useResource('/api/admin/plans', plansSchema);
  return <><ErrorNotice error={result.error} retry={result.reload} />{result.loading && <Loading>Loading plan catalog…</Loading>}
    <p>Plan assignment is a trusted operator CLI action. This view cannot upgrade a workspace or activate payments.</p>
    {result.data?.plans.map(plan => <article className="operator-record" key={plan.code}><h3>{plan.code}</h3><dl className="facts">
      <div><dt>Monthly price (USD)</dt><dd>{plan.monthly_price_usd === null ? 'Custom' : `$${plan.monthly_price_usd}`} · {plan.price_status}</dd></div>
      <div><dt>Assignment</dt><dd>{plan.assignment}</dd></div>
      <div><dt>Limits</dt><dd><pre>{JSON.stringify(plan.limits, null, 2)}</pre></dd></div>
      <div><dt>Features</dt><dd><pre>{JSON.stringify(plan.features, null, 2)}</pre></dd></div>
    </dl></article>)}
  </>;
}
function Records({ resource }: { resource: OperatorList }) {
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(25);
  const result = useResource(`/api/admin/${resource}?limit=${limit}&offset=${offset}`, operatorSchemas[resource]);
  const next = result.data?.next_offset;
  return <>
    <div className="pagination"><label>Records per page<select value={limit} onChange={e => { setLimit(Number(e.target.value)); setOffset(0); }}>{[25, 50, 100].map(n => <option key={n}>{n}</option>)}</select></label>
      <button className="button secondary" disabled={offset === 0 || result.loading} onClick={() => setOffset(Math.max(0, offset - limit))}>Previous records</button>
      <button className="button secondary" disabled={result.loading || next == null || next <= offset || next > 1000000} onClick={() => { if (next != null && next > offset && next <= 1000000) setOffset(next); }}>Next records</button>
      <button className="button secondary" onClick={result.reload}>Refresh records</button>
    </div>
    <ErrorNotice error={result.error} retry={result.reload} />
    {result.loading && <Loading>Loading records…</Loading>}
    {result.data && <><p className="footnote" role="status">Offset {result.data.offset} · {result.data.items.length} records. Results may change between pages.</p>
      {!result.data.items.length && <Empty title="No records on this page"><p>Go back or choose another view.</p></Empty>}
      {result.data.items.map((row, index) => <article className="operator-record" key={typeof row.id === 'string' ? row.id : index}><h3>Record {offset + index + 1}</h3>
        <dl className="facts">{Object.entries(row).map(([field, value]) => <div key={field}><dt>{field.replaceAll('_', ' ')}</dt><dd>{value == null ? 'Not provided' : typeof value === 'object' ? <pre>{JSON.stringify(value, null, 2)}</pre> : <span className="review-value">{String(value)}</span>}</dd></div>)}</dl>
      </article>)}
    </>}
  </>;
}
function OperatorContent() {
  const { session } = useSession();
  const [resource, setResource] = useState<OperatorList | 'events' | 'plans'>('events');
  if (session?.capabilities?.platform_admin !== true) return <ErrorNotice error={new ApiError(403, 'platform_admin_required', null)} />;
  const privateReview = resource === 'beta-requests' || resource === 'feedback';
  return <section className="panel operator-panel">
    <p>Read-only inspection. Every request is independently authorized and audited by the server. Workspace owner/admin roles do not grant platform access. Ordinary inspection excludes Terraform, report evidence and account display names.</p>
    <label>Operator view<select value={resource} onChange={e => setResource(e.target.value as typeof resource)}>
      <optgroup label="Operational inspection">{(['events', 'users', 'organizations', 'projects', 'plans', 'usage', 'failures'] as const).map(value => <option key={value} value={value}>{value === 'events' ? 'Activity summary' : value}</option>)}</optgroup>
      <optgroup label="Private review"><option value="beta-requests">Beta requests · private</option><option value="feedback">Analysis feedback · private</option></optgroup>
    </select></label>
    {privateReview && <div className="notice">Private operator review: submitted identity details or feedback text may be sensitive. Do not copy them into telemetry, URLs, logs or public issues. Records older than 90 days are hidden; physical cleanup requires the operator’s scheduled procedure.</div>}
    {resource === 'events' ? <Events /> : resource === 'plans' ? <Plans /> : <Records key={resource} resource={resource} />}
  </section>;
}
export default function Operator() {
  return <div className="container page"><PageHeading eyebrow="PLATFORM OPERATIONS" title="Operator review.">Bounded activity and private beta review for server-authorized operators.</PageHeading><AuthGate><OperatorContent /></AuthGate></div>;
}
