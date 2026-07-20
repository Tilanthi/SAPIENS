"""Trust-tiered adapter registry (Phase 1 v1).

Retires the blanket Phase-0 ``synthetic_only`` refusal in favour of tiered admission
control. Synthetic adapters are admitted automatically at the SYNTHETIC tier. A
non-synthetic (real-data) adapter is admitted only at the VETTED tier, which requires an
explicit approver and declared capabilities on record. The registry does not itself
execute adapters; admission is a recorded decision that the kernel checks before any
promotion work runs.

OS-level subprocess sandboxing and cryptographic signing are roadmap items (Phase 1 v2);
in v1 a VETTED adapter runs in-process, but its admission is explicit and auditable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .adapter import DomainAdapter


class TrustTier(Enum):
    SYNTHETIC = "synthetic"
    VETTED = "vetted"


@dataclass(frozen=True)
class AdapterRegistration:
    adapter: DomainAdapter
    tier: TrustTier
    capabilities: frozenset[str]
    approver: str
    note: str = ""

    @property
    def name(self) -> str:
        return self.adapter.manifest.name


class AdapterRegistry:
    """Records adapter admissions. Synthetic auto-admits; real adapters need a VETTED entry."""

    def __init__(self) -> None:
        self._by_name: dict[str, AdapterRegistration] = {}

    def register(
        self,
        adapter: DomainAdapter,
        *,
        tier: TrustTier | None = None,
        capabilities: tuple[str, ...] = (),
        approver: str = "",
        note: str = "",
    ) -> AdapterRegistration:
        manifest = adapter.manifest
        if manifest.synthetic_only:
            if tier not in (None, TrustTier.SYNTHETIC):
                raise ValueError("synthetic_only adapter must register at SYNTHETIC tier")
            registration = AdapterRegistration(
                adapter, TrustTier.SYNTHETIC, frozenset(), approver="", note=note
            )
        else:
            if tier == TrustTier.SYNTHETIC:
                raise ValueError("non-synthetic adapter cannot register at SYNTHETIC tier")
            if not approver:
                raise ValueError("non-synthetic adapter requires an approver on record")
            registration = AdapterRegistration(
                adapter,
                TrustTier.VETTED,
                frozenset(capabilities),
                approver=approver,
                note=note,
            )
        if registration.name in self._by_name:
            raise ValueError(f"adapter {registration.name!r} already registered")
        self._by_name[registration.name] = registration
        return registration

    def get(self, name: str) -> AdapterRegistration:
        return self._by_name[name]

    def __contains__(self, name: object) -> bool:
        return name in self._by_name

    def __len__(self) -> int:
        return len(self._by_name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._by_name)
