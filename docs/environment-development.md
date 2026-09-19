# Development configuration worksheet

Copy [.env.example](../.env.example) to `.env`. All values in that example are
release-tooling or local PostgreSQL settings, not unverified server settings.

```dotenv
POSTGRES_DB=blastradius
POSTGRES_USER=blastradius
POSTGRES_PASSWORD=local-development-only
BLASTRADIUS_PORT=8000
BLASTRADIUS_ALEMBIC_CONFIG=
```

Confirm from the integrated server documentation:

| Setting purpose | Local value/requirement |
|---|---|
| Environment mode | Explicit development; never infer production from absent secrets |
| Database | SQLite local file in ignored `.local/`, or PostgreSQL at `db:5432` inside Compose |
| Identity | Approved local/demo identity only; not enabled on public hosts |
| Browser origin/static assets | Same-origin assets at `/app/web/dist` in container |
| Scratch/output | Per-job temporary directory, cleaned on success and failure |
| Billing | Disabled by default; no live keys |
| Limits | Small finite input/resource/job limits, not unlimited |

These are configuration requirements, not asserted environment variable names.
The server owner must supply the mapping. `.env` is trusted local configuration,
not an upload format. Never commit it. `make dev` does not deploy anything publicly.
