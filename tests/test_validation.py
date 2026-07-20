import math

from sapiens.validation import (
    PassPolicy,
    benjamini_hochberg,
    betai,
    evaluate,
    holdout_split,
    pearson,
    proportion_ci,
)


def approx(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


# --- incomplete beta: analytic checks ---------------------------------------------


def test_betai_matches_analytic_beta_cdfs():
    # Beta(1,1) is uniform: I_x(1,1) = x
    assert approx(betai(1.0, 1.0, 0.3), 0.3, 1e-9)
    assert approx(betai(1.0, 1.0, 0.75), 0.75, 1e-9)
    # Beta(2,2) CDF = 3x^2 - 2x^3
    assert approx(betai(2.0, 2.0, 0.3), 3 * 0.3**2 - 2 * 0.3**3, 1e-9)
    assert approx(betai(2.0, 2.0, 0.5), 0.5, 1e-9)
    # Beta(0.5,0.5) is symmetric about 0.5
    assert approx(betai(0.5, 0.5, 0.5), 0.5, 1e-9)
    # boundaries
    assert betai(2.0, 3.0, 0.0) == 0.0
    assert betai(2.0, 3.0, 1.0) == 1.0


# --- Clopper-Pearson interval -----------------------------------------------------


def test_proportion_ci_known_values():
    ci = proportion_ci(8, 10, confidence=0.95)
    assert approx(ci.point, 0.8, 1e-12)
    assert approx(ci.lower, 0.4439, 1e-3)
    assert approx(ci.upper, 0.9748, 1e-3)

    zero = proportion_ci(0, 10)
    assert zero.lower == 0.0 and zero.point == 0.0
    full = proportion_ci(10, 10)
    assert full.upper == 1.0 and full.point == 1.0

    # interval always contains the point estimate
    for k in range(0, 11):
        c = proportion_ci(k, 10)
        assert c.lower <= c.point <= c.upper


# --- Pearson correlation + p-value ------------------------------------------------


def test_pearson_perfect_and_anticorrelated():
    up = pearson([1.0, 2, 3, 4, 5], [2.0, 4, 6, 8, 10])
    assert approx(up.r, 1.0, 1e-12)
    assert up.pvalue < 1e-15  # effectively zero (tiny float residual from r < 1.0)

    down = pearson([1.0, 2, 3, 4, 5], [10.0, 8, 6, 4, 2])
    assert approx(down.r, -1.0, 1e-12)
    assert down.pvalue < 1e-15


def test_pearson_uncorrelated_has_unit_pvalue():
    # constructed so the cross-deviation sum is exactly zero -> r == 0
    result = pearson([-1.0, 0.0, 1.0], [1.0, 0.0, 1.0])
    assert approx(result.r, 0.0, 1e-12)
    assert approx(result.pvalue, 1.0, 1e-9)


def test_pearson_pvalue_shrinks_as_correlation_strengthens():
    weak = pearson([1.0, 2, 3, 4, 5, 6, 7, 8], [1.1, 1.9, 3.2, 3.7, 5.3, 5.8, 7.1, 7.6])
    strong = pearson([1.0, 2, 3, 4, 5, 6, 7, 8], [1.0, 2.05, 2.95, 4.1, 4.9, 6.1, 6.9, 8.1])
    assert abs(strong.r) > abs(weak.r)
    assert strong.pvalue < weak.pvalue
    assert 0.0 < weak.pvalue < 1.0


# --- Benjamini-Hochberg FDR -------------------------------------------------------


def test_benjamini_hochberg_known_set():
    pvalues = [0.01, 0.04, 0.03, 0.20]
    result = benjamini_hochberg(pvalues, alpha=0.05)
    assert approx(result.adjusted[0], 0.04, 1e-9)
    assert approx(result.adjusted[1], 0.053333, 1e-5)
    assert approx(result.adjusted[2], 0.053333, 1e-5)
    assert approx(result.adjusted[3], 0.20, 1e-9)
    assert result.rejected == (True, False, False, False)


def test_benjamini_hochberg_empty_and_clamped():
    assert benjamini_hochberg([]).adjusted == ()
    big = benjamini_hochberg([0.9, 0.95])
    assert all(0.0 <= p <= 1.0 for p in big.adjusted)


# --- holdout split ----------------------------------------------------------------


def test_holdout_split_is_disjoint_deterministic_and_complete():
    a = holdout_split(20, train_fraction=0.5, seed=42)
    b = holdout_split(20, train_fraction=0.5, seed=42)
    assert a == b  # deterministic
    assert set(a.train).isdisjoint(a.test)  # leakage-safe
    assert len(a.train) == 10 and len(a.test) == 10
    assert sorted(a.train + a.test) == list(range(20))  # complete
    c = holdout_split(20, train_fraction=0.5, seed=7)
    assert c.train != a.train  # seed changes the split


# --- evidence gate ----------------------------------------------------------------


def test_evaluate_gate_decides_from_real_statistics():
    policy = PassPolicy(min_effect=0.5, ci_floor=0.4, max_pvalue=0.05)
    accept = evaluate(point=0.8, ci_lower=0.6, pvalue=0.01, policy=policy)
    assert accept.passed and not accept.reasons

    reject_effect = evaluate(point=0.3, ci_lower=0.6, pvalue=0.01, policy=policy)
    assert not reject_effect.passed and any("min_effect" in r for r in reject_effect.reasons)

    reject_pvalue = evaluate(point=0.8, ci_lower=0.6, pvalue=0.5, policy=policy)
    assert not reject_pvalue.passed and any("pvalue" in r for r in reject_pvalue.reasons)

    reject_ci = evaluate(point=0.8, ci_lower=0.2, pvalue=0.01, policy=policy)
    assert not reject_ci.passed and any("ci_lower" in r for r in reject_ci.reasons)


def test_math_module_present():
    # sanity: stdlib math exposes the special functions the module relies on
    assert callable(math.lgamma) and callable(math.erf)
