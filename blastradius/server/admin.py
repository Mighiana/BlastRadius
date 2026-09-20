import argparse
import json

from sqlalchemy import select

from blastradius.server.config import Settings
from blastradius.server.db import Database
from blastradius.server.github_api import GitHubError
from blastradius.server.github_routes import register_installation
from blastradius.server.models import Analysis, Organization, Project, User
from blastradius.server.persistence import audit, cleanup
from blastradius.server.plans import PLANS
from blastradius.server.quotas import lock_org, usage_payload
from blastradius.server.schemas import EnterpriseLimits


def assign_plan(
    db: Database,
    organization_id: str,
    plan: str,
    limits: EnterpriseLimits | None = None,
) -> dict:
    if plan not in PLANS or (limits is not None and plan != "enterprise"):
        raise ValueError("invalid plan or limits")
    with db.session(write=True) as session:
        org = lock_org(session, organization_id)
        old = org.plan
        org.plan = plan
        org.plan_limits = limits.model_dump() if limits else None
        audit(
            session,
            org.id,
            "operator",
            "plan.assigned",
            org.id,
            {
                "before": old,
                "after": plan,
                "limits": org.plan_limits,
            },
        )
        return usage_payload(session, org)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Local operator administration; no payment processing."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    assign = commands.add_parser("assign-plan")
    assign.add_argument("organization_id")
    assign.add_argument("plan", choices=list(PLANS))
    assign.add_argument(
        "--limits", help="Enterprise limits as a JSON object; all four fields required"
    )
    inspect = commands.add_parser("inspect")
    inspect.add_argument(
        "resource", choices=["users", "organizations", "projects", "failures", "usage"]
    )
    inspect.add_argument("--limit", type=int, default=100)
    inspect.add_argument("--offset", type=int, default=0)
    clean = commands.add_parser("cleanup")
    clean.add_argument("--limit", type=int, default=100)
    github = commands.add_parser(
        "github-register", help="Operator-verified workspace/account mapping"
    )
    github.add_argument("organization_id")
    github.add_argument("installation_id", type=int)
    github.add_argument("account_id", type=int)
    github.add_argument("--verification-reference", required=True)
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if not settings.admin_enabled:
        parser.error("set BR_ADMIN_ENABLED=true in the trusted operator environment")
    db = Database(settings)
    try:
        if not db.ready():
            parser.error("migrate database first")
        if args.command == "assign-plan":
            limits = EnterpriseLimits.model_validate_json(args.limits) if args.limits else None
            print(json.dumps(assign_plan(db, args.organization_id, args.plan, limits)))
        elif args.command == "cleanup":
            print(json.dumps({"removed": cleanup(db, args.limit)}))
        elif args.command == "github-register":
            try:
                print(
                    json.dumps(
                        register_installation(
                            db,
                            settings,
                            args.organization_id,
                            args.installation_id,
                            args.account_id,
                            args.verification_reference,
                        )
                    )
                )
            except (GitHubError, ValueError):
                parser.error(
                    "registration rejected; verify operator mapping, App setup and permissions"
                )
        else:
            if not 1 <= args.limit <= 1000 or args.offset < 0:
                parser.error("limit must be 1..1000 and offset nonnegative")
            with db.session(write=True) as session:
                audit(
                    session,
                    None,
                    "operator",
                    "operator.inspect",
                    args.resource,
                    {
                        "limit": args.limit,
                        "offset": args.offset,
                    },
                )
                if args.resource == "users":
                    output = [
                        {
                            "id": row.id,
                            "name": row.name,
                            "email": row.email,
                            "email_verified": row.email_verified,
                        }
                        for row in session.scalars(
                            select(User).order_by(User.id).limit(args.limit).offset(args.offset)
                        )
                    ]
                elif args.resource in ("organizations", "usage"):
                    output = [
                        {"id": row.id, "name": row.name, **usage_payload(session, row)}
                        for row in session.scalars(
                            select(Organization)
                            .order_by(Organization.id)
                            .limit(args.limit)
                            .offset(args.offset)
                        )
                    ]
                elif args.resource == "projects":
                    output = [
                        {
                            "id": row.id,
                            "organization_id": row.organization_id,
                            "name": row.name,
                            "archived_at": row.archived_at,
                        }
                        for row in session.scalars(
                            select(Project)
                            .order_by(Project.id)
                            .limit(args.limit)
                            .offset(args.offset)
                        )
                    ]
                else:
                    output = [
                        {
                            "id": row.id,
                            "organization_id": row.organization_id,
                            "project_id": row.project_id,
                            "error": row.error,
                        }
                        for row in session.scalars(
                            select(Analysis)
                            .where(Analysis.status == "failed")
                            .order_by(Analysis.created_at.desc())
                            .limit(args.limit)
                            .offset(args.offset)
                        )
                    ]
                print(json.dumps(output))
    finally:
        db.engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
