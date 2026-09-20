# Render deployment

This guide deploys the integrated FastAPI and React service with a Render-managed
PostgreSQL database. The repository's root `render.yaml` is the Blueprint for
this deployment.

The migration pre-deploy command is accepted whether Render preserves the
Docker entrypoint or invokes `sh /app/scripts/container-entrypoint.sh migrate`
directly.

## Create the Render resources

1. Connect or fork the GitHub repository in Render.
2. Choose **New → Blueprint**.
3. Select the branch that contains the intended release.
4. Render reads `render.yaml` and creates one web service and one PostgreSQL
   database with the declared settings.
5. In the web service environment, set `BR_PUBLIC_URL` to the exact public
   origin Render serves, for example:
   `https://<service>.onrender.com`.

`BR_PUBLIC_URL` must match the hostname used by the browser. If a custom domain
is added later, change `BR_PUBLIC_URL` and re-register the OIDC redirect URI for
that hostname before asking users to sign in.

The Blueprint leaves the public URL and OIDC values as operator-supplied
settings. Do not commit those values or any credentials to the repository.

## Configure OIDC

Google is one example provider:

1. Open Google Cloud Console.
2. Go to **APIs & Services → Credentials**.
3. Create an **OAuth client ID** for a **Web application**.
4. Add this authorized redirect URI:
   `https://<service>.onrender.com/api/auth/callback`.
5. Set the service's `BR_OIDC_ISSUER` to `https://accounts.google.com`.
6. Copy the generated client ID and secret into `BR_OIDC_CLIENT_ID` and
   `BR_OIDC_CLIENT_SECRET`.

Use the exact issuer and callback for the hostname in `BR_PUBLIC_URL`. Provider
setup screens and pricing can change; verify the current Google and Render
instructions before production use.

## Deploy and verify

Deploy the Blueprint after configuring the environment. The pre-deploy command
runs the packaged migrations, while the web process keeps
`BR_AUTO_MIGRATE=false`. Verify:

```text
https://<service>.onrender.com/health/live
https://<service>.onrender.com/health/ready
```

The live endpoint confirms that the process is serving. The ready endpoint
confirms that migrations, the service lease and demo fixtures are available.
Then open the service in a browser and complete a real OIDC sign-in.

## Zero-downtime deploy settings

Render can start the replacement container before stopping the old one. The old
process temporarily owns the database service lease, so the replacement uses
`BR_LEASE_WAIT_SECONDS=120` to remain live while retrying acquisition. During
that interval `/health/live` remains successful, `/health/ready` returns 503,
and database requests are fenced with 503 responses. Once the old process
releases the lease, the replacement completes startup and becomes ready. A
replacement that cannot acquire the lease before the deadline invokes the
startup fatal hook.

`BR_TRUST_PROXY_HEADERS=true` is enabled in the Blueprint because Render's
proxy is the sole network peer for this service. This lets Uvicorn recover the
forwarded client address and scheme for per-client rate limits. Uvicorn's proxy
middleware rewrites client and scheme information, not `Host`; the application
continues to derive cookies and Origin checks from `BR_PUBLIC_URL`. Do not set
this flag when untrusted clients can connect directly, and do not weaken the
application's Origin, CSRF or host validation.

The Blueprint deliberately configures one web instance and does not enable
autoscaling. The database lease is a single-service-process guard; additional
instances require a separate architecture and review.

## Cost and known caveats

Approximate monthly costs for the Blueprint are a Starter web service at about
$7/month and Basic-256mb PostgreSQL at about $6/month. The free PostgreSQL
option is not used because it expires after 30 days. Prices and plan behavior
are provider-controlled; verify the current Render pricing before provisioning.

The Render-managed internal database connection supplied by the Blueprint is not
configured as `sslmode=verify-full`. This is a known gap compared with
[environment-production.md](environment-production.md), which requires
certificate verification for a general production deployment. Treat the
Render connection's transport and trust model as an explicit platform caveat
and reassess it before handling higher-sensitivity data.

The exact Render Blueprint field behavior, generated-secret encoding and current
zero-downtime details were not independently verified against live Render
documentation in this repository. Confirm those provider-specific details,
current pricing and region availability in Render's documentation before
provisioning.
