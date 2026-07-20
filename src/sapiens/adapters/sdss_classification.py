"""SDSS star/galaxy classification connector adapter (Phase 4 — real data).

Connects to ASTRA-dev **read-only** via its bundled ``sdss_class_cache.csv`` (ugriz +
STAR/GALAXY/QSO label). Each candidate claims a measurable quantity separates stars
from non-stars; the adapter learns a threshold on a TRAIN split and reports held-out
classification accuracy with an exact Clopper-Pearson confidence interval
(``sapiens.validation.proportion_ci``). An ``EvidenceGate`` decides. Real data, real
statistics; claims no discovery. Non-synthetic -> VETTED tier.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from sapiens.budget import ExecutionContext
from sapiens.models import AdapterManifest, Candidate, Evidence
from sapiens.validation import PassPolicy, evaluate, holdout_split, proportion_ci

_POLICY = PassPolicy(min_effect=0.70, ci_floor=0.70)
_PREDICTORS = frozenset({"r-i", "g-r", "ra", "dec"})


def _identifier(*parts: object) -> str:
    return sha256("|".join(map(str, parts)).encode()).hexdigest()[:20]


@dataclass(frozen=True)
class SDSSClassRow:
    r: float
    i: float
    g: float
    ra: float
    dec: float
    is_star: bool


def _predictor_value(row: SDSSClassRow, predictor: str) -> float:
    if predictor == "r-i":
        return row.r - row.i
    if predictor == "g-r":
        return row.g - row.r
    if predictor == "ra":
        return row.ra
    if predictor == "dec":
        return row.dec
    raise ValueError(f"unknown predictor {predictor!r}")


class SDSSClassificationAdapter:
    manifest = AdapterManifest(
        name="sdss-classification",
        version="1.0",
        domain="sdss-classification",
        vocabulary=("u", "g", "r", "i", "z", "spec_class", "is_star"),
        synthetic_only=False,
    )

    def __init__(self, rows: list[SDSSClassRow]) -> None:
        if len(rows) < 10:
            raise ValueError("need at least 10 rows for a meaningful held-out test")
        self._rows: tuple[SDSSClassRow, ...] = tuple(rows)

    @classmethod
    def from_csv(cls, path: str | Path) -> SDSSClassificationAdapter:
        rows: list[SDSSClassRow] = []
        with open(path, newline="", encoding="utf-8") as handle:
            for rec in csv.DictReader(handle):
                try:
                    rows.append(
                        SDSSClassRow(
                            g=float(rec["g"]),
                            r=float(rec["r"]),
                            i=float(rec["i"]),
                            ra=float(rec["ra"]),
                            dec=float(rec["dec"]),
                            is_star=(str(rec.get("spec_class", "")).strip().upper() == "STAR"),
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
                _identifier(self.manifest.name, seed, "r-i"),
                self.manifest.domain,
                "r-i colour separates stars from non-stars in SDSS",
                {"relation": "classification", "predictor": "r-i"},
                source_adapter=self.manifest.name,
            ),
            Candidate(
                _identifier(self.manifest.name, seed, "dec"),
                self.manifest.domain,
                "declination separates stars from non-stars in SDSS",
                {"relation": "classification", "predictor": "dec"},
                source_adapter=self.manifest.name,
            ),
        )
        return candidates[:limit]

    @staticmethod
    def _learn_threshold(values: list[float], labels: list[bool]) -> tuple[float, int]:
        """Threshold + direction maximising STAR-vs-not accuracy on the train split."""
        ordered = sorted(set(values))
        candidates = ordered[:: max(1, len(ordered) // 100)]
        n = len(labels)
        best_acc, best_t, best_sign = -1.0, 0.0, 1
        for threshold in candidates:
            for sign in (1, -1):
                correct = sum(
                    1
                    for v, lab in zip(values, labels, strict=True)
                    if (v * sign > threshold * sign) == lab
                )
                acc = correct / n
                if acc > best_acc:
                    best_acc, best_t, best_sign = acc, threshold, sign
        return best_t, best_sign

    def _heldout_accuracy(self, predictor: str, *, seed: int) -> tuple[float, float, int]:
        split = holdout_split(len(self._rows), train_fraction=0.5, seed=seed)
        train_idx, test_idx = split.train, split.test
        train_vals = [_predictor_value(self._rows[t], predictor) for t in train_idx]
        train_labels = [self._rows[t].is_star for t in train_idx]
        threshold, sign = self._learn_threshold(train_vals, train_labels)
        test_vals = [_predictor_value(self._rows[t], predictor) for t in test_idx]
        test_labels = [self._rows[t].is_star for t in test_idx]
        correct = sum(
            1
            for v, lab in zip(test_vals, test_labels, strict=True)
            if (v * sign > threshold * sign) == lab
        )
        ci = proportion_ci(correct, len(test_idx))
        return ci.point, ci.lower, len(test_idx)

    def validate(
        self, candidate: Candidate, *, stage: str, seed: int, context: ExecutionContext
    ) -> tuple[Evidence, ...]:
        context.checkpoint()
        predictor = str(candidate.parameters.get("predictor", "r-i"))
        if predictor not in _PREDICTORS:
            raise ValueError(f"unknown predictor {predictor!r}")
        data_seed = seed + (4000 if stage != "internal" else 0)
        runs = 3 if stage == "review" else 1
        points: list[float] = []
        lowers: list[float] = []
        n_test = 0
        for offset in range(runs):
            context.checkpoint()
            point, lower, n_test = self._heldout_accuracy(predictor, seed=data_seed + offset * 17)
            points.append(point)
            lowers.append(lower)
        accuracy = min(points)        # conservative worst case
        ci_lower = min(lowers)
        decision = evaluate(point=accuracy, ci_lower=ci_lower, policy=_POLICY)
        score = max(0.0, min(1.0, accuracy))
        return (
            Evidence(
                _identifier(candidate.candidate_id, stage, seed),
                candidate.candidate_id,
                stage,
                decision.passed,
                f"sdss-class-{stage}-v1",
                "sdss-dr-heldout",
                seed,
                score,
                {
                    "accuracy": accuracy,
                    "ci_lower": ci_lower,
                    "n_test": n_test,
                    "predictor": predictor,
                    "runs": runs,
                    "data": "SDSS DR (ASTRA-dev cache)",
                    "reasons": list(decision.reasons),
                },
            ),
        )

    def import_structure(self, structure: dict[str, object], *, candidate_id: str) -> Candidate:
        predictor = str(structure.get("predictor", "r-i"))
        predictor = predictor if predictor in _PREDICTORS else "r-i"
        return Candidate(
            candidate_id,
            self.manifest.domain,
            "test a transferred classification structure against SDSS data",
            {"relation": "classification", "predictor": predictor},
            parent_id=str(structure.get("_source_candidate_id", "")) or None,
            source_adapter=self.manifest.name,
        )
