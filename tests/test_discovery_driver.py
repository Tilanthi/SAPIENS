from pathlib import Path

from sapiens import DiscoveryKernel, EvidenceLedger
from sapiens.adapters import SyntheticLinearAdapter, SyntheticThresholdAdapter
from sapiens.discovery import DiscoveryDriver, DiscoveryReport
from sapiens.queue import WorkQueue


def _driver(tmp_path: Path, *, seed: int = 3, adapters=None) -> DiscoveryDriver:
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    kernel = DiscoveryKernel(ledger)
    queue = WorkQueue(tmp_path / "queue.sqlite3")
    if adapters is None:
        linear = SyntheticLinearAdapter()
        adapters = {linear.manifest.name: linear}
    return DiscoveryDriver(adapters=adapters, queue=queue, kernel=kernel, seed=seed)


def test_driver_climbs_true_candidate_to_l3(tmp_path: Path):
    driver = _driver(tmp_path)
    proposed = driver.plan(limit_per_adapter=1)  # the true candidate only
    report = driver.run(worker="w", max_jobs=10, max_seconds=10, steps_per_job=20)

    assert proposed == 1
    assert isinstance(report, DiscoveryReport)
    assert len(report.reached_l3) == 1
    assert report.reached_l2 == 0
    assert report.stayed_l0 == 0
    assert report.ledger_verified is True
    assert report.scientific_discoveries_claimed == 0


def test_driver_wrong_candidate_stays_l0(tmp_path: Path):
    driver = _driver(tmp_path)
    driver.plan(limit_per_adapter=2)  # both candidates: true + wrong
    report = driver.run(worker="w", max_jobs=10, max_seconds=10, steps_per_job=20)

    assert len(report.reached_l3) == 1  # the true candidate
    assert report.stayed_l0 == 1  # the wrong candidate never passed internal


def test_driver_multiple_adapters(tmp_path: Path):
    linear = SyntheticLinearAdapter()
    threshold = SyntheticThresholdAdapter()
    adapters = {linear.manifest.name: linear, threshold.manifest.name: threshold}
    driver = _driver(tmp_path, adapters=adapters)
    driver.plan(limit_per_adapter=1)  # one true candidate per adapter
    report = driver.run(worker="w", max_jobs=10, max_seconds=10, steps_per_job=20)

    assert report.proposed == 2
    assert len(report.reached_l3) == 2
    assert report.ledger_verified is True


def test_driver_respects_budget(tmp_path: Path):
    driver = _driver(tmp_path)
    driver.plan(limit_per_adapter=1)
    # one step per job is too small to complete even the first promotion
    report = driver.run(worker="w", max_jobs=5, max_seconds=10, steps_per_job=1)

    assert report.scientific_discoveries_claimed == 0
    assert report.ledger_verified is True
    assert report.exhausted >= 1
    assert len(report.reached_l3) == 0  # could not complete a climb


def test_driver_adapter_error_is_contained(tmp_path: Path):
    class BoomAdapter(SyntheticLinearAdapter):
        def validate(self, candidate, *, stage, seed, context):  # type: ignore[override]
            raise RuntimeError("boom")

    boom = BoomAdapter()
    driver = _driver(tmp_path, adapters={boom.manifest.name: boom})
    driver.plan(limit_per_adapter=1)
    report = driver.run(worker="w", max_jobs=10, max_seconds=10, steps_per_job=20)

    assert report.stayed_l0 == 1  # candidate never promoted
    assert len(report.reached_l3) == 0
    assert report.ledger_verified is True  # run survived; ledger intact


def test_run_discovery_helper(tmp_path: Path):
    from sapiens.cli import run_discovery

    result = run_discovery(
        tmp_path, seed=5, max_jobs=10, max_seconds=10, steps_per_job=20, limit_per_adapter=1
    )

    assert result["scientific_discoveries_claimed"] == 0
    assert result["ledger_verified"] is True
    assert result["proposed"] == 2  # linear + threshold
    assert isinstance(result["reached_l3"], list)
