"""Synthetic periodic-signal adapter used only to exercise Phase-0 plumbing.

Models the classic "find the period in a noisy light curve" workflow on
fully synthetic data: a deterministic sinusoid buried in seeded Gaussian noise.
A candidate period is scored by phase-folding the curve at that period and
correlating against a sinusoidal template — the true period concentrates the
fold (high correlation), an incorrect period smears it (near-zero correlation).
No astrophysical data is used; ``scientific_discoveries_claimed`` stays 0.
"""

from __future__ import annotations

import hashlib
import math
import random

from sapiens.budget import ExecutionContext
from sapiens.models import AdapterManifest, Candidate, Evidence

# Synthetic generator parameters. The "true" signal is a unit-amplitude sinusoid
# of period TRUE_PERIOD sampled N times every DT time units, plus seeded noise.
TRUE_PERIOD = 3.0
WRONG_PERIOD = 4.5  # deliberately incommensurate alias used by the bad candidate
N = 144
DT = 0.25
AMPLITUDE = 1.0
SIGMA = 0.2
PASS_THRESHOLD = 0.5


def _identifier(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:20]


class SyntheticPhotometryAdapter:
    manifest = AdapterManifest(
        name="synthetic-photometry",
        version="1.0",
        domain="synthetic-photometry",
        vocabulary=("time", "flux", "period", "amplitude", "noise"),
    )

    def propose(self, *, seed: int, limit: int) -> tuple[Candidate, ...]:
        if limit <= 0:
            return ()
        candidates = (
            Candidate(
                _identifier(self.manifest.name, seed, "true"),
                self.manifest.domain,
                "synthetic flux varies periodically at the true folded period",
                {"relation": "periodic", "arity": 1, "period": TRUE_PERIOD},
                source_adapter=self.manifest.name,
            ),
            Candidate(
                _identifier(self.manifest.name, seed, "wrong"),
                self.manifest.domain,
                "synthetic flux varies periodically at an incorrect period",
                {"relation": "periodic", "arity": 1, "period": WRONG_PERIOD},
                source_adapter=self.manifest.name,
            ),
        )
        return candidates[:limit]

    @staticmethod
    def _correlation(period: float, *, seed: int, holdout: bool) -> float:
        """Phase-fold the synthetic curve at ``period`` and correlate with a sine template.

        Holdout uses an offset RNG seed so replication/review evidence is generated
        from independent noise, exactly as the other synthetic adapters do.
        """
        rng = random.Random(seed + (5039 if holdout else 0))
        times = (i * DT for i in range(N))
        flux: list[float] = []
        phases: list[float] = []
        for t in times:
            flux.append(AMPLITUDE * math.sin(2 * math.pi * t / TRUE_PERIOD) + rng.gauss(0, SIGMA))
            phases.append((t / period) % 1.0)
        template = [math.sin(2 * math.pi * ph) for ph in phases]
        n = len(flux)
        mean_flux = sum(flux) / n
        mean_template = sum(template) / n
        paired = zip(flux, template, strict=True)
        cov = sum((f - mean_flux) * (s - mean_template) for f, s in paired)
        var_flux = sum((f - mean_flux) ** 2 for f in flux)
        var_template = sum((s - mean_template) ** 2 for s in template)
        denom = math.sqrt(var_flux * var_template)
        if denom == 0:
            return 0.0
        return max(0.0, cov / denom)

    def validate(
        self, candidate: Candidate, *, stage: str, seed: int, context: ExecutionContext
    ) -> tuple[Evidence, ...]:
        context.checkpoint()
        period = float(candidate.parameters.get("period", TRUE_PERIOD))
        scores = [self._correlation(period, seed=seed, holdout=stage != "internal")]
        if stage == "review":
            for offset in (31, 73):
                context.checkpoint()
                scores.append(self._correlation(period, seed=seed + offset, holdout=True))
        score = min(scores)
        return (
            Evidence(
                _identifier(candidate.candidate_id, stage, seed),
                candidate.candidate_id,
                stage,
                score >= PASS_THRESHOLD,
                f"photometry-{stage}-v1",
                "synthetic-holdout" if stage != "internal" else "synthetic-train",
                seed,
                score,
                {"runs": len(scores), "deterministic": True},
            ),
        )

    def import_structure(self, structure: dict[str, object], *, candidate_id: str) -> Candidate:
        period = structure.get("period")
        period_value = float(period) if period is not None else TRUE_PERIOD
        return Candidate(
            candidate_id,
            self.manifest.domain,
            "test a transferred periodic structure against synthetic photometry",
            {"relation": "periodic", "arity": structure.get("arity", 1), "period": period_value},
            parent_id=str(structure.get("_source_candidate_id", "")) or None,
            source_adapter=self.manifest.name,
        )
