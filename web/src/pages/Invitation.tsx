import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { acceptedInvitationSchema, request } from '../api';
import { useAction } from '../hooks';
import { useSession } from '../session';
import { ErrorNotice, Loading, PageHeading } from '../components/UI';

export default function Invitation() {
  const token = useRef('');
  const [valid, setValid] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const { session, loading, error: sessionError, originMismatch, refresh, selectOrganization } = useSession();
  const action = useAction();
  useEffect(() => {
    const fragment = new URLSearchParams(window.location.hash.slice(1)).get('token');
    if (fragment !== null) {
      token.current = /^[A-Za-z0-9_-]{43}$/.test(fragment) ? fragment : '';
      window.history.replaceState(window.history.state, '', window.location.pathname + window.location.search);
      setValid(!!token.current);
    }
  }, []);
  async function accept() {
    await action.run(async () => {
      const result = await request('/api/invitations/accept', acceptedInvitationSchema, { method: 'POST', body: JSON.stringify({ token: token.current }) });
      token.current = ''; setValid(false); setAccepted(true);
      await refresh(); selectOrganization(result.organization_id);
    });
  }
  return <div className="container page"><PageHeading eyebrow="WORKSPACE INVITATION" title="Join your team.">Invitations are single-use and require the verified email address they were sent to.</PageHeading><section className="panel">
    <ErrorNotice error={action.error} />
    {accepted ? <><h2>Invitation accepted</h2><Link className="button primary" to="/dashboard">Open workspace</Link></> : sessionError ? <ErrorNotice error={sessionError} retry={() => { void refresh(); }} /> : loading && !session ? <Loading>Checking your session…</Loading> : <>
      {!valid && <p className="notice">No valid invitation token was found. Reopen the original invitation link or request a new one.</p>}
      {!session?.authenticated ? <><p>Sign in first, then reopen the original invitation link. The token was removed from this address and is never stored in browser storage.</p>{session?.auth.mode === 'oidc' && session.auth.enabled && !originMismatch ? <a className="button primary" href="/api/auth/login">Sign in with your identity provider</a> : <p className="notice">A configured identity provider is required. Local demo identities cannot accept invitations.</p>}</>
        : <><p>Signed in as <strong>{session.user?.email}</strong>. The server verifies that this address matches the invitation.</p>
          {!session.user?.email_verified && <p className="notice">Verify your email with your identity provider and sign in again before accepting.</p>}
          {session.auth.mode === 'demo' && <p className="notice">Demo identities cannot accept invitations.</p>}
          {originMismatch && <p className="notice">Open the invitation at the configured application origin.</p>}
          <button className="button primary" disabled={!valid || action.busy || !session.user?.email_verified || session.auth.mode === 'demo' || originMismatch} onClick={() => { void accept(); }}>{action.busy ? 'Accepting…' : 'Accept invitation'}</button></>}
    </>}
  </section></div>;
}
