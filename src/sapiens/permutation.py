"""Permutation-test significance (Stage G — replaces the harsh DevilsAdvocate gate).

Computes empirical p-values by shuffling labels and recomparing the statistic,
rather than relying on parametric thresholds (r >= 0.9, p < 1e-6) that are so
strict almost nothing genuine passes. Pure standard library.
"""

from __future__ import annotations

import random
from collections.abc import Callable


def permutation_pvalue(
    statistic_fn: Callable[[list[float], list[float]], float],
    xs: list[float],
    ys: list[float],
    *,
    n_permutations: int = 1000,
    seed: int = 0,
) -> float:
    """Empirical two-sided p-value via permutation.

    Shuffles ``ys`` (breaking any real association), recomputes the statistic,
    and counts how often the shuffled statistic meets or exceeds the observed.
    """
    observed = abs(statistic_fn(xs, ys))
    rng = random.Random(seed)
    count = 0
    y_copy = list(ys)
    for _ in range(n_permutations):
        rng.shuffle(y_copy)
        if abs(statistic_fn(xs, y_copy)) >= observed:
            count += 1
    return (count + 1) / (n_permutations + 1)
