import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, LockKeyhole } from 'lucide-react';
import { ApiError, mutate } from '../api';
import { useSession } from '../session';
import { ErrorNotice, Loading } from './UI';

export function AuthGate({ children }: { children: ReactNode }) {
  const { session, loading, error, originMismatch, refresh } = useSession();
  const [loginError, setLoginError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  async function login() {
    setBusy(true); setLoginError(null);
    try { await mutate('/api/auth/demo', 'POST'); await refresh(); }
    catch (err) { setLoginError(err instanceof Error ? err : new Error('Sign-in failed.')); }
    finally { setBusy(false); }
  }
  if (!session && loading) return <Loading>Loading your session…</Loading>;
  if (error) return <ErrorNotice error={error} retry={() => { void refresh(); }} />;
  if (originMismatch) return <section className="auth-card panel">
    <h2>Workspace unavailable at this address</h2>
    <ErrorNotice error={new ApiError(403, 'invalid_origin', null)} retry={() => { void refresh(); }} />
    <p>Configured origin: <code>{session?.auth.public_url}</code></p>
    <p>Current origin: <code>{window.location.origin}</code></p>
    <Link to="/demo" className="text-link">Try the public demo<ArrowRight size={16} aria-hidden="true" /></Link>
  </section>;
  if (session?.authenticated) return children;
  return <section className="auth-card panel"><LockKeyhole size={32} aria-hidden="true" /><p className="eyebrow">YOUR INFRASTRUCTURE WORKSPACE</p><h2>Start with a clear picture.</h2>
    <p>Create projects, compare Terraform changes, and keep the evidence in your analysis history.</p>
    {session?.auth.mode === 'oidc' && session.auth.enabled && <a className="button primary" href="/api/auth/login">Sign in with your identity provider<ArrowRight size={16} aria-hidden="true" /></a>}
    {session?.auth.mode === 'demo' && <><button className="button primary" disabled={busy} onClick={() => { void login(); }}>{busy ? 'Creating workspace…' : 'Create local demo workspace'}<ArrowRight size={16} aria-hidden="true" /></button>
      <p className="muted">Development mode. Each login creates a new isolated workspace; logging out loses access to this demo identity. Do not use sensitive data.</p></>}
    {session?.auth.mode === 'disabled' && <div className="notice">Workspace sign-in is not configured on this server. Public demos remain available. The operator can configure OIDC or enable local demo mode.</div>}
    <ErrorNotice error={loginError} />
    <Link to="/demo" className="text-link">Try the public demo without signing in<ArrowRight size={16} aria-hidden="true" /></Link>
  </section>;
}
