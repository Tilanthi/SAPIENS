"""Systematic sieve / robustness engine (Discovery Substrate priority 1b).

Checks anomaly populations against plausible systematics BEFORE promoting them as robust.
For SAPIENS's SDSS data: spatial clustering (are anomalies concentrated in one sky
region, suggesting a CCD/observing systematic?) and magnitude bias (are they concentrated
at the flux limit, suggesting Malmquist bias?). Only anomalies that survive the sieve are
promoted as 'robust'; failed checks are logged — nothing is silently discarded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SieveCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class SieveResult:
    domain: str
    n_anomalies: int
    survived: bool
    checks: tuple[SieveCheck, ...]
    robustness: float  # fraction of checks passed [0, 1]


_RA_DEC_RE = re.compile(r"ra=([-\d.]+),dec=([-\d.]+)")


def _parse_ra_dec(object_ref: str) -> tuple[float, float] | None:
    m = _RA_DEC_RE.search(object_ref)
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def sieve_population(
    anomalies: list,
    sample_ras: list[float],
    sample_magnitudes: list[float],
    anomaly_magnitudes: list[float],
    *,
    domain: str,
) -> SieveResult:
    """Run systematic checks on an anomaly population.

    Args:
        anomalies: list of AnomalyRecord (uses .object_ref for sky position).
        sample_ras: RA values of the full sample (to compare spatial spread).
        sample_magnitudes: magnitude values of the full sample.
        anomaly_magnitudes: magnitude values of the anomalous objects.
        domain: domain tag for the result.
    """
    checks: list[SieveCheck] = []

    # --- spatial spread ---
    anomaly_coords = [_parse_ra_dec(a.object_ref) for a in anomalies]
    anomaly_ras = [c[0] for c in anomaly_coords if c is not None]
    if anomaly_ras and sample_ras:
        anomaly_range = max(anomaly_ras) - min(anomaly_ras) if len(anomaly_ras) > 1 else 0
        sample_range = max(sample_ras) - min(sample_ras) if sample_ras else 1
        fraction = anomaly_range / sample_range if sample_range > 0 else 0
        passed = fraction >= 0.4  # anomalies should span >=40% of the sample's RA range
        checks.append(
            SieveCheck(
                "spatial_spread",
                passed,
                f"anomaly RA range covers {fraction:.1%} of sample range "
                f"({'OK' if passed else 'CLUSTERED — possible spatial systematic'})",
            )
        )

    # --- magnitude bias (Malmquist) ---
    if anomaly_magnitudes and sample_magnitudes:
        anomaly_median = sorted(anomaly_magnitudes)[len(anomaly_magnitudes) // 2]
        sample_median = sorted(sample_magnitudes)[len(sample_magnitudes) // 2]
        delta = anomaly_median - sample_median
        passed = abs(delta) < 0.5  # anomalies should not be strongly biased toward faint end
        checks.append(
            SieveCheck(
                "magnitude_bias",
                passed,
                f"anomaly median mag {anomaly_median:.2f} vs sample {sample_median:.2f} "
                f"(delta {delta:+.2f}; {'OK' if passed else 'BIASED — possible Malmquist'})",
            )
        )

    survived = all(c.passed for c in checks) if checks else False
    robustness = sum(1 for c in checks if c.passed) / len(checks) if checks else 0.0
    return SieveResult(domain, len(anomalies), survived, tuple(checks), robustness)
