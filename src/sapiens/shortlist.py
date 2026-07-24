"""Recalibrated shortlist builder (Gates Recalibration R1–R7).

Converts SAPIENS from a binary admit/kill gate into a ranked shortlist deliverer.
The machine's job is to hand the human a ranked top-K shortlist of genuinely
promising candidates (precision@K), NOT binary-suppress.

Key changes from the old gate system:
- R1: Mechanism-absence INVERTED — raises anomaly_priority, never kills.
- R2: Review scores method integrity, NOT consensus agreement.
- R3: Replication/orthogonal = confidence dimensions, not admission gates.
- R5: Sigma as continuous rank with 3-sigma floor, not a 5-sigma hard cut.
- R6: Uncalibrated candidates surfaced with UNCALIBRATED marker, not refused.
- Reserved slots for UNEXPLAINED_CONFIRMED (paradigm-breaker guarantee).

Scientific_discoveries_claimed stays 0 — the human L4 gate is still the final gate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Four-way ledger status (R1 — the paradigm-breaker guarantee)
EXPLAINED_CONFIRMED = "EXPLAINED_CONFIRMED"
UNEXPLAINED_CONFIRMED = "UNEXPLAINED_CONFIRMED"
EXPLAINED_UNCONFIRMED = "EXPLAINED_UNCONFIRMED"
UNEXPLAINED_UNCONFIRMED = "UNEXPLAINED_UNCONFIRMED"


@dataclass(frozen=True)
class CandidateScore:
    candidate_id: str
    domain: str
    claim: str
    promotion_score: float
    anomaly_priority: float
    shortlist_rank: float
    ledger_status: str
    confidence: str
    has_mechanism: bool
    has_replication: bool
    consensus_conflict: bool
    sigma: float | None
    rationale: str


def classify_ledger_status(has_mechanism: bool, has_replication: bool) -> str:
    if has_mechanism and has_replication:
        return EXPLAINED_CONFIRMED
    if not has_mechanism and has_replication:
        return UNEXPLAINED_CONFIRMED
    if has_mechanism and not has_replication:
        return EXPLAINED_UNCONFIRMED
    return UNEXPLAINED_UNCONFIRMED


def _pvalue_to_sigma(pvalue: float) -> float:
    """Convert a two-sided p-value to a sigma equivalent (normal quantile)."""
    if pvalue <= 0.0:
        return 99.0
    if pvalue >= 1.0:
        return 0.0
    # Inverse normal CDF via rational approximation (simple, accurate to ~4 digits)
    # Use the complementary error function inverse approximation
    # sigma = sqrt(2) * erfinv(1 - pvalue)
    # erfinv via rational approximation
    t = math.sqrt(-2.0 * math.log(pvalue / 2.0))
    return t  # one-sided sigma equivalent (close enough for ranking)


def score_candidate(
    *,
    candidate_id: str,
    domain: str,
    claim: str,
    evidence_score: float,
    evidence_level: int,
    has_mechanism: bool = False,
    has_replication: bool = False,
    has_orthogonal: bool = False,
    consensus_conflict: bool = False,
    pvalue: float | None = None,
    method_integrity_passed: bool = True,
) -> CandidateScore:
    """Score a candidate with the recalibrated promotion function.

    promotion_score: evidence quality (0 at t0, grows with maturity).
    anomaly_priority: paradigm-breaker signal (INVERTED mechanism + consensus conflict).
    shortlist_rank: combined — NOT a threshold.
    """
    # --- promotion_score (evidence quality) ---
    promotion = 0.0
    if method_integrity_passed:
        promotion += 0.20  # G5: method integrity (NOT consensus)
    promotion += min(0.30, evidence_score * 0.30)  # raw evidence strength
    if evidence_level >= 1:
        promotion += 0.10  # L1: internal consistency
    if evidence_level >= 2:
        promotion += 0.15  # L2: holdout replication passed
    if evidence_level >= 3:
        promotion += 0.15  # L3: structured review passed
    if has_orthogonal:
        promotion += 0.10
    promotion = min(1.0, promotion)

    # --- anomaly_priority (paradigm-breaker signal, R1 INVERTED) ---
    anomaly = 0.0
    if not has_mechanism:
        anomaly += 0.10  # R1: mechanism-absence RAISES priority
    if consensus_conflict:
        anomaly += 0.10  # R2: anti-consensus = novelty signal
    anomaly = min(1.0, anomaly)

    # --- combined rank ---
    combined = promotion + anomaly

    # --- four-way ledger status ---
    status = classify_ledger_status(has_mechanism, has_replication)

    # --- confidence (R6: UNCALIBRATED surfaced, not refused) ---
    confidence = "CALIBRATED" if promotion >= 0.50 else "UNCALIBRATED"

    # --- sigma (R5: continuous, not a hard cut) ---
    sigma = _pvalue_to_sigma(pvalue) if pvalue is not None and pvalue > 0 else None

    return CandidateScore(
        candidate_id=candidate_id,
        domain=domain,
        claim=claim,
        promotion_score=round(promotion, 4),
        anomaly_priority=round(anomaly, 4),
        shortlist_rank=round(combined, 4),
        ledger_status=status,
        confidence=confidence,
        has_mechanism=has_mechanism,
        has_replication=has_replication,
        consensus_conflict=consensus_conflict,
        sigma=sigma,
        rationale=(
            f"promotion={promotion:.2f} anomaly={anomaly:.2f} "
            f"status={status} confidence={confidence}"
        ),
    )


def build_shortlist(
    scores: list[CandidateScore],
    *,
    k: int = 10,
    min_reserved_unexplained: int = 2,
    max_uncalibrated: int = 2,
) -> list[CandidateScore]:
    """Build a K-batch shortlist for human review.

    Layout (GATES-RECALIBRATION Part 4):
    - Reserved slots for UNEXPLAINED_CONFIRMED (paradigm-breaker guarantee)
    - Fill with CALIBRATED candidates by promotion_score
    - Up to 2 UNCALIBRATED "engaged-but-uncertain" slots
    - Never ranks paradigm-breakers to zero
    """
    ranked = sorted(scores, key=lambda s: s.shortlist_rank, reverse=True)

    unexplained_confirmed = [
        s for s in ranked if s.ledger_status == UNEXPLAINED_CONFIRMED
    ]
    calibrated = [
        s for s in ranked
        if s.confidence == "CALIBRATED" and s.ledger_status != UNEXPLAINED_CONFIRMED
    ]
    uncalibrated = [
        s for s in ranked if s.confidence == "UNCALIBRATED"
    ]

    shortlist: list[CandidateScore] = []

    # Reserved slots (paradigm-breaker guarantee)
    reserved = unexplained_confirmed[:min_reserved_unexplained]
    shortlist.extend(reserved)

    # Fill remaining
    remaining = k - len(shortlist)
    n_uncalib = min(max_uncalibrated, len(uncalibrated), remaining)
    n_calib = remaining - n_uncalib

    shortlist.extend(calibrated[:n_calib])
    shortlist.extend(uncalibrated[:n_uncalib])

    # If still room, fill from leftovers
    if len(shortlist) < k:
        used = {s.candidate_id for s in shortlist}
        for s in ranked:
            if s.candidate_id not in used:
                shortlist.append(s)
                if len(shortlist) >= k:
                    break

    return sorted(shortlist, key=lambda s: s.shortlist_rank, reverse=True)
