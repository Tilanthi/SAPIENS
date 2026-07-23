import os
from pathlib import Path

import pytest

from sapiens.anomaly import AnomalyRegistry

_PHOTOZ = Path(
    os.environ.get(
        "ASTRA_SDSS_PHOTOZ_CSV",
        "/Users/gjw255/astrodata/SWARM/ASTRA-dev-main/astra_core/scientific_discovery/"
        "evolved_analysis/data/photoz_sdss_cache.csv",
    )
)


def test_registry_ranks_by_severity(tmp_path: Path):
    reg = AnomalyRegistry(tmp_path / "a.db")
    reg.register("a1", "dom", "structured_residual", "minor", 0.3, "obj1")
    reg.register("a2", "dom", "ceiling_violation", "major", 0.9, "obj2")
    reg.register("a3", "dom", "outlier_object", "medium", 0.6, "obj3")
    top = reg.top(limit=10)
    assert [a.anomaly_id for a in top] == ["a2", "a3", "a1"]


def test_registry_never_auto_discards(tmp_path: Path):
    reg = AnomalyRegistry(tmp_path / "a.db")
    reg.register("a1", "dom", "structured_residual", "test", 0.5, "obj1")
    assert len(reg) == 1
    reg.mark("a1", "investigating", "looking into it")
    assert len(reg) == 1
    assert reg.top(limit=10)[0].status == "investigating"


def test_registry_counts_by_kind(tmp_path: Path):
    reg = AnomalyRegistry(tmp_path / "a.db")
    reg.register("a1", "d", "structured_residual", "x", 0.5, "o1")
    reg.register("a2", "d", "structured_residual", "y", 0.6, "o2")
    reg.register("a3", "d", "ceiling_violation", "z", 0.7, "o3")
    assert reg.counts_by_kind() == {"structured_residual": 2, "ceiling_violation": 1}


@pytest.mark.skipif(not _PHOTOZ.exists(), reason="needs SDSS photoz cache")
def test_anomaly_scan_finds_outliers_on_real_data(tmp_path: Path, monkeypatch):
    import sapiens.ongoing as ongoing_mod

    monkeypatch.setattr(ongoing_mod, "PHOTOZ_CSV", _PHOTOZ)
    from sapiens.ongoing import run_anomaly_scan

    result = run_anomaly_scan(tmp_path / "a.db", seed=42)
    assert result["anomalies_found"] > 0
