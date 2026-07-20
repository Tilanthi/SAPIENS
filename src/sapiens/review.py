"""Structured L3 review panels (Phase 3 v1).

Replaces the single-shot L3 "review" self-check with a structured, multi-reviewer panel
that scrutinises a candidate's accumulated evidence before any L3 promotion. Reviewers
are role-specialised and produce typed objections; the panel applies a disagreement gate
(unanimous endorsement required) over one or more rounds, with objections carried forward
so reviewers can reconsider. The panel produces ledger-valid review ``Evidence``, so L3
promotion still flows through the existing kernel/ledger transition guard — traceability
is preserved.

Phase 0: reviewers are deterministic and operate on synthetic candidates and their
real-evidence histories. A domain-theorist reviewer is deliberately out of scope here
(it needs real domain knowledge, Phase 4). Nothing is claimed about nature.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .budget import ExecutionContext
from .models import Candidate, Evidence


def _identifier(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:20]


@dataclass(frozen=True)
class Objection:
    category: str  # e.g. "not-significant", "effect-too-small", "leakage-risk", "overfitting-risk"
    severity: str  # "minor" | "major" | "critical"
    rationale: str


@dataclass(frozen=True)
class ReviewOpinion:
    reviewer: str
    verdict: str  # "endorse" | "object" | "abstain"
    objections: tuple[Objection, ...]
    confidence: float  # in [0, 1]


@dataclass(frozen=True)
class ReviewReport:
    candidate_id: str
    rounds: int
    opinions_by_round: tuple[tuple[ReviewOpinion, ...], ...]
    verdict: str  # "endorse" | "object"
    objections: tuple[Objection, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return self.verdict == "endorse"


def _best_statistics(evidence: tuple[Evidence, ...]) -> tuple[float, float, int] | None:
    """Most significant (smallest p-value) statistical evidence available, or None."""
    best: tuple[float, float, int] | None = None
    for item in evidence:
        if "r" in item.details and "pvalue" in item.details:
            r = float(item.details["r"])
            pvalue = float(item.details["pvalue"])
            n = int(item.details.get("n", 0))
            if best is None or pvalue < best[1]:
                best = (r, pvalue, n)
    return best


@runtime_checkable
class Reviewer(Protocol):
    """A role-specialised reviewer that scrutinises a candidate's evidence history."""

    @property
    def role(self) -> str: ...

    def review(
        self,
        candidate: Candidate,
        evidence: tuple[Evidence, ...],
        *,
        seed: int,
        context: ExecutionContext,
        prior_objections: tuple[Objection, ...] = (),
    ) -> ReviewOpinion: ...


class StatisticianReviewer:
    """Re-examines effect size, significance, and sample size from the validation stats."""

    role = "statistician"

    def __init__(
        self, *, alpha: float = 0.05, min_effect: float = 0.5, min_sample: int = 30
    ) -> None:
        self.alpha = alpha
        self.min_effect = min_effect
        self.min_sample = min_sample

    def review(
        self,
        candidate: Candidate,
        evidence: tuple[Evidence, ...],
        *,
        seed: int,
        context: ExecutionContext,
        prior_objections: tuple[Objection, ...] = (),
    ) -> ReviewOpinion:
        context.checkpoint()
        stats = _best_statistics(evidence)
        objections: list[Objection] = []
        if stats is None:
            objections.append(
                Objection("no-statistical-evidence", "major", "no quantitative evidence to assess")
            )
            return ReviewOpinion(self.role, "object", tuple(objections), 0.0)
        r, pvalue, n = stats
        if pvalue > self.alpha:
            objections.append(
                Objection(
                    "not-significant",
                    "major",
                    f"pvalue {pvalue:.2e} exceeds alpha {self.alpha}",
                )
            )
        if r < self.min_effect:
            objections.append(
                Objection("effect-too-small", "major", f"effect {r:.3f} below {self.min_effect}")
            )
        if n < self.min_sample:
            objections.append(
                Objection("insufficient-sample", "minor", f"n={n} below {self.min_sample}")
            )
        verdict = "endorse" if not objections else "object"
        return ReviewOpinion(self.role, verdict, tuple(objections), max(0.0, 1.0 - pvalue))


class MethodologistReviewer:
    """Scrutinises methodology: review-stage evidence must be held-out, not training data."""

    role = "methodologist"

    def review(
        self,
        candidate: Candidate,
        evidence: tuple[Evidence, ...],
        *,
        seed: int,
        context: ExecutionContext,
        prior_objections: tuple[Objection, ...] = (),
    ) -> ReviewOpinion:
        context.checkpoint()
        objections: list[Objection] = []
        if not evidence:
            objections.append(Objection("no-evidence", "major", "no evidence history to review"))
        for item in evidence:
            if item.kind == "review" and item.dataset.endswith("train"):
                objections.append(
                    Objection(
                        "leakage-risk",
                        "major",
                        f"review evidence ({item.evidence_id}) computed on training data",
                    )
                )
        verdict = "endorse" if not objections else "object"
        return ReviewOpinion(self.role, verdict, tuple(objections), 0.8)


class DevilsAdvocateReviewer:
    """Adversarial: demands overwhelming evidence and probes for alternative explanations."""

    role = "devils-advocate"

    def __init__(
        self, *, overwhelming_effect: float = 0.9, overwhelming_pvalue: float = 1e-6
    ) -> None:
        self.overwhelming_effect = overwhelming_effect
        self.overwhelming_pvalue = overwhelming_pvalue

    def review(
        self,
        candidate: Candidate,
        evidence: tuple[Evidence, ...],
        *,
        seed: int,
        context: ExecutionContext,
        prior_objections: tuple[Objection, ...] = (),
    ) -> ReviewOpinion:
        context.checkpoint()
        stats = _best_statistics(evidence)
        objections: list[Objection] = []
        if stats is None:
            objections.append(
                Objection("no-statistical-evidence", "major", "nothing to cross-examine")
            )
        else:
            r, pvalue, _ = stats
            if r < self.overwhelming_effect or pvalue > self.overwhelming_pvalue:
                objections.append(
                    Objection(
                        "overfitting-risk",
                        "major",
                        "evidence not overwhelming; plausible alternative explanations remain",
                    )
                )
        verdict = "endorse" if not objections else "object"
        return ReviewOpinion(self.role, verdict, tuple(objections), 0.5)


class ReviewPanel:
    """Runs reviewers over one or more rounds with a unanimous-endorsement disagreement gate."""

    def __init__(self, reviewers: list[Reviewer], *, rounds: int = 1) -> None:
        if not reviewers:
            raise ValueError("at least one reviewer is required")
        if rounds <= 0:
            raise ValueError("rounds must be positive")
        self._reviewers = list(reviewers)
        self._rounds = rounds

    def evaluate(
        self,
        candidate: Candidate,
        evidence: tuple[Evidence, ...],
        *,
        seed: int,
        context: ExecutionContext,
    ) -> ReviewReport:
        opinions_by_round: list[tuple[ReviewOpinion, ...]] = []
        prior: tuple[Objection, ...] = ()
        verdict = "object"
        for round_index in range(self._rounds):
            round_opinions: list[ReviewOpinion] = []
            for index, reviewer in enumerate(self._reviewers):
                opinion = reviewer.review(
                    candidate,
                    evidence,
                    seed=seed + (round_index + 1) * 1000 + index,
                    context=context,
                    prior_objections=prior,
                )
                round_opinions.append(opinion)
            opinions_by_round.append(tuple(round_opinions))
            if all(opinion.verdict == "endorse" for opinion in round_opinions):
                verdict = "endorse"
                break
            prior = tuple(o for opinion in round_opinions for o in opinion.objections)
        return ReviewReport(
            candidate_id=candidate.candidate_id,
            rounds=len(opinions_by_round),
            opinions_by_round=tuple(opinions_by_round),
            verdict=verdict,
            objections=prior,
        )


def review_evidence(report: ReviewReport, candidate: Candidate, *, seed: int) -> Evidence:
    """Build ledger-valid review Evidence reflecting the panel's verdict."""
    reviewers = sorted(
        {opinion.reviewer for round_ in report.opinions_by_round for opinion in round_}
    )
    categories = sorted({o.category for o in report.objections})
    return Evidence(
        _identifier(candidate.candidate_id, "panel-review", seed),
        candidate.candidate_id,
        "review",
        report.passed,
        "panel-review-v1",
        "synthetic-panel",
        seed,
        1.0 if report.passed else 0.0,
        {
            "verdict": report.verdict,
            "rounds": report.rounds,
            "reviewers": tuple(reviewers),
            "objection_categories": tuple(categories),
            "objection_count": len(report.objections),
        },
    )


@dataclass(frozen=True)
class CatchReport:
    good_total: int
    good_endorsed: int
    bad_total: int
    bad_rejected: int

    @property
    def true_endorse_rate(self) -> float:
        return self.good_endorsed / self.good_total if self.good_total else 0.0

    @property
    def catch_rate(self) -> float:
        return self.bad_rejected / self.bad_total if self.bad_total else 0.0


def catch_rate(
    panel: ReviewPanel,
    good: list[Candidate],
    bad: list[Candidate],
    evidence_for: object,
    *,
    seed: int,
    context: ExecutionContext,
) -> CatchReport:
    """Score the panel itself: endorse known-good, reject known-bad candidates.

    ``evidence_for`` maps a candidate to its evidence history (``Callable[[Candidate],
    tuple[Evidence, ...]]``).
    """
    good_endorsed = sum(
        1
        for candidate in good
        if panel.evaluate(candidate, evidence_for(candidate), seed=seed, context=context).passed
    )
    bad_rejected = sum(
        1
        for candidate in bad
        if not panel.evaluate(
            candidate, evidence_for(candidate), seed=seed + 1, context=context
        ).passed
    )
    return CatchReport(len(good), good_endorsed, len(bad), bad_rejected)
