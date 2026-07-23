"""Ongoing discovery: wide sweep over available real adapters into the persistent store.

Each run tests every available real-data candidate — SDSS predictors (photoz +
classification) and Mopra molecular-line cubes (spatial concentration vs an RA null) —
climbing each through the kernel (capped at L3) and upserting it into the
``DiscoveryStore``. Re-running with a fresh seed re-validates on new holdout splits, so
the store tracks each candidate's evidence over time. The store never claims a discovery
— level <= L3, no human gate.
"""

from __future__ import annotations

import json
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
from .validation import holdout_split

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


# --- anomaly detection (discovery substrate v1) -----------------------------------


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _mad_sigma(values: list[float]) -> float:
    """Median absolute deviation converted to a sigma-equivalent scale (×1.4826)."""
    m = _median(values)
    return 1.4826 * _median([abs(v - m) for v in values]) or 1e-9


def run_anomaly_scan(registry_path: str | Path, *, seed: int | None = None) -> dict:
    """Detect model-mismatch anomalies in real SDSS data and register them.

    Photoz: flags objects whose z_spec residual from a u-band linear model exceeds
    4 sigma (MAD-scaled). Classification: flags objects misclassified by the learned
    r-i threshold. Each anomaly is registered with a survivability score; nothing is
    auto-discarded. These are NOT discoveries — they are "this doesn't fit; look here."
    """
    from .anomaly import AnomalyRegistry

    if seed is None:
        seed = int(time.time()) % 1_000_000
    registry = AnomalyRegistry(registry_path)
    found = 0

    if PHOTOZ_CSV.exists():
        adapter = SDSSPhotozAdapter.from_csv(PHOTOZ_CSV)
        rows = adapter._rows  # type: ignore[attr-defined]
        split = holdout_split(len(rows), train_fraction=0.5, seed=seed)
        train = [rows[i] for i in split.train]
        test = [rows[i] for i in split.test]
        # fit z = a + b*u on train
        us = [r.u for r in train]
        zs = [r.z_spec for r in train]
        mu = sum(us) / len(us)
        mz = sum(zs) / len(zs)
        cov = sum((u - mu) * (z - mz) for u, z in zip(us, zs, strict=True))
        var_u = sum((u - mu) ** 2 for u in us)
        slope = cov / var_u if var_u else 0.0
        intercept = mz - slope * mu
        # residuals on held-out test
        residuals = [(r, r.z_spec - (intercept + slope * r.u)) for r in test]
        sigma = _mad_sigma([res for _, res in residuals])
        for r, res in residuals:
            n_sigma = abs(res) / sigma
            if n_sigma > 4.0:
                severity = min(1.0, (n_sigma - 4.0) / 10.0)
                registry.register(
                    anomaly_id=f"photoz-outlier:ra={r.ra:.4f}:dec={r.dec:.4f}",
                    domain="sdss-photoz",
                    kind="structured_residual",
                    description=(
                        f"z_spec residual {res:+.4f} ({n_sigma:.1f} sigma above "
                        f"MAD scatter) from u-band photo-z model"
                    ),
                    severity=severity,
                    object_ref=f"ra={r.ra:.4f},dec={r.dec:.4f}",
                    details_json=json.dumps(
                        {
                            "u": round(r.u, 3),
                            "z_spec": round(r.z_spec, 5),
                            "z_pred": round(intercept + slope * r.u, 5),
                            "residual": round(res, 5),
                            "n_sigma": round(n_sigma, 2),
                        }
                    ),
                )
                found += 1

    if CLASS_CSV.exists():
        adapter = SDSSClassificationAdapter.from_csv(CLASS_CSV)
        rows = adapter._rows  # type: ignore[attr-defined]
        split = holdout_split(len(rows), train_fraction=0.5, seed=seed)
        train = [rows[i] for i in split.train]
        test = [rows[i] for i in split.test]
        train_vals = [r.r - r.i for r in train]
        train_labels = [r.is_star for r in train]
        threshold, sign = adapter._learn_threshold(train_vals, train_labels)
        for r in test:
            val = r.r - r.i
            predicted = val * sign > threshold * sign
            if predicted != r.is_star:
                distance = abs(val - threshold)
                severity = min(1.0, distance / 2.0)
                label = "STAR" if r.is_star else "non-STAR"
                registry.register(
                    anomaly_id=f"class-misfit:ra={r.ra:.4f}:dec={r.dec:.4f}",
                    domain="sdss-classification",
                    kind="template_rejection",
                    description=(
                        f"{label} misclassified by r-i threshold "
                        f"(r-i={val:.3f}, threshold={threshold:.3f})"
                    ),
                    severity=severity,
                    object_ref=f"ra={r.ra:.4f},dec={r.dec:.4f}",
                    details_json=json.dumps(
                        {
                            "r_minus_i": round(val, 3),
                            "threshold": round(threshold, 3),
                            "is_star": r.is_star,
                            "predicted_star": predicted,
                            "distance_from_boundary": round(distance, 3),
                        }
                    ),
                )
                found += 1

    return {"anomalies_found": found, "seed": seed, "registry_size": len(registry)}


# --- full model-mismatch detector (priority 1d) -----------------------------------


def detect_model_mismatch(registry_path: str | Path, *, seed: int | None = None) -> dict:
    """Detect sign-flips and ceiling violations in real SDSS data.

    Sign-flip: does the u-band <-> z_spec correlation flip sign or drop sharply between
    bright and faint magnitude subsamples? If so, the relationship is not universal — a
    model mismatch. Ceiling violation: any object with physically impossible values.
    """
    from .anomaly import AnomalyRegistry
    from .validation import pearson

    if seed is None:
        seed = int(time.time()) % 1_000_000
    registry = AnomalyRegistry(registry_path)
    found = 0

    if PHOTOZ_CSV.exists():
        adapter = SDSSPhotozAdapter.from_csv(PHOTOZ_CSV)
        rows = adapter._rows  # type: ignore[attr-defined]
        median_u = _median([r.u for r in rows])
        bright = [r for r in rows if r.u < median_u]
        faint = [r for r in rows if r.u >= median_u]
        rb = pearson([r.u for r in bright], [r.z_spec for r in bright])
        rf = pearson([r.u for r in faint], [r.z_spec for r in faint])
        delta = abs(rb.r - rf.r)
        sign_flip = rb.r * rf.r < 0
        if sign_flip or delta > 0.3:
            registry.register(
                anomaly_id=f"photoz-signflip:{seed}",
                domain="sdss-photoz",
                kind="model_mismatch",
                description=(
                    f"u-z correlation {'SIGN-FLIPS' if sign_flip else 'drops sharply'} "
                    f"between bright (r={rb.r:.3f}) and faint (r={rf.r:.3f}) subsamples "
                    f"(delta={delta:.3f})"
                ),
                severity=min(1.0, delta),
                object_ref="population-level",
                details_json=json.dumps(
                    {
                        "r_bright": round(rb.r, 4),
                        "r_faint": round(rf.r, 4),
                        "delta": round(delta, 4),
                    }
                ),
            )
            found += 1

        for r in rows:
            if r.u < 10.0 or r.z_spec < -0.01 or r.z_spec > 10.0:
                registry.register(
                    anomaly_id=f"photoz-ceiling:ra={r.ra:.4f}:dec={r.dec:.4f}",
                    domain="sdss-photoz",
                    kind="ceiling_violation",
                    description=f"extreme value: u={r.u:.2f}, z_spec={r.z_spec:.5f}",
                    severity=0.8,
                    object_ref=f"ra={r.ra:.4f},dec={r.dec:.4f}",
                    details_json=json.dumps({"u": r.u, "z_spec": r.z_spec}),
                )
                found += 1

    return {"mismatches_found": found, "seed": seed}


# --- cross-method tension register (priority 1c) -----------------------------------


def record_tensions(tension_path: str | Path, *, seed: int | None = None) -> dict:
    """Record precision-quantity estimates from multiple methods for tension tracking."""
    from .tension import TensionRegister, fisher_z_ci
    from .validation import pearson, proportion_ci

    if seed is None:
        seed = int(time.time()) % 1_000_000
    register = TensionRegister(tension_path)
    recorded = 0

    if PHOTOZ_CSV.exists():
        adapter = SDSSPhotozAdapter.from_csv(PHOTOZ_CSV)
        rows = adapter._rows  # type: ignore[attr-defined]
        for band_label, attr in [
            ("u_band", "u"), ("g_band", "g"), ("r_band", "r"),
            ("i_band", "i"), ("z_band", "z_mag"),
        ]:
            vals = [getattr(r, attr) for r in rows]
            zs = [r.z_spec for r in rows]
            result = pearson(vals, zs)
            ci_lo, ci_hi = fisher_z_ci(result.r, result.n)
            register.record(
                "photoz_correlation", band_label, result.r,
                ci_lo, ci_hi, seed, f"ongoing-{seed}",
            )
            recorded += 1

    if CLASS_CSV.exists():
        adapter = SDSSClassificationAdapter.from_csv(CLASS_CSV)
        rows = adapter._rows  # type: ignore[attr-defined]
        for pred_label, pred_fn in [
            ("r-i", lambda r: r.r - r.i),
            ("g-r", lambda r: r.g - r.r),
        ]:
            split = holdout_split(len(rows), train_fraction=0.5, seed=seed)
            train = [rows[i] for i in split.train]
            test = [rows[i] for i in split.test]
            train_vals = [pred_fn(r) for r in train]
            train_labels = [r.is_star for r in train]
            threshold, sign = adapter._learn_threshold(train_vals, train_labels)
            correct = sum(
                1 for r in test if (pred_fn(r) * sign > threshold * sign) == r.is_star
            )
            ci = proportion_ci(correct, len(test))
            register.record(
                "classification_accuracy", pred_label, ci.point,
                ci.lower, ci.upper, seed, f"ongoing-{seed}",
            )
            recorded += 1

    return {"tensions_recorded": recorded, "seed": seed, "register_size": len(register)}


# --- systematic sieve (priority 1b) ------------------------------------------------


def run_sieve(anomaly_registry_path: str | Path, *, seed: int | None = None) -> dict:
    """Run systematic checks on detected anomaly populations."""
    from .anomaly import AnomalyRegistry
    from .sieve import sieve_population

    if seed is None:
        seed = int(time.time()) % 1_000_000
    registry = AnomalyRegistry(anomaly_registry_path)
    results: list = []

    if PHOTOZ_CSV.exists():
        adapter = SDSSPhotozAdapter.from_csv(PHOTOZ_CSV)
        rows = adapter._rows  # type: ignore[attr-defined]
        sample_ras = [r.ra for r in rows]
        sample_mags = [r.u for r in rows]
        anomalies = [
            a for a in registry.top(limit=500)
            if a.domain == "sdss-photoz" and a.kind == "structured_residual"
        ]
        ra_lookup = {(round(r.ra, 4), round(r.dec, 4)): r for r in rows}
        anomaly_mags: list[float] = []
        for a in anomalies:
            import re
            m = re.search(r"ra=([-\d.]+),dec=([-\d.]+)", a.object_ref)
            if m:
                key = (round(float(m.group(1)), 4), round(float(m.group(2)), 4))
                if key in ra_lookup:
                    anomaly_mags.append(ra_lookup[key].u)
        result = sieve_population(
            anomalies, sample_ras, sample_mags, anomaly_mags, domain="sdss-photoz"
        )
        results.append(result)

    if CLASS_CSV.exists():
        adapter = SDSSClassificationAdapter.from_csv(CLASS_CSV)
        rows = adapter._rows  # type: ignore[attr-defined]
        sample_ras = [r.ra for r in rows]
        sample_mags = [r.r for r in rows]
        anomalies = [
            a for a in registry.top(limit=500)
            if a.domain == "sdss-classification" and a.kind == "template_rejection"
        ]
        ra_lookup = {(round(r.ra, 4), round(r.dec, 4)): r for r in rows}
        anomaly_mags_cls: list[float] = []
        for a in anomalies:
            import re
            m = re.search(r"ra=([-\d.]+),dec=([-\d.]+)", a.object_ref)
            if m:
                key = (round(float(m.group(1)), 4), round(float(m.group(2)), 4))
                if key in ra_lookup:
                    anomaly_mags_cls.append(ra_lookup[key].r)
        result = sieve_population(
            anomalies, sample_ras, sample_mags, anomaly_mags_cls, domain="sdss-classification"
        )
        results.append(result)

    return {
        "sieve_runs": len(results),
        "results": [
            {
                "domain": r.domain,
                "n_anomalies": r.n_anomalies,
                "survived": r.survived,
                "robustness": round(r.robustness, 3),
                "checks": [
                    {"name": c.name, "passed": c.passed, "detail": c.detail}
                    for c in r.checks
                ],
            }
            for r in results
        ],
    }
