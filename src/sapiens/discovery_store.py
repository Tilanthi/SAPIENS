"""Persistent store of climbed discovery candidates (ongoing discovery).

Records every candidate the autonomous pipeline promotes, with its final level and
evidence score, so a human can later query the top-ranked L3 candidates for L4 sign-off.
These are CANDIDATES, not discoveries: level never exceeds L3 here (no human gate has
been applied), so ``scientific_discoveries_claimed`` remains 0 regardless of store size.
"""

from __future__ import annotations

import sqlite3
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CandidateRecord:
    candidate_id: str
    domain: str
    claim: str
    final_level: int
    score: float
    source_adapter: str
    run_id: str
    seeded_at: float


class DiscoveryStore:
    """SQLite-backed register of climbed candidates, queryable for L4 sign-off."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS candidates (
                    candidate_id TEXT PRIMARY KEY,
                    domain TEXT NOT NULL,
                    claim TEXT NOT NULL,
                    final_level INTEGER NOT NULL,
                    score REAL NOT NULL,
                    source_adapter TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    seeded_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_level_score ON candidates(final_level, score DESC)"
            )

    def record(
        self,
        candidate_id: str,
        domain: str,
        claim: str,
        final_level: int,
        score: float,
        source_adapter: str,
        run_id: str,
        seeded_at: float | None = None,
    ) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO candidates VALUES (?,?,?,?,?,?,?,?)",
                (
                    candidate_id,
                    domain,
                    claim,
                    int(final_level),
                    float(score),
                    source_adapter,
                    run_id,
                    seeded_at if seeded_at is not None else time.time(),
                ),
            )

    def top_for_l4(self, limit: int = 10) -> list[CandidateRecord]:
        """Highest-scoring candidates that reached L3 (review-ready), ranked for human sign-off."""
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                "SELECT candidate_id, domain, claim, final_level, score, source_adapter, "
                "run_id, seeded_at FROM candidates WHERE final_level >= 3 "
                "ORDER BY score DESC, seeded_at ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [CandidateRecord(*r) for r in rows]

    def counts_by_level(self) -> dict[int, int]:
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                "SELECT final_level, COUNT(*) FROM candidates GROUP BY final_level"
            ).fetchall()
        return {int(level): int(count) for level, count in rows}

    def __len__(self) -> int:
        with sqlite3.connect(self.path) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0])


def run_discovery_sweep(
    adapters,
    store: DiscoveryStore,
    *,
    seed: int,
    run_id: str,
    registry=None,
    limit_per_adapter: int = 2,
    max_steps: int = 60,
    max_seconds: float = 30,
) -> dict[str, int]:
    """Climb each adapter's candidates L0->(<=L3) and persist them to the store.

    ``registry`` is required when non-synthetic (VETTED) adapters are present. Discovery
    never blocks on L4 — it caps at L3 and records the candidate for later human sign-off.
    """
    # Local imports avoid any import-cycle at module load.
    from .budget import ExecutionContext
    from .kernel import DiscoveryKernel
    from .ledger import EvidenceLedger
    from .models import EvidenceLevel

    def _ctx() -> ExecutionContext:
        return ExecutionContext(max_steps, max_seconds)

    summary = {"proposed": 0, "reached_l3": 0}
    for adapter in adapters:
        with tempfile.TemporaryDirectory() as directory:
            ledger = EvidenceLedger(Path(directory) / "evidence.jsonl")
            kernel = DiscoveryKernel(ledger, registry=registry)
            for candidate in adapter.propose(seed=seed, limit=limit_per_adapter):
                kernel.register(candidate)
                level = EvidenceLevel.L0
                for offset in (0, 1, 2):
                    try:
                        reached = kernel.validate_next(
                            adapter, candidate, seed=seed + offset, context=_ctx()
                        )
                    except Exception:
                        break
                    if reached == level:
                        break
                    level = reached
                scores = [
                    float(event.payload["score"])
                    for event in ledger.events()
                    if event.candidate_id == candidate.candidate_id
                    and event.kind == "evidence"
                    and event.payload.get("score") is not None
                ]
                score = max(scores) if scores else 0.0
                store.record(
                    candidate.candidate_id,
                    candidate.domain,
                    candidate.claim,
                    int(level),
                    score,
                    adapter.manifest.name,
                    run_id,
                )
                summary["proposed"] += 1
                if level == EvidenceLevel.L3:
                    summary["reached_l3"] += 1
    return summary
