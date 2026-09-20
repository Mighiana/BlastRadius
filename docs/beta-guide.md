# BlastRadius private-beta guide

**Your Terraform diff shows what changed. BlastRadius shows what became reachable.**

BlastRadius is for Terraform reviewers who want to understand how a proposed
AWS change alters modeled exposure and access to sensitive resources. Platform
engineers, cloud security teams, small SaaS engineering teams and consultancies
can evaluate it alongside their existing review and security tools.

The recommended starting point is a small, authorized AWS Terraform root in a
GitHub repository. Evaluate synthetic inputs first. This guide describes the
current implementation; it does not announce a public service, paid subscription
or completed hosted-provider acceptance.

On an operator-approved deployment, **Request beta access** opens `/beta`. Review
the privacy notice and explicitly consent before submitting. The saved response
means the request was stored for operator review; it is not an account, invitation
or confirmation email. Do not submit Terraform, credentials or private
infrastructure details. Account access uses the configured OIDC provider.

## Start with a known example

1. Open the [customer sample](customer-samples.md) and its generated reports.
   Compare the one-line SSH edit, the path evidence and the remediation rerun.
2. Run its installed-CLI commands locally, or follow
   [getting started](getting-started.md) for the integrated local application.
   Use Python 3.12, Node 24.19.0, Git and Make for that developer setup.
3. In a project, choose **HCL files** and provide **Baseline** and **Candidate**
   snapshots of one Terraform root. Baseline is the reference configuration;
   candidate is the proposed change. Labels help identify them later.
4. Select **Analyze change**. Read decision, responsible change, source diff,
   Before/After graph, per-hop evidence, coverage diagnostics and remediation.
5. After reviewing a supported patch, submit repaired files as another comparison.
   Return to project history to review the saved result. Download JSON/Markdown;
   saved SARIF requires an operator-granted entitlement. Public-demo SARIF and
   CLI SARIF do not require a paid account. There is no payment checkout.

The application also accepts already-produced **Plan JSON**, as does the CLI.
Generate it only in a trusted Terraform environment, review its contents before
sharing, and retain the prior/proposed snapshots needed for comparison. The
analyzer does not create the plan. Source patch generation is unavailable for
plan input.

## What works, and what remains limited

The static model covers selected security-group ingress, EC2 attachments,
instance profiles, IAM-to-S3 relationships, bucket public exposure and sensitivity
classification. It produces decisions, explainable paths, coverage diagnostics
and JSON/Markdown/SARIF reports. Local remediation handles a limited set of HCL
edits such as the sample's administrative CIDR; it does not repair arbitrary IAM.

Read the exact [coverage table](coverage.md), [limitations](limitations.md) and
[security model](security-model.md). Unexpanded modules, unresolved expressions,
unknown plan values, unsupported resources and analysis budgets can prevent a
complete result. There is no live AWS discovery, drift check, full routing,
effective-IAM evaluation, cross-account path analysis or universal AWS coverage.
GitHub Enterprise and aggregation across Terraform roots are not supported.

| Result | How to act |
|---|---|
| BLOCK CHANGE | Review new evidence and policy violations, repair the candidate, rerun. |
| REVIEW REQUIRED | Resolve coverage diagnostics or seek human review. Do not interpret a zero count or high score as safety. |
| SAFE TO MERGE | Read as “No new modeled blocking findings detected.” Check coverage and existing exposure; this does not certify the infrastructure. |
| Error / failed analysis | No merge-safety conclusion is available. Diagnose and rerun. |

CLI exit 0 passes its configured gate; by default that can include REVIEW.
Use `--fail-on-review` for a strict CI gate. BLOCK and strict REVIEW exit 1;
usage/input errors exit 2. The existing JSON `passed` boolean is insufficient
for approval: REVIEW can carry `passed: true`. Check decision, completeness and
exit code. See the [reproducible REVIEW example](customer-samples.md#expected-decisions-and-interpretation).

## Submit Terraform safely

Use synthetic or customer-approved inputs you are authorized to analyze. Minimize
the root to what is needed for the question. Do not upload credentials, access
tokens, private keys, state files, customer identifiers or unnecessary sensitive
values from plans. Terraform source, plan JSON and reports can expose internal
architecture, names, ARNs and policy details even without obvious secrets.

Review files locally before submission. If needed, construct a minimal synthetic
reproduction with the same relationships; do not remove the very condition or
reference being investigated and then treat that as identical evidence.
Keep private inputs in an approved local or controlled CI environment until
the operator has confirmed identity, access, retention and deletion arrangements.
Demo authentication is for local development, not private customer onboarding.

Uploads are bounded UTF-8 file maps or plan JSON. The current UI accepts up to
30 `.tf` files per snapshot, simple filenames, a 1 MiB full request and
300 resources per snapshot. These service bounds differ from the
[CLI engine budgets](coverage.md#fixed-analysis-budgets). Split inputs only when
the resulting analysis still includes the relationships you need to assess.

BlastRadius treats candidate source as data. It does not execute Terraform,
providers, module downloads, candidate programs or repository workflows. It
does not accept arbitrary URL analysis inputs. This boundary does not eliminate
all parsing or hosting risks. Read [data lifecycle](data-lifecycle.md) before
sending private data; downloaded reports, CI artifacts and comments have their
own access and retention rules.

## GitHub integration

Two paths exist; use the documented path approved for your evaluation:

- **Actions:** follow [GitHub Actions onboarding](github-actions.md). The reviewed
  workflow runs the installed analyzer against base/head data and uses trusted
  base policy. Keep analyzer and Action SHA pins reviewed. Preserve exit codes;
  add strict REVIEW gating where required. Inspect the summary/artifacts when
  token restrictions prevent a comment. Do not change to `pull_request_target`
  to obtain write permissions. Set a required check after confirming its name
  and successful delivery on your own controlled repository.
- **GitHub.com App:** the [operator-managed integration](github.md) requires
  provider configuration, installation ownership verification, operator workspace
  registration and an owner/admin project connection. An installation URL alone
  does not complete authorization. Only complete SAFE analysis produces a
  successful App check; REVIEW/BLOCK/errors fail it. Provider behavior has mocked
  coverage; new live installation/webhook/comment acceptance remains an operator
  task, not a promise made by this guide.

Historical same-repository Actions acceptance does not establish fork/private
repository or current App acceptance. Neither workflow authorizes a merge by
itself; repository branch protection and team review still govern merging.
No AWS credentials are needed for static analysis.

## Report an incorrect finding

Use a non-sensitive [project issue](https://github.com/Mighiana/BlastRadius/issues).
Include:

- Analyzer revision/version and whether you used CLI, local UI, Actions or App.
- Minimal synthetic BEFORE/AFTER inputs and the policy/strict-mode settings.
- Expected decision versus actual decision, completeness diagnostics and exit.
- The resource addresses, relationship and source evidence you believe are wrong.
- A redacted report or relevant excerpt and why the actual AWS controls differ.

Do not post a real customer plan or private report publicly. Distinguish an
incorrect modeled relationship from an AWS control the model explicitly excludes.
Security vulnerabilities follow the private route below.

## Report a missing relationship

Provide a synthetic minimal example: resource types, their Terraform references,
which direction access should flow, and why. Describe the expected path and any
relevant IAM conditions or network prerequisites. Include diagnostics, the input
adapter and exact revision. State whether this blocks evaluation or is an
optional coverage request. Unsupported cases need review; absence of a graph
edge is not proof of absent access.

## Feedback and support

Use **Give feedback** on a retained completed or failed analysis for a Yes/No
usefulness response and optional short message. Feedback is private operator
review content under the 90-day policy; keep infrastructure and secrets out.
Use [project issues](https://github.com/Mighiana/BlastRadius/issues) for non-sensitive
product questions. Explain your review workflow, what decision
you were trying to make, what confused you, and what evidence was missing.
The [interview questionnaire](customer-interview.md) can structure a conversation.
The [commercial API contract](beta-api.md) describes storage and deletion limits.

For vulnerabilities, follow [SECURITY.md](../SECURITY.md): use GitHub private
vulnerability reporting if enabled; otherwise request a private contact route
in a minimal issue without including sensitive or exploit details. Do not send
credentials. The [support page](support.md) records the current limits; a verified
private support channel and response commitments must be agreed before
commercial onboarding. There is no asserted support email, SLA or certification.
