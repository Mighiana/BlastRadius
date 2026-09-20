# Workspaces, roles and invitations

Persisted/API role values are lowercase: `owner`, `admin`, `developer`, `viewer`.
Migration 0002 converts legacy `member` to `developer`. UI labels may capitalize
them; mutations must use the API values.

| Action | Owner | Admin | Developer | Viewer |
|---|---|---|---|---|
| Read workspace projects/results/history/usage/policy | Yes | Yes | Yes | Yes |
| Run/delete analyses | Yes | Yes | Yes | No |
| Create/edit/archive/delete projects | Yes | Yes | No | No |
| Edit workspace name | Yes | Yes | No | No |
| Edit entitled policies | Yes | Yes | No | No |
| List team/invitations, revoke invitations/remove nonowners | Yes | Yes | No | No |
| Invite or change nonowner roles (Team+) | Yes | Yes | No | No |
| Grant/manage owner role (Team+ for role changes) | Yes | No | No | No |
| Read plan identity/billing placeholder | Yes | No | No | No |
| Delete workspace | Yes | No | No | No |
| Assign beta plan | Operator CLI only | No | No | No |

The last owner cannot be demoted or removed. Owner transfer promotes a current
member before demoting the old owner. Role/quota mutations serialize through the
workspace lock. Membership is checked on every request; removal revokes access
without waiting for session expiration. A foreign tenant ID returns 404.

Invitations require Team/Enterprise and reserve a seat for seven days. The
creator receives a copyable link once and manually delivers it; there is no
email provider integration. Store only SHA-256 of a 32-byte cryptographic random
token. Subsequent list/audit reads never reveal it. A link can be revoked and
accepted only once, by a logged-in OIDC user with a verified matching email.
Role grants exclude owners. Acceptance locks the workspace, rechecks expiry,
plan/seat budget and token status, and inserts membership in the same transaction.

Creating invitations does not disclose whether the email has an account. An
already-member acceptance has the same unavailable response as an invalid link.
Demo sessions create isolated disposable users with no verified email; they
cannot impersonate real users or accept team invitations. Tests create explicit
verified fixtures internally; no such fixture endpoint exists in the service.
