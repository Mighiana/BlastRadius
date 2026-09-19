from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from blastradius import __version__
from blastradius.server.config import Settings
from blastradius.server.db import Database
from blastradius.server.github_api import GitHubAPI, GitHubError
from blastradius.server.github_publish import active, publish
from blastradius.server.github_types import LifecycleEvent, PullEvent
from blastradius.server.jobs import JobManager, execute
from blastradius.server.models import (
    Analysis,
    GitHubDelivery,
    GitHubInstallation,
    GitHubRun,
    Project,
    RepositoryConnection,
)
from blastradius.server.persistence import audit, effective_policy, persist_result
from blastradius.server.quotas import lock_org, quota
from blastradius.server.schemas import AnalysisInput


class GitHubService:
    def __init__(self, db: Database, settings: Settings, jobs: JobManager):
        self.db, self.settings, self.jobs = db, settings, jobs
        self.api_factory: Callable[[], GitHubAPI] = lambda: GitHubAPI(settings)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="github")
        self.lock = threading.Lock()

    def recover(self) -> None:
        with self.db.session(write=True) as session:
            session.execute(
                update(GitHubDelivery)
                .where(GitHubDelivery.status == "queued")
                .values(status="retryable", error="server_restarted")
            )
            session.execute(
                update(GitHubRun)
                .where(GitHubRun.status == "pending")
                .values(status="ready", error="server_restarted")
            )

    def shutdown(self) -> None:
        self.executor.shutdown(wait=True)

    def accept(
        self,
        delivery_id: str,
        digest: str,
        event: str,
        payload: PullEvent | LifecycleEvent | None,
    ) -> dict[str, str]:
        with self.lock:
            return self._accept(delivery_id, digest, event, payload)

    def _accept(
        self,
        delivery_id: str,
        digest: str,
        event: str,
        payload: PullEvent | LifecycleEvent | None,
    ) -> dict[str, str]:
        reserved = False
        try:
            with self.db.session(write=True) as session:
                delivery = session.get(GitHubDelivery, delivery_id)
                if delivery and delivery.body_hash != digest:
                    raise HTTPException(409, "github_delivery_conflict")
                if not delivery:
                    delivery = session.scalar(
                        select(GitHubDelivery).where(GitHubDelivery.body_hash == digest)
                    )
                if delivery:
                    if delivery.status != "retryable" or delivery.attempts >= 3:
                        return {"status": "duplicate"}
                    delivery.attempts += 1
                    delivery.status, delivery.error = "queued", None
                    delivery_id = delivery.id
                else:
                    delivery = GitHubDelivery(id=delivery_id, body_hash=digest, event=event)
                    session.add(delivery)
                if isinstance(payload, LifecycleEvent):
                    installation = session.get(GitHubInstallation, payload.installation.id)
                    if installation:
                        if event == "installation" and payload.action in ("deleted", "suspend"):
                            installation.status = (
                                "deleted" if payload.action == "deleted" else "suspended"
                            )
                            session.execute(
                                update(RepositoryConnection)
                                .where(RepositoryConnection.installation_id == installation.id)
                                .values(status="revoked")
                            )
                        elif event == "installation_repositories" and payload.action == "removed":
                            session.execute(
                                update(RepositoryConnection)
                                .where(
                                    RepositoryConnection.installation_id == installation.id,
                                    RepositoryConnection.repository_id.in_(
                                        [repo.id for repo in payload.repositories_removed]
                                    ),
                                )
                                .values(status="revoked")
                            )
                    delivery.status = "handled"
                    return {"status": "handled"}
                if payload is None:
                    delivery.status = "ignored"
                    return {"status": "ignored"}
                connection = session.scalar(
                    select(RepositoryConnection)
                    .join(GitHubInstallation)
                    .where(
                        RepositoryConnection.repository_id == payload.repository.id,
                        RepositoryConnection.installation_id == payload.installation.id,
                        RepositoryConnection.status == "active",
                        GitHubInstallation.status == "active",
                    )
                )
                project = session.get(Project, connection.project_id) if connection else None
                if not connection or not project or project.archived_at is not None:
                    delivery.status = "ignored"
                    return {"status": "ignored"}
                org = lock_org(session, project.organization_id)
                policy = effective_policy(org, project)
                root = project.terraform_root
                connection_id = connection.id
                if not self.jobs.reserve():
                    raise HTTPException(503, "analysis_queue_full")
                reserved = True
                session.flush()
            self.executor.submit(self._run, delivery_id, connection_id, payload, root, policy)
            reserved = False
            return {"status": "queued"}
        except IntegrityError:
            return {"status": "duplicate"}
        finally:
            if reserved:
                self.jobs.slots.release()

    def _run(
        self,
        delivery_id: str,
        connection_id: str,
        payload: PullEvent,
        root: str,
        policy: dict,
    ) -> None:
        status, error = "handled", None
        try:
            self.process(connection_id, payload, root, policy, delivery_id)
        except GitHubError as exc:
            status = "retryable" if exc.retryable or exc.uncertain else "rejected"
            error = exc.code
            if exc.code == "github_installation_unavailable":
                with self.db.session(write=True) as session:
                    connection = session.get(RepositoryConnection, connection_id)
                    if connection:
                        connection.status = "revoked"
        except Exception:
            status, error = "retryable", "github_processing_failed"
        finally:
            try:
                with self.db.session(write=True) as session:
                    delivery = session.get(GitHubDelivery, delivery_id)
                    if delivery:
                        delivery.status, delivery.error = status, error
            finally:
                self.jobs.slots.release()

    def process(
        self,
        connection_id: str,
        payload: PullEvent,
        root: str,
        policy: dict,
        delivery_id: str,
    ) -> None:
        connection, installation, project = active(self.db, connection_id)
        with self.api_factory() as api:
            api.installation(installation.id, installation.account_id)
            token = api.installation_token(installation.id, connection.repository_id)
            repository = api.repository(token, connection.repository_id, installation.account_id)
            pull = api.pull(token, repository, payload.number)
            if (
                payload.installation.id != installation.id
                or payload.repository.id != repository.id
                or payload.pull_request != pull
                or payload.number != payload.pull_request.number
            ):
                raise GitHubError("github_stale_or_mismatched_event")
            run_id = hashlib.sha256(
                json.dumps(
                    [connection_id, pull.model_dump(), root, policy, __version__, "github-v1"],
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            with self.db.session(write=True) as session:
                run = session.get(GitHubRun, run_id)
                if run and run.status in ("published", "expired"):
                    return
                if not run:
                    run = GitHubRun(
                        id=run_id,
                        connection_id=connection_id,
                        pull_number=pull.number,
                        base_sha=pull.base.sha,
                        head_sha=pull.head.sha,
                        base_ref=pull.base.ref,
                        head_ref=pull.head.ref,
                        head_repository_id=pull.head.repo.id,
                    )
                    session.add(run)
                    org = lock_org(session, project.organization_id)
                    try:
                        quota(session, org, "analyses_per_month")
                    except HTTPException:
                        run.status, run.error = "ready", "analysis_quota_exceeded"
                    else:
                        job = Analysis(
                            project_id=project.id,
                            organization_id=project.organization_id,
                            created_by=connection.created_by,
                            input_type="github",
                            base_label=pull.base.ref,
                            candidate_label=pull.head.ref,
                            base_ref=pull.base.ref,
                            candidate_ref=pull.head.ref,
                            base_sha=pull.base.sha,
                            candidate_sha=pull.head.sha,
                            status="running",
                            started_at=time.time(),
                            policy_snapshot=policy,
                        )
                        session.add(job)
                        session.flush()
                        run.analysis_id = job.id
                        audit(session, org.id, "github", "github.analysis", job.id)
                analysis_id, run_status = run.analysis_id, run.status
            if run_status == "pending" and analysis_id:
                response: dict
                completed_job: Analysis | None
                try:
                    before = api.snapshot(token, repository, pull.base.sha, root)
                    after = api.snapshot(token, repository, pull.head.sha, root)
                    inputs = AnalysisInput(
                        project_id=project.id,
                        before_files=before,
                        after_files=after,
                        base_label=pull.base.ref,
                        candidate_label=pull.head.ref,
                    )
                    if len(inputs.model_dump_json().encode()) > self.settings.max_body_bytes:
                        raise GitHubError("github_source_limit")
                    active(self.db, connection_id)
                    response = execute(inputs, self.settings, policy)
                    active(self.db, connection_id)
                except GitHubError as exc:
                    response = {"error": exc.code}
                except Exception:
                    response = {"error": "github_analysis_failed"}
                with self.db.session(write=True) as session:
                    completed_job = session.get(Analysis, analysis_id)
                    run = session.get(GitHubRun, run_id)
                    if not completed_job or not run:
                        return
                    completed_job.status = "failed" if response.get("error") else "succeeded"
                    completed_job.error = response.get("error")
                    if not completed_job.error:
                        persist_result(session, completed_job, response["result"])
                    completed_job.completed_at = time.time()
                    run.status, run.error = "ready", completed_job.error
        for attempt in range(2):
            try:
                with self.api_factory() as api:
                    publish(api, self.db, run_id, self.settings)
                return
            except GitHubError as exc:
                with self.db.session(write=True) as session:
                    run = session.get(GitHubRun, run_id)
                    if run:
                        run.error = exc.code
                        if exc.code == "github_analysis_expired":
                            run.status = "expired"
                if attempt or not (exc.retryable or exc.uncertain):
                    raise
