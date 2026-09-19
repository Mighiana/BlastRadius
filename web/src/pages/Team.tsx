import { useState } from 'react';
import { auditSchema, canManage, createdInvitationSchema, invitationsSchema, membersSchema, mutate, request, roleSchema, type Organization, type Role } from '../api';
import { useAction, useResource } from '../hooks';
import { useOrganization, useSession } from '../session';
import { AuthGate } from '../components/AuthGate';
import { WorkspaceNav } from '../components/WorkspaceNav';
import { ErrorNotice, Loading, PageHeading } from '../components/UI';

function Management({ org }: { org: Organization }) {
  const base = `/api/organizations/${encodeURIComponent(org.id)}`;
  const members = useResource(`${base}/members`, membersSchema);
  const [page, setPage] = useState(0);
  const invitations = useResource(`${base}/invitations?limit=20&offset=${page * 20}`, invitationsSchema);
  const [auditPage, setAuditPage] = useState(0);
  const audit = useResource(org.usage.features.audit ? `${base}/audit?limit=20&offset=${auditPage * 20}` : null, auditSchema);
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<'admin' | 'developer' | 'viewer'>('developer');
  const [invitationLink, setInvitationLink] = useState('');
  const [remove, setRemove] = useState('');
  const [roles, setRoles] = useState<Record<string, Role>>({});
  const action = useAction();
  const { refresh } = useSession();
  const entitled = org.usage.features.team;
  const reload = async () => { members.reload(); invitations.reload(); audit.reload(); await refresh(); };
  return <div className="report-stack"><section className="panel"><h2>Workspace members</h2>
    <p>Owners manage ownership. Admins manage projects and non-owner members. Developers run analyses. Viewers inspect retained evidence.</p>
    {!entitled && <p className="notice">Invitations and role changes require Team or Enterprise. Existing members remain visible.</p>}
    <ErrorNotice error={action.error} />{action.notice && <p role="status" className="notice">{action.notice}</p>}
    <ErrorNotice error={members.error} retry={members.reload} />{members.loading && <Loading>Loading members…</Loading>}
    <div className="management-list">{members.data?.members.map(member => {
      const protectedOwner = member.role === 'owner' && (org.role !== 'owner' || members.data?.members.filter(item => item.role === 'owner').length === 1);
      return <article key={member.user_id}><div><strong>{member.name}</strong><p>{member.email} · {member.role}</p>{protectedOwner && <small>Ownership protection: this owner cannot be removed or demoted here.</small>}</div>
        <div className="button-row"><label>Role for {member.name}<select disabled={action.busy || !entitled || protectedOwner} value={roles[member.user_id] ?? member.role} onChange={e => setRoles({ ...roles, [member.user_id]: roleSchema.parse(e.target.value) })}>{(['owner', 'admin', 'developer', 'viewer'] as const).filter(value => value !== 'owner' || org.role === 'owner' || member.role === 'owner').map(value => <option key={value}>{value}</option>)}</select></label>
          <button className="button secondary" disabled={action.busy || !entitled || protectedOwner || !roles[member.user_id] || roles[member.user_id] === member.role} onClick={() => { void action.run(async () => { await mutate(`${base}/members/${encodeURIComponent(member.user_id)}`, 'PATCH', { role: roles[member.user_id] }); await reload(); }, 'Member role updated.'); }}>Save role</button>
          {!protectedOwner && <button className="button danger" disabled={action.busy} onClick={() => setRemove(member.user_id)}>Remove {member.name}</button>}
        </div>{remove === member.user_id && <div className="notice confirm-delete"><span>Remove this member’s workspace access?</span><button className="button danger" disabled={action.busy} onClick={() => { void action.run(async () => { await mutate(`${base}/members/${encodeURIComponent(member.user_id)}`, 'DELETE'); setRemove(''); await reload(); }, 'Member removed.'); }}>Confirm remove member</button><button className="button secondary" onClick={() => setRemove('')}>Cancel</button></div>}
      </article>;
    })}</div>
  </section><section className="panel"><h2>Invitations</h2>
    <p>Links expire after seven days. Deliver the one-time link privately to the invited email address; the service does not send email.</p>
    {entitled && <form className="inline-form" onSubmit={e => {
      e.preventDefault(); setInvitationLink('');
      void action.run(async () => {
        const result = await request(`${base}/invitations`, createdInvitationSchema, { method: 'POST', body: JSON.stringify({ email, role }) });
        const url = new URL(result.invitation_url);
        if (url.origin !== window.location.origin || url.pathname !== '/invitations/accept') throw new Error('Invitation created, but its configured origin differs. Ask the operator to correct the public URL before inviting again.');
        setInvitationLink(url.href); setEmail(''); await reload();
      }, 'Invitation created. Deliver the link privately.');
    }}><label>Invite email<input type="email" required maxLength={320} value={email} onChange={e => setEmail(e.target.value)} /></label><label>Invitation role<select value={role} onChange={e => setRole(e.target.value === 'admin' ? 'admin' : e.target.value === 'viewer' ? 'viewer' : 'developer')}><option value="developer">Developer</option><option value="viewer">Viewer</option><option value="admin">Admin</option></select></label><button className="button primary" disabled={action.busy}>Create invitation</button></form>}
    {invitationLink && <div className="notice invitation-delivery"><label>One-time invitation link<input readOnly value={invitationLink} onFocus={e => e.target.select()} /></label><p>Copy this now. It will not appear in subsequent invitation reads.</p><button className="button secondary" onClick={() => setInvitationLink('')}>Dismiss link</button></div>}
    <ErrorNotice error={invitations.error} retry={invitations.reload} />{invitations.loading && <Loading>Loading invitations…</Loading>}
    {!invitations.loading && invitations.data?.invitations.length === 0 && <p>No invitations on this page.</p>}
    <div className="management-list">{invitations.data?.invitations.map(invite => {
      const status = invite.accepted_at ? 'Accepted' : invite.revoked_at ? 'Revoked' : invite.expires_at * 1000 <= Date.now() ? 'Expired' : 'Pending';
      return <article key={invite.id}><div><strong>{invite.email}</strong><p>{invite.role} · {status} · expires {new Date(invite.expires_at * 1000).toLocaleDateString()}</p></div>{status === 'Pending' && <button className="button secondary" disabled={action.busy} onClick={() => { void action.run(async () => { await mutate(`${base}/invitations/${encodeURIComponent(invite.id)}`, 'DELETE'); await reload(); }, 'Invitation revoked.'); }}>Revoke invitation</button>}</article>;
    })}</div><div className="pagination"><button className="button secondary" disabled={!page || invitations.loading} onClick={() => setPage(n => n - 1)}>Previous invitations</button><span>Page {page + 1}</span><button className="button secondary" disabled={invitations.loading || (invitations.data?.invitations.length ?? 0) < 20} onClick={() => setPage(n => n + 1)}>Next invitations</button></div>
  </section><section className="panel"><h2>Audit visibility</h2>{!org.usage.features.audit ? <p>Team and Enterprise include workspace audit events.</p> : <><ErrorNotice error={audit.error} retry={audit.reload} />{audit.loading && <Loading>Loading audit events…</Loading>}<div className="management-list">{audit.data?.events.map(event => <article key={event.id}><div><strong>{event.action}</strong><p>{new Date(event.created_at * 1000).toLocaleString()} · actor {event.actor ?? 'system'}</p><code>{event.target_id}</code></div></article>)}</div>{audit.data?.events.length === 0 && <p>No audit events on this page.</p>}<div className="pagination"><button className="button secondary" disabled={!auditPage || audit.loading} onClick={() => setAuditPage(n => n - 1)}>Previous events</button><span>Page {auditPage + 1}</span><button className="button secondary" disabled={audit.loading || (audit.data?.events.length ?? 0) < 20} onClick={() => setAuditPage(n => n + 1)}>Next events</button></div></>}</section></div>;
}
function TeamContent() {
  const { organization } = useOrganization();
  return <><WorkspaceNav />{organization && canManage(organization.role) ? <Management org={organization} key={organization.id} /> : <p className="notice">Member management is available to workspace owners and admins.</p>}</>;
}
export default function Team() {
  return <div className="container page"><PageHeading eyebrow="TEAM" title="The right access for each reviewer.">Manage roles, privately delivered invitations and workspace audit events.</PageHeading><AuthGate><TeamContent /></AuthGate></div>;
}
