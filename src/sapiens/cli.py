"""Bounded demonstration CLI; never emits a scientific-discovery claim."""

from __future__ import annotations

import argparse
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .adapters import SyntheticLinearAdapter, SyntheticPhotometryAdapter, SyntheticThresholdAdapter
from .bridge import transfer
from .budget import ExecutionContext
from .discovery import DiscoveryDriver
from .discovery_store import DiscoveryStore
from .kernel import DiscoveryKernel
from .ledger import EvidenceLedger
from .models import EvidenceLevel
from .ongoing import run_ongoing
from .queue import WorkQueue


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

    # Photometry: a periodic synthetic domain, promoted through the ladder, then
    # transferred into the ecology (threshold) domain — confidence resets to L0.
    photometry_adapter = SyntheticPhotometryAdapter()
    photometry = photometry_adapter.propose(seed=21, limit=1)[0]
    kernel.register(photometry)
    photometry_level = EvidenceLevel.L0
    for seed in (22, 23):
        photometry_level = kernel.validate_next(
            photometry_adapter,
            photometry,
            seed=seed,
            context=ExecutionContext(max_steps=10, max_seconds=2),
        )
    photometry_imported, photometry_imported_level, _ = transfer(
        photometry, photometry_level, target_adapter, candidate_id="cross-domain-photometry"
    )
    kernel.register(photometry_imported, transferred_from=photometry.candidate_id)
    return {
        "experimental": True,
        "scientific_discoveries_claimed": 0,
        "source": {"domain": source.domain, "level": source_level.name},
        "transfer": {"target_domain": imported.domain, "level": imported_level.name},
        "photometry": {
            "domain": photometry.domain,
            "level": photometry_level.name,
            "transfer": {
                "target_domain": photometry_imported.domain,
                "level": photometry_imported_level.name,
            },
        },
        "ledger_verified": ledger.verify(),
    }


def run_discovery(
    workdir: Path,
    *,
    seed: int = 7,
    max_jobs: int = 20,
    max_seconds: float = 10.0,
    steps_per_job: int = 20,
    limit_per_adapter: int = 2,
) -> dict[str, object]:
    """Run the autonomous discovery driver over the synthetic adapters."""
    ledger = EvidenceLedger(workdir / "evidence.jsonl")
    kernel = DiscoveryKernel(ledger)
    queue = WorkQueue(workdir / "discovery-queue.sqlite3")
    linear = SyntheticLinearAdapter()
    threshold = SyntheticThresholdAdapter()
    adapters = {linear.manifest.name: linear, threshold.manifest.name: threshold}
    driver = DiscoveryDriver(adapters=adapters, queue=queue, kernel=kernel, seed=seed)
    driver.plan(limit_per_adapter=limit_per_adapter)
    report = driver.run(
        worker="discovery-1",
        max_jobs=max_jobs,
        max_seconds=max_seconds,
        steps_per_job=steps_per_job,
    )
    return {
        "experimental": True,
        "scientific_discoveries_claimed": report.scientific_discoveries_claimed,
        "proposed": report.proposed,
        "reached_l3": list(report.reached_l3),
        "reached_l2": report.reached_l2,
        "reached_l1": report.reached_l1,
        "stayed_l0": report.stayed_l0,
        "exhausted": report.exhausted,
        "ledger_verified": report.ledger_verified,
    }


@contextmanager
def _workdir(path: Path | None):
    if path is not None:
        path.mkdir(parents=True, exist_ok=True)
        yield path
    else:
        with tempfile.TemporaryDirectory() as directory:
            yield Path(directory)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a bounded synthetic SAPIENS workflow")
    sub = parser.add_subparsers(dest="command")

    demo_parser = sub.add_parser("demo", help="synthetic cross-domain demo (default)")
    demo_parser.add_argument("--workdir", type=Path)

    discover_parser = sub.add_parser("discover", help="autonomous discovery driver")
    discover_parser.add_argument("--workdir", type=Path)
    discover_parser.add_argument("--seed", type=int, default=7)
    discover_parser.add_argument("--max-jobs", type=int, default=20)
    discover_parser.add_argument("--max-seconds", type=float, default=10.0)
    discover_parser.add_argument("--steps-per-job", type=int, default=20)
    discover_parser.add_argument("--limit-per-adapter", type=int, default=2)

    ongoing_parser = sub.add_parser(
        "discover-ongoing", help="ongoing wide discovery sweep into the persistent store"
    )
    ongoing_parser.add_argument(
        "--store", type=Path, default=Path(".sapiens_state/discovery.sqlite3")
    )
    ongoing_parser.add_argument("--seed", type=int, default=None)
    ongoing_parser.add_argument("--run-id", default=None)

    args = parser.parse_args()

    if args.command == "discover":
        with _workdir(args.workdir) as workdir:
            result = run_discovery(
                workdir,
                seed=args.seed,
                max_jobs=args.max_jobs,
                max_seconds=args.max_seconds,
                steps_per_job=args.steps_per_job,
                limit_per_adapter=args.limit_per_adapter,
            )
    elif args.command == "discover-ongoing":
        result = {"experimental": True, "scientific_discoveries_claimed": 0}
        result.update(run_ongoing(args.store, seed=args.seed, run_id=args.run_id))
        if result.get("swept", 0) > 0:
            top = DiscoveryStore(args.store).top_for_l4(limit=10)
            result["top_for_l4"] = [
                {
                    "candidate_id": r.candidate_id,
                    "domain": r.domain,
                    "score": round(r.score, 4),
                    "claim": r.claim,
                }
                for r in top
            ]
    else:
        # No subcommand (backward compatible) or explicit "demo".
        workdir_arg = args.workdir if args.command == "demo" else None
        with _workdir(workdir_arg) as workdir:
            result = run_demo(workdir)

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
