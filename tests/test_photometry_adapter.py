from pathlib import Path

from sapiens import DiscoveryKernel, EvidenceLedger, EvidenceLevel, transfer
from sapiens.adapters import SyntheticPhotometryAdapter, SyntheticThresholdAdapter
from sapiens.budget import ExecutionContext


def _ctx() -> ExecutionContext:
    return ExecutionContext(20, 30)


def test_photometry_true_period_promotes_to_l3(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    kernel = DiscoveryKernel(ledger)
    adapter = SyntheticPhotometryAdapter()
    candidate = adapter.propose(seed=5, limit=1)[0]
    kernel.register(candidate)
    assert kernel.validate_next(adapter, candidate, seed=40, context=_ctx()) == EvidenceLevel.L1
    assert kernel.validate_next(adapter, candidate, seed=41, context=_ctx()) == EvidenceLevel.L2
    assert kernel.validate_next(adapter, candidate, seed=42, context=_ctx()) == EvidenceLevel.L3
    assert ledger.verify() is True


def test_photometry_wrong_period_does_not_promote(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    kernel = DiscoveryKernel(ledger)
    adapter = SyntheticPhotometryAdapter()
    candidate = adapter.propose(seed=5, limit=2)[1]  # the wrong-period candidate
    kernel.register(candidate)
    assert kernel.validate_next(adapter, candidate, seed=40, context=_ctx()) == EvidenceLevel.L0


def test_photometry_evidence_is_well_formed():
    adapter = SyntheticPhotometryAdapter()
    candidate = adapter.propose(seed=9, limit=1)[0]
    evidence = adapter.validate(candidate, stage="replication", seed=7, context=_ctx())
    assert len(evidence) == 1
    item = evidence[0]
    assert item.candidate_id == candidate.candidate_id
    assert item.kind == "replication"
    assert item.score is not None and 0.0 <= item.score <= 1.0
    assert item.passed is True


def test_photometry_transfer_resets_to_l0_and_links_parent():
    source_adapter = SyntheticPhotometryAdapter()
    target_adapter = SyntheticThresholdAdapter()
    source = source_adapter.propose(seed=1, limit=1)[0]
    imported, level, envelope = transfer(
        source, EvidenceLevel.L3, target_adapter, candidate_id="photo-transfer-1"
    )
    assert level == EvidenceLevel.L0
    assert imported.domain == target_adapter.manifest.domain
    assert imported.parent_id == source.candidate_id
    assert envelope.source_level_discarded == EvidenceLevel.L3
