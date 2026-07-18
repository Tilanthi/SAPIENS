# Roadmap

## Phase 0 — shipped in this PR

- Standalone SAPIENS repository.
- Clean-room core package and docs.
- Synthetic integrated orchestration.
- Tests and Python matrix CI.

## Phase 1 — legal/licence gate and adapter hardening

- Obtain explicit licences/permissions for any ASTRA-family code reuse before extraction.
- Replace synthetic-only adapter gate with a trust-tiered adapter registry.
- Add subprocess isolation and OS-level resource limits for untrusted adapters.
- Add signed ledger checkpoints or external anchoring.

## Phase 2 — validation framework v1

- Expand L0→L2 automated gates with statistical sanity checks, holdout protocols, and explicit leakage controls.
- Add seeded-bias fixtures and calibration reports.
- Add confidence aggregation only after calibration data exists; do not invent precision.

## Phase 3 — structured L3 review panels

- Role-specialized reviewer schemas: statistician, domain theorist, methodologist, devil's advocate.
- Multi-round reports, objection tracking, disagreement gates.
- Catch-rate scoring on seeded known-bad and known-good candidates.

## Phase 4 — real domain adapters

- ASTRA/GEODISC/BIODISC/SLATE adapters only after licence and owner review.
- Domain-specific validators remain sandboxed behind adapters.
- Cross-domain method transfer enters target domain at L0 every time.

## Phase 5 — external-review workflows

- Human L4 gates.
- Reproduction bundles.
- Prediction tracking and demotion on contradicting evidence.
