"""Cooperative, monotonic resource budgets for bounded Phase-0 work."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


class BudgetExceeded(RuntimeError):
    pass


class Preempted(RuntimeError):
    pass


@dataclass
class ExecutionContext:
    max_steps: int
    max_seconds: float
    steps: int = 0
    _started: float = field(default_factory=time.monotonic)
    _preempted: bool = False

    def __post_init__(self) -> None:
        if self.max_steps <= 0 or self.max_seconds <= 0:
            raise ValueError("budgets must be positive")

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._started

    def preempt(self) -> None:
        self._preempted = True

    def checkpoint(self, units: int = 1) -> None:
        if units < 0:
            raise ValueError("units cannot be negative")
        if self._preempted:
            raise Preempted("work preempted at a safe point")
        self.steps += units
        if self.steps > self.max_steps or self.elapsed > self.max_seconds:
            raise BudgetExceeded("resource budget exhausted")
