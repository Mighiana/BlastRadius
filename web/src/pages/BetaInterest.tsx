import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { ApiError, request } from '../api';
import { betaInputSchema, betaPrivacySchema, betaStoredSchema } from '../beta-api';
import { useResource } from '../hooks';
import { useSession } from '../session';
import { ErrorNotice, Loading, PageHeading } from '../components/UI';

export default function BetaInterest() {
  const privacy = useResource('/api/beta-interest/privacy', betaPrivacySchema);
  const { session, loading, error: sessionError, originMismatch, refresh } = useSession();
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || saved || !privacy.data || !session || originMismatch) return;
    setUncertain(false);
    const form = new FormData(event.currentTarget);
    const value = (key: string) => String(form.get(key) ?? '');
    const number = (key: string) => value(key) === '' ? null : Number(value(key));
    const parsed = betaInputSchema.safeParse({
      name: value('name'), email: value('email'), company: value('company'), role: value('role'),
      team_size: number('team_size'), repository_count: number('repository_count'),
      primary_cloud: value('primary_cloud') || null, source_control: value('source_control') || null,
      problem: value('problem'), privacy_version: privacy.data.version, privacy_consent: form.get('consent') === 'on',
    });
    if (!parsed.success) { setError(new Error('Check your name, email, consent and optional fields. Text must be within the displayed limits and contain no control characters.')); return; }
    setBusy(true); setError(null);
    try {
      await request('/api/beta-interest', betaStoredSchema, { method: 'POST', body: JSON.stringify(parsed.data) });
      setSaved(true);
    } catch (err) { setError(err instanceof Error ? err : new Error('Could not save your request.')); setUncertain(!(err instanceof ApiError)); }
    finally { setBusy(false); }
  }
  return <div className="container page beta-page"><PageHeading eyebrow="BLASTRADIUS BETA" title="Request early access.">Tell us about your Terraform review workflow. No payment details, account creation or GitHub connection required.</PageHeading>
    {saved ? <section className="panel"><h2 role="status" tabIndex={-1} ref={element => { element?.focus(); }}>Your beta interest has been saved.</h2><p>Your request is stored for authorized operator review. This does not guarantee access or send an email.</p><Link className="button primary" to="/demo">Try the demo</Link></section>
      : <form className="panel settings-form beta-form" onSubmit={event => { void submit(event); }}>
        <ErrorNotice error={sessionError} retry={() => { void refresh(); }} />
        <ErrorNotice error={privacy.error} retry={privacy.reload} />
        {originMismatch && <ErrorNotice error={new ApiError(403, 'invalid_origin', null)} />}
        {(loading || privacy.loading) && <Loading>Preparing the privacy notice and secure session…</Loading>}
        <p id="beta-sensitive">Do not include Terraform, credentials, tokens, repository URLs or private infrastructure details. Optional fields may be left blank.</p>
        <fieldset className="form-fields" disabled={busy || loading || !session || !privacy.data || originMismatch} aria-describedby="beta-sensitive">
          <div className="form-grid"><label>Name (required, up to 100 characters)<input name="name" autoComplete="name" required maxLength={100} /></label><label>Email (required)<input name="email" autoComplete="email" type="email" required maxLength={320} /></label></div>
          <details><summary>Optional workflow details</summary><div className="form-grid">
            <label>Company (optional, up to 120 characters)<input name="company" autoComplete="organization" maxLength={120} /></label>
            <label>Role (optional, up to 80 characters)<input name="role" autoComplete="organization-title" maxLength={80} /></label>
            <label>Team size (optional)<input name="team_size" type="number" min={1} max={100000} step={1} /></label>
            <label>Terraform repositories (optional)<input name="repository_count" type="number" min={0} max={100000} step={1} /></label>
            <label>Primary cloud (optional)<select name="primary_cloud"><option value="">Prefer not to say</option>{['aws', 'azure', 'gcp', 'multiple', 'other', 'none'].map(value => <option key={value} value={value}>{value.toUpperCase()}</option>)}</select></label>
            <label>Source control (optional)<select name="source_control"><option value="">Prefer not to say</option>{['github', 'gitlab', 'both', 'other', 'none'].map(value => <option key={value} value={value}>{value}</option>)}</select></label>
          </div><label>Biggest Terraform review or security problem (optional, up to 1000 characters)<textarea name="problem" rows={4} maxLength={1000} aria-describedby="beta-sensitive" /></label></details>
          {privacy.data && <div className="notice" id="beta-privacy">{privacy.data.notice}</div>}
          <label className="check-field"><input type="checkbox" name="consent" required aria-describedby="beta-privacy" />I consent to storing these details for beta-interest review.</label>
          <button className="button primary" disabled={busy} type="submit">{busy ? 'Saving request…' : 'Save beta interest'}</button>
        </fieldset>
        <ErrorNotice error={error} />
        {uncertain && <p className="notice">If the connection was interrupted, the request may already have been saved. We do not retry automatically; submitting again may create a duplicate.</p>}
        <Link className="text-link" to="/privacy">Read the privacy information</Link>
      </form>}
  </div>;
}
