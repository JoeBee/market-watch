"""Background job runner for long data refresh tasks (persisted in SQLite)."""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from market_watch.db.store import Database


@dataclass
class Job:
    id: str
    status: str = "pending"
    message: str = ""
    result: Any = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None


class JobManager:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()
        self._lock = threading.Lock()

    def _persist(self, job: Job) -> None:
        self.db.save_job(
            job_id=job.id,
            status=job.status,
            message=job.message,
            result=str(job.result) if job.result is not None else None,
            error=job.error,
            created_at=job.created_at,
            finished_at=job.finished_at,
        )

    def get(self, job_id: str) -> Job | None:
        row = self.db.load_job(job_id)
        if not row:
            return None
        return Job(
            id=row["id"],
            status=row["status"],
            message=row["message"] or "",
            result=row["result"],
            error=row["error"],
            created_at=row["created_at"],
            finished_at=row["finished_at"],
        )

    def submit(self, fn: Callable[[Callable[[str], None]], Any], label: str = "task") -> str:
        job_id = str(uuid.uuid4())
        job = Job(id=job_id, message=f"Starting {label}…")
        with self._lock:
            self._persist(job)

        def progress(msg: str) -> None:
            with self._lock:
                current = self.get(job_id)
                if current:
                    current.message = msg
                    self._persist(current)

        def run() -> None:
            with self._lock:
                current = self.get(job_id)
                if current:
                    current.status = "running"
                    self._persist(current)
            try:
                result = fn(progress)
                with self._lock:
                    current = self.get(job_id)
                    if current:
                        current.status = "completed"
                        current.result = result
                        current.message = "Complete."
                        current.finished_at = datetime.now(timezone.utc).isoformat()
                        self._persist(current)
            except Exception as exc:
                with self._lock:
                    current = self.get(job_id)
                    if current:
                        current.status = "failed"
                        current.error = str(exc)
                        current.message = str(exc)
                        current.finished_at = datetime.now(timezone.utc).isoformat()
                        self._persist(current)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return job_id


job_manager = JobManager()
