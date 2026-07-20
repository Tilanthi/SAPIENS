"""Synthetic regression adapter: real held-out statistics, not a rigged score.

Unlike the Phase-0 plumbing adapters (linear/threshold) that return a planted score to
exercise the pipeline, this adapter evaluates each candidate against held-out synthetic
data using a genuine Pearson correlation and its p-value (from ``sapiens.validation``)
and lets an ``EvidenceGate`` decide pass/fail. The methodology is real even though the
data is synthetic; nothing is claimed about nature.

A candidate hypothesises the *direction* of the predictor/response relationship. The
adapter generates synthetic data with a true positive slope and measures how well the
candidate's predicted direction correlates with the held-out response. A candidate with
the correct direction yields a strong positive correlation and passes the gate; a
candidate with the wrong direction yields a strong *negative* correlation and fails —
notably failing on effect size even though the correlation is "significant", which is the
correct behaviour (a significant result in the wrong direction is not evidence for the
candidate).
"""

from __future__ import annotations

import hashlib
import random

from sapiens.budget import ExecutionContext
from sapiens.models import AdapterManifest, Candidate, Evidence
from sapiens.validation import PassPolicy, evaluate, pearson

_SLOPE = 2.0
_NOISE = 1.0
_N = 60
_POLICY = PassPolicy(min_effect=0.5, max_pvalue=0.05)


def _identifier(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:20]


class SyntheticRegressionAdapter:
    manifest = AdapterManifest(
        name="synthetic-regression",
        version="1.0",
        domain="synthetic-regression",
        vocabulary=("predictor", "response", "slope", "noise"),
    )

    def propose(self, *, seed: int, limit: int) -> tuple[Candidate, ...]:
        if limit <= 0:
            return ()
        candidates = (
            Candidate(
                _identifier(self.manifest.name, seed, "positive"),
                self.manifest.domain,
                "response increases with the predictor in the synthetic generator",
                {"relation": "linear", "arity": 1, "direction": 1},
                source_adapter=self.manifest.name,
            ),
            Candidate(
                _identifier(self.manifest.name, seed, "negative"),
                self.manifest.domain,
                "response decreases with the predictor in the synthetic generator",
                {"relation": "linear", "arity": 1, "direction": -1},
                source_adapter=self.manifest.name,
            ),
        )
        return candidates[:limit]

    @staticmethod
    def _heldout_correlation(direction: int, *, seed: int) -> tuple[float, float]:
        """Real Pearson correlation between the candidate's prediction and held-out y."""
        rng = random.Random(seed)
        xs = [rng.uniform(-5.0, 5.0) for _ in range(_N)]
        ys = [_SLOPE * x + rng.gauss(0.0, _NOISE) for x in xs]
        predictions = [direction * x for x in xs]
        result = pearson(predictions, ys)
        return result.r, result.pvalue

    def validate(
        self, candidate: Candidate, *, stage: str, seed: int, context: ExecutionContext
    ) -> tuple[Evidence, ...]:
        context.checkpoint()
        direction = int(candidate.parameters.get("direction", 1))
        data_seed = seed + (2000 if stage != "internal" else 0)
        runs = 3 if stage == "review" else 1
        correlations: list[float] = []
        pvalues: list[float] = []
        for offset in range(runs):
            context.checkpoint()
            r, p = self._heldout_correlation(direction, seed=data_seed + offset * 13)
            correlations.append(r)
            pvalues.append(p)
        # conservative worst case across runs: smallest effect, largest p-value
        point = min(correlations)
        pvalue = max(pvalues)
        decision = evaluate(point=point, pvalue=pvalue, policy=_POLICY)
        score = max(0.0, min(1.0, point))
        return (
            Evidence(
                _identifier(candidate.candidate_id, stage, seed),
                candidate.candidate_id,
                stage,
                decision.passed,
                f"regression-{stage}-v1",
                "synthetic-heldout" if stage != "internal" else "synthetic-train",
                seed,
                score,
                {
                    "r": point,
                    "pvalue": pvalue,
                    "n": _N,
                    "runs": runs,
                    "reasons": list(decision.reasons),
                },
            ),
        )

    def import_structure(self, structure: dict[str, object], *, candidate_id: str) -> Candidate:
        return Candidate(
            candidate_id,
            self.manifest.domain,
            "test a transferred linear structure against synthetic regression data",
            {"relation": "linear", "arity": structure.get("arity", 1), "direction": 1},
            parent_id=str(structure.get("_source_candidate_id", "")) or None,
            source_adapter=self.manifest.name,
        )
