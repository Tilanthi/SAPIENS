from pathlib import Path

import pytest

from sapiens import Evidence, EvidenceLedger, EvidenceLevel
from sapiens.ledger import LedgerIntegrityError


def _seed_candidate(ledger: EvidenceLedger) -> str:
    ledger.record_candidate("c1")
    ledger.record_evidence(Evidence("e1", "c1", "internal", True, "p", "d", 1, 0.9, {}))
    ledger.promote("c1", EvidenceLevel.L1, ("e1",))
    return "c1"


def test_checkpoint_keeps_verify_true_and_anchors_tip(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    _seed_candidate(ledger)
    tip_before = ledger.events()[-1].event_hash

    cp = ledger.checkpoint(signer="alice", note="phase-1-v2 anchor")

    assert cp.kind == "checkpoint"
    assert cp.payload["signer"] == "alice"
    assert cp.payload["tip"] == tip_before  # anchored the pre-checkpoint tip
    assert ledger.verify() is True


def test_checkpoint_does_not_change_candidate_state(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    _seed_candidate(ledger)
    ledger.checkpoint(signer="alice")
    # the candidate is still exactly at L1 — the checkpoint carried no transition
    assert ledger.state("c1").level == EvidenceLevel.L1


def test_checkpoint_then_tamper_is_detected(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    _seed_candidate(ledger)
    ledger.checkpoint(signer="alice")

    # append a malformed event that breaks the hash chain, bypassing append()
    with open(tmp_path / "events.jsonl", "a", encoding="utf-8") as handle:
        handle.write(
            '{"seq":99,"kind":"candidate","candidate_id":"x","payload":{},'
            '"previous_hash":"deadbeef","event_hash":"deadbeef"}\n'
        )
    with pytest.raises(LedgerIntegrityError):
        ledger.verify()


def test_multiple_checkpoints_chain_correctly(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    _seed_candidate(ledger)
    ledger.checkpoint(signer="alice")
    ledger.checkpoint(signer="bob")
    events = ledger.events()
    kinds = [e.kind for e in events]
    assert kinds.count("checkpoint") == 2
    assert ledger.verify() is True
