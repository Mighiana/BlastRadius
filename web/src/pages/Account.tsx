import { useState } from 'react';
import { mutate, sessionsSchema } from '../api';
import { useAction, useResource } from '../hooks';
import { useSession } from '../session';
import { AuthGate } from '../components/AuthGate';
import { WorkspaceNav } from '../components/WorkspaceNav';
import { ErrorNotice, Loading, PageHeading } from '../components/UI';

function AccountContent() {
  const { session, refresh } = useSession();
  const sessions = useResource('/api/account/sessions', sessionsSchema);
  const action = useAction();
  const [confirmAll, setConfirmAll] = useState(false);
  return <><WorkspaceNav /><section className="panel">
    <h2>Your account</h2><dl className="facts"><div><dt>Name</dt><dd>{session?.user?.name}</dd></div><div><dt>Email</dt><dd>{session?.user?.email}</dd></div><div><dt>Email verification</dt><dd>{session?.user?.email_verified ? 'Verified' : 'Not verified — invitations require a verified matching email'}</dd></div><div><dt>Authentication</dt><dd>{session?.auth.mode}</dd></div></dl>
    <p>Identity details are managed by your identity provider. Demo accounts are temporary and cannot accept invitations.</p>
  </section><section className="panel">
    <div className="panel-heading"><h2>Active sessions</h2><button className="button secondary" onClick={sessions.reload}>Refresh sessions</button></div>
    <ErrorNotice error={sessions.error} retry={sessions.reload} /><ErrorNotice error={action.error} />
    {action.notice && <p className="notice" role="status">{action.notice}</p>}
    {sessions.loading && <Loading>Loading sessions…</Loading>}
    <div className="management-list">{sessions.data?.sessions.map(item => <article key={item.id}>
      <div><strong>{item.current ? 'This session' : 'Another session'}</strong><p>Created {item.created_at ? new Date(item.created_at * 1000).toLocaleString() : 'before session tracking was added'}<br />Expires {new Date(item.expires_at * 1000).toLocaleString()}</p></div>
      <button className="button secondary" disabled={action.busy} onClick={() => { void action.run(async () => {
        await mutate(`/api/account/sessions/${encodeURIComponent(item.id)}`, 'DELETE');
        if (item.current) await refresh(); else sessions.reload();
      }, 'Session revoked.'); }}>{item.current ? 'Sign out this session' : 'Revoke session'}</button>
    </article>)}</div>
    {sessions.data?.sessions.length === 0 && <p>No active sessions.</p>}
    {confirmAll ? <div className="notice confirm-delete"><span>This signs you out on every device, including here.</span><button className="button danger" disabled={action.busy} onClick={() => { void action.run(async () => { await mutate('/api/account/sessions', 'DELETE'); await refresh(); }); }}>Confirm sign out everywhere</button><button className="button secondary" onClick={() => setConfirmAll(false)}>Cancel</button></div>
      : <button className="button danger" disabled={action.busy} onClick={() => setConfirmAll(true)}>Sign out everywhere</button>}
  </section></>;
}
export default function Account() {
  return <div className="container page"><PageHeading eyebrow="ACCOUNT" title="Your identity and sessions.">Review your account and revoke access from signed-in devices.</PageHeading><AuthGate><AccountContent /></AuthGate></div>;
}
