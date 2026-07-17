# Provenance and Licence Inventory

## Summary

SAPIENS Phase 0 is a new standalone repository. Implementation is clean-room and standard-library based. It does **not** copy upstream ASTRA-family source files.

## Inspected sources

| Source | Exact ref / status | Licence observed | Reuse decision |
|---|---:|---|---|
| `Tilanthi/ASTRA-dev` | `b70bf16be847b12e270081b5f1fb7ca8bf7636ec`; Beast fork PR `thebeastagi/ASTRA-dev#1` at `5412a505f8eb2aa7464f7b05270f23df11cee409` | No root license found by GitHub metadata or root-file inspection | No code copied. High-level concepts only from authorized ASTRA planning deliverables. |
| `Tilanthi/ASTRA` | `378bb72c7b34f2ebcf588fbe673eb3a5d9cc4a48` | No root license found | No code copied. |
| `Tilanthi/GEODISC` | `30c6080fa52cf4454d2016c8671dc85116b5e9d9` | No root license found | No code copied. |
| `Tilanthi/BIODISC` | `6b1636d83d78ae7868bf96677c05b944c66f8e4d` | No root license found | No code copied. |
| `Tilanthi/SLATE` | `d7cd6c1b3968f334acc6b777f670e6f7554db7d2` | MIT License, copyright 2026 SLATE Project Contributors | Compatible, but Phase 0 still copied no SLATE source; concepts remain adapter-calibration background. |
| `/shared/deliverables/astra-implementation-plan-2026-07-17/` | local deliverable | Beast-authored plan | Used as requirements/design input. |
| `/shared/deliverables/astra-phase0-execution-2026-07-17/` | local deliverable | Beast-authored execution report | Used for license/drift/validation context. |

## Borrowed concepts, not files

- Domain adapter boundary.
- L0→L4 evidence ladder.
- Cross-domain transfer iron rule: never carry confidence unchanged across domains.
- Bounded background-discovery queue/daemon concept.
- Synthetic adapters to prove orchestration without scientific claims.

These are implemented with new names, new code, and new tests in this repository.

## Notices preserved

No third-party source code is included. Therefore no third-party notices are embedded in source. The SLATE MIT text was inspected but not copied into this repository because no SLATE source was reused.

## Known licence gate

ASTRA-dev/ASTRA/GEODISC/BIODISC lack explicit licences at inspected refs. Any future kernel extraction from those repositories requires a signed/committed compatible licence or separate written permission. Until then: architecture-only references or clean-room reimplementation only.
