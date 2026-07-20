from pathlib import Path

from sapiens import DiscoveryKernel, EvidenceLedger, EvidenceLevel
from sapiens.adapters import SyntheticRegressionAdapter
from sapiens.budget import ExecutionContext
from sapiens.models import Candidate, Evidence
from sapiens.review import (
    CatchReport,
    DevilsAdvocateReviewer,
    MethodologistReviewer,
    ReviewPanel,
    StatisticianReviewer,
    catch_rate,
    review_evidence,
)


def _ctx() -> ExecutionContext:
    """A fresh budget per call — avoids shared mutable state accumulating across tests."""
    return ExecutionContext(50, 30)


def _candidate(cid: str = "c1", direction: int = 1) -> Candidate:
    return Candidate(
        cid, "synthetic-regression", "a test claim",
        {"relation": "linear", "arity": 1, "direction": direction},
    )


def _evidence(
    cid: str = "c1",
    *,
    kind: str = "replication",
    passed: bool = True,
    r: float = 0.95,
    pvalue: float = 1e-20,
    n: int = 60,
    dataset: str = "synthetic-heldout",
) -> Evidence:
    return Evidence(
        f"ev-{cid}-{kind}", cid, kind, passed, f"{kind}-v1", dataset, 7,
        max(0.0, min(1.0, r)),
        {"r": r, "pvalue": pvalue, "n": n, "deterministic": True},
    )


# --- individual reviewers ---------------------------------------------------------


def test_statistician_endorses_strong_evidence_objects_on_weak():
    reviewer = StatisticianReviewer()
    strong = reviewer.review(
        _candidate(), (_evidence(r=0.95, pvalue=1e-20),), seed=1, context=_ctx()
    )
    assert strong.verdict == "endorse" and not strong.objections

    weak = reviewer.review(_candidate(), (_evidence(r=0.3, pvalue=0.5),), seed=1, context=_ctx())
    assert weak.verdict == "object"
    categories = {o.category for o in weak.objections}
    assert "not-significant" in categories and "effect-too-small" in categories

    wrong = reviewer.review(
        _candidate(), (_evidence(r=-0.95, pvalue=1e-20),), seed=1, context=_ctx()
    )
    assert wrong.verdict == "object"
    assert any(o.category == "effect-too-small" for o in wrong.objections)


def test_methodologist_flags_review_on_training_data():
    reviewer = MethodologistReviewer()
    clean = reviewer.review(
        _candidate(),
        (_evidence(kind="review", dataset="synthetic-heldout"),),
        seed=1, context=_ctx(),
    )
    assert clean.verdict == "endorse"

    leaked = reviewer.review(
        _candidate(),
        (_evidence(kind="review", dataset="synthetic-train"),),
        seed=1, context=_ctx(),
    )
    assert leaked.verdict == "object"
    assert any(o.category == "leakage-risk" for o in leaked.objections)


def test_devils_advocate_requires_overwhelming_evidence():
    reviewer = DevilsAdvocateReviewer()
    overwhelming = reviewer.review(
        _candidate(), (_evidence(r=0.99, pvalue=1e-40),), seed=1, context=_ctx()
    )
    assert overwhelming.verdict == "endorse"

    merely_strong = reviewer.review(
        _candidate(), (_evidence(r=0.8, pvalue=1e-10),), seed=1, context=_ctx()
    )
    assert merely_strong.verdict == "object"
    assert any(o.category == "overfitting-risk" for o in merely_strong.objections)


# --- panel disagreement gate and multi-round --------------------------------------


def test_panel_requires_unanimous_endorsement():
    panel = ReviewPanel([StatisticianReviewer(), MethodologistReviewer(), DevilsAdvocateReviewer()])
    accepted = panel.evaluate(
        _candidate(), (_evidence(r=0.99, pvalue=1e-40),), seed=1, context=_ctx()
    )
    assert accepted.passed and accepted.verdict == "endorse" and accepted.rounds == 1

    # devil's advocate objects to merely-strong evidence -> whole panel objects
    rejected = panel.evaluate(
        _candidate(), (_evidence(r=0.8, pvalue=1e-10),), seed=1, context=_ctx()
    )
    assert not rejected.passed and rejected.verdict == "object"


def test_panel_multi_round_runs_until_unanimous_or_exhausted():
    panel = ReviewPanel([StatisticianReviewer(), DevilsAdvocateReviewer()], rounds=2)
    # evidence too weak for devil's advocate -> never unanimous -> 2 rounds, object
    report = panel.evaluate(_candidate(), (_evidence(r=0.8, pvalue=1e-10),), seed=1, context=_ctx())
    assert report.rounds == 2
    assert report.verdict == "object"
    assert len(report.objections) >= 1


# --- catch-rate scoring of the panel itself ---------------------------------------


def test_catch_rate_endorses_good_rejects_bad():
    panel = ReviewPanel(
        [StatisticianReviewer(), MethodologistReviewer(), DevilsAdvocateReviewer()]
    )
    good = [_candidate(f"g{i}") for i in range(3)]
    bad = [_candidate(f"b{i}") for i in range(3)]

    def evidence_for(candidate: Candidate) -> tuple[Evidence, ...]:
        if candidate.candidate_id.startswith("g"):
            return (_evidence(cid=candidate.candidate_id, r=0.99, pvalue=1e-40),)
        return (_evidence(cid=candidate.candidate_id, r=0.2, pvalue=0.4),)

    report = catch_rate(panel, good, bad, evidence_for, seed=3, context=_ctx())
    assert isinstance(report, CatchReport)
    assert report.true_endorse_rate == 1.0
    assert report.catch_rate == 1.0


# --- integration: panel drives L3 promotion through the real kernel/ledger --------


def _panel_reviewed_regression(panel: ReviewPanel):
    class PanelReviewedRegression(SyntheticRegressionAdapter):
        def validate(self, candidate, *, stage, seed, context):  # type: ignore[override]
            if stage == "review":
                history = (
                    super().validate(candidate, stage="internal", seed=seed, context=context)
                    + super().validate(
                        candidate, stage="replication", seed=seed + 1, context=context
                    )
                )
                report = panel.evaluate(candidate, history, seed=seed, context=context)
                return (review_evidence(report, candidate, seed=seed),)
            return super().validate(candidate, stage=stage, seed=seed, context=context)

    return PanelReviewedRegression()


def test_panel_drives_l3_promotion_on_real_evidence(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    kernel = DiscoveryKernel(ledger)
    panel = ReviewPanel(
        [StatisticianReviewer(), MethodologistReviewer(), DevilsAdvocateReviewer()]
    )
    adapter = _panel_reviewed_regression(panel)
    candidate = adapter.propose(seed=1, limit=1)[0]  # correct (positive) direction

    kernel.register(candidate)
    assert kernel.validate_next(adapter, candidate, seed=10, context=_ctx()) == EvidenceLevel.L1
    assert kernel.validate_next(adapter, candidate, seed=11, context=_ctx()) == EvidenceLevel.L2
    # L3 is now decided by the structured panel, not a self-check
    assert kernel.validate_next(adapter, candidate, seed=12, context=_ctx()) == EvidenceLevel.L3
    assert ledger.verify() is True


def test_review_evidence_reflects_panel_verdict():
    candidate = _candidate()
    panel = ReviewPanel([StatisticianReviewer()])

    endorsed = panel.evaluate(candidate, (_evidence(r=0.99, pvalue=1e-40),), seed=1, context=_ctx())
    ev_pass = review_evidence(endorsed, candidate, seed=1)
    assert ev_pass.kind == "review" and ev_pass.passed is True

    # an objected panel yields failing review evidence -> would block any L3 promotion
    objected = panel.evaluate(candidate, (_evidence(r=0.2, pvalue=0.4),), seed=1, context=_ctx())
    ev_fail = review_evidence(objected, candidate, seed=1)
    assert ev_fail.passed is False
    assert ev_fail.details["objection_count"] >= 1

