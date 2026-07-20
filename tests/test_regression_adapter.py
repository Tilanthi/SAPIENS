from pathlib import Path

from sapiens import DiscoveryKernel, EvidenceLedger, EvidenceLevel
from sapiens.adapters import SyntheticRegressionAdapter
from sapiens.budget import ExecutionContext


def _ctx() -> ExecutionContext:
    return ExecutionContext(20, 5)


def test_regression_positive_candidate_climbs_with_real_evidence(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    kernel = DiscoveryKernel(ledger)
    adapter = SyntheticRegressionAdapter()
    candidate = adapter.propose(seed=1, limit=1)[0]  # correct (positive) direction
    kernel.register(candidate)
    # each promotion is decided by a genuine held-out Pearson test, not a rigged score
    assert kernel.validate_next(adapter, candidate, seed=10, context=_ctx()) == EvidenceLevel.L1
    assert kernel.validate_next(adapter, candidate, seed=11, context=_ctx()) == EvidenceLevel.L2
    assert kernel.validate_next(adapter, candidate, seed=12, context=_ctx()) == EvidenceLevel.L3
    assert ledger.verify() is True


def test_regression_wrong_direction_fails_on_real_evidence(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    kernel = DiscoveryKernel(ledger)
    adapter = SyntheticRegressionAdapter()
    candidate = adapter.propose(seed=1, limit=2)[1]  # wrong (negative) direction
    kernel.register(candidate)
    # significant correlation but in the WRONG direction -> fails on effect size
    assert kernel.validate_next(adapter, candidate, seed=10, context=_ctx()) == EvidenceLevel.L0


def test_regression_evidence_carries_real_statistics():
    adapter = SyntheticRegressionAdapter()
    candidate = adapter.propose(seed=1, limit=1)[0]
    evidence = adapter.validate(candidate, stage="replication", seed=7, context=_ctx())
    item = evidence[0]
    assert item.kind == "replication"
    assert item.details["n"] == 60
    assert item.details["r"] > 0.5  # genuinely strong held-out correlation
    assert item.details["pvalue"] < 0.05  # genuinely significant
    assert item.passed is True
