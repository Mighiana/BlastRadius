from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from blastradius.server.config import Settings
from blastradius.server.db import Database, LeaseLost
from blastradius.server.events import analysis_event, terminal_events
from blastradius.server.models import Analysis, AnalysisStatus, GitHubRun, RunStatus
from blastradius.server.persistence import persist_result
from blastradius.server.results import worker_response
from blastradius.server.schemas import AnalysisInput, WorkerInput

logger = logging.getLogger("blastradius.jobs")


def execute(
    payload: AnalysisInput,
    settings: Settings,
    policy_snapshot: dict | None = None,
    lease_healthy: Callable[[], bool] | None = None,
    stopping: threading.Event | None = None,
    work_dir: Path | None = None,
) -> dict:
    jobs_dir = work_dir or settings.data_dir.resolve() / "jobs"
    jobs_dir = jobs_dir.resolve()
    jobs_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="job-", dir=jobs_dir) as directory:
        workdir = Path(directory)
        (workdir / "input.json").write_text(
            WorkerInput(analysis=payload, policy_snapshot=policy_snapshot).model_dump_json(),
            encoding="utf-8",
        )
        try:
            command = [
                sys.executable,
                "-I",
                "-m",
                "blastradius.server.worker",
                str(workdir),
                str(settings.max_resources),
                str(settings.job_timeout_seconds),
            ]
            if lease_healthy is None:
                completed = subprocess.run(
                    command,
                    cwd=workdir,
                    env={"PATH": os.defpath, "PYTHONHASHSEED": "0"},
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=settings.job_timeout_seconds,
                    check=False,
                )
                returncode = completed.returncode
            else:
                if not lease_healthy():
                    return {"error": "service_lease_lost"}
                with subprocess.Popen(
                    command,
                    cwd=workdir,
                    env={"PATH": os.defpath, "PYTHONHASHSEED": "0"},
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ) as process:
                    deadline = time.monotonic() + settings.job_timeout_seconds
                    while process.poll() is None:
                        error = (
                            "server_restarted"
                            if stopping is not None and stopping.is_set()
                            else "service_lease_lost"
                            if not lease_healthy()
                            else "analysis_timeout"
                            if time.monotonic() >= deadline
                            else None
                        )
                        if error:
                            process.kill()
                            process.wait()
                            return {"error": error}
                        try:
                            process.wait(timeout=0.1)
                        except subprocess.TimeoutExpired:
                            pass
                    returncode = process.returncode
        except subprocess.TimeoutExpired:
            return {"error": "analysis_timeout"}
        output = workdir / "output.json"
        if returncode != 0 or not output.exists():
            return {"error": "worker_failed"}
        if output.stat().st_size > 8 * 1024 * 1024:
            return {"error": "result_too_large"}
        return json.loads(output.read_text(encoding="utf-8"))


class JobManager:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self.slots = threading.BoundedSemaphore(settings.max_jobs)
        self.executor = ThreadPoolExecutor(
            max_workers=settings.workers, thread_name_prefix="analysis"
        )
        self.persistence_failed = threading.Event()
        self.draining = threading.Event()
        self.stopping = threading.Event()
        self.running: set[Future] = set()
        self.running_lock = threading.Lock()

    def recover(self) -> None:
        while True:
            with self.db.session(write=True) as session:
                rows = list(
                    session.scalars(
                        select(Analysis)
                        .where(Analysis.status.in_((AnalysisStatus.QUEUED, AnalysisStatus.RUNNING)))
                        .order_by(Analysis.id)
                        .limit(100)
                        .with_for_update()
                    )
                )
                for job in rows:
                    job.status, job.error, job.completed_at = (
                        AnalysisStatus.FAILED,
                        "server_restarted",
                        time.time(),
                    )
                    job.result, job.decision = None, None
                    terminal_events(session, job)
            if len(rows) < 100:
                break
        directory = self.settings.data_dir / "jobs"
        if directory.exists():
            for path in directory.glob("job-*"):
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)

    def reserve(self) -> bool:
        return (
            not self.draining.is_set()
            and self.db.lease_healthy()
            and not self.persistence_failed.is_set()
            and self.slots.acquire(blocking=False)
        )

    def submit(self, analysis_id: str, payload: AnalysisInput) -> None:
        try:
            self.track(self.executor.submit(self._run, analysis_id, payload))
        except Exception:
            self.finish(analysis_id, {"error": "dispatch_failed"})
            raise

    def finish(self, analysis_id: str, response: object, run_id: str | None = None) -> str:
        validated = worker_response(response)
        cause: str | None = None
        for attempt in range(3):
            try:
                with self.db.session(write=True) as session:
                    job = session.scalar(
                        select(Analysis).where(Analysis.id == analysis_id).with_for_update()
                    )
                    if not job or job.status not in (AnalysisStatus.QUEUED, AnalysisStatus.RUNNING):
                        return "deleted_or_terminal"
                    job.error = validated.get("error")
                    if not job.error:
                        persist_result(session, job, validated["result"])
                    else:
                        job.result, job.decision = None, None
                    job.status = AnalysisStatus.FAILED if job.error else AnalysisStatus.SUCCEEDED
                    job.completed_at = time.time()
                    terminal_events(session, job)
                    if run_id:
                        run = session.get(GitHubRun, run_id)
                        if run:
                            run.status, run.error = RunStatus.READY, job.error
                    outcome = job.status
                return outcome
            except LeaseLost:
                raise
            except SQLAlchemyError as error:
                cause = type(error).__name__
                self._log_persistence_error(analysis_id, attempt, error)
                validated = {"error": "worker_failed"}
                if attempt < 2:
                    time.sleep(0.05 * (attempt + 1))
            except Exception as error:
                cause = type(error).__name__
                self._log_persistence_error(analysis_id, attempt, error)
                validated = {"error": "worker_failed"}
        self.persistence_failed.set()
        logger.error(
            json.dumps(
                {
                    "event": "analysis.persistence_failed",
                    "analysis_id": analysis_id,
                    "exception": cause,
                }
            )
        )
        raise RuntimeError("terminal_persistence_failed")

    @staticmethod
    def _log_persistence_error(analysis_id: str, attempt: int, error: Exception) -> None:
        logger.warning(
            json.dumps(
                {
                    "event": "analysis.persistence_error",
                    "analysis_id": analysis_id,
                    "attempt": attempt + 1,
                    "exception": type(error).__name__,
                }
            )
        )

    def _run(self, analysis_id: str, payload: AnalysisInput) -> None:
        started = time.monotonic()
        context: dict = {"analysis_id": analysis_id, "outcome": "deleted"}
        try:
            with self.db.session(write=True) as session:
                job = session.get(Analysis, analysis_id)
                if not job or job.status != AnalysisStatus.QUEUED:
                    return
                job.status, job.started_at = AnalysisStatus.RUNNING, time.time()
                analysis_event(session, job, "analysis_started")
                policy_snapshot = job.policy_snapshot
                context.update(
                    {
                        "request_id": job.request_id,
                        "organization_id": job.organization_id,
                        "project_id": job.project_id,
                    }
                )
            response = (
                {"error": "server_restarted"}
                if self.stopping.is_set()
                else execute(
                    payload, self.settings, policy_snapshot, self.db.lease_healthy, self.stopping
                )
            )
            context["outcome"] = self.finish(analysis_id, response)
        except LeaseLost:
            context["outcome"] = "service_lease_lost"
        except Exception:
            context["outcome"] = "failed"
            if not self.persistence_failed.is_set():
                self.finish(analysis_id, {"error": "worker_failed"})
        finally:
            context["duration_ms"] = round((time.monotonic() - started) * 1000)
            logger.info(json.dumps({"event": "analysis.completed", **context}))
            self.slots.release()

    def track(self, future: Future) -> None:
        def discard(done: Future) -> None:
            with self.running_lock:
                self.running.discard(done)

        with self.running_lock:
            self.running.add(future)
        future.add_done_callback(discard)

    def drain(
        self,
        executors: list[tuple[ThreadPoolExecutor, set[Future] | None]],
        deadline: float,
    ) -> None:
        """Let all work finish until the shared deadline, then stop it."""
        self.draining.set()
        for executor, _ in executors:
            executor.shutdown(wait=False, cancel_futures=False)
        with self.running_lock:
            running = set(self.running)
        wait(running, timeout=max(0.0, deadline - time.monotonic()))
        for _, futures in executors:
            if futures is not None:
                with self.running_lock:
                    pending = set(futures)
                for future in pending:
                    future.cancel()
        self.stopping.set()
        for executor, _ in executors:
            executor.shutdown(wait=True)

    def shutdown(self, deadline: float | None = None) -> None:
        if deadline is None:
            deadline = time.monotonic() + self.settings.shutdown_drain_seconds
        self.drain([(self.executor, None)], deadline)
