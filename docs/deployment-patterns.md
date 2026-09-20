# Deployment patterns for private beta

All patterns keep one application container/process, PostgreSQL, a private backend
network and one trusted HTTPS application origin. The API and built frontend ship
in the same reviewed image. Payments remain disabled. This comparison selects no
provider and authorizes no purchase or deployment.

| Pattern | Complexity | Operator responsibilities | Fit and constraints |
|---|---|---|---|
| Managed container service + managed PostgreSQL + managed TLS ingress | Lowest ongoing infrastructure work; moderate initial identity/network setup | Disable scaling/overlapping rollouts, run one migration job, mount secrets/private key, set writable scratch bounds, verify DB TLS and restore | Practical default to evaluate for beta, **only** if the service supports exactly one replica, stop-before-start deployment, adequate shutdown grace and private DB connectivity |
| Small Linux VM + container runtime + PostgreSQL + TLS reverse proxy | Simple topology; highest routine maintenance if PostgreSQL is on the VM | OS/runtime updates, firewall, certificate renewal, disk/WAL capacity, encrypted off-host backup, supervision and full host recovery | Suitable when an operator can own that work; a managed DB reduces database work but not VM maintenance. One host remains a failure domain |
| Existing conventional container cluster + managed PostgreSQL + TLS ingress | Highest complexity for a new installation; reasonable when a team already operates it | One-replica/recreate policy, singleton migration job, network policies, secret mounts, resource/shutdown limits, persistent scratch handling, cluster upgrades | Use existing expertise. Rolling updates and horizontal autoscaling are incompatible with the current queue/lease; a cluster does not make queued jobs durable |

## Common acceptance questions

Before choosing, prove that the platform can:

1. Keep exactly one ASGI process per database, stop admission and stop the old
   process before starting its successor. The service lease rejects overlap.
2. Execute `migrate` once using the release image and a migration identity, then
   `serve` using a narrower runtime identity. Gate traffic on `/health/ready`.
3. Run as UID 10001 with a read-only root, bounded writable `BR_DATA_DIR` and `/tmp`,
   CPU/memory/PID limits, and private database access with certificate verification.
4. Preserve the public `Host` through TLS termination without trusting arbitrary
   forwarded headers; use the exact origin in `BR_PUBLIC_URL`.
5. Inject runtime secrets and a regular, readable, mode-0600 GitHub PEM. A platform
   that exposes only symlink secret mounts needs a reviewed compatible mount;
   do not weaken the application's private-file check.
6. Omit callback queries, authorization headers, cookies and request bodies from
   ingress/application monitoring, and route actionable alerts to an operator.
7. Restore encrypted backups into isolation, retain a reviewed previous image,
   and provide evidence for the owner's agreed recovery objectives.

The local [Compose reference](deployment.md#postgresql-compose) is useful for
development and compatibility checks. It does not supply production TLS,
restricted DB roles, off-host backup, on-call coverage or external acceptance.

Use the [owner checklist](owner-setup.md) to record choices and approvals, the
[production worksheet](environment-production.md) for exact settings, and
[operations](operations.md) for drain, recovery and retention procedures.
