"""Ongoing discovery: wide sweep over available real adapters into the persistent store.

Each run tests every available real-data predictor (not just one or two candidates),
climbing each through the kernel (capped at L3) and upserting it into the
``DiscoveryStore``. Re-running with a fresh seed re-validates the same candidate set on
new holdout splits, so the store tracks each candidate's evidence over time. The store
never claims a discovery — level <= L3, no human gate.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from .adapters import SDSSClassificationAdapter, SDSSPhotozAdapter
from .budget import ExecutionContext
from .discovery_store import DiscoveryStore
from .kernel import DiscoveryKernel
from .ledger import EvidenceLedger
from .models import Candidate, EvidenceLevel
from .trust import AdapterRegistry

_DATA = Path(
    "/Users/gjw255/astrodata/SWARM/ASTRA-dev-main/astra_core/scientific_discovery/"
    "evolved_analysis/data"
)
PHOTOZ_CSV = _DATA / "photoz_sdss_cache.csv"
CLASS_CSV = _DATA / "sdss_class_cache.csv"

_PHOTOZ_PREDICTORS = ("u", "g", "r", "i", "z_mag", "ra", "dec")
_CLASS_PREDICTORS = ("r-i", "g-r", "ra", "dec")


def _available_adapters() -> list:
    """Load the real SDSS adapters that have data present (read-only). Empty if none."""
    adapters = []
    if PHOTOZ_CSV.exists():
        base = SDSSPhotozAdapter.from_csv(PHOTOZ_CSV)
        adapters.append((base, _PHOTOZ_PREDICTORS, "correlation"))
    if CLASS_CSV.exists():
        base = SDSSClassificationAdapter.from_csv(CLASS_CSV)
        adapters.append((base, _CLASS_PREDICTORS, "classification"))
    return adapters


def run_ongoing(store_path: str | Path, *, seed: int | None = None, run_id: str | None = None):
    """Sweep every available real predictor and upsert candidates into the store."""
    if seed is None:
        seed = int(time.time()) % 1_000_000
    store = DiscoveryStore(store_path)
    adapters = _available_adapters()
    if not adapters:
        return {
            "note": "no real SDSS data available; nothing to sweep",
            "swept": 0,
            "reached_l3": 0,
        }

    registry = AdapterRegistry()
    for base, _, _ in adapters:
        registry.register(
            base,
            approver="ongoing-discovery",
            capabilities=("filesystem-read",),
            note="SDSS connector",
        )

    swept = reached_l3 = 0
    for base, predictors, relation in adapters:
        with tempfile.TemporaryDirectory() as directory:
            ledger = EvidenceLedger(Path(directory) / "evidence.jsonl")
            kernel = DiscoveryKernel(ledger, registry=registry)
            for predictor in predictors:
                candidate = Candidate(
                    f"{base.manifest.name}:{predictor}",
                    base.manifest.domain,
                    f"{predictor} predicts target ({relation})",
                    {"relation": relation, "predictor": predictor},
                    source_adapter=base.manifest.name,
                )
                kernel.register(candidate)
                level = EvidenceLevel.L0
                for offset in (0, 1, 2):
                    try:
                        reached = kernel.validate_next(
                            base, candidate, seed=seed + offset, context=ExecutionContext(60, 30)
                        )
                    except Exception:
                        break
                    if reached == level:
                        break
                    level = reached
                scores = [
                    float(event.payload["score"])
                    for event in ledger.events()
                    if event.candidate_id == candidate.candidate_id
                    and event.kind == "evidence"
                    and event.payload.get("score") is not None
                ]
                store.record(
                    candidate.candidate_id,
                    candidate.domain,
                    candidate.claim,
                    int(level),
                    max(scores) if scores else 0.0,
                    base.manifest.name,
                    run_id or f"ongoing-{seed}",
                )
                swept += 1
                if level == EvidenceLevel.L3:
                    reached_l3 += 1
    return {"swept": swept, "reached_l3": reached_l3, "seed": seed, "store_size": len(store)}
