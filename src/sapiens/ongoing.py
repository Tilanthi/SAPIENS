"""Ongoing discovery: wide sweep over available real adapters into the persistent store.

Each run tests every available real-data candidate — SDSS predictors (photoz +
classification) and Mopra molecular-line cubes (spatial concentration vs an RA null) —
climbing each through the kernel (capped at L3) and upserting it into the
``DiscoveryStore``. Re-running with a fresh seed re-validates on new holdout splits, so
the store tracks each candidate's evidence over time. The store never claims a discovery
— level <= L3, no human gate.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from .adapters import SDSSClassificationAdapter, SDSSPhotozAdapter
from .adapters.mopra import MopraMolecularAdapter
from .budget import ExecutionContext
from .discovery_store import DiscoveryStore
from .kernel import DiscoveryKernel
from .ledger import EvidenceLedger
from .models import Candidate, EvidenceLevel
from .trust import AdapterRegistry

_ASTRA_DATA = Path(
    "/Users/gjw255/astrodata/SWARM/ASTRA-dev-main/astra_core/scientific_discovery/"
    "evolved_analysis/data"
)
PHOTOZ_CSV = _ASTRA_DATA / "photoz_sdss_cache.csv"
CLASS_CSV = _ASTRA_DATA / "sdss_class_cache.csv"

_MOPRA_DIR = Path("/Users/gjw255/astrodata/MOPRA_SgrB2")
_MOPRA_CUBES = [
    (_MOPRA_DIR / "SgrB2_bb_13CO_110_cube.fits", "13CO"),
    (_MOPRA_DIR / "SgrB2_89_HCO+_nb_cube.fits", "HCO+"),
    (_MOPRA_DIR / "SgrB2_88_HCN_nb_cube.fits", "HCN"),
    (_MOPRA_DIR / "SgrB2_97_CS_nb_cube.fits", "CS"),
    (_MOPRA_DIR / "SgrB2_86_SiO_nb_cube.fits", "SiO"),
]

_PHOTOZ_PREDICTORS = ("u", "g", "r", "i", "z_mag", "ra", "dec")
_CLASS_PREDICTORS = ("r-i", "g-r", "ra", "dec")


def _candidate_key(adapter, candidate) -> str:
    """Stable store key so re-runs upsert the same candidate rather than duplicating."""
    tag = candidate.parameters.get("predictor") or candidate.parameters.get("claim_type") or "x"
    return f"{adapter.manifest.name}:{tag}"


def _available_sources(seed: int) -> list:
    """Return [(adapter, [candidates]), ...] for every real dataset present."""
    sources: list = []

    if PHOTOZ_CSV.exists():
        base = SDSSPhotozAdapter.from_csv(PHOTOZ_CSV)
        cands = [
            Candidate(
                f"{base.manifest.name}:{p}",
                base.manifest.domain,
                f"{p} predicts redshift",
                {"relation": "correlation", "predictor": p},
                source_adapter=base.manifest.name,
            )
            for p in _PHOTOZ_PREDICTORS
        ]
        sources.append((base, cands))

    if CLASS_CSV.exists():
        base = SDSSClassificationAdapter.from_csv(CLASS_CSV)
        cands = [
            Candidate(
                f"{base.manifest.name}:{p}",
                base.manifest.domain,
                f"{p} separates stars",
                {"relation": "classification", "predictor": p},
                source_adapter=base.manifest.name,
            )
            for p in _CLASS_PREDICTORS
        ]
        sources.append((base, cands))

    for cube_path, molecule in _MOPRA_CUBES:
        if not cube_path.exists():
            continue
        try:
            base = MopraMolecularAdapter.from_fits(cube_path, molecule=molecule)
        except Exception:
            continue  # astropy missing or unreadable cube -> skip silently
        sources.append((base, list(base.propose(seed=seed, limit=2))))

    return sources


def run_ongoing(store_path: str | Path, *, seed: int | None = None, run_id: str | None = None):
    """Sweep every available real candidate and upsert into the store."""
    if seed is None:
        seed = int(time.time()) % 1_000_000
    store = DiscoveryStore(store_path)
    sources = _available_sources(seed)
    if not sources:
        return {
            "note": "no real data available (SDSS caches + Mopra cubes); nothing to sweep",
            "swept": 0,
            "reached_l3": 0,
        }

    registry = AdapterRegistry()
    for adapter, _ in sources:
        registry.register(
            adapter,
            approver="ongoing-discovery",
            capabilities=("filesystem-read",),
            note="real-data connector",
        )

    swept = reached_l3 = 0
    for adapter, candidates in sources:
        with tempfile.TemporaryDirectory() as directory:
            ledger = EvidenceLedger(Path(directory) / "evidence.jsonl")
            kernel = DiscoveryKernel(ledger, registry=registry)
            for candidate in candidates:
                key = _candidate_key(adapter, candidate)
                kernel.register(candidate)
                level = EvidenceLevel.L0
                for offset in (0, 1, 2):
                    try:
                        reached = kernel.validate_next(
                            adapter, candidate, seed=seed + offset, context=ExecutionContext(60, 30)
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
                    key,
                    candidate.domain,
                    candidate.claim,
                    int(level),
                    max(scores) if scores else 0.0,
                    adapter.manifest.name,
                    run_id or f"ongoing-{seed}",
                )
                swept += 1
                if level == EvidenceLevel.L3:
                    reached_l3 += 1
    return {"swept": swept, "reached_l3": reached_l3, "seed": seed, "store_size": len(store)}
