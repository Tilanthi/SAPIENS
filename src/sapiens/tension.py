"""Cross-method tension register (Discovery Substrate priority 1c).

Tracks precision-quantity estimates from multiple methods with disjoint systematics
across runs, and flags persistent disagreements (non-overlapping CIs across >=min_seeds)
as tensions — candidate model mismatches. Never averages disagreements away; escalates
them. For SAPIENS: the 'u-band photo-z correlation' vs 'g-band photo-z correlation'
measure the same underlying quantity (broadband photometry -> redshift) with disjoint
calibration/dust systematics; persistent disagreement is a tension worth investigating.
"""

from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TensionRecord:
    quantity: str
    method_a: str
    value_a: float
    ci_a: tuple[float, float]
    method_b: str
    value_b: float
    ci_b: tuple[float, float]
    overlap: bool
    persistent_disagreement: bool


def fisher_z_ci(r: float, n: int) -> tuple[float, float]:
    """95% CI on Pearson r via Fisher z-transformation (pure stdlib)."""
    r_clamped = max(-0.9999, min(0.9999, r))
    if n < 4:
        return (-1.0, 1.0)
    z = math.atanh(r_clamped)
    se = 1.0 / math.sqrt(n - 3)
    z_crit = 1.959964
    return (math.tanh(z - z_crit * se), math.tanh(z + z_crit * se))


class TensionRegister:
    """Persistent SQLite store tracking multi-method estimates and their disagreements."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS estimates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    quantity TEXT NOT NULL, method TEXT NOT NULL, value REAL NOT NULL,
                    ci_lower REAL NOT NULL, ci_upper REAL NOT NULL,
                    seed INTEGER NOT NULL, run_id TEXT NOT NULL, recorded_at REAL NOT NULL)"""
            )

    def record(
        self,
        quantity: str,
        method: str,
        value: float,
        ci_lower: float,
        ci_upper: float,
        seed: int,
        run_id: str = "",
    ) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT INTO estimates (quantity, method, value, ci_lower, ci_upper, "
                "seed, run_id, recorded_at) VALUES (?,?,?,?,?,?,?,?)",
                (quantity, method, value, ci_lower, ci_upper, seed, run_id, time.time()),
            )

    def tensions(self, min_seeds: int = 3) -> list[TensionRecord]:
        """Flag quantities where >=2 methods persistently disagree (non-overlapping CIs)."""
        with sqlite3.connect(self.path) as conn:
            pairs = conn.execute(
                "SELECT quantity, method, COUNT(DISTINCT seed) FROM estimates "
                "GROUP BY quantity, method HAVING COUNT(DISTINCT seed) >= ?",
                (min_seeds,),
            ).fetchall()
            quantities = sorted({q for q, _, _ in pairs})
            results: list[TensionRecord] = []
            for q in quantities:
                methods = [m for pq, m, _ in pairs if pq == q]
                for i, ma in enumerate(methods):
                    for mb in methods[i + 1 :]:
                        ra = conn.execute(
                            "SELECT value, ci_lower, ci_upper FROM estimates "
                            "WHERE quantity=? AND method=? ORDER BY recorded_at DESC LIMIT 1",
                            (q, ma),
                        ).fetchone()
                        rb = conn.execute(
                            "SELECT value, ci_lower, ci_upper FROM estimates "
                            "WHERE quantity=? AND method=? ORDER BY recorded_at DESC LIMIT 1",
                            (q, mb),
                        ).fetchone()
                        if not ra or not rb:
                            continue
                        overlap = ra[1] <= rb[2] and rb[1] <= ra[2]
                        all_a = conn.execute(
                            "SELECT ci_lower, ci_upper, seed FROM estimates "
                            "WHERE quantity=? AND method=?",
                            (q, ma),
                        ).fetchall()
                        all_b = conn.execute(
                            "SELECT ci_lower, ci_upper, seed FROM estimates "
                            "WHERE quantity=? AND method=?",
                            (q, mb),
                        ).fetchall()
                        total = 0
                        non_overlap = 0
                        for la, ua, sa in all_a:
                            for lb, ub, sb in all_b:
                                if sa == sb:
                                    total += 1
                                    if not (la <= ub and lb <= ua):
                                        non_overlap += 1
                        persistent = total > 0 and non_overlap / total > 0.5
                        results.append(
                            TensionRecord(
                                q, ma, ra[0], (ra[1], ra[2]),
                                mb, rb[0], (rb[1], rb[2]),
                                overlap, persistent,
                            )
                        )
            return sorted(results, key=lambda t: (not t.persistent_disagreement, t.overlap))

    def __len__(self) -> int:
        with sqlite3.connect(self.path) as conn:
            return int(conn.execute("SELECT COUNT(*) FROM estimates").fetchone()[0])
