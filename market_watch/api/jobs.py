"""In-memory background job runner for long data refresh tasks."""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


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
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def submit(self, fn: Callable[[Callable[[str], None]], Any], label: str = "task") -> str:
        job_id = str(uuid.uuid4())
        job = Job(id=job_id, message=f"Starting {label}…")
        with self._lock:
            self._jobs[job_id] = job

        def progress(msg: str) -> None:
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id].message = msg

        def run() -> None:
            with self._lock:
                self._jobs[job_id].status = "running"
            try:
                result = fn(progress)
                with self._lock:
                    self._jobs[job_id].status = "completed"
                    self._jobs[job_id].result = result
                    self._jobs[job_id].message = "Complete."
                    self._jobs[job_id].finished_at = datetime.now(timezone.utc).isoformat()
            except Exception as exc:
                with self._lock:
                    self._jobs[job_id].status = "failed"
                    self._jobs[job_id].error = str(exc)
                    self._jobs[job_id].message = str(exc)
                    self._jobs[job_id].finished_at = datetime.now(timezone.utc).isoformat()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return job_id


job_manager = JobManager()
