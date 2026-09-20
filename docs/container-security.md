# Container security assessment

Assessed 2026-09-20 on Linux amd64 with Trivy 0.74.0, vulnerability database v2
updated `2026-09-20T07:08:21.474120123Z`. **Promotion remains blocked.** Database
HIGH/CRITICAL findings remain unfixed; an empty application scan does not establish
absence of vulnerabilities. In particular, application zlib has a carried-forward
MEDIUM finding that Alpine's scanner feed omits.

## Evidence and inventory

The [complete JSON ledger](https://app.devin.ai/attachments/47fca95b-8838-4c32-a1a9-86247d2016aa/ledger.json)
preserves all **428 supplied package-level rows** (152 app, 276 database), plus all
245 rebuilt-image rows. No duplicates, lower severities, or UNKNOWN rows are
discarded. Each row records CVE, binary/source package, installed/fixed versions,
image/stage, runtime scope, advisory, relevance, uncertainty, remediation and
residual risk. Source/CVE groups explain repeated library/meta-package findings;
they do not replace the package rows.

The [full Markdown inventory](https://app.devin.ai/attachments/38bf10f2-ec01-448e-ac1b-b2da1ea08b7d/vulnerabilities.md)
is a readable companion. Raw rebuilt scans:
[application](https://app.devin.ai/attachments/c48d2090-fa4e-45ef-91e1-22489586b39d/app.json),
[database](https://app.devin.ai/attachments/6712c7b7-3ee8-48b5-b41d-d53e2231b4e0/database.json),
[scanner provenance](https://app.devin.ai/attachments/731463b2-d33e-44eb-b817-d1e77381aa13/scanner.json).
These are organization-accessible audit attachments. The ledger embeds all six
input hashes, scanner versions and complete package inventories. Scanner JSON is
version/database provenance, not an additional image vulnerability scan.

| Image | Phase | CRITICAL | HIGH | MEDIUM | LOW | UNKNOWN | Total |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| App | Supplied | 0 | 44 | 49 | 57 | 2 | 152 |
| App | Rebuilt, scanner-reported | 0 | 0 | 0 | 0 | 0 | 0 |
| Database | Supplied | 1 | 61 | 89 | 119 | 6 | 276 |
| Database | Rebuilt | 1 | 54 | 80 | 104 | 6 | 245 |

Both rebuilt image secret scans and the repository secret scan passed. These
counts are scanner output, not a count of all actual vulnerabilities. The ledger's
`carried_forward_findings` separately retains application `CVE-2026-85091` at its
supplied MEDIUM severity with the new zlib version.

Local image index digests (not published to a registry):

```text
blastradius:container-hardening
sha256:c5ff267354f89cb1d3c8f48af470532537d9077fbe74bea160bb18293a46a00d
blastradius-postgres:container-hardening
sha256:ef3407d92be22a544e7aa4789303cdc9c601460c565a271563a1294c37637076
```

These images contain the application at `5c832771b9e6ee467b35fdf49aeba3d3242921b4`
plus this Dockerfile change. Integration must rebuild/rescan after combining other
contributions. Multi-architecture indexes are pinned, but only amd64 was tested.
Base digests do not lock floating transitive Python dependencies; the recorded
inventory and exact built image digest identify what was assessed.

## Changes and vendor evidence

The [Dockerfile](../Dockerfile) pins all bases by digest. Official image tag data
was checked in the Docker library's [Python](https://github.com/docker-library/official-images/blob/master/library/python)
and [PostgreSQL](https://github.com/docker-library/official-images/blob/master/library/postgres)
manifests before choosing them.

| Stage | Immutable base |
| --- | --- |
| Database | `postgres:16.15-trixie@sha256:a3b7f434b2dc57ce85a67e171163eb8ab1a1ebcb39d27484661f26b1dfbe30d6` |
| Frontend build | `node:24.19.0-bookworm-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df` |
| Python build and runtime | `python:3.12.14-alpine3.24@sha256:c4634f578a412db396771b61b064c6e546c9d6414c7fb5b1b05d5871f1885f7b` |

Python now uses supported Alpine 3.24/musl, with matching build/runtime stages.
Debian glibc/account/package-management tooling is no longer in the app image.
No application dependency pins changed. Python headers, config build data,
ensurepip, pip and caches are removed from the final image. Installed package
metadata is preserved; APK and dpkg databases are explicitly verified by smoke
checks. Node/compiler tools remain outside the final application image.

Vendor evidence is version-bound in
[container-security-assessments.json](container-security-assessments.json). It
never changes scanner severity or the promotion policy:

* Alpine's [security database](https://secdb.alpinelinux.org/v3.24/main.json)
  records fixes through util-linux `2.42.3-r1` for `CVE-2026-76642`,
  `CVE-2026-78408`, `CVE-2026-78409`, `CVE-2026-78410` and `CVE-2022-0563`.
  Only `libuuid` from that source is installed in the application.
* Application ncurses `6.6_p20260516-r0` is beyond the upstream fixed ranges for
  [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720)
  and [CVE-2025-6141](https://security-tracker.debian.org/tracker/CVE-2025-6141).
  `infocmp` is absent. This differs from Debian's older installed ncurses.
* Alpine explicitly fixes `CVE-2026-27171` in zlib `1.3.2-r0`, but
  [CVE-2026-85091](https://security-tracker.debian.org/tracker/CVE-2026-85091)
  includes zlib 1.3.2 in its affected range. Its
  [APKBUILD](https://gitlab.alpinelinux.org/alpine/aports/-/raw/3.24-stable/main/zlib/APKBUILD)
  has no corresponding patch. Non-blocking `gzwrite` followed by
  `gzprintf`/`gzvprintf` with stale buffers is the reported prerequisite.
  Application reachability is unproven, not ruled out; retain this residual risk.
* `bzip2recover` is absent from the application; only `libbz2` remains.
  The ledger distinguishes the vulnerable utility from source-related packages.

The database retains its existing supported PostgreSQL major, libc, UID and
volume format. GnuPG key-import tools are purged after image construction, removing
7 HIGH package rows and other findings. Package metadata remains intact. Existing
removal of unused `gosu` and the distribution's default snakeoil private key is
preserved. Required libraries and restore tools remain installed.

## Remaining database blockers

All these HIGH/CRITICAL rows have **no fixed version in the supplied/current Trivy
Debian records**. Reduced privileges constrain some prerequisites; they do not
justify suppressions or severity reductions.

| CVEs | Installed package/source | Relevance and residual risk |
| --- | --- | --- |
| `CVE-2026-6653` (CRITICAL), `CVE-2026-74860`, `CVE-2026-86138`, `CVE-2026-86139`, `CVE-2026-86140`, `CVE-2026-86142`, `CVE-2026-86143`, `CVE-2026-86144` | libxml2 `2.12.7+dfsg+really2.9.14-2.1+deb13u3` | PostgreSQL links XML and can expose SQL XML functions. Application queries do not intentionally use XML, but SQL access/future changes can expose it. Python binding/xmlcatalog advisories have different prerequisites from core XML code. |
| `CVE-2026-76642`, `CVE-2026-78408`, `CVE-2026-78409`, `CVE-2026-78410` | util-linux source `2.41.5-0+deb13u1`, nine binary packages per CVE | Mount/nsenter privileged operations. Dropped capabilities and no-new-privileges constrain execution; source findings also flag libraries that do not contain the vulnerable utility. |
| `CVE-2025-69720` | ncurses `6.5+20250216-2`, four packages | `infocmp` overflow; Debian Trixie remains vulnerable while newer upstream/unstable versions are fixed. Shared library and terminfo rows are source associations, not four independently proven call paths. |
| `CVE-2026-16742` | systemd `257.13-1~deb13u1`, libsystemd0/libudev1 | Libraries installed; this does not show that the affected systemd service is running. Reachability unproven. |
| `CVE-2026-54369` | libacl1 `2.3.2-2+b1` | Filesystem ACL operations and advisory privilege/path prerequisites require separate call-path analysis. |
| `CVE-2026-9538` | Perl `5.40.1-6+deb13u1`, four packages | Interpreter/modules support packaging tools; removing them indiscriminately can break database helpers. No claim of request-path nonexploitability. |

The full ledger also itemizes all 80 MEDIUM, 104 LOW and 6 UNKNOWN remaining
database rows, including zlib, SQLite, PAM, Kerberos, LDAP, compression, C library
and terminal issues. UNKNOWN is retained as uncertainty, never treated as safe.

## Alternatives evaluated

* **Debian Trixie update/purge:** supplied images already used current supported
  patched base tags. Removing GnuPG was safe; a simulated PAM removal would also
  remove required util-linux dependencies. Do not delete libraries, essential
  packages or package metadata to make scanning quiet.
* **Official PostgreSQL 16.15 Alpine 3.24:** scanned without OS findings, but
  libxml2 `2.13.9-r2` security metadata documents `CVE-2026-6732`, not the supplied
  high libxml2 advisories affecting versions before 2.15.4. An empty different
  distribution feed is insufficient remediation evidence. It also changes
  PostgreSQL's libc/collation behavior. Rejected.
* **Official PostgreSQL 16.15 Bookworm:** pulled and scanned; still reports
  critical `CVE-2026-6653` for libxml2 `2.9.14+dfsg-1.3~deb12u6`. Its unmodified
  base has 16 CRITICAL/99 HIGH rows including extra base tooling. It does not solve
  the blocker; these counts are not a like-for-like hardened-image comparison.
* **Chainguard minimal PostgreSQL:** the available immutable public `latest`
  (`sha256:18b4fa98035d553204c4409a104b5839e3235a276a4b961589e67457eef55265`)
  reports PostgreSQL 18.6; public `:16` returned manifest unknown. The vendor
  [documentation](https://images.chainguard.dev/directory/image/postgres/overview)
  describes authenticated specific versions and collation migration differences.
  A major data migration or new registry provisioning is outside this change.
* **Debian unstable or custom source-built PostgreSQL/libxml2:** sid/forky has
  fixes for some packages, but mixing unsupported package sets or maintaining an
  untracked private build is not a supported drop-in remedy. Reconsider only with
  maintained provenance, a compatible database plan and complete validation.

## Runtime and integration contract

The app still uses UID/GID `10001`, installed `/opt/venv` packages and the same
`serve`/`migrate` entrypoint. Database UID/GID remains `999`; existing PostgreSQL
volumes and `pg_dump`/`pg_restore` commands remain compatible. Compose is unchanged:
read-only root, dropped capabilities, no-new-privileges, bounded resources, writable
temporary/data paths, and health checks. Production requires the existing explicit
auth/settings, trusted origin and migration setup; the smoke harness uses isolated
development/demo settings and disposable test-only credentials.

The application does not include a source checkout, Node, git, compilers or pip.
The database retains PostgreSQL utilities, dpkg metadata and its required libraries.
`BR_AUTO_MIGRATE=false`, readiness, missing-config exit 2 and invalid-command exit 2
remain intact. SAFE/BLOCK semantics are unchanged. BlastRadius is a static modeled
analyzer; its passing user-facing statement is “No new modeled blocking findings
detected.” Container checks provide no security certification.

## Reproduce

Use Python 3.12, Node 24, Docker and Trivy. Preserve the original three supplied
files as `before/app.json`, `before/database.json`, `before/scanner.json`.

```bash
.venv/bin/python -m pytest
make check frontend wheel
mkdir -p .local/audit
docker buildx build --load --target runtime -t blastradius:local \
  --metadata-file .local/audit/app-build.json .
docker buildx build --load --target database -t blastradius-postgres:local \
  --metadata-file .local/audit/database-build.json .
bash scripts/verify-containers.sh blastradius:local blastradius-postgres:local
make container-audit secret-audit
.venv/bin/python scripts/container_ledger.py \
  --before-app before/app.json --before-database before/database.json \
  --before-scanner before/scanner.json \
  --after-app .local/audit/app.json --after-database .local/audit/database.json \
  --after-scanner .local/audit/scanner.json \
  --assessments docs/container-security-assessments.json \
  --output .local/audit/ledger.json --markdown .local/audit/vulnerabilities.md
make promotion-check
```

The last command is expected to **fail** until HIGH/CRITICAL findings are resolved.
No ignore file, `--ignore-unfixed`, severity adjustment or policy change was added.
Future package/version changes invalidate the optional manual assessments
automatically; re-review vendor evidence instead of extending a waiver.

Verified: 999 Python tests passed/11 skipped; 30 release tests; Ruff/mypy; docs;
94 frontend tests, lint, typecheck and production build; wheel integration;
Python/npm dependency audits; both image builds, vulnerability/secret scans and unchanged promotion failure
(`make` exit 2). Container smoke passed migration `0001` → current head `0003`,
idempotent migration, dump/restore with preserved data, psycopg binary operation,
nine installed-worker cases, readiness/static UI, non-root/read-only operation,
absent build tools, package metadata and entrypoint failures.

No browser, live AWS, hosted auth, cross-architecture or discarded build-stage
vulnerability testing is represented by these results. The host kernel is outside
the image scans. Rebuild, rerun the ledger and require the unchanged promotion
gate after integration or vendor updates; do not promote this database image.
