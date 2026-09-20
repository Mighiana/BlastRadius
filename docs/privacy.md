# Privacy policy template — LEGAL REVIEW REQUIRED

**Draft only. Not an effective policy or a claim of compliance.**
Owner/counsel must approve the actual service, controller identity, jurisdictions,
subprocessors and implemented data lifecycle before publication.

## Information to complete

- Controller/legal entity, business address and verified privacy contact.
- Effective date, countries served, processing geography and representative
  requirements.
- Identity provider, hosting/database, monitoring, email and billing processors
  actually used; no provider should be listed merely because it is planned.
- Legal bases, contractual obligations, international transfer mechanism,
  retention periods, rights-request process and complaint authority as applicable.
- Cookie/session/analytics inventory; do not add an unnecessary tracking promise.

## Proposed product-specific disclosure

The service may process account/organization membership, project metadata,
uploaded Terraform/plan inputs, resource topology, analysis results, timestamps
and usage. Plans can contain credentials or other sensitive values; users should
minimize submitted data and avoid private inputs in public demonstrations.

Commercial-beta intake additionally stores name/email, optional bounded workflow
details and the agreed notice version. Analysis feedback links a usefulness
response and optional text to the authenticated user/workspace/project/analysis.
Authorized platform operators can review these records across tenants; ordinary
workspace roles cannot access that review surface. Free text is not automatically
scrubbed, and submission does not send email or grant access.

First-party activity contains fixed event names, timestamps and optional UUID
references, without source, tokens, email/name, IP or browser fingerprints.
There is no browser ingestion endpoint or third-party analytics integration.
Commercial records expire from views after 90 days; physical deletion requires
operator cleanup. Event capacity also removes oldest rows at 100,000.
The [commercial data inventory](data-lifecycle.md#commercial-beta-records)
and [API contract](beta-api.md) define the implemented boundaries; approve the
lawful basis and exact notice before accepting real submissions.

Specify what raw input is stored, what is only processed temporarily, whether
reports include source evidence, who can access each category, and whether
automated analysis uses any third-party AI service. Do not imply inputs are never
retained or never shared until the implementation and providers prove that.

Document purposes separately: delivering analysis, access control, abuse defense,
support and any approved billing. Do not repurpose customer infrastructure data
for training/marketing without an explicit lawful approved policy.

## Retention, deletion and rights

Use the [data lifecycle](data-lifecycle.md) inventory to choose exact periods.
State live-database deletion timing, backup expiry/recovery behavior, external
GitHub artifacts/comments and legally required billing-record exceptions.
Do not promise immediate deletion everywhere.

Define authentication for access/correction/export/deletion requests, who may
act for an organization, response process and appeals where required.
State breach notification handling under applicable law without inventing
unimplemented operational guarantees.

**Launch blockers:** unidentified controller/contact, unapproved subprocessors,
undefined retention and untested deletion. Keep this draft visibly labeled until
resolved. No GDPR/CCPA or other certification/compliance claim is made.
