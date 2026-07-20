"""Synthetic demonstration adapters and real-data connectors; not scientific models."""

from .linear import SyntheticLinearAdapter
from .photometry import SyntheticPhotometryAdapter
from .regression import SyntheticRegressionAdapter
from .sdss_classification import SDSSClassificationAdapter
from .sdss_photoz import SDSSPhotozAdapter
from .threshold import SyntheticThresholdAdapter

__all__ = [
    "SDSSClassificationAdapter",
    "SDSSPhotozAdapter",
    "SyntheticLinearAdapter",
    "SyntheticPhotometryAdapter",
    "SyntheticRegressionAdapter",
    "SyntheticThresholdAdapter",
]
