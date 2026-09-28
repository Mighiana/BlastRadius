# Container security assessment

Assessed 2026-09-20 on Linux amd64 with Trivy 0.74.0, vulnerability database v2
updated `2026-09-20T07:08:21.474120123Z`. The database image now uses the
validated Alpine target recorded below; the current promotion gate is rerun after
each image rebuild.

## Evidence and inventory

### Historical Debian defensive security reassessment

Runtime revision `abfe328` adds the OIDC claim-provenance fix and beta/operator
deep links after the prior integrated head `5cc9257`. Both images were rebuilt
and rescanned with Trivy 0.74.0 and the same database update timestamp above.
Raw current scans:
[application](https://app.devin.ai/attachments/f7a73168-55f2-4d78-9519-ca8977649499/app.json),
[database](https://app.devin.ai/attachments/9ab00555-74ab-4264-9f69-b9800328228a/database.json),
[scanner provenance](https://app.devin.ai/attachments/4936ae52-3584-41f6-ae86-64f27b003881/scanner.json).
The [security shell evidence](https://app.devin.ai/attachments/48613f5e-db67-4065-86e4-c2cac80db482/security-shell-evidence.tar.gz)
includes the historical Debian builds, container checks, repository/image secret
scans and the then-unchanged promotion failure (make exit 2).

Current local Linux amd64 image index digests (not published):

```text
blastradius:local
sha256:41a5bcccbf6fcb9c64032f69ce758f9836a82ee5afeb0888d34d891c19888785
blastradius-postgres:local
sha256:a5b7f4a9f4305aa2affb350705551a6adae2e607351e27f11f84c3fc911b987e
```

Counts remain database **1 CRITICAL / 54 HIGH / 80 MEDIUM / 104 LOW / 6 UNKNOWN**,
application scanner-reported **0**. The separate zlib MEDIUM residual remains;
no feed silence is interpreted as a fix. Prior ledgers, source advisories and
supplied baseline findings below are retained. Runtime metadata, nonroot
operation, read-only roots, restore/migration behavior, psycopg binary support,
nine installed-worker cases and entrypoint failure behavior all passed again.
No Dockerfile, dependency, runtime policy or scanner suppression changed.
Those results are historical and are superseded by the Alpine adoption section
below. Subsequent installed-package browser acceptance at `da043fb` passed; see
[readiness](readiness.md#current-commercial-beta-browser-acceptance).

### Historical integrated Debian release reassessment

The integrated implementation at `5be27d0` was rebuilt and rescanned after all
backend/frontend/customer/operations contributions. The
[integrated JSON ledger](https://app.devin.ai/attachments/0bb0f1ae-0dd6-4eac-bd84-1a3f3df6defc/ledger.json)
and [Markdown inventory](https://app.devin.ai/attachments/f63bde6f-a8b8-48e8-b59e-af2339c8fc49/vulnerabilities.md)
retain **673 unique rows**, all 428 supplied baseline rows, 245 rebuilt database
rows and the separate zlib carried-forward finding. Counts and vendor
assessments below remain unchanged. Raw integrated scans:
[application](https://app.devin.ai/attachments/3906777f-7b3a-412c-a31d-1c2558c56e2c/app.json),
[database](https://app.devin.ai/attachments/f3204b11-3df1-494a-acd9-b302330e6b06/database.json),
[scanner provenance](https://app.devin.ai/attachments/542418c0-511f-4611-9920-0e0c7200ef4c/scanner.json).

Integrated local image index digests (no registry publication):

```text
blastradius:local
sha256:cd698f66ed62afe9713e12f677ad7e622fd5863bc685d8fb9d23636d286dab07
blastradius-postgres:local
sha256:890ea229acebe3df0619a79bd72251f1c7e82cee9ca5c40446415e2f6e06f09e
```

Both historical image builds/secret scans, repository secret scan and container smoke passed.
Smoke reached migration `0004` from `0001`, verified idempotency/data-preserving
restore, nine installed worker cases, binary psycopg, health/static assets,
nonroot/read-only roots, absent build tools and exit-2 entrypoint failures.
The historical promotion check **failed (make exit 2)** on the database
HIGH/CRITICAL findings. Full integrated shell counts and the separately tested
commercial retention/restore evidence are in [readiness](readiness.md).
Subsequent integrated local browser acceptance passed at `da043fb`, as recorded
in [readiness](readiness.md#current-commercial-beta-browser-acceptance).

### Contributor evidence before integration

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
| Database | `postgres:16.15-alpine3.23@sha256:621a761097839bdb50207afd6b87a72f38e2d718dd46c3d744828d8917c4f1e0` |
| Frontend build | `node:24.19.0-bookworm-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df` |
| Python build and runtime | `python:3.12.14-alpine3.24@sha256:c4634f578a412db396771b61b064c6e546c9d6414c7fb5b1b05d5871f1885f7b` |

Python now uses supported Alpine 3.24/musl, with matching build/runtime stages.
Debian glibc/account/package-management tooling is no longer in the app image.
No application dependency pins changed. Python headers, config build data,
ensurepip, pip and caches are removed from the final image. Installed package
metadata is preserved; APK metadata is explicitly verified by smoke checks.
Node/compiler tools remain outside the final application image.

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

The database retains its existing supported PostgreSQL major while moving to
Alpine/musl and UID/GID 70. The unused bundled `gosu` launcher is removed after
the Alpine package upgrade; package metadata remains intact and required
PostgreSQL/restore tools remain installed. Existing glibc data volumes are not
reused; use the documented logical migration before cutover.

## Historical Debian database blockers (superseded by Alpine adoption)

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

## Private-beta rescan (2026-09-21)

Both images were rebuilt from the branch head using the repository Dockerfile
targets and rescanned with Trivy 0.74.0; the binary SHA-256 was verified using
the release workflow's checksum. The totals are:

| Image | CRITICAL | HIGH | MEDIUM | LOW | UNKNOWN |
| --- | ---: | ---: | ---: | ---: | ---: |
| `python 3.12.14-alpine3.24` (app) | 0 | 0 | 0 | 0 | 0 |
| `postgres 16.15-trixie` (database) | 1 | 54 | 80 | 104 | 6 |

Of the 55 CRITICAL/HIGH rows, 51 are `affected` and 4 are `fix_deferred`;
none are `will_not_fix`, and none has a Debian fixed version. Nothing in the
database image is therefore fixable by package upgrade today. Nothing was
suppressed, and `make promotion-check` is unchanged.

### Candidate base images scanned

| Candidate | CRITICAL | HIGH | MEDIUM | LOW | UNKNOWN |
| --- | ---: | ---: | ---: | ---: | ---: |
| `postgres:16-trixie` | 2 | 82 | 110 | 121 | 7 |
| `postgres:16-alpine` | 1 | 21 | 21 | 2 | 1 |
| `postgres:16.15-alpine3.23` | 1 | 21 | 21 | 2 | 1 |
| `python:3.12-alpine` | 0 | 0 | 5 | 1 | 0 |

`postgres:16-trixie` is in the same pinned digest family and is worse.
The Alpine candidates retain CRITICAL/HIGH findings, mostly Go stdlib
findings in bundled `gosu`, plus libxml2. Trivy lists fixed versions upstream,
but the official image has not been rebuilt with them. The Alpine candidate was
later adopted after confirming that the findings are confined to the removable
bundled `gosu` launcher; its musl/collation migration is documented below.

### Complete CRITICAL/HIGH ledger

Every row below is in the final runtime database image; none is build-only.
The relevance column points to the matching package-group row in
“Remaining database blockers” above.

| CVE | Component | Installed version | Fixed version | Severity | Runtime vs build-only | Status | Relevance / remediation / residual risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CVE-2026-6653 | `libxml2` | `2.12.7+dfsg+really2.9.14-2.1+deb13u3` | `none` | CRITICAL | runtime (final stage; OS package) | affected | see libxml2 row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2025-69720 | `libncursesw6` | `6.5+20250216-2` | `none` | HIGH | runtime (final stage; OS package) | affected | see ncurses row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2025-69720 | `libtinfo6` | `6.5+20250216-2` | `none` | HIGH | runtime (final stage; OS package) | affected | see ncurses row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2025-69720 | `ncurses-base` | `6.5+20250216-2` | `none` | HIGH | runtime (final stage; OS package) | affected | see ncurses row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2025-69720 | `ncurses-bin` | `6.5+20250216-2` | `none` | HIGH | runtime (final stage; OS package) | affected | see ncurses row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-16742 | `libsystemd0` | `257.13-1~deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see systemd row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-16742 | `libudev1` | `257.13-1~deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see systemd row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-54369 | `libacl1` | `2.3.2-2+b1` | `none` | HIGH | runtime (final stage; OS package) | affected | see libacl1 row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-74860 | `libxml2` | `2.12.7+dfsg+really2.9.14-2.1+deb13u3` | `none` | HIGH | runtime (final stage; OS package) | affected | see libxml2 row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-76642 | `bsdutils` | `1:2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-76642 | `libblkid1` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-76642 | `liblastlog2-2` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-76642 | `libmount1` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-76642 | `libsmartcols1` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-76642 | `libuuid1` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-76642 | `login` | `1:4.16.0-2+really2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-76642 | `mount` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-76642 | `util-linux` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78408 | `bsdutils` | `1:2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78408 | `libblkid1` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78408 | `liblastlog2-2` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78408 | `libmount1` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78408 | `libsmartcols1` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78408 | `libuuid1` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78408 | `login` | `1:4.16.0-2+really2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78408 | `mount` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78408 | `util-linux` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78409 | `bsdutils` | `1:2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78409 | `libblkid1` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78409 | `liblastlog2-2` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78409 | `libmount1` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78409 | `libsmartcols1` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78409 | `libuuid1` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78409 | `login` | `1:4.16.0-2+really2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78409 | `mount` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78409 | `util-linux` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78410 | `bsdutils` | `1:2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78410 | `libblkid1` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78410 | `liblastlog2-2` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78410 | `libmount1` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78410 | `libsmartcols1` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78410 | `libuuid1` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78410 | `login` | `1:4.16.0-2+really2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78410 | `mount` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-78410 | `util-linux` | `2.41.5-0+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | affected | see util-linux row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-86138 | `libxml2` | `2.12.7+dfsg+really2.9.14-2.1+deb13u3` | `none` | HIGH | runtime (final stage; OS package) | affected | see libxml2 row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-86139 | `libxml2` | `2.12.7+dfsg+really2.9.14-2.1+deb13u3` | `none` | HIGH | runtime (final stage; OS package) | affected | see libxml2 row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-86140 | `libxml2` | `2.12.7+dfsg+really2.9.14-2.1+deb13u3` | `none` | HIGH | runtime (final stage; OS package) | affected | see libxml2 row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-86142 | `libxml2` | `2.12.7+dfsg+really2.9.14-2.1+deb13u3` | `none` | HIGH | runtime (final stage; OS package) | affected | see libxml2 row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-86143 | `libxml2` | `2.12.7+dfsg+really2.9.14-2.1+deb13u3` | `none` | HIGH | runtime (final stage; OS package) | affected | see libxml2 row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-86144 | `libxml2` | `2.12.7+dfsg+really2.9.14-2.1+deb13u3` | `none` | HIGH | runtime (final stage; OS package) | affected | see libxml2 row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-9538 | `libperl5.40` | `5.40.1-6+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | fix_deferred | see perl row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-9538 | `perl` | `5.40.1-6+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | fix_deferred | see perl row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-9538 | `perl-base` | `5.40.1-6+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | fix_deferred | see perl row above; remediation: vendor fix or managed PostgreSQL |
| CVE-2026-9538 | `perl-modules-5.40` | `5.40.1-6+deb13u1` | `none` | HIGH | runtime (final stage; OS package) | fix_deferred | see perl row above; remediation: vendor fix or managed PostgreSQL |

### Classification

- **Hosted deployment path:** The Render deployment uses Render-managed
  PostgreSQL; the `database` image is used only by the self-hosted
  docker-compose path. The hosted private beta therefore does not run this
  image at all; the `app` image that does run has 0 findings.
- **PRIVATE BETA:** not blocked (hosted, managed PostgreSQL, clean app image).
- **PUBLIC BETA:** not blocked for the hosted service; the adopted database
  image also passes the current CRITICAL/HIGH promotion gate.
- **PRODUCTION V1:** the hosted path remains recommended with managed
  PostgreSQL. Self-hosted distribution uses the adopted Alpine image and must
  follow the documented glibc-to-musl logical migration; do not reuse an old
  glibc data volume.
- **Re-scan cadence for beta:** re-run `make image && make container-audit`
  before each hosted deploy; a new CRITICAL/HIGH in the app image blocks the
  deploy.

## Alpine database image adopted

Adopted 2026-09-21.

The Alpine candidate was adopted after confirming that every Alpine
CRITICAL/HIGH row came from the bundled `/usr/local/bin/gosu`. The database
stage already runs as the `postgres` user and never needs privilege dropping,
so removing that launcher is the existing documented remediation, not a
suppression. The Debian candidate had no available fixes and no safely
purgeable package group; see the historical ledger above and the candidate
comparison in the private-beta rescan.

The adopted immutable base is:

```text
postgres:16.15-alpine3.23@sha256:621a761097839bdb50207afd6b87a72f38e2d718dd46c3d744828d8917c4f1e0
```

The rebuilt image scan reports zero findings in every severity category:

| Image | CRITICAL | HIGH | MEDIUM | LOW | UNKNOWN |
| --- | ---: | ---: | ---: | ---: | ---: |
| `blastradius:local` | 0 | 0 | 0 | 0 | 0 |
| `blastradius-postgres:local` | 0 | 0 | 0 | 0 | 0 |

Alpine uses musl libc and can produce different collation behavior. An existing
glibc/Trixie volume is therefore not reused: run
[`scripts/pg_migrate.sh`](../scripts/pg_migrate.sh), restore into a fresh
`postgres-alpine-data` volume so indexes are rebuilt, validate collation-sensitive
queries, and then remove the old volume deliberately. The promotion gate is
unchanged; it now passes because the adopted image contains no CRITICAL/HIGH
findings.

## Alternatives evaluated

* **Debian Trixie update/purge:** the supplied image had no Debian fixed versions
  for its 55 CRITICAL/HIGH rows, and removing relevant libraries or essential
  packages would break PostgreSQL or the base system. It was superseded by the
  Alpine adoption above.
* **Official PostgreSQL 16.15 Alpine 3.24:** scanned without OS findings, but
  libxml2 `2.13.9-r2` security metadata documents `CVE-2026-6732`, not the supplied
  high libxml2 advisories affecting versions before 2.15.4. The adopted Alpine
  3.23 image is a different candidate: its findings were confirmed to be only
  the removable bundled `gosu` component, and its musl/collation migration is
  documented above.
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
`serve`/`migrate` entrypoint. The database uses UID/GID `70`; fresh Alpine
volumes and `pg_dump`/`pg_restore` commands are supported, but existing glibc
volumes require logical migration. Compose uses:
read-only root, dropped capabilities, no-new-privileges, bounded resources, writable
temporary/data paths, and health checks. Production requires the existing explicit
auth/settings, trusted origin and migration setup; the smoke harness uses isolated
development/demo settings and disposable test-only credentials.

The application does not include a source checkout, Node, git, compilers or pip.
The database retains PostgreSQL utilities, APK metadata and its required libraries.
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

The last command must pass with the adopted image. No ignore file,
`--ignore-unfixed`, severity adjustment or policy change was added.
Future package/version changes invalidate the optional manual assessments
automatically; re-review vendor evidence instead of extending a waiver.

Before integration: 999 Python tests passed/11 skipped; 30 release tests; Ruff/mypy; docs;
94 frontend tests, lint, typecheck and production build; wheel integration;
Python/npm dependency audits; both image builds, vulnerability/secret scans and unchanged promotion failure
(`make` exit 2). Container smoke passed migration `0001` → current head `0003`,
idempotent migration, dump/restore with preserved data, psycopg binary operation,
nine installed-worker cases, readiness/static UI, non-root/read-only operation,
absent build tools, package metadata and entrypoint failures.

No browser, live AWS, hosted auth, cross-architecture or discarded build-stage
vulnerability testing is represented by these results. The host kernel is outside
the image scans. Rebuild, rerun the ledger and require the unchanged promotion
gate after integration or vendor updates.
