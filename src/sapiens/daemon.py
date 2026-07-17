"""Bounded background-discovery worker skeleton.

Phase 0 executes registered in-process handlers cooperatively. Untrusted adapters and
hard process isolation are explicitly deferred; no dynamic imports or shell execution
are accepted from queue payloads.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .budget import BudgetExceeded, ExecutionContext, Preempted
from .queue import Job, WorkQueue

Handler = Callable[[Job, ExecutionContext], dict[str, object]]


@dataclass(frozen=True)
class DaemonReport:
    completed: int
    preempted: int
    exhausted: int
    empty: bool


class DiscoveryDaemon:
    def __init__(self, queue: WorkQueue, handlers: dict[str, Handler]) -> None:
        self.queue = queue
        self.handlers = dict(handlers)
        if not self.handlers:
            raise ValueError("at least one explicitly registered handler is required")

    def run_bounded(
        self,
        *,
        worker: str,
        max_jobs: int,
        max_seconds: float,
        steps_per_job: int,
        should_preempt: Callable[[], bool] | None = None,
    ) -> DaemonReport:
        if max_jobs <= 0 or max_seconds <= 0 or steps_per_job <= 0:
            raise ValueError("daemon budgets must be positive")
        start = time.monotonic()
        completed = preempted = exhausted = 0
        empty = False
        for _ in range(max_jobs):
            remaining = max_seconds - (time.monotonic() - start)
            if remaining <= 0:
                exhausted += 1
                break
            if should_preempt and should_preempt():
                preempted += 1
                break
            job = self.queue.lease(worker, seconds=max(1.0, remaining + 1.0))
            if job is None:
                empty = True
                break
            handler = self.handlers.get(job.kind)
            if handler is None:
                self.queue.release(job)
                exhausted += 1
                continue
            context = ExecutionContext(max_steps=steps_per_job, max_seconds=remaining)
            try:
                result = handler(job, context)
                context.checkpoint(0)
                self.queue.finish(job, result)
                completed += 1
            except Preempted:
                self.queue.release(job, preempted=True)
                preempted += 1
                break
            except BudgetExceeded:
                self.queue.release(job)
                exhausted += 1
        return DaemonReport(completed, preempted, exhausted, empty)
