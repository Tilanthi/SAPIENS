# SAPIENS

**SAPIENS** = **Superintelligent Autonomous Platform for Integrated Exploration of Natural Sciences**.

Phase 0 is a concrete, buildable foundation for traceable scientific-discovery workflows. It is intentionally modest: an **experimental scientific-discovery platform**, not AGI, not autonomous truth, not a benchmark-gain announcement, and not a claim that the included synthetic examples discovered anything about nature.

## What Phase 0 includes

- Clean-room Python package (`sapiens-discovery`), standard-library runtime.
- Domain-neutral `DomainAdapter` contract.
- Append-only hash-chained evidence ledger with L0→L4 transition rules.
- Shared discovery kernel that can promote candidates only through bounded evidence gates.
- Cross-domain bridge that transfers structure/method only and always resets target confidence to **L0**.
- Bounded SQLite work queue and preemptible daemon skeleton.
- Two deterministic synthetic adapters/datasets:
  - `synthetic-kinematics` linear relation.
  - `synthetic-ecology` threshold interaction.
- Documentation: architecture, provenance, validation, roadmap, and a bounded humour hook.

## Quick start

```bash
python -m pip install -e ".[dev]"
ruff check src tests
pytest
python -m sapiens.cli
```

Expected CLI contract includes:

```json
{
  "experimental": true,
  "scientific_discoveries_claimed": 0,
  "transfer": {"level": "L0"}
}
```

## Evidence levels

- **L0 Candidate**: traceable candidate only; not believed.
- **L1 Internal**: passed internal/synthetic consistency checks.
- **L2 Replication**: passed held-out/reproducibility checks.
- **L3 Review**: passed bounded structured review/adversarial checks.
- **L4 External-ready**: requires explicit human gate; disabled for autonomous Phase-0 promotion.

## Legal boundary

No ASTRA-dev, ASTRA, GEODISC, BIODISC, or SLATE source file was copied into this repo. SAPIENS Phase 0 is a clean-room implementation from requirements, high-level architecture, and observed license facts documented in [`PROVENANCE.md`](PROVENANCE.md).
