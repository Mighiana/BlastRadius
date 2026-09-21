# Google sign-in for private-beta testers

The hosted beta uses Google as its OpenID Connect provider and the Google OAuth
consent screen is deliberately left in **Testing** mode. In Testing mode only
e-mail addresses listed as *test users* can sign in; everyone else sees Google's
"access blocked" page before BlastRadius is ever reached. That is the beta's
allow-list, so do **not** publish the consent screen while the beta is private.

## Per-tester checklist

```text
tester e-mail (a Google account or Google Workspace address)
  → add as OAuth test user                (owner, Google Cloud console)
  → send the BlastRadius URL + beta welcome (owner)
  → tester signs in once                  (tester)
  → confirm first sign-in                 (owner: tester appears under users)
```

Then continue with [the private-beta checklist](private-beta-checklist.md).

## Owner steps: add a test user

1. Open <https://console.cloud.google.com/> and select the project that owns the
   BlastRadius OAuth client (the one whose client ID is in `BR_OIDC_CLIENT_ID`).
2. Go to **APIs & Services → OAuth consent screen** (Google now also labels this
   **Google Auth Platform → Audience**).
3. Confirm **Publishing status: Testing**.
4. Under **Test users** choose **Add users**, enter the tester's e-mail address
   exactly as they will sign in with, and save. Google allows at most 100 test
   users per project; that is far above the 5–10 people this beta targets.
5. Send the tester `https://blastradius-hulf.onrender.com` together with
   [the beta welcome](beta-welcome.md). Tell them the first page may take about a
   minute to load while the free instance wakes up.
6. After they sign in, confirm the sign-in from the operator side: the user is
   listed by the trusted CLI (`BR_ADMIN_ENABLED=true blastradius-admin inspect users`)
   or the `/api/admin` inspection routes, and appears in the workspace they created.

Removing a tester: delete the address from **Test users** (blocks new sign-ins)
and, if their data must go, follow the deletion steps in
[data-lifecycle.md](data-lifecycle.md). Existing BlastRadius sessions expire on
their own schedule; sign-out or session cleanup ends them sooner.

## Behaviour to expect in Testing mode

- The Google consent page shows the app name with a "Google hasn't verified this
  app" notice for some accounts. That is normal for Testing mode.
- BlastRadius only requests `openid email profile`; no Google API access is
  granted and no refresh tokens are stored, so the 7-day refresh-token limit of
  Testing mode does not affect BlastRadius sessions.
- Google Workspace administrators may block third-party apps for their domain;
  a tester from such a domain needs their admin to allow the client ID.

## Later: making sign-in public

Only when the beta is opened to people who are not individually invited, work
through this owner checklist:

1. Decide the allow-list replacement first. Without Testing mode anyone with a
   Google account can sign in, so BlastRadius needs its own gate (invitation
   codes, an approved-domain list or operator approval) before publishing.
2. Complete the consent screen:
   - [ ] App name.
   - [ ] User support email.
   - [ ] Developer contact information.
3. Configure the authorized domain. Google requires an authorized domain that
   the owner controls. `blastradius-hulf.onrender.com` cannot be added as an
   authorized domain because the owner does not control `onrender.com`.
   Therefore a custom domain that the owner controls is a prerequisite for
   publishing. This is a public-beta owner action.
4. Configure the redirect and public URLs:
   - Authorized redirect URI:
     `https://<BR_PUBLIC_URL host>/api/auth/callback`
   - Homepage: the custom `BR_PUBLIC_URL`.
   - Privacy policy: `https://<BR_PUBLIC_URL host>/privacy`.
   - Terms of service: `https://<BR_PUBLIC_URL host>/terms`.
5. Confirm that the OAuth scope is limited to `openid`, `email`, and `profile`.
   Remove test users when the public gate is ready, then publish the consent
   screen.
6. Set the production variables:

   ```text
   BR_AUTH_MODE=oidc
   BR_OIDC_ISSUER=https://accounts.google.com
   BR_OIDC_CLIENT_ID=...
   BR_OIDC_CLIENT_SECRET=...
   BR_PUBLIC_URL=...
   ```

   `BR_PUBLIC_URL` must match the owner-controlled custom domain used for the
   homepage and callback.
7. Re-run the sign-in acceptance from [the checklist](private-beta-checklist.md)
   with an account that was never a test user.

None of these steps is performed automatically by BlastRadius or its deployment
blueprint.
