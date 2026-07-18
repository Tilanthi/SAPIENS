"""Bounded demonstration CLI; never emits a scientific-discovery claim."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from .adapters import SyntheticLinearAdapter, SyntheticThresholdAdapter
from .bridge import transfer
from .budget import ExecutionContext
from .kernel import DiscoveryKernel
from .ledger import EvidenceLedger
from .models import EvidenceLevel


def run_demo(workdir: Path) -> dict[str, object]:
    ledger = EvidenceLedger(workdir / "evidence.jsonl")
    kernel = DiscoveryKernel(ledger)
    source_adapter = SyntheticLinearAdapter()
    target_adapter = SyntheticThresholdAdapter()
    source = source_adapter.propose(seed=7, limit=1)[0]
    kernel.register(source)
    source_level = EvidenceLevel.L0
    for seed in (11, 12):
        source_level = kernel.validate_next(
            source_adapter,
            source,
            seed=seed,
            context=ExecutionContext(max_steps=10, max_seconds=2),
        )
    imported, imported_level, _ = transfer(
        source, source_level, target_adapter, candidate_id="cross-domain-demo"
    )
    kernel.register(imported, transferred_from=source.candidate_id)
    return {
        "experimental": True,
        "scientific_discoveries_claimed": 0,
        "source": {"domain": source.domain, "level": source_level.name},
        "transfer": {"target_domain": imported.domain, "level": imported_level.name},
        "ledger_verified": ledger.verify(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a bounded synthetic SAPIENS demonstration")
    parser.add_argument("--workdir", type=Path)
    args = parser.parse_args()
    if args.workdir:
        args.workdir.mkdir(parents=True, exist_ok=True)
        result = run_demo(args.workdir)
    else:
        with tempfile.TemporaryDirectory() as directory:
            result = run_demo(Path(directory))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
