"""Real statistical validation machinery (Phase 2 v1).

Replaces adapter-internal "rigged" scores with genuine, reproducible statistics so that
evidence reflects held-out reality, not a planted answer. Pure standard library — no
numpy/scipy — to stay inside the Phase-0 runtime constraint.

The backbone is the regularized incomplete beta function ``I_x(a, b)`` (Lentz continued
fraction), from which the exact Clopper-Pearson binomial interval and the Pearson
correlation p-value are derived. Multiple-comparison correction (Benjamini-Hochberg FDR)
is included because any real discovery loop tests many candidates and raw p-values would
yield floods of false positives. Everything here is deterministic.

This module is statistics only — it claims nothing about nature and performs no
scientific discovery.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

_BETA_EPS = 3e-12
_BETA_MAXIT = 300
_BETA_FPMIN = 1e-300


def _betacf(a: float, b: float, x: float) -> float:
    """Continued-fraction expansion for the incomplete beta (Lentz's method)."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _BETA_FPMIN:
        d = _BETA_FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, _BETA_MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < _BETA_FPMIN:
            d = _BETA_FPMIN
        c = 1.0 + aa / c
        if abs(c) < _BETA_FPMIN:
            c = _BETA_FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < _BETA_FPMIN:
            d = _BETA_FPMIN
        c = 1.0 + aa / c
        if abs(c) < _BETA_FPMIN:
            c = _BETA_FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _BETA_EPS:
            break
    return h


def betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b) in [0, 1]."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    # log of the beta function B(a, b) = Gamma(a)Gamma(b)/Gamma(a+b); front = x^a (1-x)^b / B(a,b)
    log_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(a * math.log(x) + b * math.log(1.0 - x) - log_beta)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _beta_quantile(a: float, b: float, p: float) -> float:
    """Inverse of betai: the x in (0, 1) with I_x(a, b) = p, via bisection."""
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if betai(a, b, mid) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


@dataclass(frozen=True)
class ProportionCI:
    lower: float
    point: float
    upper: float


def proportion_ci(successes: int, trials: int, *, confidence: float = 0.95) -> ProportionCI:
    """Exact Clopper-Pearson confidence interval for a binomial proportion."""
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    if trials <= 0 or not 0 <= successes <= trials:
        raise ValueError("require 0 <= successes <= trials and trials > 0")
    alpha = 1.0 - confidence
    point = successes / trials
    lower = 0.0 if successes == 0 else _beta_quantile(successes, trials - successes + 1, alpha / 2)
    upper = 1.0 if successes == trials else _beta_quantile(
        successes + 1, trials - successes, 1.0 - alpha / 2
    )
    return ProportionCI(lower, point, upper)


@dataclass(frozen=True)
class PearsonResult:
    r: float
    pvalue: float
    n: int


def pearson(x: list[float], y: list[float]) -> PearsonResult:
    """Pearson correlation coefficient with a two-sided p-value under H0: r == 0."""
    n = len(x)
    if n != len(y):
        raise ValueError("x and y must have equal length")
    if n < 3:
        raise ValueError("pearson requires at least 3 paired observations")
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    sxx = sum((a - mean_x) ** 2 for a in x)
    syy = sum((b - mean_y) ** 2 for b in y)
    sxy = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y, strict=True))
    if sxx == 0.0 or syy == 0.0:
        return PearsonResult(0.0, 1.0, n)
    r = sxy / (math.sqrt(sxx) * math.sqrt(syy))
    r = max(-1.0, min(1.0, r))
    if abs(r) >= 1.0:
        pvalue = 0.0
    else:
        df = n - 2
        pvalue = betai(df / 2.0, 0.5, 1.0 - r * r)
    return PearsonResult(r, pvalue, n)


@dataclass(frozen=True)
class MultipleComparison:
    adjusted: tuple[float, ...]
    rejected: tuple[bool, ...]


def benjamini_hochberg(pvalues: list[float], *, alpha: float = 0.05) -> MultipleComparison:
    """Benjamini-Hochberg FDR-adjusted p-values and rejection decisions."""
    n = len(pvalues)
    if n == 0:
        return MultipleComparison((), ())
    if any(not 0.0 <= p <= 1.0 for p in pvalues):
        raise ValueError("p-values must lie in [0, 1]")
    order = sorted(range(n), key=lambda i: pvalues[i])  # ascending by p-value
    adjusted = [0.0] * n
    running = float("inf")
    for step, idx in enumerate(reversed(order), start=1):
        asc_rank = n - (step - 1)
        value = min(pvalues[idx] * n / asc_rank, running)
        adjusted[idx] = min(value, 1.0)
        running = value
    rejected = tuple(a <= alpha for a in adjusted)
    return MultipleComparison(tuple(adjusted), rejected)


@dataclass(frozen=True)
class HoldoutSplit:
    train: tuple[int, ...]
    test: tuple[int, ...]
    seed: int


def holdout_split(n: int, *, train_fraction: float = 0.5, seed: int) -> HoldoutSplit:
    """Deterministic, leakage-safe train/test index split."""
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0.0 < train_fraction < 1.0:
        raise ValueError("train_fraction must be in (0, 1)")
    indices = list(range(n))
    rng = random.Random(seed)
    rng.shuffle(indices)
    cut = int(n * train_fraction)
    return HoldoutSplit(tuple(indices[:cut]), tuple(indices[cut:]), seed)


@dataclass(frozen=True)
class PassPolicy:
    """A real-evidence policy: pass requires point, CI floor, and p-value thresholds."""

    min_effect: float = 0.0
    ci_floor: float | None = None
    max_pvalue: float | None = None


@dataclass(frozen=True)
class PassDecision:
    passed: bool
    point: float
    ci_lower: float | None
    pvalue: float | None
    reasons: tuple[str, ...]


def evaluate(
    *,
    point: float,
    ci_lower: float | None = None,
    pvalue: float | None = None,
    policy: PassPolicy,
) -> PassDecision:
    """Decide pass/fail from real statistics, returning the reasons for any failure."""
    reasons: list[str] = []
    if point < policy.min_effect:
        reasons.append(f"point {point:.4g} below min_effect {policy.min_effect:.4g}")
    if policy.ci_floor is not None and (ci_lower is None or ci_lower < policy.ci_floor):
        reasons.append(f"ci_lower {ci_lower} below ci_floor {policy.ci_floor}")
    if policy.max_pvalue is not None and (pvalue is None or pvalue > policy.max_pvalue):
        reasons.append(f"pvalue {pvalue} above max_pvalue {policy.max_pvalue}")
    return PassDecision(
        passed=not reasons,
        point=point,
        ci_lower=ci_lower,
        pvalue=pvalue,
        reasons=tuple(reasons),
    )


# --- multi-parameter OLS solver (Stage J) ------------------------------------------


def _gaussian_solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Solve Ax=b via Gaussian elimination with partial pivoting."""
    n = len(vector)
    aug = [list(matrix[i]) + [vector[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        aug[col], aug[pivot] = aug[pivot], aug[col]
        if abs(aug[col][col]) < 1e-12:
            continue
        for row in range(col + 1, n):
            factor = aug[row][col] / aug[col][col]
            for k in range(col, n + 1):
                aug[row][k] -= factor * aug[col][k]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = aug[i][n]
        for j in range(i + 1, n):
            x[i] -= aug[i][j] * x[j]
        if abs(aug[i][i]) > 1e-12:
            x[i] /= aug[i][i]
    return x


def ols_fit_predict(
    x_train: list[list[float]], y_train: list[float], x_test: list[list[float]]
) -> list[float]:
    """Ordinary least squares: fit on train, predict on test. Pure stdlib.

    Enables multi-parameter model-fitting validation (Stage J) — replaces the
    single-predictor Pearson-only mode with full linear-regression residuals.
    """
    n_features = len(x_train[0]) if x_train else 0
    dim = n_features + 1  # + intercept
    xtx = [[0.0] * dim for _ in range(dim)]
    xty = [0.0] * dim
    for i in range(len(y_train)):
        row = list(x_train[i]) + [1.0]
        for a in range(dim):
            for b in range(dim):
                xtx[a][b] += row[a] * row[b]
            xty[a] += row[a] * y_train[i]
    beta = _gaussian_solve(xtx, xty)
    predictions: list[float] = []
    for x in x_test:
        row = list(x) + [1.0]
        predictions.append(sum(beta[a] * row[a] for a in range(dim)))
    return predictions
