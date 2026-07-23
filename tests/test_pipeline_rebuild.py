"""Tests for the pipeline rebuild modules (Stages A, E, F, G, H, J)."""

import random

from sapiens.adapters.desi import DesiPhotozAdapter, DesiRow
from sapiens.budget import ExecutionContext
from sapiens.generators import (
    AnomalyDrivenGenerator,
    DataScanGenerator,
    HypothesisGenerator,
)
from sapiens.permutation import permutation_pvalue
from sapiens.timedomain import LightCurve, LightCurvePoint
from sapiens.validation import ols_fit_predict, pearson

# --- Stage A: hypothesis generators ---


def test_data_scan_generator_produces_candidates():
    gen = DataScanGenerator("test-domain", ("u", "g", "r"))
    assert isinstance(gen, HypothesisGenerator)
    cands = gen.generate(seed=1, limit=3, context=ExecutionContext(10, 5))
    assert len(cands) == 3
    assert all(c.domain == "test-domain" for c in cands)
    assert cands[0].parameters["predictor"] == "u"


def test_anomaly_driven_generator_produces_candidate():
    gen = AnomalyDrivenGenerator("test-domain")
    cands = gen.generate(seed=1, limit=1, context=ExecutionContext(10, 5))
    assert len(cands) >= 1
    assert "anomaly" in cands[0].parameters.get("source", "").lower()


# --- Stage G: permutation test ---


def test_permutation_pvalue_strong_signal():
    # x and y strongly correlated -> permutation p-value should be small
    xs = [1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    ys = [2.0, 4, 6, 8, 10, 12, 14, 16, 18, 20]

    def stat(a, b):
        return pearson(a, b).r

    p = permutation_pvalue(stat, xs, ys, n_permutations=200, seed=42)
    assert p < 0.05  # strong signal -> significant


def test_permutation_pvalue_null_signal():
    rng = random.Random(0)
    xs = [rng.uniform(0, 10) for _ in range(20)]
    ys = [rng.uniform(0, 10) for _ in range(20)]

    def stat(a, b):
        return pearson(a, b).r

    p = permutation_pvalue(stat, xs, ys, n_permutations=200, seed=42)
    assert p > 0.1  # null -> not significant


# --- Stage J: OLS solver ---


def test_ols_fits_linear_data():
    rng = random.Random(0)
    x_train = [[rng.uniform(0, 10), rng.uniform(0, 10)] for _ in range(50)]
    y_train = [2.0 * x[0] + 3.0 * x[1] + 1.0 + rng.gauss(0, 0.01) for x in x_train]
    x_test = [[1.0, 1.0], [5.0, 0.0], [0.0, 5.0]]
    preds = ols_fit_predict(x_train, y_train, x_test)
    # y = 2*1+3*1+1=6, 2*5+0+1=11, 0+15+1=16
    assert abs(preds[0] - 6.0) < 0.5
    assert abs(preds[1] - 11.0) < 0.5
    assert abs(preds[2] - 16.0) < 0.5


# --- Stage E: DESI connector ---


def test_desi_adapter_constructs_and_validates():
    rng = random.Random(0)
    rows = [
        DesiRow(
            u=rng.uniform(17, 22),
            g=rng.uniform(17, 22),
            r=rng.uniform(17, 22),
            i=rng.uniform(17, 22),
            z_mag=rng.uniform(17, 22),
            z_spec=rng.uniform(0, 1),
        )
        for _ in range(100)
    ]
    adapter = DesiPhotozAdapter(rows)
    assert adapter.manifest.synthetic_only is False
    cand = adapter.propose(seed=1, limit=1)[0]
    assert cand.domain == "desi-photoz"
    ev = adapter.validate(cand, stage="internal", seed=7, context=ExecutionContext(20, 5))[0]
    assert ev.candidate_id == cand.candidate_id


# --- Stage H: time-domain protocol ---


def test_light_curve_is_immutable():
    pt = LightCurvePoint(mjd=59000.0, magnitude=18.5, magnitude_error=0.01, filter="r")
    lc = LightCurve(object_id="test", ra=10.0, dec=-1.0, points=(pt,))
    assert lc.points[0].magnitude == 18.5


# --- Stage F: literature index (offline — just tests the protocol) ---


def test_novelty_report_dataclass():
    from sapiens.literature import NoveltyReport

    report = NoveltyReport(n_matches=0, top_titles=(), novelty_score=1.0)
    assert report.novelty_score == 1.0
