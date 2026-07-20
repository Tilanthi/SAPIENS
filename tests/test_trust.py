from pathlib import Path

import pytest

from sapiens import DiscoveryKernel, EvidenceLedger, EvidenceLevel
from sapiens.adapters import SyntheticLinearAdapter
from sapiens.budget import ExecutionContext
from sapiens.models import AdapterManifest, Candidate, Evidence
from sapiens.trust import AdapterRegistry, TrustTier

CTX = ExecutionContext(20, 5)


class _RealAdapter:
    """A minimal non-synthetic adapter (constructible now that the manifest is relaxed)."""

    def __init__(self, name: str = "real-demo", domain: str = "real-demo") -> None:
        self.manifest = AdapterManifest(name, "1.0", domain, ("x",), synthetic_only=False)

    def propose(self, *, seed: int, limit: int):
        if limit <= 0:
            return ()
        return (
            Candidate(
                f"real-{seed}", self.manifest.domain, "a real-data claim",
                {"v": 1}, source_adapter=self.manifest.name,
            ),
        )

    def validate(self, candidate, *, stage, seed, context):
        context.checkpoint()
        return (
            Evidence(
                f"ev-{candidate.candidate_id}-{stage}", candidate.candidate_id, stage, True,
                "real-v1", "real-data", seed, 0.9, {"deterministic": True},
            ),
        )

    def import_structure(self, structure, *, candidate_id):
        return Candidate(
            candidate_id, self.manifest.domain, "imported real structure",
            {"v": 1}, source_adapter=self.manifest.name,
        )


# --- registry admission rules -----------------------------------------------------


def test_manifest_now_permits_non_synthetic_flag():
    manifest = AdapterManifest("real", "1.0", "real-domain", ("x",), synthetic_only=False)
    assert manifest.synthetic_only is False  # relaxed: a declared flag, not refused at construction


def test_synthetic_adapter_auto_admits_at_synthetic_tier():
    registry = AdapterRegistry()
    registration = registry.register(SyntheticLinearAdapter())
    assert registration.tier is TrustTier.SYNTHETIC
    assert registration.approver == ""
    assert registration.name in registry


def test_non_synthetic_requires_approver_and_capabilities():
    registry = AdapterRegistry()
    with pytest.raises(ValueError):
        registry.register(_RealAdapter())  # no approver -> refused

    registration = registry.register(
        _RealAdapter(), approver="alice", capabilities=("filesystem-read",)
    )
    assert registration.tier is TrustTier.VETTED
    assert registration.approver == "alice"
    assert registration.capabilities == frozenset({"filesystem-read"})


def test_tier_mismatch_refused_both_directions():
    registry = AdapterRegistry()
    with pytest.raises(ValueError):
        registry.register(_RealAdapter(), tier=TrustTier.SYNTHETIC, approver="alice")
    with pytest.raises(ValueError):
        registry.register(SyntheticLinearAdapter(), tier=TrustTier.VETTED)


def test_duplicate_registration_refused():
    registry = AdapterRegistry()
    registry.register(SyntheticLinearAdapter())
    with pytest.raises(ValueError):
        registry.register(SyntheticLinearAdapter())


# --- kernel admission: registry vs strict backstop --------------------------------


def test_kernel_admits_non_synthetic_via_registry(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    registry = AdapterRegistry()
    adapter = _RealAdapter()
    registry.register(adapter, approver="alice", capabilities=("filesystem-read",))
    kernel = DiscoveryKernel(ledger, registry=registry)

    candidate = adapter.propose(seed=1, limit=1)[0]
    kernel.register(candidate)
    # admitted via registry -> validate_next proceeds and promotes
    assert kernel.validate_next(adapter, candidate, seed=10, context=CTX) == EvidenceLevel.L1
    assert ledger.verify() is True


def test_kernel_without_registry_refuses_non_synthetic(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    kernel = DiscoveryKernel(ledger)  # no registry -> strict validate_adapter backstop
    adapter = _RealAdapter()
    candidate = adapter.propose(seed=1, limit=1)[0]
    kernel.register(candidate)
    with pytest.raises(ValueError):
        kernel.validate_next(adapter, candidate, seed=10, context=CTX)


def test_kernel_with_registry_refuses_unregistered(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    registry = AdapterRegistry()
    adapter = _RealAdapter()  # deliberately NOT registered
    kernel = DiscoveryKernel(ledger, registry=registry)
    candidate = adapter.propose(seed=1, limit=1)[0]
    kernel.register(candidate)
    with pytest.raises(ValueError):
        kernel.validate_next(adapter, candidate, seed=10, context=CTX)
