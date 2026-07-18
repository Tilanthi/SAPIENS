"""Synthetic threshold-interaction adapter used only for integration tests."""

from __future__ import annotations

import hashlib
import random

from sapiens.budget import ExecutionContext
from sapiens.models import AdapterManifest, Candidate, Evidence


def _identifier(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:20]


class SyntheticThresholdAdapter:
    manifest = AdapterManifest(
        name="synthetic-threshold",
        version="1.0",
        domain="synthetic-ecology",
        vocabulary=("temperature", "moisture", "threshold", "interaction"),
    )

    def propose(self, *, seed: int, limit: int) -> tuple[Candidate, ...]:
        if limit <= 0:
            return ()
        candidates = (
            Candidate(
                _identifier(self.manifest.name, seed, "interaction"),
                self.manifest.domain,
                "response activates above a two-variable synthetic threshold",
                {"relation": "threshold-interaction", "arity": 2, "threshold": 1.0},
                source_adapter=self.manifest.name,
            ),
            Candidate(
                _identifier(self.manifest.name, seed, "overfit"),
                self.manifest.domain,
                "a seed-specific threshold generalizes to unseen synthetic data",
                {"relation": "threshold-interaction", "arity": 2, "threshold": 1.8},
                source_adapter=self.manifest.name,
            ),
        )
        return candidates[:limit]

    @staticmethod
    def _accuracy(threshold: float, *, seed: int, holdout: bool) -> float:
        rng = random.Random(seed + (7919 if holdout else 0))
        correct = 0
        total = 80
        for _ in range(total):
            x, y = rng.random(), rng.random()
            actual = x + y >= 1.0
            predicted = x + y >= threshold
            correct += actual == predicted
        return correct / total

    def validate(
        self, candidate: Candidate, *, stage: str, seed: int, context: ExecutionContext
    ) -> tuple[Evidence, ...]:
        context.checkpoint()
        threshold = float(candidate.parameters.get("threshold", 1.0))
        scores = [self._accuracy(threshold, seed=seed, holdout=stage != "internal")]
        if stage == "review":
            for offset in (31, 73):
                context.checkpoint()
                scores.append(self._accuracy(threshold, seed=seed + offset, holdout=True))
        score = min(scores)
        return (
            Evidence(
                _identifier(candidate.candidate_id, stage, seed),
                candidate.candidate_id,
                stage,
                score >= 0.85,
                f"threshold-{stage}-v1",
                "synthetic-holdout" if stage != "internal" else "synthetic-train",
                seed,
                score,
                {"runs": len(scores), "deterministic": True},
            ),
        )

    def import_structure(self, structure: dict[str, object], *, candidate_id: str) -> Candidate:
        relation = str(structure.get("relation", "unknown"))
        return Candidate(
            candidate_id,
            self.manifest.domain,
            "test a transferred structural relation against synthetic threshold data",
            {"relation": relation, "arity": structure.get("arity", 1), "threshold": 1.0},
            parent_id=str(structure.get("_source_candidate_id", "")) or None,
            source_adapter=self.manifest.name,
        )
