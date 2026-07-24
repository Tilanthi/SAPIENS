"""Tests for the physics-motivated Mopra adapter v2."""

import random
from pathlib import Path

import pytest

from sapiens.adapters.mopra import MopraMolecularAdapter
from sapiens.budget import ExecutionContext

_CUBE = Path("/Users/gjw255/astrodata/MOPRA_SgrB2/SgrB2_bb_13CO_110_cube.fits")


def _ctx() -> ExecutionContext:
    return ExecutionContext(60, 30)


def _has_astropy() -> bool:
    try:
        import astropy  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        return False
    return True


def _synthetic_adapter(
    n: int = 500, seed: int = 0, *, aspect: float = 2.5, v_range: float = 20.0
) -> MopraMolecularAdapter:
    """Concentrated emission with given aspect ratio and velocity range."""
    rng = random.Random(seed)
    distances, intensities = [], []
    for _ in range(n):
        d = rng.uniform(0.0, 10.0)
        intensities.append(5.0 / (1.0 + d) + rng.gauss(0.0, 0.2))
        distances.append(d)
    return MopraMolecularAdapter(
        molecule="TEST",
        distances=distances,
        intensities=intensities,
        aspect_ratio=aspect,
        velocity_range_km=v_range,
    )


# --- concentration (dense-core signature) ---


def test_concentration_passes_on_synthetic():
    adapter = _synthetic_adapter()
    candidate = adapter.propose(seed=1, limit=3)[0]
    assert candidate.parameters["claim_type"] == "concentration"
    evidence = adapter.validate(candidate, stage="replication", seed=7, context=_ctx())[0]
    assert evidence.passed is True
    assert evidence.details["score"] > 0.25


# --- filamentarity (star-formation filament) ---


def test_filamentarity_passes_when_elongated():
    adapter = _synthetic_adapter(aspect=3.0)
    candidate = adapter.propose(seed=1, limit=3)[1]
    assert candidate.parameters["claim_type"] == "filamentarity"
    evidence = adapter.validate(candidate, stage="replication", seed=7, context=_ctx())[0]
    assert evidence.passed is True
    assert evidence.details["aspect_ratio"] >= 3.0


def test_filamentarity_fails_when_circular():
    adapter = _synthetic_adapter(aspect=1.1)
    candidate = adapter.propose(seed=1, limit=3)[1]
    evidence = adapter.validate(candidate, stage="replication", seed=7, context=_ctx())[0]
    assert evidence.passed is False


# --- velocity gradient (organised gas motion) ---


def test_velocity_passes_when_coherent():
    adapter = _synthetic_adapter(v_range=25.0)
    candidate = adapter.propose(seed=1, limit=3)[2]
    assert candidate.parameters["claim_type"] == "velocity-gradient"
    evidence = adapter.validate(candidate, stage="replication", seed=7, context=_ctx())[0]
    assert evidence.passed is True
    assert evidence.details["v_range_km"] >= 25.0


def test_velocity_fails_when_incoherent():
    adapter = _synthetic_adapter(v_range=3.0)
    candidate = adapter.propose(seed=1, limit=3)[2]
    evidence = adapter.validate(candidate, stage="replication", seed=7, context=_ctx())[0]
    assert evidence.passed is False


# --- adapter properties ---


def test_mopra_is_non_synthetic_and_needs_approver():
    from sapiens.trust import AdapterRegistry

    adapter = _synthetic_adapter()
    assert adapter.manifest.synthetic_only is False
    registry = AdapterRegistry()
    with pytest.raises(ValueError):
        registry.register(adapter)
    registry.register(adapter, approver="tester", capabilities=("filesystem-read",))


# --- integration on real FITS cube ---


@pytest.mark.skipif(
    not (_has_astropy() and _CUBE.exists()), reason="needs astropy + Mopra 13CO cube"
)
def test_real_cube_produces_three_physics_candidates():
    adapter = MopraMolecularAdapter.from_fits(_CUBE, molecule="13CO")
    candidates = adapter.propose(seed=1, limit=3)
    assert len(candidates) == 3
    claim_types = [c.parameters["claim_type"] for c in candidates]
    assert "concentration" in claim_types
    assert "filamentarity" in claim_types
    assert "velocity-gradient" in claim_types
    # Each should produce valid evidence
    for c in candidates:
        ev = adapter.validate(c, stage="internal", seed=7, context=_ctx())[0]
        assert ev.candidate_id == c.candidate_id
        assert ev.kind == "internal"
