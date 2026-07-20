"""Minimal domain-neutral orchestration boundary."""

from __future__ import annotations

from .adapter import DomainAdapter, validate_adapter
from .budget import ExecutionContext
from .ledger import EvidenceLedger
from .models import Candidate, EvidenceLevel

_STAGE_BY_LEVEL = {
    EvidenceLevel.L1: "internal",
    EvidenceLevel.L2: "replication",
    EvidenceLevel.L3: "review",
}


class DiscoveryKernel:
    def __init__(self, ledger: EvidenceLedger, *, registry: object | None = None) -> None:
        self.ledger = ledger
        self.registry = registry

    def register(self, candidate: Candidate, *, transferred_from: str | None = None) -> None:
        self.ledger.record_candidate(candidate.candidate_id, transferred_from=transferred_from)

    def _admit(self, adapter: DomainAdapter) -> None:
        # With a registry, admission is registry-governed (Phase 1). Without one, the
        # strict validate_adapter backstop refuses non-synthetic adapters (Phase 0).
        if self.registry is not None:
            if adapter.manifest.name not in self.registry:
                raise ValueError(
                    f"adapter {adapter.manifest.name!r} is not admitted by the registry"
                )
        else:
            validate_adapter(adapter)

    def validate_next(
        self,
        adapter: DomainAdapter,
        candidate: Candidate,
        *,
        seed: int,
        context: ExecutionContext,
    ) -> EvidenceLevel:
        self._admit(adapter)
        if candidate.domain != adapter.manifest.domain:
            raise ValueError("candidate domain does not match adapter")
        current = self.ledger.state(candidate.candidate_id).level
        if current >= EvidenceLevel.L3:
            raise ValueError("Phase 0 automated kernel cannot promote beyond L3")
        target = EvidenceLevel(current + 1)
        stage = _STAGE_BY_LEVEL[target]
        evidence = adapter.validate(candidate, stage=stage, seed=seed, context=context)
        refs: list[str] = []
        for item in evidence:
            if item.candidate_id != candidate.candidate_id or item.kind != stage:
                raise ValueError("adapter returned mis-scoped evidence")
            self.ledger.record_evidence(item)
            if item.passed:
                refs.append(item.evidence_id)
        if not refs:
            return current
        self.ledger.promote(candidate.candidate_id, target, tuple(refs))
        return target
