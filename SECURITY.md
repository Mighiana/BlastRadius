# Security policy

BlastRadius is a defensive static-analysis tool with an incomplete cloud model.
A passing result is not proof of infrastructure safety. Review coverage warnings
and use independent controls. This repository does not assert a security
certification, uptime guarantee or fully supported commercial release.

## Reporting a vulnerability

Use GitHub's private vulnerability-reporting option on the repository's
[Security page](https://github.com/Mighiana/BlastRadius/security) **if enabled**.
If private reporting is unavailable, open a minimal
[issue](https://github.com/Mighiana/BlastRadius/issues) requesting a private
contact channel without including exploit details or sensitive data.
No separate support/security email or domain is asserted.

Include privately: affected revision, deployment context, reproduction using
synthetic data, expected/observed impact and any suggested mitigation.
Never send access tokens, real customer plans, private keys or unrelated data.
Avoid testing against public demos, third-party repositories or cloud accounts
without authorization.

The maintainer must confirm a private reporting route and response policy before
commercial onboarding. No response deadline, bounty or blanket legal safe-harbor
promise is made here.

## Scope and versions

Report parser/code-execution bugs, tenant-isolation failures, authentication or
authorization bypass, unsafe file access, report XSS, denial of service,
credential leakage, webhook forgery and workflow trust-boundary violations.
Model correctness issues matter too; distinguish false findings/coverage gaps
from exploitable service vulnerabilities.

There is no announced supported-version matrix. Provide the exact commit or
image digest. Do not assume the legacy public demo, historical Actions analyzer
pin and development delivery branch run identical code.

## Operator responsibilities

Use [deployment](docs/deployment.md), [threat model](docs/threat-model.md) and
[data lifecycle](docs/data-lifecycle.md). Configure production identity, tenant
isolation, TLS, quotas, retention, backups and dependency maintenance before
accepting private customer inputs.

No candidate code or Terraform providers may run in privileged reporting jobs.
Never resolve fork-token restrictions by moving to `pull_request_target`.
Live provider writes and release publication require separate owner approval.
