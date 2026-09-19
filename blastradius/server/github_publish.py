from __future__ import annotations

from pydantic import TypeAdapter, ValidationError

from blastradius.server.config import Settings
from blastradius.server.db import Database
from blastradius.server.github_api import GitHubAPI, GitHubError
from blastradius.server.github_types import Check, Checks, Comment, Repository
from blastradius.server.models import (
    Analysis,
    GitHubInstallation,
    GitHubRun,
    Organization,
    Project,
    RepositoryConnection,
)
from blastradius.server.persistence import cutoff

MARKER = "<!-- blastradius-app-result -->"
CHECK_NAME = "BlastRadius"
LIMITATIONS = (
    "Static AWS/Terraform model only; unsupported inputs require review. "
    "No candidate code, workflows, providers or modules were executed. "
    "A passing check is not proof that infrastructure is secure. "
    "The linked report requires workspace access and expires under its retention policy."
)


def active(
    db: Database, connection_id: str
) -> tuple[RepositoryConnection, GitHubInstallation, Project]:
    with db.session() as session:
        connection = session.get(RepositoryConnection, connection_id)
        if not connection or connection.status != "active":
            raise GitHubError("github_connection_revoked")
        installation = session.get(GitHubInstallation, connection.installation_id)
        project = session.get(Project, connection.project_id)
        if (
            not installation
            or installation.status != "active"
            or not project
            or installation.organization_id != project.organization_id
            or project.archived_at is not None
        ):
            raise GitHubError("github_connection_revoked")
        return connection, installation, project


def current(
    api: GitHubAPI, db: Database, run: GitHubRun, token: str, repository: Repository
) -> None:
    active(db, run.connection_id)
    pull = api.pull(token, repository, run.pull_number)
    if (
        pull.head.sha != run.head_sha
        or pull.base.sha != run.base_sha
        or pull.head.repo.id != run.head_repository_id
        or pull.base.ref != run.base_ref
        or pull.head.ref != run.head_ref
    ):
        raise GitHubError("github_stale_head")


def owned_comment(comment: Comment, settings: Settings) -> bool:
    return bool(
        comment.user.type == "Bot"
        and comment.performed_via_github_app
        and comment.performed_via_github_app.id == settings.github_app_id
        and (comment.body or "").startswith(MARKER)
    )


def summary(db: Database, run: GitHubRun, settings: Settings) -> tuple[str, str, str, str]:
    with db.session() as session:
        connection = session.get(RepositoryConnection, run.connection_id)
        assert connection is not None
        job = session.get(Analysis, run.analysis_id) if run.analysis_id else None
        project = session.get(Project, connection.project_id)
        assert project is not None
        org = session.get(Organization, project.organization_id)
        assert org is not None
        if run.created_at <= cutoff(org) or (
            run.analysis_id and (job is None or job.created_at <= cutoff(org))
        ):
            raise GitHubError("github_analysis_expired")
        url = f"{settings.public_url.rstrip('/')}/dashboard?project={project.id}"
        title, conclusion = "REVIEW REQUIRED", "failure"
        details = "Analysis unavailable. Review manually or use the safe Actions integration."
        if job:
            url = f"{settings.public_url.rstrip('/')}/dashboard?project={project.id}&analysis={job.id}"
            if job.status == "succeeded":
                title = job.decision or "REVIEW REQUIRED"
                complete = bool(job.result and job.result.get("analysis_complete") is True)
                if title == "SAFE TO MERGE" and complete:
                    conclusion = "success"
                details = (
                    f"Score: {job.score_before} → {job.score_after}. "
                    f"New critical paths: {job.critical_paths_added}; "
                    f"removed: {job.critical_paths_removed}."
                )
                if not complete and title == "SAFE TO MERGE":
                    title = "REVIEW REQUIRED"
        text = (
            f"{MARKER}\n## {title}\n\n"
            f"Commit: `{run.head_sha}`\n\n{details}\n\n"
            f"[View analysis]({url})\n\n{LIMITATIONS}"
        )
        return title, conclusion, text, url


def publish(api: GitHubAPI, db: Database, run_id: str, settings: Settings) -> None:
    with db.session() as session:
        run = session.get(GitHubRun, run_id)
        assert run is not None
    connection, installation, _ = active(db, run.connection_id)
    api.installation(installation.id, installation.account_id)
    token = api.installation_token(installation.id, connection.repository_id, write=True)
    repository = api.repository(token, connection.repository_id, installation.account_id)
    prefix = f"/repos/{repository.full_name}"
    title, conclusion, text, url = summary(db, run, settings)
    current(api, db, run, token, repository)
    checks = api.model(
        Checks,
        "GET",
        f"{prefix}/commits/{run.head_sha}/check-runs?check_name={CHECK_NAME}&filter=all&per_page=100",
        token,
    )
    if checks.total_count > 100:
        raise GitHubError("github_check_scan_limit")
    matches = [
        check
        for check in checks.check_runs
        if check.app.id == settings.github_app_id
        and check.external_id == run.id
        and check.head_sha == run.head_sha
    ]
    if len(matches) > 1:
        raise GitHubError("github_duplicate_checks")
    check_id = matches[0].id if matches else None
    if not check_id:
        if run.check_uncertain or run.check_id:
            raise GitHubError("github_check_reconciliation_required")
        current(api, db, run, token, repository)
        with db.session(write=True) as session:
            stored = session.get(GitHubRun, run_id)
            assert stored is not None
            stored.check_uncertain = True
        check = api.model(
            Check,
            "POST",
            f"{prefix}/check-runs",
            token,
            {
                "name": CHECK_NAME,
                "head_sha": run.head_sha,
                "external_id": run.id,
                "status": "in_progress",
                "details_url": url,
            },
        )
        if (
            check.app.id != settings.github_app_id
            or check.head_sha != run.head_sha
            or check.external_id != run.id
        ):
            raise GitHubError("github_check_mismatch")
        check_id = check.id
    with db.session(write=True) as session:
        stored = session.get(GitHubRun, run_id)
        assert stored is not None
        stored.check_id, stored.check_uncertain = check_id, False
    current(api, db, run, token, repository)
    api.request(
        "PATCH",
        f"{prefix}/check-runs/{check_id}",
        token,
        {
            "status": "completed",
            "conclusion": conclusion,
            "details_url": url,
            "output": {"title": title, "summary": text},
        },
    )
    comments: list[Comment] = []
    for page in range(1, 6):
        try:
            batch = TypeAdapter(list[Comment]).validate_python(
                api.request(
                    "GET",
                    f"{prefix}/issues/{run.pull_number}/comments?per_page=100&page={page}",
                    token,
                )
            )
        except ValidationError:
            raise GitHubError("github_response_invalid") from None
        comments.extend(comment for comment in batch if owned_comment(comment, settings))
        if len(batch) < 100:
            break
    else:
        raise GitHubError("github_comment_scan_limit")
    if len(comments) > 1:
        raise GitHubError("github_duplicate_comments")
    current(api, db, run, token, repository)
    if comments:
        api.request("PATCH", f"{prefix}/issues/comments/{comments[0].id}", token, {"body": text})
    else:
        # Uncertain POSTs are reconciled by reads, never blindly repeated.
        with db.session(write=True) as session:
            uncertain = (
                session.query(GitHubRun)
                .filter(
                    GitHubRun.connection_id == run.connection_id,
                    GitHubRun.pull_number == run.pull_number,
                    GitHubRun.comment_uncertain.is_(True),
                )
                .first()
            )
            if uncertain is not None:
                raise GitHubError("github_comment_reconciliation_required")
            stored = session.get(GitHubRun, run_id)
            assert stored is not None
            stored.comment_uncertain = True
        comment = api.model(
            Comment, "POST", f"{prefix}/issues/{run.pull_number}/comments", token, {"body": text}
        )
        if not owned_comment(comment, settings):
            raise GitHubError("github_comment_mismatch")
    with db.session(write=True) as session:
        for stored in session.query(GitHubRun).filter(
            GitHubRun.connection_id == run.connection_id,
            GitHubRun.pull_number == run.pull_number,
        ):
            stored.comment_uncertain = False
        stored = session.get(GitHubRun, run_id)
        assert stored is not None
        stored.status = "published"
