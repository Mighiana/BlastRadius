# BlastRadius Beta — welcome

**Your Terraform diff shows what changed. BlastRadius shows what became reachable.**

You have been invited to a small private beta (5–10 people). Thank you for
trying it. This page is everything you need for your first session; the longer
[private-beta guide](beta-guide.md) has the details when you want them.

## Who this beta is for

- People who write or review **Terraform for AWS**
- Teams that review infrastructure changes as **GitHub pull requests**
- **DevOps / platform engineers** who own the review gate
- **Cloud security engineers** who are asked "is this change safe?"

If that is not you, you are still welcome — tell us what you expected instead.

## Your first 15 minutes

1. **Open the link you were sent** — `https://blastradius-hulf.onrender.com`.
   The beta runs on a free instance that sleeps when idle; the first page can
   take about a minute to appear. Wait, do not reload repeatedly.
2. **Sign in with Google.** Use the e-mail address you gave us — only invited
   addresses are allowed in. If Google says "access blocked", send us the exact
   address you tried.
3. **Create a workspace.** A workspace is your private area; nobody outside it
   can see your projects or results. Name it after your team.
4. **Create a project.** A project groups comparisons for one Terraform root or
   repository, e.g. `payments-production`.
5. **Run the example first.** In *New comparison*, press **Load the example**;
   it fills in a small baseline and a candidate that opens SSH to the internet.
   Press **Analyze change**. The result should be **BLOCK CHANGE** with one
   attack path from the internet to a sensitive S3 bucket.
6. **Read the result.** Top to bottom: the decision, the *responsible change*
   (the one line that caused it), the before/after graph, the attack path with
   evidence per hop, coverage (what the model could and could not see), and a
   suggested fix. Three decisions exist:
   - **BLOCK CHANGE** — the change creates a new modeled path or violation.
   - **REVIEW REQUIRED** — the analysis could not see everything; a human
     must look. This is *not* a pass.
   - **SAFE TO MERGE** — read it as "no new modeled blocking findings detected".
     It is not a certificate that your infrastructure is secure.
7. **Try your own change.** Paste the baseline (current) and candidate
   (proposed) `.tf` files of a *small* root, or upload a `terraform show -json`
   plan produced in your own environment. See "Before you upload" below.
8. **Tell us whether it was useful.** Every result has a **Give feedback**
   button: Yes/No plus an optional sentence. That single click is the most
   valuable thing you can do for us.

Results, projects and workspaces are still there when you sign out and back in.

## What works today

- Static analysis of Terraform HCL (baseline vs. candidate) or one plan JSON
- AWS: security-group ingress, EC2 and instance profiles, IAM-to-S3 access,
  public S3 exposure, sensitivity classification
- Explainable attack paths with per-hop evidence and the responsible change
- Coverage diagnostics that say what was not modeled
- Analysis history per project, JSON and Markdown export
- GitHub Actions workflow for pull requests (see the guide)

## What is not supported yet

- Azure, GCP, Kubernetes
- Live AWS account scanning, drift detection or effective-IAM evaluation
- Full VPC routing, cross-account paths, or the whole AWS resource catalogue
- Terraform modules that are not expanded, unresolved expressions, unknown plan
  values — these produce **REVIEW REQUIRED**, by design
- SARIF download in the web app (CLI SARIF works; web SARIF needs an entitlement)
- Payments, SAML, mobile apps

## Before you upload

- Terraform can reveal a lot about your infrastructure: names, ARNs, CIDRs,
  policies. Upload only what you are authorized to share, and keep the root small.
- **Never upload secrets**: no access keys, tokens, private keys, passwords,
  state files or customer data. Plan JSON can contain secret values — check it.
- BlastRadius **does not need AWS credentials** and never asks for them.
- Nothing is executed. Terraform, providers, modules and your code are read as
  text only.
- Free-plan results are kept **7 days**, then hidden and deleted by cleanup.
  You can delete any analysis yourself from the history list; workspace owners
  can archive projects in settings, and the operator can delete a workspace on
  request. Feedback text is kept for 90 days for the operator to read.
- Temporary files used during an analysis live in a scratch directory that is
  removed when the job finishes.

Details: [data lifecycle](data-lifecycle.md), [privacy](privacy.md).

## Reporting problems

Use a [GitHub issue](https://github.com/Mighiana/BlastRadius/issues) (public —
never paste real Terraform or a real report) or reply to the person who
invited you. Please include the analysis ID (the `analysis=` value in the page
address while a result is open) and say which
of these it is:

| What you saw | Tell us |
| --- | --- |
| **Incorrect finding** — the path is wrong | Which hop is wrong and what the real AWS control is |
| **False positive** — BLOCK on something that is fine | Why the change is acceptable, and whether a policy setting should have allowed it |
| **Missing relationship** — a path you know exists was not found | The resource types and how they reference each other (a synthetic snippet is ideal) |
| **Broken analysis** — failed, stuck or REVIEW you did not expect | The status, the diagnostics shown, and roughly what the input contained |
| **UI bug** — something looks or behaves wrong | Browser, screen width, and a screenshot without sensitive data |

Security issues: follow [SECURITY.md](../SECURITY.md) instead of a public issue.

## What we can and cannot promise

This is a beta run by a very small team. We read every piece of feedback and
fix what we can, but there is **no 24/7 support, no SLA and no uptime
guarantee**. The instance may be asleep or briefly down; the free database may
be moved (with notice) before it expires. Do not rely on BlastRadius as your
only merge gate during the beta.

When you have run a few real changes, please answer the
[eleven short questions](beta-feedback-form.md).
