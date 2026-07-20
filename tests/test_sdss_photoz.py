import os
import random
from pathlib import Path

import pytest

from sapiens import DiscoveryKernel, EvidenceLedger, EvidenceLevel
from sapiens.adapters import SDSSPhotozAdapter
from sapiens.adapters.sdss_photoz import SDSSRow
from sapiens.budget import ExecutionContext
from sapiens.trust import AdapterRegistry

_ASTRA_CSV = Path(
    os.environ.get(
        "ASTRA_SDSS_PHOTOZ_CSV",
        "/Users/gjw255/astrodata/SWARM/ASTRA-dev-main/astra_core/scientific_discovery/"
        "evolved_analysis/data/photoz_sdss_cache.csv",
    )
)


def _ctx() -> ExecutionContext:
    return ExecutionContext(40, 10)


def _synthetic_rows(n: int = 300, seed: int = 0) -> list[SDSSRow]:
    """u is made to correlate strongly with z_spec; declination is independent."""
    rng = random.Random(seed)
    rows: list[SDSSRow] = []
    for _ in range(n):
        u = rng.uniform(17.0, 21.0)
        z_spec = 0.15 * (u - 17.0) + rng.gauss(0.0, 0.01)  # near-linear in u
        rows.append(
            SDSSRow(
                u=u, g=u, r=u, i=u, z_mag=u, z_spec=z_spec,
                ra=rng.uniform(0.0, 360.0), dec=rng.uniform(-1.0, 1.0),
            )
        )
    return rows


# --- unit tests (CI-safe; no ASTRA-dev dependency) --------------------------------


def test_sdss_true_candidate_passes_on_synthetic_data():
    adapter = SDSSPhotozAdapter(_synthetic_rows())
    candidate = adapter.propose(seed=1, limit=1)[0]  # predictor = u
    evidence = adapter.validate(candidate, stage="replication", seed=7, context=_ctx())[0]
    assert evidence.passed is True
    assert evidence.details["r"] > 0.5
    assert evidence.details["pvalue"] < 0.05
    assert evidence.details["data"] == "SDSS DR (ASTRA-dev cache)"


def test_sdss_false_candidate_fails_on_synthetic_data():
    adapter = SDSSPhotozAdapter(_synthetic_rows())
    candidate = adapter.propose(seed=1, limit=2)[1]  # predictor = dec
    evidence = adapter.validate(candidate, stage="replication", seed=7, context=_ctx())[0]
    assert evidence.passed is False
    assert evidence.details["r"] < 0.5


def test_sdss_from_csv_round_trip_skips_bad_rows(tmp_path: Path):
    path = tmp_path / "mini.csv"
    lines = ["objid,ra,dec,u,g,r,i,z_mag,z_spec,plate,mjd,fiberid"]
    for n in range(12):  # adapter requires >= 10 usable rows for a held-out test
        lines.append(
            f"{n},{1.0 + 0.01 * n},0.5,{18 + 0.1 * n},17.5,17.0,16.7,16.5,{0.05 * n},1,1,1"
        )
    lines.append("bad,row,here,nope,nope,nope,nope,nope,nope,1,1,1")  # skipped
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    adapter = SDSSPhotozAdapter.from_csv(path)
    assert len(adapter._rows) == 12  # type: ignore[attr-defined]


def test_sdss_adapter_is_non_synthetic_and_registry_requires_approver():
    assert SDSSPhotozAdapter.manifest.synthetic_only is False
    adapter = SDSSPhotozAdapter(_synthetic_rows())
    registry = AdapterRegistry()
    with pytest.raises(ValueError):
        registry.register(adapter)  # non-synthetic requires an approver
    registration = registry.register(
        adapter, approver="tester", capabilities=("filesystem-read",)
    )
    assert registration.tier.value == "vetted"


# --- integration test: real SDSS data from ASTRA-dev (skipped if absent) -----------


@pytest.mark.skipif(not _ASTRA_CSV.exists(), reason="ASTRA-dev SDSS cache not present")
def test_sdss_real_data_discovery_pipeline(tmp_path: Path):
    adapter = SDSSPhotozAdapter.from_csv(_ASTRA_CSV)

    # non-synthetic -> must be admitted at VETTED tier with an approver + capabilities
    registry = AdapterRegistry()
    registry.register(
        adapter,
        approver="gjw255",
        capabilities=("filesystem-read",),
        note="ASTRA-dev SDSS photoz connector",
    )
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    kernel = DiscoveryKernel(ledger, registry=registry)

    true_candidate = adapter.propose(seed=1, limit=1)[0]  # u-band <-> redshift
    def climb(candidate):
        return [
            kernel.validate_next(adapter, candidate, seed=s, context=_ctx())
            for s in (10, 11, 12)
        ]

    kernel.register(true_candidate)
    # real held-out SDSS evidence: u-band correlation clears every gate up to L3
    assert climb(true_candidate) == [EvidenceLevel.L1, EvidenceLevel.L2, EvidenceLevel.L3]
    assert ledger.verify() is True

    false_candidate = adapter.propose(seed=1, limit=2)[1]  # declination <-> redshift (null)
    kernel.register(false_candidate)
    false_level = kernel.validate_next(adapter, false_candidate, seed=10, context=_ctx())
    assert false_level == EvidenceLevel.L0
