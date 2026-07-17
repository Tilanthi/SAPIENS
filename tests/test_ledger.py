from pathlib import Path

import pytest

from sapiens.ledger import EvidenceLedger, LedgerIntegrityError
from sapiens.models import Candidate, Evidence, EvidenceLevel


def test_ledger_promotion_path_and_replay(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    c = Candidate("c1", "synthetic", "claim")
    ledger.record_candidate(c.candidate_id)
    for level, kind in [
        (EvidenceLevel.L1, "internal"),
        (EvidenceLevel.L2, "replication"),
        (EvidenceLevel.L3, "review"),
    ]:
        ev = Evidence(
            f"e{int(level)}", "c1", kind, True, f"p-{kind}", "synthetic", int(level), 0.95
        )
        ledger.record_evidence(ev)
        ledger.promote("c1", level, (ev.evidence_id,))
    assert ledger.verify()
    assert EvidenceLedger(tmp_path / "events.jsonl").state("c1").level == EvidenceLevel.L3


def test_illegal_skip_promotion_rejected(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    ledger.record_candidate("c1")
    ev = Evidence("e1", "c1", "replication", True, "p", "synthetic", 1, 0.99)
    ledger.record_evidence(ev)
    with pytest.raises(LedgerIntegrityError):
        ledger.promote("c1", EvidenceLevel.L2, ("e1",))


def test_l4_requires_human_gate(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    ledger.record_candidate("c1")
    for level, kind in [
        (EvidenceLevel.L1, "internal"),
        (EvidenceLevel.L2, "replication"),
        (EvidenceLevel.L3, "review"),
    ]:
        ev = Evidence(f"e{int(level)}", "c1", kind, True, "p", "synthetic", int(level), 1.0)
        ledger.record_evidence(ev)
        ledger.promote("c1", level, (ev.evidence_id,))
    external = Evidence("e4", "c1", "external", True, "p", "external-review", 4, 1.0)
    ledger.record_evidence(external)
    with pytest.raises(LedgerIntegrityError):
        ledger.promote("c1", EvidenceLevel.L4, ("e4",))


def test_hash_chain_detects_tamper(tmp_path: Path):
    path = tmp_path / "events.jsonl"
    ledger = EvidenceLedger(path)
    ledger.record_candidate("c1")
    data = path.read_text()
    path.write_text(data.replace("c1", "c2", 1))
    with pytest.raises(LedgerIntegrityError):
        EvidenceLedger(path).verify()


def test_demotion_requires_reason_and_lower_level(tmp_path: Path):
    ledger = EvidenceLedger(tmp_path / "events.jsonl")
    ledger.record_candidate("c1")
    ev = Evidence("e1", "c1", "internal", True, "p", "synthetic", 1, 1.0)
    ledger.record_evidence(ev)
    ledger.promote("c1", EvidenceLevel.L1, ("e1",))
    bad = Evidence("bad", "c1", "replication", False, "p", "synthetic", 2, 0.0)
    ledger.record_evidence(bad)
    ledger.demote("c1", EvidenceLevel.L0, ("bad",), reason="failed replication")
    assert ledger.state("c1").level == EvidenceLevel.L0
