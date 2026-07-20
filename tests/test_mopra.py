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


def _synthetic_concentrated(n: int = 500, seed: int = 0) -> MopraMolecularAdapter:
    """Intensity falls with distance (centrally concentrated); x-index is unrelated."""
    rng = random.Random(seed)
    distances, intensities, x_indices = [], [], []
    for _ in range(n):
        d = rng.uniform(0.0, 10.0)
        intensities.append(5.0 / (1.0 + d) + rng.gauss(0.0, 0.2))  # ~1/distance
        distances.append(d)
        x_indices.append(rng.uniform(0.0, 33.0))  # unrelated to intensity
    return MopraMolecularAdapter(
        molecule="TEST", distances=distances, intensities=intensities, x_indices=x_indices
    )


def test_mopra_concentration_passes_on_synthetic():
    adapter = _synthetic_concentrated()
    candidate = adapter.propose(seed=1, limit=1)[0]  # concentration claim
    evidence = adapter.validate(candidate, stage="replication", seed=7, context=_ctx())[0]
    assert evidence.passed is True
    assert evidence.details["stat"] > 0.3


def test_mopra_ra_gradient_fails_on_synthetic():
    adapter = _synthetic_concentrated()
    candidate = adapter.propose(seed=1, limit=2)[1]  # ra-gradient (null)
    evidence = adapter.validate(candidate, stage="replication", seed=7, context=_ctx())[0]
    assert evidence.passed is False


def test_mopra_is_non_synthetic_and_needs_approver():
    from sapiens.trust import AdapterRegistry

    adapter = _synthetic_concentrated()
    assert adapter.manifest.synthetic_only is False
    registry = AdapterRegistry()
    with pytest.raises(ValueError):
        registry.register(adapter)
    registry.register(adapter, approver="tester", capabilities=("filesystem-read",))


@pytest.mark.skipif(
    not (_has_astropy() and _CUBE.exists()), reason="needs astropy + a Mopra 13CO cube"
)
def test_mopra_real_cube_is_centraly_concentrated():
    adapter = MopraMolecularAdapter.from_fits(_CUBE, molecule="13CO")
    candidate = adapter.propose(seed=1, limit=1)[0]
    evidence = adapter.validate(candidate, stage="replication", seed=7, context=_ctx())[0]
    assert evidence.details["molecule"] == "13CO"
    assert evidence.details["stat"] > 0.2  # real molecular cores are centrally concentrated
