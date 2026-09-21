# Private-beta acceptance checklist (per tester)

Copy this block once per invited tester. Owner steps are marked (O), tester
steps (T). Nothing below is a production-readiness claim; it confirms that one
invited person can use the hosted beta end to end.

```text
Tester: ______________________   Invited: ____-__-__   Workspace: ______________

[ ] tester authorized for OIDC          (O) e-mail added as Google OAuth test user
                                            docs/oidc-beta-testers.md
[ ] URL and welcome sent                (O) https://blastradius-hulf.onrender.com
                                            + docs/beta-welcome.md
[ ] sign-in successful                  (T) Google consent → BlastRadius shows the
                                            signed-in workspace page
[ ] workspace created                   (T) name visible in the header switcher
[ ] project created                     (T) project appears in the workspace list
[ ] first analysis completed            (T) "Try the example" or own Terraform;
                                            status reaches succeeded or failed
                                            (never stuck in running > 2 min)
[ ] result understandable               (T) tester can say in one sentence what
                                            the decision means and which change
                                            caused it — write their sentence down
[ ] exports work                        (T) JSON and Markdown download
[ ] history persists                    (T) sign out, sign back in: same
                                            workspace, project and analysis
[ ] feedback mechanism available        (T) "Was this useful?" on the result is
                                            saved; (O) row visible via
                                            GET /api/admin/feedback or
                                            blastradius-admin inspect feedback
[ ] no sensitive data unexpectedly logged (O) hosted logs for the tester's
                                            request IDs show only method,
                                            endpoint, status, duration, IDs;
                                            no Terraform, tokens, cookies, e-mails
[ ] tester knows how to report problems (T) docs/beta-welcome.md "Reporting"
[ ] validation questions answered       (T) docs/beta-feedback-form.md

Notes / blockers:
```

## Owner sign-off for the cohort

```text
[ ] every tester above has all boxes ticked or a recorded blocker
[ ] hosted /health/ready returned 200 at the start of the cohort
[ ] Render free database expiry date noted; migration plan read
    (docs/database-migration.md)
[ ] app container image rescanned: 0 CRITICAL/HIGH
[ ] feedback rows reviewed weekly; expired rows cleaned
    (blastradius-admin cleanup-commercial)
```
