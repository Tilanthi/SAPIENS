"""SAPIENS: experimental, traceable scientific-discovery workflow plumbing."""

from .adapter import DomainAdapter
from .bridge import TransferEnvelope, transfer
from .discovery import DiscoveryDriver, DiscoveryReport
from .kernel import DiscoveryKernel
from .ledger import EvidenceLedger
from .models import AdapterManifest, Candidate, Evidence, EvidenceLevel

__all__ = [
    "AdapterManifest",
    "Candidate",
    "DiscoveryDriver",
    "DiscoveryKernel",
    "DiscoveryReport",
    "DomainAdapter",
    "Evidence",
    "EvidenceLedger",
    "EvidenceLevel",
    "TransferEnvelope",
    "transfer",
]
__version__ = "0.1.0"
