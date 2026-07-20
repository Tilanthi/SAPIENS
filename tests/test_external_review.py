from pathlib import Path

import pytest

from sapiens import DiscoveryKernel, EvidenceLedger, EvidenceLevel
from sapiens.adapters import SyntheticLinearAdapter
from sapiens.budget import ExecutionContext
from sapiens.external_review import build_reproduction_bundle


def _ctx() -> ExecutionContext:
    return ExecutionContext(20, 5)


def _climb_to_l3(kernel: DiscoveryKernel, adapter, candidate) -> None:
    for seed in (10, 11, 12):
        kernel.validate_next(adapter, candidate, seed=seed, context=_ctx())


def _l3_candidate(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "e.jsonl")
    kernel = DiscoveryKernel(ledger)
    adapter = SyntheticLinearAdapter()
    candidate = adapter.propose(seed=3, limit=1)[0]
    kernel.register(candidate)
    _climb_to_l3(kernel, adapter, candidate)
    return ledger, kernel, candidate


def test_promote_to_l4_requires_a_human_reviewer(tmp_path: Path):
    _, kernel, candidate = _l3_candidate(tmp_path)
    with pytest.raises(ValueError):
        kernel.promote_to_l4(candidate.candidate_id, reviewer="", passed=True)


def test_promote_to_l4_requires_l3_first(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "e.jsonl")
    kernel = DiscoveryKernel(ledger)
    adapter = SyntheticLinearAdapter()
    candidate = adapter.propose(seed=3, limit=1)[0]
    kernel.register(candidate)
    kernel.validate_next(adapter, candidate, seed=10, context=_ctx())  # L1 only
    with pytest.raises(ValueError):
        kernel.promote_to_l4(candidate.candidate_id, reviewer="alice", passed=True)


def test_promote_to_l4_success_reaches_l4_and_verifies(tmp_path: Path):
    ledger, kernel, candidate = _l3_candidate(tmp_path)
    level = kernel.promote_to_l4(
        candidate.candidate_id, reviewer="alice", passed=True,
        timestamp="2026-07-20", notes="external reproduction confirmed",
    )
    assert level == EvidenceLevel.L4
    assert ledger.state(candidate.candidate_id).level == EvidenceLevel.L4
    assert ledger.verify() is True  # human_gate + external evidence enforced by the chain


def test_promote_to_l4_failed_review_keeps_l3_and_records_verdict(tmp_path: Path):
    ledger, kernel, candidate = _l3_candidate(tmp_path)
    level = kernel.promote_to_l4(candidate.candidate_id, reviewer="bob", passed=False)
    assert level == EvidenceLevel.L3  # stayed at L3
    assert ledger.verify() is True
    events = [e for e in ledger.events() if e.candidate_id == candidate.candidate_id]
    assert any(
        e.kind == "evidence"
        and e.payload.get("kind") == "external"
        and e.payload.get("passed") is False
        for e in events
    )


def test_autonomous_kernel_cannot_reach_l4(tmp_path: Path):
    _, kernel, candidate = _l3_candidate(tmp_path)
    # validate_next caps at L3 even with a passing adapter
    with pytest.raises(ValueError):
        kernel.validate_next(
            SyntheticLinearAdapter(), candidate, seed=99, context=_ctx()
        )


def test_reproduction_bundle_contains_full_evidence_trail(tmp_path: Path):
    ledger, _, candidate = _l3_candidate(tmp_path)
    bundle = build_reproduction_bundle(ledger, candidate)
    assert bundle.candidate_id == candidate.candidate_id
    assert bundle.claim == candidate.claim
    assert len(bundle.evidence) >= 3  # internal + replication + review
    assert len(bundle.transitions) == 3  # L1, L2, L3 promotions
    assert bundle.bundle_hash
    # deterministic content hash
    assert build_reproduction_bundle(ledger, candidate).bundle_hash == bundle.bundle_hash
