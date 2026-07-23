"""Time-domain connector protocols (Stage H — ZTF alerts + Gaia TAP).

Defines the protocols for ingesting time-domain data (light curves, alerts,
astrometric time series) which 4/5 astronomy breakthroughs require.
Concrete connectors need network access to broker APIs (ALeRCE, Lasair, Gaia TAP);
these stubs define the interface and provide synthetic-data constructors for testing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class LightCurvePoint:
    mjd: float
    magnitude: float
    magnitude_error: float
    filter: str


@dataclass(frozen=True)
class LightCurve:
    object_id: str
    ra: float
    dec: float
    points: tuple[LightCurvePoint, ...]


@runtime_checkable
class TimeDomainConnector(Protocol):
    """Ingests time-domain astronomy data (light curves, alerts)."""

    @property
    def name(self) -> str: ...

    def fetch_anomalies(self, *, since_mjd: float, limit: int) -> tuple[LightCurve, ...]: ...
