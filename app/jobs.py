from __future__ import annotations

import copy
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self) -> str:
        job_id = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._jobs[job_id] = {
                "jobId": job_id,
                "status": "queued",
                "createdAt": now,
                "updatedAt": now,
            }
        return job_id

    def run(self, job_id: str, worker: Callable[[], dict[str, Any]]) -> None:
        self._update(job_id, status="processing")
        try:
            result = worker()
        except Exception as exc:  # noqa: BLE001 - errors are exposed as job status for the demo UI.
            self._update(job_id, status="failed", error=str(exc))
            return
        self._update(job_id, status="completed", result=result)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return copy.deepcopy(job) if job else None

    def _update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            if job_id not in self._jobs:
                return
            self._jobs[job_id].update(changes)
            self._jobs[job_id]["updatedAt"] = time.time()


layout_jobs = JobStore()
