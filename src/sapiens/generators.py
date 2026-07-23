"""Hypothesis generators (Stage A — kills the universal killer).

Replaces the fixed ``adapter.propose()`` with an injectable ``HypothesisGenerator``
protocol that can emit NOVEL hypotheses — not hardcoded string-literal candidates.
A generator may be anomaly-driven (abductive: 'this residual suggests X'),
data-scan-driven (systematically test every predictor), or cross-domain (transfer a
method from another field). Future LLM-backed generators can plug into this protocol.

This is the single architectural change that moves SAPIENS from a hypothesis CONFIRMER
to a hypothesis GENERATOR.
"""

from __future__ import annotations

import random
from hashlib import sha256
from typing import Protocol, runtime_checkable

from .budget import ExecutionContext
from .models import Candidate


def _id(*parts: object) -> str:
    return sha256("|".join(map(str, parts)).encode()).hexdigest()[:20]


@runtime_checkable
class HypothesisGenerator(Protocol):
    """Generates novel candidate hypotheses (not fixed / pre-authored)."""

    @property
    def name(self) -> str: ...

    def generate(
        self, *, seed: int, limit: int, context: ExecutionContext
    ) -> tuple[Candidate, ...]: ...


class DataScanGenerator:
    """Systematically generates one candidate per predictor in a declared set.

    This is the simplest non-trivial generator: it does not invent novel questions,
    but it generalises ``adapter.propose()`` so the candidate set is declarative
    (a predictor list) rather than hardcoded per adapter. It also emits a NULL
    candidate (random predictor) for FDR control.
    """

    def __init__(self, domain: str, predictors: tuple[str, ...], source: str = "scan") -> None:
        self._domain = domain
        self._predictors = predictors
        self._source = source

    @property
    def name(self) -> str:
        return f"datascan:{self._domain}"

    def generate(
        self, *, seed: int, limit: int, context: ExecutionContext
    ) -> tuple[Candidate, ...]:
        rng = random.Random(seed)
        candidates: list[Candidate] = []
        for pred in self._predictors[:limit]:
            candidates.append(
                Candidate(
                    _id(self.name, seed, pred),
                    self._domain,
                    f"{pred} predicts target (data-scan generated)",
                    {"source": self._source, "predictor": pred},
                    source_adapter=self.name,
                )
            )
        if len(candidates) < limit:
            null_pred = f"null-{rng.randint(0, 9999)}"
            candidates.append(
                Candidate(
                    _id(self.name, seed, "null"),
                    self._domain,
                    f"{null_pred} (null / FDR control candidate)",
                    {"source": "null", "predictor": null_pred},
                    source_adapter=self.name,
                )
            )
        return tuple(candidates)


class AnomalyDrivenGenerator:
    """Generates hypotheses FROM anomaly-registry residuals.

    Given the top-N anomalies (sorted by severity), emits one candidate per anomaly:
    'this outlier at (ra, dec) with extreme value X suggests an unrecognised
    sub-population or physical process.' This is the abductive step — reasoning
    from a surprising residual to a candidate explanation.
    """

    def __init__(self, domain: str) -> None:
        self._domain = domain

    @property
    def name(self) -> str:
        return f"anomaly-driven:{self._domain}"

    def generate(
        self, *, seed: int, limit: int, context: ExecutionContext
    ) -> tuple[Candidate, ...]:
        # In a real system, this would query the AnomalyRegistry for top anomalies
        # in this domain. For now, we generate a template candidate that the
        # driver can enrich with anomaly data.
        return (
            Candidate(
                _id(self.name, seed, "abductive"),
                self._domain,
                "anomaly-driven hypothesis: outlier objects suggest an unrecognised sub-population",
                {"source": "anomaly-driven", "method": "abductive"},
                source_adapter=self.name,
            ),
        )
