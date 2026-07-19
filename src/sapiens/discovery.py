"""Autonomous discovery driver: proposes candidates and climbs them via the daemon.

The driver is the brain (decides *what* to discover); ``DiscoveryDaemon`` is the bounded
executor. One climb job is enqueued per proposed candidate; the daemon leases and runs
each under step/time budgets through a handler that calls ``kernel.validate_next`` until
the candidate fails or reaches L3. Candidates reaching L3 are reported as "awaiting human
review"; L4 stays human-gated. Phase 0 only: synthetic adapters, no discovery claim.

This is a core module — it never imports ``sapiens.adapters``; adapter instances are
injected by the caller (e.g. ``cli.py``), exactly as the rest of the core package does.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .adapter import DomainAdapter
from .budget import BudgetExceeded, ExecutionContext, Preempted
from .daemon import DiscoveryDaemon, Handler
from .kernel import DiscoveryKernel
from .models import Candidate, EvidenceLevel
from .queue import Job, WorkQueue


@dataclass(frozen=True)
class DiscoveryReport:
    """Outcome of a discovery run. Claims nothing about nature."""

    proposed: int
    reached_l3: tuple[str, ...]  # candidate ids awaiting human review
    reached_l2: int
    reached_l1: int
    stayed_l0: int
    exhausted: int
    ledger_verified: bool
    scientific_discoveries_claimed: int = 0  # constant by construction


def make_climb_handler(
    kernel: DiscoveryKernel,
    adapter: DomainAdapter,
    candidates_by_id: Mapping[str, Candidate],
    seed: int,
) -> Handler:
    """Build a daemon handler that climbs one candidate as far as evidence allows."""

    def handler(job: Job, context: ExecutionContext) -> dict[str, object]:
        candidate = candidates_by_id[job.payload["candidate_id"]]
        level = kernel.ledger.state(candidate.candidate_id).level
        try:
            while level < EvidenceLevel.L3:
                context.checkpoint()
                reached = kernel.validate_next(adapter, candidate, seed=seed, context=context)
                if reached == level:
                    break  # evidence did not pass; stop climbing
                level = reached
        except (Preempted, BudgetExceeded):
            raise  # cooperative signals: let the daemon handle them
        except Exception as exc:  # contain adapter failures so the run stays alive
            return {"candidate_id": candidate.candidate_id, "level": level.name, "error": str(exc)}
        return {"candidate_id": candidate.candidate_id, "level": level.name}

    return handler


class DiscoveryDriver:
    """Plans candidate discovery work and runs it through the bounded daemon."""

    def __init__(
        self,
        *,
        adapters: Mapping[str, DomainAdapter],
        queue: WorkQueue,
        kernel: DiscoveryKernel,
        seed: int,
    ) -> None:
        if not adapters:
            raise ValueError("at least one adapter is required")
        self._adapters = dict(adapters)
        self._queue = queue
        self._kernel = kernel
        self._seed = seed
        self._candidates_by_id: dict[str, Candidate] = {}

    def plan(self, *, limit_per_adapter: int = 2) -> int:
        """Propose candidates, register them at L0, enqueue one climb job each."""
        if limit_per_adapter <= 0:
            raise ValueError("limit_per_adapter must be positive")
        proposed = 0
        for adapter in self._adapters.values():
            for candidate in adapter.propose(seed=self._seed, limit=limit_per_adapter):
                self._kernel.register(candidate)
                self._candidates_by_id[candidate.candidate_id] = candidate
                self._queue.enqueue(
                    job_id=candidate.candidate_id,
                    kind=adapter.manifest.name,
                    payload={"candidate_id": candidate.candidate_id, "seed": self._seed},
                    idempotency_key=candidate.candidate_id,
                )
                proposed += 1
        return proposed

    def run(
        self,
        *,
        worker: str,
        max_jobs: int,
        max_seconds: float,
        steps_per_job: int,
    ) -> DiscoveryReport:
        """Execute queued climb jobs through the daemon and summarise the result."""
        if not self._candidates_by_id:
            raise ValueError("plan() must be called before run()")
        handlers = {
            adapter.manifest.name: make_climb_handler(
                self._kernel, adapter, self._candidates_by_id, self._seed
            )
            for adapter in self._adapters.values()
        }
        daemon = DiscoveryDaemon(self._queue, handlers)
        daemon_report = daemon.run_bounded(
            worker=worker,
            max_jobs=max_jobs,
            max_seconds=max_seconds,
            steps_per_job=steps_per_job,
        )
        return self._summarise(daemon_report.exhausted)

    def _summarise(self, exhausted: int) -> DiscoveryReport:
        reached_l3: list[str] = []
        l2 = l1 = l0 = 0
        for candidate_id in self._candidates_by_id:
            level = self._kernel.ledger.state(candidate_id).level
            if level == EvidenceLevel.L3:
                reached_l3.append(candidate_id)
            elif level == EvidenceLevel.L2:
                l2 += 1
            elif level == EvidenceLevel.L1:
                l1 += 1
            else:
                l0 += 1
        return DiscoveryReport(
            proposed=len(self._candidates_by_id),
            reached_l3=tuple(reached_l3),
            reached_l2=l2,
            reached_l1=l1,
            stayed_l0=l0,
            exhausted=exhausted,
            ledger_verified=self._kernel.ledger.verify(),
        )
