# Operations and metrics

This is an operator runbook for the target service. Items requiring infrastructure
or code integration are requirements, not claims of installed monitoring.

## Startup and readiness

Use the [deployment procedure](deployment.md): migrate once, then start traffic.
Separate liveness (process can respond) from readiness (required DB/schema and
configuration are usable). Never mark failed analysis as a healthy zero-finding
result. The supplied image uses `/health/ready` for schema/demo readiness.

Set finite worker/concurrency/time/input limits. If the implementation uses
in-process work, explicitly document loss on restart; do not promise durable
queue delivery. Scaling API replicas does not solve CPU-bound graph traversal.

## Logging contract

Use structured logs with timestamp, level, event name, request/job ID, route
template, status, duration and model version. Include opaque tenant/project IDs
only when necessary and access-controlled; avoid raw names.

Never log tokens, authorization/cookie headers, keys, webhook raw bodies,
full Terraform plans or complete source by default. Redact error details before
returning them to users. Do not log database URLs containing passwords.
Keep privileged audit events separate from verbose debugging.

Optional error monitoring must remain off without credentials. Review payload
scrubbing before enabling it; stack frames can include customer data.
Do not add a Sentry DSN or pretend an error-monitoring hook exists without code.

## Metrics to implement and observe

| Signal | Why | Suggested dimensions |
|---|---|---|
| Request latency/error rate | API availability | route template, status class |
| Analysis duration and timeout count | Parser/graph saturation | input mode, model version |
| Queue wait/depth, active workers | Capacity and backpressure | worker pool |
| Input bytes/resources/path cap hits | Abuse/coverage pressure | input mode, limit type |
| Decision and incomplete counts | Result quality | decision, diagnostic category |
| Auth failures and denied tenant access | Access-control incidents | reason category |
| Database pool saturation/migration version | Storage readiness | instance |
| Scratch bytes and cleanup failures | Disk exhaustion and retention | worker |
| Usage quota rejections | Limit enforcement | plan identifier |
| Publisher/webhook retries and stale skips | Integration reliability | event category |

These are proposed metrics, not current exported metric names.
Do not use tenant IDs, resource addresses or filenames as high-cardinality metric
labels. Choose alert thresholds after load tests; no SLA/SLO is asserted here.

## Backup and recovery

Use encrypted PostgreSQL backups with restricted operator access and independently
tested restore. Record snapshot time, migration head, model/service version and
retention. Keep backup credentials separate from application credentials.

After restore: verify schema compatibility, confirm tenant-scoped reads/deletes,
reapply deletion tombstones, and check that jobs and billing/webhook deduplication
are not replayed as new writes. Recovery time and recovery point objectives
remain owner decisions, not guarantees.

## Incident workflow

1. Restrict the affected surface or pause admission; preserve redacted evidence.
2. Identify affected versions, tenants and timeframe without dumping customer plans.
3. Revoke/rotate compromised credentials through the provider's approved process.
4. Recover using a reviewed image/database procedure; do not run destructive
   rollback commands reflexively.
5. Validate isolation, readiness and delayed jobs before restoring traffic.
6. Follow approved legal/security notification obligations and record follow-up tests.

For an analysis correctness incident, retain model/input hashes when permitted,
mark affected reports for review, and never silently rewrite past decisions.
Contact routing is in [support](support.md) and [security policy](../SECURITY.md).
