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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import select, update

from blastradius.server.config import Settings
from blastradius.server.db import Database
from blastradius.server.models import Analysis
from blastradius.server.persistence import persist_result
from blastradius.server.schemas import AnalysisInput, WorkerInput

logger = logging.getLogger("blastradius.jobs")


def execute(
    payload: AnalysisInput, settings: Settings, policy_snapshot: dict | None = None
) -> dict:
    jobs_dir = settings.data_dir.resolve() / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="job-", dir=jobs_dir) as directory:
        workdir = Path(directory)
        (workdir / "input.json").write_text(
            WorkerInput(analysis=payload, policy_snapshot=policy_snapshot).model_dump_json(),
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-m",
                    "blastradius.server.worker",
                    str(workdir),
                    str(settings.max_resources),
                    str(settings.job_timeout_seconds),
                ],
                cwd=workdir,
                env={"PATH": os.defpath, "PYTHONHASHSEED": "0"},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=settings.job_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"error": "analysis_timeout"}
        output = workdir / "output.json"
        if completed.returncode != 0 or not output.exists():
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

    def recover(self) -> None:
        with self.db.session(write=True) as session:
            session.execute(
                update(Analysis)
                .where(Analysis.status.in_(("queued", "running")))
                .values(status="failed", error="server_restarted", completed_at=time.time())
            )
        directory = self.settings.data_dir / "jobs"
        if directory.exists():
            for path in directory.glob("job-*"):
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)

    def reserve(self) -> bool:
        return self.slots.acquire(blocking=False)

    def submit(self, analysis_id: str, payload: AnalysisInput) -> None:
        self.executor.submit(self._run, analysis_id, payload)

    def _run(self, analysis_id: str, payload: AnalysisInput) -> None:
        started = time.monotonic()
        context: dict = {"analysis_id": analysis_id, "outcome": "deleted"}
        try:
            with self.db.session(write=True) as session:
                job = session.get(Analysis, analysis_id)
                if not job:
                    return
                job.status, job.started_at = "running", time.time()
                policy_snapshot = job.policy_snapshot
                context.update(
                    {
                        "request_id": job.request_id,
                        "organization_id": job.organization_id,
                        "project_id": job.project_id,
                    }
                )
            response = execute(payload, self.settings, policy_snapshot)
            with self.db.session(write=True) as session:
                job = session.scalar(
                    select(Analysis).where(Analysis.id == analysis_id).with_for_update()
                )
                if job:
                    job.status = "failed" if response.get("error") else "succeeded"
                    job.error = response.get("error")
                    if not job.error:
                        persist_result(session, job, response["result"])
                    job.completed_at = time.time()
                    context["outcome"] = job.status
        except Exception:
            context["outcome"] = "failed"
            with self.db.session(write=True) as session:
                session.execute(
                    update(Analysis)
                    .where(Analysis.id == analysis_id)
                    .values(status="failed", error="worker_failed", completed_at=time.time())
                )
        finally:
            context["duration_ms"] = round((time.monotonic() - started) * 1000)
            logger.info(json.dumps({"event": "analysis.completed", **context}))
            self.slots.release()

    def shutdown(self) -> None:
        self.executor.shutdown(wait=True)
