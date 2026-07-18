"""The clean boundary between the shared kernel and scientific domains."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .budget import ExecutionContext
from .models import AdapterManifest, Candidate, Evidence


@runtime_checkable
class DomainAdapter(Protocol):
    """A domain supplies data/generation/checks, never evidence-level decisions."""

    @property
    def manifest(self) -> AdapterManifest: ...

    def propose(self, *, seed: int, limit: int) -> tuple[Candidate, ...]: ...

    def validate(
        self, candidate: Candidate, *, stage: str, seed: int, context: ExecutionContext
    ) -> tuple[Evidence, ...]: ...

    def import_structure(self, structure: dict[str, object], *, candidate_id: str) -> Candidate: ...


def validate_adapter(adapter: DomainAdapter) -> None:
    if not isinstance(adapter, DomainAdapter):
        raise TypeError("adapter does not implement DomainAdapter")
    manifest = adapter.manifest
    if not manifest.synthetic_only:
        raise ValueError("Phase 0 refuses non-synthetic adapters")
