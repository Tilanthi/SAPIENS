from pathlib import Path

from sapiens import DiscoveryKernel, EvidenceLedger, EvidenceLevel, transfer
from sapiens.adapters import SyntheticLinearAdapter, SyntheticThresholdAdapter
from sapiens.budget import ExecutionContext


def test_synthetic_kernel_promotes_to_l3(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    kernel = DiscoveryKernel(ledger)
    adapter = SyntheticLinearAdapter()
    candidate = adapter.propose(seed=3, limit=1)[0]
    kernel.register(candidate)
    assert (
        kernel.validate_next(adapter, candidate, seed=10, context=ExecutionContext(10, 2))
        == EvidenceLevel.L1
    )
    assert (
        kernel.validate_next(adapter, candidate, seed=11, context=ExecutionContext(10, 2))
        == EvidenceLevel.L2
    )
    assert (
        kernel.validate_next(adapter, candidate, seed=12, context=ExecutionContext(10, 2))
        == EvidenceLevel.L3
    )


def test_bad_synthetic_candidate_does_not_promote(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    kernel = DiscoveryKernel(ledger)
    adapter = SyntheticLinearAdapter()
    candidate = adapter.propose(seed=3, limit=2)[1]
    kernel.register(candidate)
    assert (
        kernel.validate_next(adapter, candidate, seed=10, context=ExecutionContext(10, 2))
        == EvidenceLevel.L0
    )


def test_cross_domain_transfer_resets_to_l0_and_links_parent(tmp_path: Path):
    source_adapter = SyntheticLinearAdapter()
    target_adapter = SyntheticThresholdAdapter()
    source = source_adapter.propose(seed=1, limit=1)[0]
    imported, level, envelope = transfer(
        source, EvidenceLevel.L3, target_adapter, candidate_id="transferred-1"
    )
    assert level == EvidenceLevel.L0
    assert imported.domain == target_adapter.manifest.domain
    assert imported.parent_id == source.candidate_id
    assert envelope.source_level_discarded == EvidenceLevel.L3


def test_cli_demo_contract(tmp_path: Path):
    from sapiens.cli import run_demo

    result = run_demo(tmp_path)
    assert result["scientific_discoveries_claimed"] == 0
    assert result["transfer"]["level"] == "L0"
    assert result["ledger_verified"] is True
