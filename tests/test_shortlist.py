"""Tests for the recalibrated shortlist builder (Gates Recalibration R1-R7)."""

from sapiens.shortlist import (
    EXPLAINED_CONFIRMED,
    EXPLAINED_UNCONFIRMED,
    UNEXPLAINED_CONFIRMED,
    UNEXPLAINED_UNCONFIRMED,
    build_shortlist,
    classify_ledger_status,
    score_candidate,
)

# --- R1: four-way ledger status ---


def test_classify_four_way():
    assert classify_ledger_status(True, True) == EXPLAINED_CONFIRMED
    assert classify_ledger_status(False, True) == UNEXPLAINED_CONFIRMED
    assert classify_ledger_status(True, False) == EXPLAINED_UNCONFIRMED
    assert classify_ledger_status(False, False) == UNEXPLAINED_UNCONFIRMED


# --- R1: mechanism-absence raises anomaly_priority (INVERTED) ---


def test_mechanism_absence_raises_priority():
    with_mechanism = score_candidate(
        candidate_id="c1", domain="d", claim="concentrated",
        evidence_score=0.6, evidence_level=3,
        has_mechanism=True, has_replication=True,
    )
    without_mechanism = score_candidate(
        candidate_id="c2", domain="d", claim="unknown anomaly",
        evidence_score=0.6, evidence_level=3,
        has_mechanism=False, has_replication=True,
    )
    # Same evidence, but mechanism-absent gets higher anomaly_priority
    assert without_mechanism.anomaly_priority > with_mechanism.anomaly_priority
    # And therefore higher combined rank
    assert without_mechanism.shortlist_rank > with_mechanism.shortlist_rank
    # The unexplained one is classified as paradigm-breaker
    assert without_mechanism.ledger_status == UNEXPLAINED_CONFIRMED
    assert with_mechanism.ledger_status == EXPLAINED_CONFIRMED


# --- R2: consensus-conflict raises priority ---


def test_consensus_conflict_raises_priority():
    normal = score_candidate(
        candidate_id="c1", domain="d", claim="standard result",
        evidence_score=0.5, evidence_level=2,
        has_mechanism=True, has_replication=True,
    )
    conflicted = score_candidate(
        candidate_id="c2", domain="d", claim="contradicts consensus",
        evidence_score=0.5, evidence_level=2,
        has_mechanism=True, has_replication=True,
        consensus_conflict=True,
    )
    assert conflicted.anomaly_priority > normal.anomaly_priority


# --- R6: UNCALIBRATED candidates surfaced, not refused ---


def test_uncalibrated_candidate_surfaced():
    weak = score_candidate(
        candidate_id="c1", domain="d", claim="weak evidence",
        evidence_score=0.1, evidence_level=1,  # only passed L1
        has_mechanism=False, has_replication=False,
    )
    assert weak.confidence == "UNCALIBRATED"
    assert weak.shortlist_rank > 0  # not refused — has a rank


# --- shortlist reserved slots (paradigm-breaker guarantee) ---


def test_shortlist_reserves_unexplained_confirmed():
    # 3 explained (high promotion) + 1 unexplained confirmed (lower, but paradigm-breaker)
    explained = [
        score_candidate(
            candidate_id=f"c{i}", domain="d", claim=f"standard {i}",
            evidence_score=0.7, evidence_level=3,
            has_mechanism=True, has_replication=True,
        )
        for i in range(3)
    ]
    paradigm = score_candidate(
        candidate_id="breaker", domain="d", claim="inexplicable but reproducible",
        evidence_score=0.3, evidence_level=2,
        has_mechanism=False, has_replication=True,
    )
    shortlist = build_shortlist(explained + [paradigm], k=4, min_reserved_unexplained=1)
    ids = {s.candidate_id for s in shortlist}
    assert "breaker" in ids  # paradigm-breaker survives despite lower promotion_score


def test_shortlist_includes_uncalibrated():
    strong = score_candidate(
        candidate_id="strong", domain="d", claim="strong",
        evidence_score=0.8, evidence_level=3,
        has_mechanism=True, has_replication=True,
    )
    weak = score_candidate(
        candidate_id="weak", domain="d", claim="weak but interesting",
        evidence_score=0.1, evidence_level=1,
        has_mechanism=False, has_replication=False,
    )
    shortlist = build_shortlist([strong, weak], k=2)
    ids = {s.candidate_id for s in shortlist}
    assert "weak" in ids  # uncalibrated candidate included, not refused
