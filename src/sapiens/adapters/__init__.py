"""Synthetic-only demonstration adapters; not scientific models."""

from .linear import SyntheticLinearAdapter
from .photometry import SyntheticPhotometryAdapter
from .threshold import SyntheticThresholdAdapter

__all__ = [
    "SyntheticLinearAdapter",
    "SyntheticPhotometryAdapter",
    "SyntheticThresholdAdapter",
]
