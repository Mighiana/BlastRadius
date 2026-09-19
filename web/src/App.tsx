import { Component, useEffect, useState, type ReactNode } from 'react';
import { Link, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { ArrowUpRight, GitBranch, Menu, Radar, X } from 'lucide-react';
import Landing from './pages/Landing';
import Demo from './pages/Demo';
import Workspace from './pages/Workspace';
import Billing from './pages/Billing';
import Guide from './pages/Guide';
import { mutate } from './api';
import { useSession } from './session';
import { ErrorNotice } from './components/UI';

class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <div className="container page"><div className="panel"><h1>This page could not be displayed.</h1><p>Please reload the app. Your saved analyses remain in the workspace.</p><a className="button primary" href="/">Reload app</a></div></div>;
    return this.props.children;
  }
}
function RouteFocus() {
  const { pathname } = useLocation();
  useEffect(() => {
    const title = pathname === '/' ? 'Know before you merge' : pathname.slice(1).replace(/^\w/, c => c.toUpperCase());
    document.title = `BlastRadius — ${title}`;
    window.scrollTo({ top: 0 });
    document.getElementById('main')?.focus({ preventScroll: true });
  }, [pathname]);
  return null;
}
function Header() {
  const { session, originMismatch, refresh } = useSession();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  useEffect(() => { setOpen(false); }, [pathname]);
  async function logout() {
    setBusy(true); setError(null);
    try { await mutate('/api/auth/logout', 'POST'); await refresh(); navigate('/'); }
    catch (err) { setError(err instanceof Error ? err : new Error('Sign-out failed.')); }
    finally { setBusy(false); }
  }
  return <header className="site-header"><div className="container header-inner"><Link to="/" className="brand" aria-label="BlastRadius home"><span className="brand-icon"><Radar size={23} strokeWidth={1.8} /></span>BlastRadius</Link>
    <button className="icon-button mobile-menu" aria-label={open ? 'Close navigation' : 'Open navigation'} aria-expanded={open} aria-controls="main-navigation" onClick={() => setOpen(!open)}>{open ? <X /> : <Menu />}</button>
    <nav className={open ? 'main-nav is-open' : 'main-nav'} id="main-navigation" aria-label="Main navigation" onKeyDown={e => { if (e.key === 'Escape') setOpen(false); }}>
      <NavLink to="/demo">Product demo</NavLink><NavLink to="/guide">Documentation</NavLink><NavLink to="/pricing">Pricing</NavLink>
      {session?.authenticated && <NavLink to="/history">History</NavLink>}
      <NavLink className="nav-cta" to="/dashboard">{session?.authenticated ? 'Workspace' : 'Get started'}<ArrowUpRight size={15} aria-hidden="true" /></NavLink>
      {session?.authenticated && <button className="text-button" disabled={busy || originMismatch} title={originMismatch ? 'Sign-out requires the configured application origin.' : undefined} onClick={() => { void logout(); }}>{busy ? 'Signing out…' : 'Sign out'}</button>}
    </nav>
  </div><div className="container"><ErrorNotice error={error} /></div></header>;
}
export default function App() {
  return <><a className="skip-link" href="#main">Skip to content</a><Header /><RouteFocus /><main id="main" tabIndex={-1}>
    <ErrorBoundary><Routes><Route path="/" element={<Landing />} /><Route path="/demo" element={<Demo />} />
      <Route path="/dashboard" element={<Workspace />} /><Route path="/history" element={<Workspace />} />
      <Route path="/pricing" element={<Billing publicPage />} /><Route path="/billing" element={<Billing />} /><Route path="/guide" element={<Guide />} />
      <Route path="*" element={<div className="container page"><h1>Page not found</h1><p>This route does not exist.</p><Link to="/" className="button primary">Back to home</Link></div>} />
    </Routes></ErrorBoundary>
  </main><footer className="site-footer"><div className="container footer-grid"><div><Link className="brand" to="/"><Radar size={23} aria-hidden="true" />BlastRadius</Link><p>Know the path before you merge.</p><span className="footnote">Static evidence. Explicit limitations.</span></div><nav aria-label="Footer navigation"><Link to="/demo">Product demo</Link><Link to="/guide">Documentation</Link><Link to="/pricing">Plans</Link><Link to="/guide#privacy">Privacy & security</Link><a href="https://github.com/Mighiana/BlastRadius" target="_blank" rel="noreferrer"><GitBranch size={15} aria-hidden="true" />GitHub<ArrowUpRight size={14} aria-hidden="true" /></a></nav></div><div className="container footer-bottom"><span>Built for infrastructure reviewers.</span><span>Billing: test mode only</span></div></footer></>;
}
