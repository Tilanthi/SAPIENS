from pathlib import Path

from sapiens.adapters import SyntheticLinearAdapter, SyntheticThresholdAdapter
from sapiens.discovery_store import DiscoveryStore, run_discovery_sweep


def test_store_top_for_l4_ranks_l3_candidates_by_score(tmp_path: Path):
    store = DiscoveryStore(tmp_path / "d.db")
    store.record("a", "dom", "claim a", final_level=3, score=0.90, source_adapter="s", run_id="r1")
    store.record("b", "dom", "claim b", final_level=3, score=0.95, source_adapter="s", run_id="r1")
    store.record("c", "dom", "claim c", final_level=1, score=0.50, source_adapter="s", run_id="r1")

    top = store.top_for_l4(limit=10)
    # only L3 candidates, ranked by score descending
    assert [r.candidate_id for r in top] == ["b", "a"]
    assert all(r.final_level == 3 for r in top)


def test_store_is_idempotent_on_candidate_id(tmp_path: Path):
    store = DiscoveryStore(tmp_path / "d.db")
    store.record("a", "dom", "claim", final_level=3, score=0.90, source_adapter="s", run_id="r1")
    store.record("a", "dom", "claim", final_level=3, score=0.93, source_adapter="s", run_id="r2")
    assert len(store) == 1
    assert store.top_for_l4()[0].score == 0.93
    assert store.top_for_l4()[0].run_id == "r2"


def test_run_discovery_sweep_persists_climbed_candidates(tmp_path: Path):
    store = DiscoveryStore(tmp_path / "d.db")
    summary = run_discovery_sweep(
        [SyntheticLinearAdapter(), SyntheticThresholdAdapter()],
        store,
        seed=3,
        run_id="test",
        limit_per_adapter=2,
    )
    assert summary["proposed"] == 4  # 2 adapters x (true + wrong)
    top = store.top_for_l4(limit=10)
    # the true candidate of each adapter reaches L3
    assert len(top) == 2
    assert all(r.final_level == 3 for r in top)
    counts = store.counts_by_level()
    assert counts.get(3, 0) == 2


def test_store_counts_by_level(tmp_path: Path):
    store = DiscoveryStore(tmp_path / "d.db")
    store.record("a", "d", "c", final_level=3, score=0.9, source_adapter="s", run_id="r")
    store.record("b", "d", "c", final_level=0, score=0.1, source_adapter="s", run_id="r")
    assert store.counts_by_level() == {3: 1, 0: 1}
