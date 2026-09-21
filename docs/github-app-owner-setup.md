# GitHub App owner setup worksheet

This is the fill-in worksheet for the hosted beta at
<https://blastradius-hulf.onrender.com>. For protocol behavior, security
boundaries, and API details, see [GitHub App integration](github.md).

## App metadata

| GitHub App field | Enter this value |
| --- | --- |
| Suggested App name | `BlastRadius Beta` |
| Homepage URL | `https://blastradius-hulf.onrender.com` |
| Callback URL | None; the hosted flow does not use a GitHub OAuth or setup callback |
| Webhook URL | `https://blastradius-hulf.onrender.com/api/github/webhook` |
| Webhook active | On |
| SSL verification | On |

Record the owning account, App slug, numeric App ID, installation owner, and
key-rotation owner in an access-controlled operator record.

## Webhook events

Enable exactly these events for the beta App:

- Pull request
- Installation
- Installation repositories

## Permissions

Repository permissions:

| Permission | Access | Why |
| --- | --- | --- |
| Contents | Read | Required to inspect repository contents |
| Pull requests | Read/Write | Required to process PRs and publish or update PR comments |
| Checks | Read/Write | Required to publish or update checks |
| Metadata | Read | Required by GitHub App APIs |

Organization permissions: **none**.

## Secrets and private key

Generate a webhook secret of at least 32 random characters:

```bash
python -c "import secrets;print(secrets.token_urlsafe(48))"
```

Generate the private key in the GitHub App settings. Upload it to Render as a
Secret File at:

```text
/etc/secrets/github-app.pem
```

The mounted key must be a regular file. Render Secret Files can expose a
symlink, and the symlink caveat described in [GitHub App integration](github.md)
must be checked for this deployment. The owner must verify that the mounted
path is a regular file with mode `0600`. Production configuration fails closed
if the configured key path is not a regular file.

## Hosted environment variables

Set all four values together:

| Variable | Value |
| --- | --- |
| `BR_GITHUB_APP_ID` | Numeric App ID |
| `BR_GITHUB_APP_SLUG` | GitHub-generated App slug |
| `BR_GITHUB_PRIVATE_KEY_FILE` | `/etc/secrets/github-app.pem` |
| `BR_GITHUB_WEBHOOK_SECRET` | The generated webhook secret |

The production configuration rule requires all four variables to be set
together; partial GitHub App configuration is rejected.

## Operator registration

Registration is an operator-only action:

```text
blastradius-admin github-register …
```

It requires `BR_ADMIN_ENABLED=true` and must run only in a trusted operator
environment, never on the web service. After registration, the workspace owner
or administrator connects the selected repository through the normal
workspace flow.

## Live acceptance checklist

- [ ] Install the App on one test repository.
- [ ] Open a pull request.
- [ ] Expect one comment, one check, and a link to the hosted analysis.
- [ ] Push a new commit and confirm the existing comment is updated rather than
      duplicated.
- [ ] Send a forged webhook signature and expect `401` or `403`.
- [ ] Uninstall the App and confirm the installation is revoked.

Live acceptance has **not yet been performed**. Current status: **implemented
and mock-tested**. The mock regression coverage includes:

- `test_forged_signatures_do_not_queue` — signature validation;
- `test_product_milestones_and_replay_are_exactly_once` — installation mapping
  and stable processing;
- `test_head_is_rechecked_before_every_publishing_mutation` — stale-head
  behavior;
- `test_removed_provider_permissions_reject_without_work` and
  `test_permissions_removed_after_analysis_block_publication` — permissions;
- `test_uncertain_mutations_reconcile_without_duplicates` and
  `test_human_marker_not_modified_and_bot_comment_updated_on_new_head` — one
  stable comment;
- `test_status_config_csrf_and_tenant_registration_boundary` — tenant
  isolation;
- `test_forks_are_read_through_base_repo_and_never_executed` — never executing
  code.
