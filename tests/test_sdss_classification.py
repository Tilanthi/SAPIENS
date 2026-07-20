import os
import random
from pathlib import Path

import pytest

from sapiens import DiscoveryDriver, DiscoveryKernel, EvidenceLedger, EvidenceLevel
from sapiens.adapters import SDSSClassificationAdapter, SDSSPhotozAdapter
from sapiens.adapters.sdss_classification import SDSSClassRow
from sapiens.budget import ExecutionContext
from sapiens.queue import WorkQueue
from sapiens.trust import AdapterRegistry

_DATA = Path(
    "/Users/gjw255/astrodata/SWARM/ASTRA-dev-main/astra_core/scientific_discovery/"
    "evolved_analysis/data"
)
_PHOTOZ_CSV = Path(os.environ.get("ASTRA_SDSS_PHOTOZ_CSV", _DATA / "photoz_sdss_cache.csv"))
_CLASS_CSV = Path(os.environ.get("ASTRA_SDSS_CLASS_CSV", _DATA / "sdss_class_cache.csv"))
_HAVE_REAL = _PHOTOZ_CSV.exists() and _CLASS_CSV.exists()


def _ctx() -> ExecutionContext:
    return ExecutionContext(60, 30)


def _synthetic_class_rows(n: int = 400, seed: int = 0) -> list[SDSSClassRow]:
    """r-i separates stars from non-stars; ra/dec do not."""
    rng = random.Random(seed)
    rows: list[SDSSClassRow] = []
    for _ in range(n):
        star = rng.random() < 0.5
        r_minus_i = rng.gauss(0.10 if star else 0.50, 0.05)  # bimodal by class
        rows.append(
            SDSSClassRow(
                g=r_minus_i, r=r_minus_i, i=0.0,
                ra=rng.uniform(0.0, 360.0), dec=rng.uniform(-1.0, 1.0),
                is_star=star,
            )
        )
    return rows


# --- unit tests (CI-safe) ---------------------------------------------------------


def test_classification_true_predictor_passes_synthetic():
    adapter = SDSSClassificationAdapter(_synthetic_class_rows())
    candidate = adapter.propose(seed=1, limit=1)[0]  # r-i
    evidence = adapter.validate(candidate, stage="replication", seed=7, context=_ctx())[0]
    assert evidence.passed is True
    assert evidence.details["accuracy"] > 0.70


def test_classification_false_predictor_fails_synthetic():
    adapter = SDSSClassificationAdapter(_synthetic_class_rows())
    candidate = adapter.propose(seed=1, limit=2)[1]  # ra
    evidence = adapter.validate(candidate, stage="replication", seed=7, context=_ctx())[0]
    assert evidence.passed is False


def test_classification_registry_requires_approver():
    adapter = SDSSClassificationAdapter(_synthetic_class_rows())
    registry = AdapterRegistry()
    with pytest.raises(ValueError):
        registry.register(adapter)
    registry.register(adapter, approver="tester", capabilities=("filesystem-read",))


# --- integration: real SDSS classification data (skipped if ASTRA-dev absent) ------


@pytest.mark.skipif(not _CLASS_CSV.exists(), reason="ASTRA-dev SDSS class cache not present")
def test_sdss_classification_real_data_pipeline(tmp_path: Path):
    adapter = SDSSClassificationAdapter.from_csv(_CLASS_CSV)
    registry = AdapterRegistry()
    registry.register(
        adapter, approver="gjw255", capabilities=("filesystem-read",),
        note="ASTRA-dev SDSS classification connector",
    )
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    kernel = DiscoveryKernel(ledger, registry=registry)

    def climb(candidate):
        return [
            kernel.validate_next(adapter, candidate, seed=s, context=_ctx())
            for s in (10, 11, 12)
        ]

    true_candidate = adapter.propose(seed=1, limit=1)[0]  # r-i colour rule
    kernel.register(true_candidate)
    assert climb(true_candidate) == [EvidenceLevel.L1, EvidenceLevel.L2, EvidenceLevel.L3]
    assert ledger.verify() is True

    false_candidate = adapter.propose(seed=1, limit=2)[1]  # right ascension (null)
    kernel.register(false_candidate)
    false_level = kernel.validate_next(adapter, false_candidate, seed=10, context=_ctx())
    assert false_level == EvidenceLevel.L0


# --- #1: autonomous discovery over BOTH real SDSS adapters via the daemon ----------


@pytest.mark.skipif(not _HAVE_REAL, reason="ASTRA-dev SDSS caches not present")
def test_discovery_driver_runs_on_real_sdss_data(tmp_path: Path):
    photoz = SDSSPhotozAdapter.from_csv(_PHOTOZ_CSV)
    classifier = SDSSClassificationAdapter.from_csv(_CLASS_CSV)
    registry = AdapterRegistry()
    for adapter in (photoz, classifier):
        registry.register(
            adapter, approver="gjw255", capabilities=("filesystem-read",),
            note="ASTRA-dev SDSS connector",
        )
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    kernel = DiscoveryKernel(ledger, registry=registry)
    queue = WorkQueue(tmp_path / "discovery-queue.sqlite3")
    driver = DiscoveryDriver(
        adapters={photoz.manifest.name: photoz, classifier.manifest.name: classifier},
        queue=queue,
        kernel=kernel,
        seed=3,
    )
    driver.plan(limit_per_adapter=1)  # one true candidate per real adapter
    report = driver.run(worker="real-sdss", max_jobs=20, max_seconds=120, steps_per_job=60)

    # both real candidates climb to L3 autonomously through the daemon
    assert len(report.reached_l3) == 2
    assert report.stayed_l0 == 0
    assert report.ledger_verified is True
    assert report.scientific_discoveries_claimed == 0
