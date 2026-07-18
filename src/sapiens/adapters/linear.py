"""Synthetic linear-relation adapter used only to exercise Phase-0 plumbing."""

from __future__ import annotations

import hashlib
import random

from sapiens.budget import ExecutionContext
from sapiens.models import AdapterManifest, Candidate, Evidence


def _identifier(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:20]


class SyntheticLinearAdapter:
    manifest = AdapterManifest(
        name="synthetic-linear",
        version="1.0",
        domain="synthetic-kinematics",
        vocabulary=("input", "response", "slope", "noise"),
    )

    def propose(self, *, seed: int, limit: int) -> tuple[Candidate, ...]:
        if limit <= 0:
            return ()
        candidates = (
            Candidate(
                _identifier(self.manifest.name, seed, "positive"),
                self.manifest.domain,
                "response increases with input in the synthetic generator",
                {"relation": "monotonic", "arity": 1, "direction": 1},
                source_adapter=self.manifest.name,
            ),
            Candidate(
                _identifier(self.manifest.name, seed, "negative"),
                self.manifest.domain,
                "response decreases with input in the synthetic generator",
                {"relation": "monotonic", "arity": 1, "direction": -1},
                source_adapter=self.manifest.name,
            ),
        )
        return candidates[:limit]

    @staticmethod
    def _score(direction: int, *, seed: int, holdout: bool) -> float:
        rng = random.Random(seed + (1009 if holdout else 0))
        pairs = [(x / 10, 2.0 * (x / 10) + rng.gauss(0, 0.2)) for x in range(1, 31)]
        mean_x = sum(x for x, _ in pairs) / len(pairs)
        mean_y = sum(y for _, y in pairs) / len(pairs)
        covariance = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
        return 0.99 if covariance * direction > 0 else 0.01

    def validate(
        self, candidate: Candidate, *, stage: str, seed: int, context: ExecutionContext
    ) -> tuple[Evidence, ...]:
        direction = int(candidate.parameters.get("direction", 1))
        runs = 3 if stage == "review" else 1
        scores = []
        for offset in range(runs):
            context.checkpoint()
            scores.append(
                self._score(direction, seed=seed + offset * 17, holdout=stage != "internal")
            )
        score = min(scores)
        passed = score >= 0.9
        return (
            Evidence(
                _identifier(candidate.candidate_id, stage, seed),
                candidate.candidate_id,
                stage,
                passed,
                f"linear-{stage}-v1",
                "synthetic-holdout" if stage != "internal" else "synthetic-train",
                seed,
                score,
                {"runs": runs, "deterministic": True},
            ),
        )

    def import_structure(self, structure: dict[str, object], *, candidate_id: str) -> Candidate:
        return Candidate(
            candidate_id,
            self.manifest.domain,
            "test transferred structural pattern against synthetic linear data",
            {
                "relation": structure.get("relation", "unknown"),
                "arity": structure.get("arity", 1),
                "direction": 1,
            },
            parent_id=str(structure.get("_source_candidate_id", "")) or None,
            source_adapter=self.manifest.name,
        )
