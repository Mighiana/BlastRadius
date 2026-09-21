import { useState, type FormEvent } from 'react';
import { z } from 'zod';
import { request } from '../api';
import { feedbackInputSchema, feedbackResponseSchema, feedbackSavedSchema } from '../beta-api';
import { useResource } from '../hooks';
import { useSession } from '../session';
import { ErrorNotice, Loading } from './UI';

function FeedbackForm({ analysisId, initial }: { analysisId: string; initial: z.infer<typeof feedbackResponseSchema> }) {
  const { session, originMismatch } = useSession();
  const [useful, setUseful] = useState<boolean | null>(initial.feedback?.useful ?? null);
  const [message, setMessage] = useState(initial.feedback?.message ?? '');
  const [saved, setSaved] = useState(!!initial.feedback);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !session?.authenticated || originMismatch) return;
    const parsed = feedbackInputSchema.safeParse({ useful, message });
    if (!parsed.success) { setError(new Error('Choose Yes or No and keep your message within 1000 characters without control characters.')); return; }
    setBusy(true); setError(null); setSaved(false);
    try {
      const response = await request(`/api/analyses/${encodeURIComponent(analysisId)}/feedback`, feedbackSavedSchema, { method: 'PUT', body: JSON.stringify(parsed.data) });
      setUseful(response.feedback.useful); setMessage(response.feedback.message); setSaved(true);
    } catch (err) { setError(err instanceof Error ? err : new Error('Could not save feedback.')); }
    finally { setBusy(false); }
  }
  return <form className="settings-form" onSubmit={event => { void submit(event); }}>
    <p id={`feedback-privacy-${analysisId}`}>Only authorized platform operators can review your feedback. Your account, workspace, project and analysis are associated by the server. Feedback is retained for up to 90 days in the review view; physical deletion is operator-managed. Do not include Terraform, credentials, tokens or private infrastructure details.</p>
    <fieldset disabled={busy || originMismatch || !session?.authenticated} className="form-fields" aria-describedby={`feedback-privacy-${analysisId}`}>
      <legend>Was this analysis useful?</legend>
      <div className="button-row">{[true, false].map(value => <label className="check-field" key={String(value)}><input type="radio" name={`useful-${analysisId}`} required checked={useful === value} onChange={() => { setUseful(value); setSaved(false); }} />{value ? 'Yes' : 'No'}</label>)}</div>
      <label>What was missing? (optional, up to 1000 characters)<textarea rows={3} maxLength={1000} value={message} onChange={e => { setMessage(e.target.value); setSaved(false); }} /></label>
      <button className="button secondary" disabled={useful === null || busy} type="submit">{busy ? 'Saving feedback…' : 'Save feedback'}</button>
    </fieldset>
    {saved && <p className="notice" role="status">Your feedback has been saved.</p>}
    <ErrorNotice error={error} />
  </form>;
}
function FeedbackReader({ analysisId }: { analysisId: string }) {
  const feedback = useResource(`/api/analyses/${encodeURIComponent(analysisId)}/feedback`, feedbackResponseSchema);
  return <>
    <ErrorNotice error={feedback.error} retry={feedback.reload} />
    {feedback.loading && <Loading>Loading your feedback…</Loading>}
    {feedback.data && <FeedbackForm key={analysisId} analysisId={analysisId} initial={feedback.data} />}
  </>;
}
export function AnalysisFeedback({ analysisId }: { analysisId: string }) {
  const { session } = useSession();
  const [open, setOpen] = useState(false);
  if (!session?.authenticated) return null;
  return <section className="panel feedback-panel" aria-label="Analysis feedback"><h2>Help improve BlastRadius Beta</h2>
    <p>Was this analysis useful? Share a Yes/No response and an optional note for private operator review.</p>
    <button className="button secondary" aria-expanded={open} aria-controls={`feedback-${analysisId}`} onClick={() => setOpen(!open)}>{open ? 'Close feedback' : 'Give feedback'}</button>
    <div id={`feedback-${analysisId}`}>{open && <FeedbackReader analysisId={analysisId} />}</div>
  </section>;
}
