import { AlertCircle, LoaderCircle, ShieldCheck, ShieldAlert, ShieldQuestion } from 'lucide-react';
import type { ReactNode } from 'react';
import { ApiError } from '../api';

export function ErrorNotice({ error, retry }: { error: Error | null; retry?: () => void }) {
  if (!error) return null;
  return <div role="alert" className="notice error"><AlertCircle size={18} aria-hidden="true" /><div>
    <p>{error.message}</p>
    {error instanceof ApiError && error.requestId && <small>Reference: {error.requestId}</small>}
    {retry && <button type="button" className="text-button" onClick={retry}>Try again</button>}
  </div></div>;
}
export function Loading({ children = 'Loading analysis…' }: { children?: ReactNode }) {
  return <div role="status" className="loading"><LoaderCircle className="spin" size={20} aria-hidden="true" />{children}</div>;
}
export function Decision({ decision }: { decision: string }) {
  const kind = decision === 'SAFE TO MERGE' ? 'safe' : decision === 'BLOCK CHANGE' ? 'block' : 'review';
  const Icon = kind === 'safe' ? ShieldCheck : kind === 'block' ? ShieldAlert : ShieldQuestion;
  return <span className={`decision ${kind}`}><Icon size={16} aria-hidden="true" />{decision}</span>;
}
export function Empty({ title, children }: { title: string; children: ReactNode }) {
  return <div className="empty"><ShieldQuestion size={28} aria-hidden="true" /><h3>{title}</h3>{children}</div>;
}
export function PageHeading({ eyebrow, title, children }: { eyebrow: string; title: string; children?: ReactNode }) {
  return <div className="page-heading"><p className="eyebrow">{eyebrow}</p><h1>{title}</h1>{children && <p className="lede">{children}</p>}</div>;
}
