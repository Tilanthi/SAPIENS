"""Synthetic-only demonstration adapters; not scientific models."""

from .linear import SyntheticLinearAdapter
from .threshold import SyntheticThresholdAdapter

__all__ = ["SyntheticLinearAdapter", "SyntheticThresholdAdapter"]
