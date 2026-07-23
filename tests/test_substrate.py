from pathlib import Path

import pytest

from sapiens.anomaly import AnomalyRecord

_PHOTOZ = Path(
    "/Users/gjw255/astrodata/SWARM/ASTRA-dev-main/astra_core/scientific_discovery/"
    "evolved_analysis/data/photoz_sdss_cache.csv"
)


# --- tension register ---


def test_fisher_z_ci():
    from sapiens.tension import fisher_z_ci

    lo, hi = fisher_z_ci(0.8, 100)
    assert lo < 0.8 < hi
    assert hi - lo < 0.2  # tight for n=100


def test_tension_register_finds_persistent_disagreement(tmp_path: Path):
    from sapiens.tension import TensionRegister

    reg = TensionRegister(tmp_path / "t.db")
    for seed in range(5):
        reg.record("q", "A", 0.80, 0.75, 0.85, seed)
        reg.record("q", "B", 0.30, 0.25, 0.35, seed)  # non-overlapping
    tensions = reg.tensions(min_seeds=3)
    assert len(tensions) >= 1
    assert not tensions[0].overlap
    assert tensions[0].persistent_disagreement


def test_tension_register_no_disagreement_when_overlapping(tmp_path: Path):
    from sapiens.tension import TensionRegister

    reg = TensionRegister(tmp_path / "t.db")
    for seed in range(5):
        reg.record("q", "A", 0.70, 0.60, 0.80, seed)
        reg.record("q", "B", 0.75, 0.65, 0.85, seed)  # overlapping
    tensions = reg.tensions(min_seeds=3)
    if tensions:
        assert tensions[0].overlap


# --- systematic sieve ---


def test_sieve_flags_spatial_clustering():
    from sapiens.sieve import sieve_population

    clustered = [
        AnomalyRecord(f"a{i}", "d", "k", "x", 0.5, f"ra={100+i*0.001:.4f},dec=0.0", "{}", 0.0)
        for i in range(10)
    ]
    wide_ras = list(range(0, 360))
    result = sieve_population(clustered, wide_ras, [20.0] * 100, [20.0] * 10, domain="test")
    spatial = [c for c in result.checks if c.name == "spatial_spread"]
    assert spatial and not spatial[0].passed


def test_sieve_passes_well_distributed():
    from sapiens.sieve import sieve_population

    spread = [
        AnomalyRecord(f"a{i}", "d", "k", "x", 0.5, f"ra={i*36:.4f},dec=0.0", "{}", 0.0)
        for i in range(10)
    ]
    sample_ras = [i * 36 for i in range(10)]
    result = sieve_population(spread, sample_ras, [20.0] * 10, [20.0] * 10, domain="test")
    spatial = [c for c in result.checks if c.name == "spatial_spread"]
    assert spatial and spatial[0].passed


# --- model-mismatch detector (integration) ---


@pytest.mark.skipif(not _PHOTOZ.exists(), reason="needs SDSS photoz cache")
def test_model_mismatch_runs_on_real_data(tmp_path: Path):
    from sapiens.ongoing import detect_model_mismatch

    result = detect_model_mismatch(tmp_path / "m.db", seed=42)
    assert "mismatches_found" in result
