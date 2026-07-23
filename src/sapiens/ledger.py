"""Durable append-only evidence ledger with hash-chain integrity.

Hash chaining detects accidental or after-the-fact modification; it does not prove
identity, authorship, scientific validity, or resistance to an actor who can rewrite
an entire file. Signatures and external anchoring are roadmap items.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .models import Evidence, EvidenceLevel

GENESIS = "0" * 64
_ALLOWED_KINDS = {
    "candidate", "evidence", "promotion", "demotion",
    "transfer", "checkpoint", "preregistration",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False
    ).encode("utf-8")


@dataclass(frozen=True)
class LedgerEvent:
    seq: int
    kind: str
    candidate_id: str
    payload: dict[str, Any]
    previous_hash: str
    event_hash: str


@dataclass(frozen=True)
class CandidateState:
    level: EvidenceLevel
    evidence_ids: frozenset[str]


class LedgerIntegrityError(ValueError):
    pass


class EvidenceLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def _read_unlocked(self) -> list[LedgerEvent]:
        events: list[LedgerEvent] = []
        with self.path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.endswith("\n"):
                    raise LedgerIntegrityError(f"partial final record at line {line_number}")
                try:
                    raw = json.loads(line)
                    events.append(LedgerEvent(**raw))
                except (json.JSONDecodeError, TypeError) as exc:
                    raise LedgerIntegrityError(f"invalid record at line {line_number}") from exc
        self._verify(events)
        return events

    @staticmethod
    def _verify(events: Iterable[LedgerEvent]) -> None:
        previous = GENESIS
        expected_seq = 1
        seen_evidence: dict[str, tuple[str, bool, str]] = {}
        states: dict[str, EvidenceLevel] = {}
        for event in events:
            if event.seq != expected_seq or event.previous_hash != previous:
                raise LedgerIntegrityError("sequence gap or broken hash-chain link")
            if event.kind not in _ALLOWED_KINDS:
                raise LedgerIntegrityError("unknown event kind")
            unsigned = {
                "seq": event.seq,
                "kind": event.kind,
                "candidate_id": event.candidate_id,
                "payload": event.payload,
                "previous_hash": event.previous_hash,
            }
            digest = hashlib.sha256(_canonical(unsigned)).hexdigest()
            if digest != event.event_hash:
                raise LedgerIntegrityError("event hash mismatch")
            if event.kind in ("checkpoint", "preregistration"):
                # global integrity marker: participates in the hash chain but carries no
                # candidate-state transition
                previous = event.event_hash
                expected_seq += 1
                continue
            current = states.get(event.candidate_id)
            if event.kind in {"candidate", "transfer"}:
                if current is not None or event.payload.get("level") != 0:
                    raise LedgerIntegrityError("candidate must be created exactly once at L0")
                states[event.candidate_id] = EvidenceLevel.L0
            elif event.kind == "evidence":
                if current is None:
                    raise LedgerIntegrityError("evidence references unknown candidate")
                evidence_id = event.payload.get("evidence_id")
                if not evidence_id or evidence_id in seen_evidence:
                    raise LedgerIntegrityError("duplicate or missing evidence id")
                seen_evidence[evidence_id] = (
                    event.candidate_id,
                    bool(event.payload.get("passed")),
                    str(event.payload.get("kind", "")),
                )
            else:
                if current is None:
                    raise LedgerIntegrityError("transition references unknown candidate")
                target = EvidenceLevel(int(event.payload.get("to_level", -1)))
                refs = tuple(event.payload.get("evidence_refs", ()))
                if event.kind == "promotion":
                    if target != current + 1:
                        raise LedgerIntegrityError("promotion must advance exactly one level")
                    if not refs or any(
                        ref not in seen_evidence
                        or seen_evidence[ref][0] != event.candidate_id
                        or not seen_evidence[ref][1]
                        for ref in refs
                    ):
                        raise LedgerIntegrityError(
                            "promotion lacks passing candidate-local evidence"
                        )
                    required_kind = {1: "internal", 2: "replication", 3: "review", 4: "external"}[
                        int(target)
                    ]
                    if not any(seen_evidence[ref][2] == required_kind for ref in refs):
                        raise LedgerIntegrityError(f"promotion requires {required_kind} evidence")
                    if target == EvidenceLevel.L4 and not event.payload.get("human_gate"):
                        raise LedgerIntegrityError("L4 requires an explicit human gate")
                else:
                    if target >= current or not event.payload.get("reason") or not refs:
                        raise LedgerIntegrityError(
                            "demotion requires lower target, reason, and evidence"
                        )
                states[event.candidate_id] = target
            previous = event.event_hash
            expected_seq += 1

    def events(self) -> tuple[LedgerEvent, ...]:
        return tuple(self._read_unlocked())

    def verify(self) -> bool:
        self._read_unlocked()
        return True

    def state(self, candidate_id: str) -> CandidateState:
        level: EvidenceLevel | None = None
        evidence_ids: set[str] = set()
        for event in self._read_unlocked():
            if event.candidate_id != candidate_id:
                continue
            if event.kind in {"candidate", "transfer"}:
                level = EvidenceLevel.L0
            elif event.kind == "evidence":
                evidence_ids.add(str(event.payload["evidence_id"]))
            elif event.kind in ("checkpoint", "preregistration"):
                continue
            else:
                level = EvidenceLevel(int(event.payload["to_level"]))
        if level is None:
            raise KeyError(candidate_id)
        return CandidateState(level, frozenset(evidence_ids))

    def append(self, kind: str, candidate_id: str, payload: dict[str, Any]) -> LedgerEvent:
        if kind not in _ALLOWED_KINDS or not candidate_id:
            raise ValueError("invalid event")
        with self.path.open("r+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            events = self._read_unlocked()
            previous = events[-1].event_hash if events else GENESIS
            unsigned = {
                "seq": len(events) + 1,
                "kind": kind,
                "candidate_id": candidate_id,
                "payload": payload,
                "previous_hash": previous,
            }
            event = LedgerEvent(
                **unsigned, event_hash=hashlib.sha256(_canonical(unsigned)).hexdigest()
            )
            self._verify([*events, event])
            stream.seek(0, os.SEEK_END)
            stream.write(_canonical(asdict(event)).decode("utf-8") + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            return event

    def record_candidate(self, candidate_id: str, *, transferred_from: str | None = None) -> None:
        kind = "transfer" if transferred_from else "candidate"
        self.append(kind, candidate_id, {"level": 0, "transferred_from": transferred_from})

    def record_evidence(self, evidence: Evidence) -> None:
        self.append(
            "evidence",
            evidence.candidate_id,
            {
                "evidence_id": evidence.evidence_id,
                "candidate_id": evidence.candidate_id,
                "kind": evidence.kind,
                "passed": evidence.passed,
                "protocol": evidence.protocol,
                "dataset": evidence.dataset,
                "seed": evidence.seed,
                "score": evidence.score,
                "details": dict(evidence.details),
            },
        )

    def promote(
        self,
        candidate_id: str,
        to_level: EvidenceLevel,
        evidence_refs: tuple[str, ...],
        *,
        human_gate: bool = False,
    ) -> None:
        self.append(
            "promotion",
            candidate_id,
            {
                "to_level": int(to_level),
                "evidence_refs": list(evidence_refs),
                "human_gate": human_gate,
            },
        )

    def demote(
        self,
        candidate_id: str,
        to_level: EvidenceLevel,
        evidence_refs: tuple[str, ...],
        *,
        reason: str,
    ) -> None:
        self.append(
            "demotion",
            candidate_id,
            {"to_level": int(to_level), "evidence_refs": list(evidence_refs), "reason": reason},
        )

    def checkpoint(self, *, signer: str = "", note: str = "") -> LedgerEvent:
        """Append a hash-chained integrity checkpoint anchoring the current tip.

        The ``signer`` is recorded provenance, not a cryptographic signature (external
        anchoring / signing is a roadmap item). The checkpoint participates in the
        tamper-evident hash chain but carries no candidate-state transition.
        """
        events = self._read_unlocked()
        tip = events[-1].event_hash if events else GENESIS
        return self.append(
            "checkpoint",
            "__checkpoint__",
            {"tip": tip, "signer": signer, "note": note},
        )
