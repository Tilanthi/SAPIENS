"""Minimal sandboxable adapters used by the sandbox test suite (Phase 1 v2).

These are module-level and picklable so the ``spawn`` child process can import them.
They are not scientific models — they exist only to exercise the sandbox's fast /
timeout / crash paths deterministically.
"""

from __future__ import annotations

import time

from .budget import ExecutionContext
from .models import AdapterManifest, Candidate, Evidence

_MANIFEST = AdapterManifest("sandbox-example", "1.0", "sandbox-example", ("x",))


def _candidate() -> Candidate:
    return Candidate("c", "sandbox-example", "example", {}, source_adapter="sandbox-example")


class FastExampleAdapter:
    manifest = _MANIFEST

    def propose(self, *, seed: int, limit: int) -> tuple[Candidate, ...]:
        return (_candidate(),) if limit > 0 else ()

    def validate(
        self, candidate: Candidate, *, stage: str, seed: int, context: ExecutionContext
    ) -> tuple[Evidence, ...]:
        context.checkpoint()
        return (
            Evidence(
                "e", candidate.candidate_id, stage, True, "fast", "synthetic", seed, 0.9, {}
            ),
        )

    def import_structure(self, structure: dict[str, object], *, candidate_id: str) -> Candidate:
        return _candidate()


class SleepyExampleAdapter(FastExampleAdapter):
    """Validate sleeps past any reasonable sandbox timeout."""

    def validate(
        self, candidate: Candidate, *, stage: str, seed: int, context: ExecutionContext
    ) -> tuple[Evidence, ...]:
        time.sleep(5.0)
        return super().validate(candidate, stage=stage, seed=seed, context=context)


class CrashingExampleAdapter(FastExampleAdapter):
    """Validate raises, to confirm the host survives."""

    def validate(
        self, candidate: Candidate, *, stage: str, seed: int, context: ExecutionContext
    ) -> tuple[Evidence, ...]:
        raise RuntimeError("deliberate crash for sandbox test")
