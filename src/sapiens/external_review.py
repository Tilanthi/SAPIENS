"""Human external-review workflow + reproduction bundles (Phase 5 v1).

L4 (externally review-ready) is the only evidence level that requires an explicit human
gate; the autonomous kernel caps at L3 (``validate_next``). This module assembles a
``ReproductionBundle`` — the candidate plus its full evidence trail plus a content hash —
that a human reviewer examines before signing the L4 gate via
``DiscoveryKernel.promote_to_l4``. External reproduction itself is externally gated
(third-party reviewers, independent re-runs) and is not performed here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .ledger import EvidenceLedger
from .models import Candidate, Evidence


@dataclass(frozen=True)
class HumanSignature:
    reviewer: str
    timestamp: str = ""
    notes: str = ""


@dataclass(frozen=True)
class ReproductionBundle:
    candidate_id: str
    claim: str
    parameters: dict[str, Any]
    evidence: tuple[Evidence, ...]
    transitions: tuple[tuple[str, int, tuple[str, ...]], ...]
    bundle_hash: str


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str
    ).encode("utf-8")


def _evidence_from_event(payload: dict[str, Any]) -> Evidence:
    return Evidence(
        payload["evidence_id"],
        payload["candidate_id"],
        payload["kind"],
        payload["passed"],
        payload["protocol"],
        payload["dataset"],
        payload["seed"],
        payload.get("score"),
        dict(payload.get("details", {})),
    )


def build_reproduction_bundle(ledger: EvidenceLedger, candidate: Candidate) -> ReproductionBundle:
    """Assemble the candidate's full traceable record + a content hash for review."""
    events = [e for e in ledger.events() if e.candidate_id == candidate.candidate_id]
    evidence = tuple(_evidence_from_event(e.payload) for e in events if e.kind == "evidence")
    transitions = tuple(
        (e.kind, int(e.payload["to_level"]), tuple(e.payload.get("evidence_refs", ())))
        for e in events
        if e.kind in {"promotion", "demotion"}
    )
    summary = {
        "candidate_id": candidate.candidate_id,
        "claim": candidate.claim,
        "parameters": dict(candidate.parameters),
        "evidence": [
            {"evidence_id": e.evidence_id, "kind": e.kind, "passed": e.passed, "score": e.score}
            for e in evidence
        ],
        "transitions": [list(t) for t in transitions],
    }
    bundle_hash = hashlib.sha256(_canonical(summary)).hexdigest()
    return ReproductionBundle(
        candidate_id=candidate.candidate_id,
        claim=candidate.claim,
        parameters=dict(candidate.parameters),
        evidence=evidence,
        transitions=transitions,
        bundle_hash=bundle_hash,
    )
