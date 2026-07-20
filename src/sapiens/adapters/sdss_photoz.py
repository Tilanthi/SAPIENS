"""SDSS photometric-redshift connector adapter (Phase 4 v1 — real data).

Connects to ASTRA-dev **read-only**: it loads ASTRA-dev's bundled real SDSS cache
(``photoz_sdss_cache.csv``: u,g,r,i,z magnitudes + spectroscopic redshift ``z_spec``) at
runtime via ``from_csv``. It never imports ASTRA code and never modifies the ASTRA-dev
folder. Each candidate is a claim that some measurable quantity correlates with
redshift; the adapter tests the claim with a genuine held-out Pearson correlation and
p-value (``sapiens.validation``) and an ``EvidenceGate`` decides.

Real data, real statistics — but the adapter claims **no discovery**: promotion only
means the correlation held on held-out SDSS objects. Non-synthetic
(``synthetic_only=False``) → must be admitted at ``VETTED`` tier through the trust
registry (approver + capabilities on record).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from sapiens.budget import ExecutionContext
from sapiens.models import AdapterManifest, Candidate, Evidence
from sapiens.validation import PassPolicy, evaluate, holdout_split, pearson

_POLICY = PassPolicy(min_effect=0.5, max_pvalue=0.05)
_FIELDS = frozenset({"u", "g", "r", "i", "z_mag", "z_spec", "ra", "dec"})


def _identifier(*parts: object) -> str:
    return sha256("|".join(map(str, parts)).encode()).hexdigest()[:20]


@dataclass(frozen=True)
class SDSSRow:
    u: float
    g: float
    r: float
    i: float
    z_mag: float
    z_spec: float
    ra: float
    dec: float


class SDSSPhotozAdapter:
    manifest = AdapterManifest(
        name="sdss-photoz",
        version="1.0",
        domain="sdss-photoz",
        vocabulary=("u", "g", "r", "i", "z", "z_spec", "redshift"),
        synthetic_only=False,
    )

    def __init__(self, rows: list[SDSSRow]) -> None:
        if len(rows) < 10:
            raise ValueError("need at least 10 rows for a meaningful held-out test")
        self._rows: tuple[SDSSRow, ...] = tuple(rows)

    @classmethod
    def from_csv(cls, path: str | Path) -> SDSSPhotozAdapter:
        """Load real SDSS rows from ASTRA-dev's cache (read-only)."""
        rows: list[SDSSRow] = []
        with open(path, newline="", encoding="utf-8") as handle:
            for rec in csv.DictReader(handle):
                try:
                    rows.append(
                        SDSSRow(
                            u=float(rec["u"]),
                            g=float(rec["g"]),
                            r=float(rec["r"]),
                            i=float(rec["i"]),
                            z_mag=float(rec["z_mag"]),
                            z_spec=float(rec["z_spec"]),
                            ra=float(rec["ra"]),
                            dec=float(rec["dec"]),
                        )
                    )
                except (KeyError, ValueError, TypeError):
                    continue
        if len(rows) < 10:
            raise ValueError(f"insufficient usable rows in {path}")
        return cls(rows)

    def propose(self, *, seed: int, limit: int) -> tuple[Candidate, ...]:
        if limit <= 0:
            return ()
        candidates = (
            Candidate(
                _identifier(self.manifest.name, seed, "u"),
                self.manifest.domain,
                "u-band magnitude correlates with spectroscopic redshift in SDSS",
                {"relation": "correlation", "predictor": "u"},
                source_adapter=self.manifest.name,
            ),
            Candidate(
                _identifier(self.manifest.name, seed, "dec"),
                self.manifest.domain,
                "declination correlates with spectroscopic redshift in SDSS",
                {"relation": "correlation", "predictor": "dec"},
                source_adapter=self.manifest.name,
            ),
        )
        return candidates[:limit]

    def _heldout_correlation(self, predictor: str, *, seed: int) -> tuple[float, float, int]:
        split = holdout_split(len(self._rows), train_fraction=0.5, seed=seed)
        xs = [getattr(self._rows[t], predictor) for t in split.test]
        ys = [self._rows[t].z_spec for t in split.test]
        result = pearson(xs, ys)
        return result.r, result.pvalue, len(split.test)

    def validate(
        self, candidate: Candidate, *, stage: str, seed: int, context: ExecutionContext
    ) -> tuple[Evidence, ...]:
        context.checkpoint()
        predictor = str(candidate.parameters.get("predictor", "u"))
        if predictor not in _FIELDS:
            raise ValueError(f"unknown predictor {predictor!r}")
        data_seed = seed + (3000 if stage != "internal" else 0)
        runs = 3 if stage == "review" else 1
        correlations: list[float] = []
        pvalues: list[float] = []
        n_test = 0
        for offset in range(runs):
            context.checkpoint()
            r, pvalue, n_test = self._heldout_correlation(predictor, seed=data_seed + offset * 17)
            correlations.append(r)
            pvalues.append(pvalue)
        point = min(correlations)  # conservative worst case across runs
        pvalue = max(pvalues)
        decision = evaluate(point=point, pvalue=pvalue, policy=_POLICY)
        score = max(0.0, min(1.0, point))
        return (
            Evidence(
                _identifier(candidate.candidate_id, stage, seed),
                candidate.candidate_id,
                stage,
                decision.passed,
                f"sdss-photoz-{stage}-v1",
                "sdss-dr-heldout",
                seed,
                score,
                {
                    "r": point,
                    "pvalue": pvalue,
                    "n_test": n_test,
                    "predictor": predictor,
                    "runs": runs,
                    "data": "SDSS DR (ASTRA-dev cache)",
                    "reasons": list(decision.reasons),
                },
            ),
        )

    def import_structure(self, structure: dict[str, object], *, candidate_id: str) -> Candidate:
        predictor = str(structure.get("predictor", "u"))
        predictor = predictor if predictor in _FIELDS else "u"
        return Candidate(
            candidate_id,
            self.manifest.domain,
            "test a transferred correlation structure against SDSS redshift data",
            {"relation": "correlation", "predictor": predictor},
            parent_id=str(structure.get("_source_candidate_id", "")) or None,
            source_adapter=self.manifest.name,
        )
