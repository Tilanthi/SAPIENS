"""Synthetic-only demonstration adapters; not scientific models."""

from .linear import SyntheticLinearAdapter
from .regression import SyntheticRegressionAdapter
from .threshold import SyntheticThresholdAdapter

__all__ = [
    "SyntheticLinearAdapter",
    "SyntheticRegressionAdapter",
    "SyntheticThresholdAdapter",
]
