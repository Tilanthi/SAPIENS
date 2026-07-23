"""Anomaly registry — the discovery substrate's central registry (v1).

A persistent store of anomalies (structured residuals, outlier objects,
template-rejection failures, ceiling violations) detected across all data pipelines.
Anomalies are RANKED by a survivability score and NEVER silently discarded — they
persist until a human investigates and marks them explained or discarded.

Anomalies are NOT discoveries: they are flagged 'this does not fit; look here.'
scientific_discoveries_claimed stays 0 regardless of anomaly count.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AnomalyRecord:
    anomaly_id: str
    domain: str
    kind: str  # structured_residual | outlier | template_rejection | ceiling_violation
    description: str
    severity: float  # survivability score [0, 1]; higher = more likely genuinely anomalous
    object_ref: str  # e.g. "ra=166.45,dec=-0.89"
    details_json: str  # JSON-encoded details dict
    detected_at: float
    status: str = "new"  # new | investigating | explained | discarded
    investigation_note: str = ""


class AnomalyRegistry:
    """Persistent, append-only registry of anomalies, ranked by survivability.

    Never auto-discards. Every anomaly survives until a human marks it.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS anomalies (
                    anomaly_id TEXT PRIMARY KEY,
                    domain TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    description TEXT NOT NULL,
                    severity REAL NOT NULL,
                    object_ref TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    detected_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new',
                    investigation_note TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_severity ON anomalies(severity DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_status ON anomalies(status)"
            )

    def register(
        self,
        anomaly_id: str,
        domain: str,
        kind: str,
        description: str,
        severity: float,
        object_ref: str,
        details_json: str = "{}",
        detected_at: float | None = None,
    ) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO anomalies VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    anomaly_id,
                    domain,
                    kind,
                    description,
                    max(0.0, min(1.0, severity)),
                    object_ref,
                    details_json,
                    detected_at if detected_at is not None else time.time(),
                    "new",
                    "",
                ),
            )

    def top(self, limit: int = 10, status: str | None = None) -> list[AnomalyRecord]:
        sql = (
            "SELECT anomaly_id, domain, kind, description, severity, object_ref, "
            "details_json, detected_at, status, investigation_note FROM anomalies"
        )
        params: list = []
        if status:
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY severity DESC, detected_at ASC LIMIT ?"
        params.append(limit)
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [AnomalyRecord(*r) for r in rows]

    def mark(self, anomaly_id: str, status: str, note: str = "") -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "UPDATE anomalies SET status=?, investigation_note=? WHERE anomaly_id=?",
                (status, note, anomaly_id),
            )

    def counts_by_kind(self) -> dict[str, int]:
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                "SELECT kind, COUNT(*) FROM anomalies GROUP BY kind"
            ).fetchall()
        return {k: n for k, n in rows}

    def counts_by_status(self) -> dict[str, int]:
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM anomalies GROUP BY status"
            ).fetchall()
        return {s: n for s, n in rows}

    def __len__(self) -> int:
        with sqlite3.connect(self.path) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM anomalies").fetchone()[0])
