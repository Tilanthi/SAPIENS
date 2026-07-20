"""Subprocess sandbox for VETTED adapters (Phase 1 v2).

Runs an adapter's ``validate()`` in a child process under a wall-clock timeout and
hard-terminates it on timeout, so a misbehaving or non-synthetic (real-data) adapter
cannot hang or crash the host process. Uses ``multiprocessing`` with the ``spawn``
start method (a fresh process; no inherited state) for the cleanest isolation available
in the standard library.

Honest scope: this is process-level isolation + wall-clock timeout, NOT full cgroup /
container isolation — memory and CPU limits beyond wall-clock remain a roadmap item.
The adapter, candidate, and returned evidence must be picklable, and the adapter class
must be importable at module level (``spawn`` re-imports it in the child).
"""

from __future__ import annotations

import multiprocessing as mp
from dataclasses import dataclass
from queue import Empty

from .budget import ExecutionContext
from .models import Candidate, Evidence


@dataclass(frozen=True)
class SandboxResult:
    evidence: tuple[Evidence, ...] | None
    timed_out: bool
    error: str | None

    @property
    def ok(self) -> bool:
        return self.evidence is not None and not self.timed_out and self.error is None


def _sandbox_target(queue, adapter, candidate, stage, seed, max_steps, max_seconds) -> None:
    """Child-process entry point: run validate and post the result (or error string)."""
    try:
        context = ExecutionContext(max_steps, max_seconds)
        result = adapter.validate(candidate, stage=stage, seed=seed, context=context)
        queue.put(tuple(result))
    except Exception as exc:  # capture any adapter failure so the host stays alive
        queue.put(str(exc))


def sandboxed_validate(
    candidate: Candidate,
    *,
    adapter,
    stage: str,
    seed: int,
    max_steps: int,
    max_seconds: float,
    timeout: float,
) -> SandboxResult:
    """Run ``adapter.validate`` in a spawned child; hard-terminate if it exceeds ``timeout``."""
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    context = mp.get_context("spawn")
    queue: mp.Queue = context.Queue()
    process = context.Process(
        target=_sandbox_target,
        args=(queue, adapter, candidate, stage, seed, max_steps, max_seconds),
    )
    process.start()
    process.join(timeout)
    if process.is_alive():
        process.terminate()
        process.join()
        return SandboxResult(evidence=None, timed_out=True, error=None)
    try:
        outcome = queue.get_nowait()
    except Empty:
        return SandboxResult(evidence=None, timed_out=False, error="child produced no result")
    if isinstance(outcome, str):
        return SandboxResult(evidence=None, timed_out=False, error=outcome)
    return SandboxResult(evidence=tuple(outcome), timed_out=False, error=None)
