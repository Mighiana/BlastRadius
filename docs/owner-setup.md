# Owner setup and release acceptance

This checklist covers deployment preparation, domain, OIDC, GitHub App and
operations readiness (brief phases 20–24). Local tests and the synthetic restore
drill are preparation evidence. Hosting, domain ownership, real provider
configuration, legal approval and live acceptance still require the owner.
No accounts, paid resources, public deployments or live provider writes are
created by these instructions.

Record an accountable person and an access-controlled evidence reference for each
gate. Never put credentials, customer dumps or private keys in the checklist.

## 1. Release and hosting decision

- [ ] Select a [deployment pattern](deployment-patterns.md) and approved geography.
  Assign release, database, identity, GitHub and incident owners; record the support
  route and backup contact. One person may hold several roles.
- [ ] Record source SHA, application/model version, immutable app and DB image
  digests, migration head, dependency inventory and the previous reviewed image.
- [ ] Run the [scan gate](deployment.md#scan-evidence-and-promotion-gate) on the
  final images. The documented baseline still has HIGH/CRITICAL findings and
  fails promotion; local recovery success does not waive that gate.
- [ ] Confirm the service supports a single process/replica, no overlapping
  rollout, bounded scratch, nonroot/read-only execution, a migration job, shutdown
  grace and private DB access. No infrastructure has been provisioned here.
- [ ] Approve data geography, terms/privacy, subprocessors, retention/deletion,
  incident notification and support ownership before accepting customer data.

## 2. Domain and TLS

- [ ] Choose and control the exact application origin. Replace **every**
  `app.example.com` in the [origin worksheet](environment-production.md#domains-and-origins)
  with that same owned hostname. Decide whether marketing/docs need separate hosts.
- [ ] Publish DNS to the approved ingress, issue/verify the certificate and chain,
  redirect HTTP to HTTPS, and monitor certificate renewal/expiry. Keep database
  and backend ports private. Do not point public DNS at this session.
- [ ] Set `BR_PUBLIC_URL` explicitly; preserve its host at the ingress and health
  probe. Test unexpected Host rejection and cross-origin mutation rejection through
  the real ingress without broadening CORS or forwarding trust.
- [ ] Check `/health/live` and `/health/ready` from the ingress and operator network.
  Production TLS/DNS/certificate monitoring remain unverified until these steps run.

## 3. Identity provider

- [ ] Register a confidential web client with a trusted provider using the exact
  [OIDC worksheet](auth.md#provider-registration-worksheet): issuer, client ID,
  secret reference, callback and `openid email profile`.
- [ ] Apply the provider's beta-user access policy and require verified email there
  if your onboarding policy needs it. BlastRadius keys identity by issuer/subject;
  unverified or missing email is discarded rather than becoming a login allowlist.
- [ ] Provision stable session signing and OIDC client secrets via the secret
  manager; assign renewal/revocation ownership. Never put them in Vite/build inputs.
- [ ] Through actual HTTPS, test login, callback, refreshed session/CSRF, denied
  state/nonce/issuer, session revocation and application logout. Verify Secure,
  HttpOnly and SameSite cookies. Test the provider's allowed/denied beta accounts.
- [ ] Record that application logout does not log out the provider. Configure
  provider SSO expiry/revocation separately; there is no implemented global logout.

## 4. GitHub App

- [ ] Create an owner-managed GitHub.com App with the exact
  [registration fields and minimum permissions](github.md#operator-setup).
  Choose the owning account, unique App name/slug, homepage and selected repos.
- [ ] Set the HTTPS webhook URL, shared secret, pull request subscription and
  lifecycle handling; leave GitHub-user OAuth/setup callbacks unused.
- [ ] Mount the downloaded RSA key privately for the app UID; record App ID,
  slug, secret references, installation ID and account ID without recording secrets.
- [ ] Independently verify workspace-owner authority over the GitHub account and
  record the nonsecret approval reference. Run the local `github-register` command,
  then let the workspace owner/admin connect the selected repository.
- [ ] With separately approved test-repository writes, verify signed delivery,
  a new-head analysis/check/comment, deduplication, required-check behavior, removed
  repositories and revoked installations. Local mocks do not establish live results.
- [ ] Assign an operator for failed delivery redelivery, uncertain publication,
  key rotation and installation revocation. Never give tenants the operator flag.

## 5. Operations and cutover

- [ ] Configure PostgreSQL with verified TLS, encrypted storage, a migration owner
  and a nonowner runtime role. Apply/review DML and schema-use grants after each
  migration; runtime may read but may not mutate `alembic_version`.
- [ ] Approve backup/log retention, recovery point and recovery time objectives;
  configure encrypted off-host backups/PITR, separate recovery credentials and
  tested restore access. Run the [local drill](operations.md#local-postgresql-restore-drill),
  then an isolated provider restore and deletion replay. Record measured timings.
- [ ] Install bounded report cleanup, backup completion/age alarms, readiness/error
  and disk/WAL/scratch alerts, certificate monitoring and incident routing. Trigger
  a controlled alarm to verify delivery; a documented schedule is not automation.
- [ ] Follow [drain and rollback](operations.md#release-drain-and-rollback), migrate
  once with ingress closed, start the runtime identity and verify readiness.
- [ ] Complete actual HTTPS/OIDC/tenant and GitHub acceptance; assign the final
  owner go/no-go decision. Keep traffic closed if any mandatory gate is unresolved.

## Outstanding external evidence

Until owners record completion above, the release lacks live hosting/network/TLS,
OIDC and GitHub acceptance, provider backup/PITR and disaster recovery evidence,
installed monitoring/retention schedules, and legal/operating approval. The image
promotion findings remain a separate release blocker. This document neither
asserts production readiness nor security certification.
