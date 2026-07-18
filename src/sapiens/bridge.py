"""Cross-domain structural transfer with mandatory confidence reset."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .adapter import DomainAdapter
from .models import Candidate, EvidenceLevel


@dataclass(frozen=True)
class TransferEnvelope:
    source_candidate_id: str
    source_domain: str
    target_domain: str
    structure: Mapping[str, Any]
    source_level_discarded: EvidenceLevel


def transfer(
    source: Candidate,
    source_level: EvidenceLevel,
    target: DomainAdapter,
    *,
    candidate_id: str,
) -> tuple[Candidate, EvidenceLevel, TransferEnvelope]:
    """Transfer method/structure only; target confidence always starts at L0."""
    if source.domain == target.manifest.domain:
        raise ValueError("cross-domain transfer requires different domains")
    structure = {
        "relation": source.parameters.get("relation", "unknown"),
        "arity": source.parameters.get("arity", 1),
        "_source_candidate_id": source.candidate_id,
    }
    envelope = TransferEnvelope(
        source_candidate_id=source.candidate_id,
        source_domain=source.domain,
        target_domain=target.manifest.domain,
        structure=structure,
        source_level_discarded=source_level,
    )
    imported = target.import_structure(dict(structure), candidate_id=candidate_id)
    if imported.domain != target.manifest.domain or imported.parent_id != source.candidate_id:
        raise ValueError("adapter returned an invalid transferred candidate")
    return imported, EvidenceLevel.L0, envelope
