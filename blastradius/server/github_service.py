from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from blastradius import __version__
from blastradius.server.config import Settings
from blastradius.server.events import analysis_event
from blastradius.server.db import Database
from blastradius.server.github_api import GitHubAPI, GitHubError
from blastradius.server.github_publish import active, publish
from blastradius.server.github_types import LifecycleEvent, PullEvent
from blastradius.server.jobs import JobManager, execute
from blastradius.server.db import LeaseLost
from blastradius.server.models import (
    Analysis,
    GitHubDelivery,
    GitHubInstallation,
    GitHubRun,
    Project,
    RepositoryConnection,
)
from blastradius.server.persistence import audit, effective_policy
from blastradius.server.quotas import lock_org, quota
from blastradius.server.schemas import AnalysisInput

LOGGER = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
MAX_PENDING_DELIVERIES = 1000
RETRY_SECONDS = 30
DISPATCH_POLL_SECONDS = 2.0


def _log(event: str, **fields: str | int) -> None:
    """Delivery lifecycle log: identifiers and outcomes only, never payload or headers."""
    LOGGER.info(json.dumps({"event": event, **fields}, sort_keys=True))


class _Stopping(Exception):
    """Processing interrupted by shutdown; the delivery stays queued for the next owner."""


class GitHubService:
    def __init__(self, db: Database, settings: Settings, jobs: JobManager):
        self.db, self.settings, self.jobs = db, settings, jobs
        self.api_factory: Callable[[], GitHubAPI] = lambda: GitHubAPI(
            settings, stop=self.jobs.stopping.is_set
        )
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="github")
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.dispatcher: threading.Thread | None = None

    def recover(self) -> None:
        with self.db.session(write=True) as session:
            deliveries = list(
                session.scalars(
                    select(GitHubDelivery).where(GitHubDelivery.status == "queued")
                )
            )
            for delivery in deliveries:
                # One interruption per attempt is free; consecutive interruptions
                # consume the attempt so a crash loop still terminates.
                if delivery.error != "server_restarted":
                    delivery.attempts = max(delivery.attempts - 1, 0)
                delivery.status = "pending"
                delivery.error = "server_restarted"
                delivery.next_attempt_at = None
            for run in session.scalars(select(GitHubRun).where(GitHubRun.status == "pending")):
                analysis = session.get(Analysis, run.analysis_id) if run.analysis_id else None
                if (
                    analysis is None
                    or analysis.status in ("queued", "running")
                    or (analysis.status == "failed" and analysis.error == "server_restarted")
                ):
                    run.analysis_id = None
                    run.error = "server_restarted"
                else:
                    run.status, run.error = "ready", "server_restarted"

    def start(self, stop: threading.Event) -> None:
        """Dispatch persisted deliveries while this process holds the service lease."""
        if not self.settings.github_enabled or self.dispatcher is not None:
            return

        def loop() -> None:
            while not stop.is_set():
                self.wake.wait(DISPATCH_POLL_SECONDS)
                self.wake.clear()
                if stop.is_set():
                    return
                try:
                    self.dispatch_pending()
                except Exception as error:
                    _log("github.webhook_failed", stage="dispatch", error=type(error).__name__)

        self.dispatcher = threading.Thread(target=loop, name="github-dispatch", daemon=True)
        self.dispatcher.start()
        self.wake.set()

    def shutdown(self, deadline: float) -> None:
        # Deliveries not yet started stay queued in the database for the next owner.
        self.jobs.draining.set()
        self.wake.set()
        if self.dispatcher is not None:
            self.dispatcher.join(timeout=5)

    def receive(
        self,
        delivery_id: str,
        digest: str,
        event: str,
        payload: PullEvent | LifecycleEvent | None,
    ) -> dict[str, str]:
        """Durably record a verified delivery, then dispatch it if this process may.

        For supported pull_request and installation events, an identical body has
        the same action, head/base SHAs, and updated_at, so it is a GitHub
        redelivery of the same event and yields the same deterministic GitHubRun.
        Deduplicating it cannot drop a distinct event.

        The caller answers 2xx only after this returns, i.e. after the commit.
        """
        _log("github.webhook_received", delivery_id=delivery_id, github_event=event)
        if payload is None:
            _log("github.webhook_processed", delivery_id=delivery_id, status="ignored")
            return {"status": "ignored"}
        try:
            with self.db.intake() as session:
                delivery = session.get(GitHubDelivery, delivery_id)
                if delivery and delivery.body_hash != digest:
                    raise HTTPException(409, "github_delivery_conflict")
                if not delivery:
                    delivery = session.scalar(
                        select(GitHubDelivery).where(GitHubDelivery.body_hash == digest)
                    )
                if delivery:
                    if (
                        delivery.status == "rejected"
                        and delivery.error == "github_payload_unavailable"
                        and payload is not None
                    ):
                        delivery.status = "pending"
                        delivery.error = None
                        delivery.next_attempt_at = None
                        delivery.payload = payload.model_dump_json()
                        delivery.attempts = 0
                        delivery_id = delivery.id
                    elif delivery.status == "retryable":
                        if delivery.payload is None and payload is not None:
                            delivery.status, delivery.error, delivery.next_attempt_at = (
                                "pending",
                                None,
                                None,
                            )
                            delivery.payload = payload.model_dump_json()
                            delivery_id = delivery.id
                        else:
                            _log("github.webhook_duplicate", delivery_id=delivery_id)
                            return {"status": "duplicate"}
                    else:
                        _log("github.webhook_duplicate", delivery_id=delivery_id)
                        return {"status": "duplicate"}
                else:
                    backlog = (
                        session.scalar(
                            select(func.count())
                            .select_from(GitHubDelivery)
                            .where(
                                GitHubDelivery.status.in_(("pending", "retryable", "queued"))
                            )
                        )
                        or 0
                    )
                    if backlog >= MAX_PENDING_DELIVERIES:
                        _log(
                            "github.webhook_failed",
                            delivery_id=delivery_id,
                            error="github_backlog_full",
                        )
                        raise HTTPException(503, "github_backlog_full")
                    session.add(
                        GitHubDelivery(
                            id=delivery_id,
                            body_hash=digest,
                            event=event,
                            status="pending",
                            attempts=0,
                            payload=payload.model_dump_json() if payload is not None else None,
                        )
                    )
        except IntegrityError:
            _log("github.webhook_duplicate", delivery_id=delivery_id)
            return {"status": "duplicate"}
        except SQLAlchemyError:
            _log("github.webhook_failed", delivery_id=delivery_id, error="intake_unavailable")
            raise HTTPException(503, "github_intake_unavailable") from None
        _log("github.webhook_persisted", delivery_id=delivery_id, github_event=event)
        return self.dispatch(delivery_id)

    def dispatch_pending(self) -> int:
        """Claim due deliveries in arrival order; stops at the first one that must wait."""
        dispatched = 0
        while self.db.lease_healthy() and not self.jobs.draining.is_set():
            now = time.time()
            try:
                with self.db.session(write=True) as session:
                    delivery = session.scalar(
                        select(GitHubDelivery)
                        .where(
                            or_(
                                GitHubDelivery.status == "pending",
                                (GitHubDelivery.status == "retryable")
                                & (GitHubDelivery.attempts < MAX_ATTEMPTS)
                                & (GitHubDelivery.next_attempt_at <= now),
                            )
                        )
                        .order_by(GitHubDelivery.created_at, GitHubDelivery.id)
                        .limit(1)
                        .with_for_update(skip_locked=True)
                    )
                    if delivery is None:
                        return dispatched
                    if delivery.status == "retryable":
                        delivery.status, delivery.next_attempt_at = "pending", None
                    delivery_id = delivery.id
            except LeaseLost:
                return dispatched
            if self.dispatch(delivery_id)["status"] == "deferred":
                return dispatched
            dispatched += 1
        return dispatched

    def dispatch(self, delivery_id: str) -> dict[str, str]:
        if not self.db.lease_healthy() or self.jobs.draining.is_set():
            return self._deferred(delivery_id, "service_lease_unavailable")
        with self.lock:
            reserved = False
            try:
                with self.db.session(write=True) as session:
                    delivery = session.scalar(
                        select(GitHubDelivery)
                        .where(GitHubDelivery.id == delivery_id)
                        .with_for_update()
                    )
                    if delivery is None:
                        return {"status": "queued"}
                    if delivery.status != "pending":
                        return {
                            "status": delivery.status
                            if delivery.status in ("handled", "ignored", "rejected")
                            else "queued"
                        }
                    try:
                        payload = (
                            PullEvent.model_validate_json(delivery.payload or "")
                            if delivery.event == "pull_request"
                            else LifecycleEvent.model_validate_json(delivery.payload or "")
                        )
                    except ValidationError:
                        # Recorded before payloads were persisted; only a redelivery can help.
                        delivery.status, delivery.error = "rejected", "github_payload_unavailable"
                        delivery.payload = None
                        return self._failed(delivery_id, "github_payload_unavailable")
                    claim: dict = {}
                    if isinstance(payload, LifecycleEvent):
                        self._lifecycle(session, delivery.event, payload)
                        delivery.status, delivery.payload = "handled", None
                        status = "handled"
                    else:
                        claim = self._claim(session, delivery, payload)
                        status = claim["status"]
                        reserved = status == "queued"
                        if status == "deferred":
                            return self._deferred(delivery_id, "analysis_queue_full")
                        if status == "rejected":
                            return self._failed(delivery_id, "github_attempts_exhausted")
            except LeaseLost:
                if reserved:
                    self.jobs.slots.release()
                return self._deferred(delivery_id, "service_lease_lost")
            except SQLAlchemyError:
                if reserved:
                    self.jobs.slots.release()
                self.wake.set()
                return self._deferred(delivery_id, "database_unavailable")
            except BaseException:
                if reserved:
                    self.jobs.slots.release()
                raise
            if not isinstance(payload, PullEvent) or not reserved:
                _log("github.webhook_processed", delivery_id=delivery_id, status=status)
                return {"status": status}
            try:
                self.jobs.track(
                    self.executor.submit(
                        self._run,
                        delivery_id,
                        claim["connection_id"],
                        payload,
                        claim["root"],
                        claim["policy"],
                    )
                )
            except RuntimeError:
                self.jobs.slots.release()
                try:
                    with self.db.session(write=True) as session:
                        delivery = session.get(GitHubDelivery, delivery_id)
                        if delivery and delivery.status == "queued":
                            delivery.status = "pending"
                            delivery.attempts = max(delivery.attempts - 1, 0)
                except LeaseLost:
                    pass
                except SQLAlchemyError:
                    pass
                self.wake.set()
                return self._deferred(delivery_id, "service_stopping")
            return {"status": "queued"}

    def _failed(self, delivery_id: str, error: str) -> dict[str, str]:
        _log("github.webhook_failed", delivery_id=delivery_id, status="rejected", error=error)
        return {"status": "rejected"}

    def _deferred(self, delivery_id: str, reason: str) -> dict[str, str]:
        _log("github.webhook_deferred", delivery_id=delivery_id, reason=reason)
        return {"status": "deferred"}

    def _lifecycle(self, session: Session, event: str, payload: LifecycleEvent) -> None:
        installation = session.get(GitHubInstallation, payload.installation.id)
        if not installation:
            return
        if event == "installation" and payload.action in ("deleted", "suspend"):
            installation.status = "deleted" if payload.action == "deleted" else "suspended"
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

    def _claim(self, session: Session, delivery: GitHubDelivery, payload: PullEvent) -> dict:
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
            delivery.status, delivery.payload = "ignored", None
            return {"status": "ignored"}
        org = lock_org(session, project.organization_id)
        policy = effective_policy(org, project)
        if not self.jobs.reserve():
            return {"status": "deferred"}
        delivery.attempts += 1
        if delivery.attempts > MAX_ATTEMPTS:
            self.jobs.slots.release()
            delivery.status = "rejected"
            delivery.error = "github_attempts_exhausted"
            delivery.payload = None
            return {"status": "rejected"}
        delivery.status = "queued"
        return {
            "status": "queued",
            "connection_id": connection.id,
            "root": project.terraform_root,
            "policy": policy,
        }

    def _run(
        self,
        delivery_id: str,
        connection_id: str,
        payload: PullEvent,
        root: str,
        policy: dict,
    ) -> None:
        status: str | None = "handled"
        error: str | None = None
        try:
            self.process(connection_id, payload, root, policy, delivery_id)
        except (LeaseLost, _Stopping):
            status = None
        except GitHubError as exc:
            if exc.code == "service_stopping":
                status = None
            else:
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
                if status is None:
                    # Left queued: the next lease holder's recover() re-arms it.
                    _log("github.webhook_deferred", delivery_id=delivery_id, reason="service_stopping")
                else:
                    with self.db.session(write=True) as session:
                        delivery = session.get(GitHubDelivery, delivery_id)
                        if delivery:
                            delivery.status, delivery.error = status, error
                            if status == "retryable":
                                if delivery.attempts >= MAX_ATTEMPTS:
                                    delivery.status = "rejected"
                                    status = "rejected"
                                    delivery.next_attempt_at = None
                                    delivery.payload = None
                                else:
                                    delivery.next_attempt_at = (
                                        time.time() + RETRY_SECONDS * delivery.attempts
                                    )
                            else:
                                delivery.payload = None
                    _log(
                        "github.webhook_processed" if status == "handled" else "github.webhook_failed",
                        delivery_id=delivery_id,
                        status=status,
                        **({"error": error} if error else {}),
                    )
            except LeaseLost:
                _log("github.webhook_deferred", delivery_id=delivery_id, reason="service_lease_lost")
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
                        status="pending",
                    )
                    session.add(run)
                if run.status == "pending" and run.analysis_id is None:
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
                        analysis_event(session, job, "analysis_started")
                        audit(session, org.id, "github", "github.analysis", job.id)
                analysis_id, run_status = run.analysis_id, run.status
            if run_status == "pending" and analysis_id:
                response: dict
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
                    response = execute(
                        inputs, self.settings, policy, self.db.lease_healthy, self.jobs.stopping
                    )
                    active(self.db, connection_id)
                except GitHubError as exc:
                    if exc.code == "service_stopping":
                        raise _Stopping
                    response = {"error": exc.code}
                except Exception:
                    response = {"error": "github_analysis_failed"}
                if (
                    isinstance(response, dict)
                    and response.get("error") == "server_restarted"
                    and self.jobs.stopping.is_set()
                ):
                    raise _Stopping
                self.jobs.finish(analysis_id, response, run_id)
        if self.jobs.stopping.is_set():
            raise _Stopping
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
