import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { request, sessionSchema, setCsrf, type Session } from './api';

const Context = createContext<{
  session: Session | null; error: Error | null; loading: boolean; originMismatch: boolean; refresh: () => Promise<void>;
} | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const pending = useRef<Promise<void> | null>(null);
  const refresh = useCallback(() => {
    if (pending.current) return pending.current;
    setLoading(true);
    pending.current = request('/api/me', sessionSchema).then(next => {
      setCsrf(next.csrf_token);
      setSession(next);
      setError(null);
    }).catch((err: unknown) => {
      setSession(null);
      setCsrf('');
      setError(err instanceof Error ? err : new Error('Session could not be loaded.'));
    }).finally(() => {
      pending.current = null;
      setLoading(false);
    });
    return pending.current;
  }, []);
  useEffect(() => {
    void refresh();
    const listener = () => { void refresh(); };
    window.addEventListener('br:session-refresh', listener);
    return () => window.removeEventListener('br:session-refresh', listener);
  }, [refresh]);
  const originMismatch = !!session && new URL(session.auth.public_url).origin !== window.location.origin;
  return <Context value={{ session, error, loading, originMismatch, refresh }}>{children}</Context>;
}
export function useSession() {
  const context = useContext(Context);
  if (!context) throw new Error('Session provider missing.');
  return context;
}
