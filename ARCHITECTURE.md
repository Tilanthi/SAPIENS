# SAPIENS Architecture

**SAPIENS** is an experimental, traceable scientific-discovery workflow platform. Despite
the aspirational acronym it is **not** AGI/ASI/superintelligence and claims **no** scientific
discovery; the CLI reports `"scientific_discoveries_claimed": 0` until a human signs an L4
gate on a real, externally-reproduced candidate. Everything below is plumbing that makes a
future discovery *trustworthy*; it does not itself discover.

## Phase status

| Phase | Capability | Status |
|-------|------------|--------|
| 0 | Trust substrate (models, ledger, kernel, bridge, bounded daemon) | ✅ |
| 1 v1 | Trust-tiered adapter registry (retires the `synthetic_only` gate) | ✅ |
| 1 v2 | Signed ledger checkpoints + subprocess sandbox + picklable records | ✅ |
| 2 | Real validation statistics (CIs, p-values, FDR, holdouts, gates) | ✅ |
| 3 | Structured L3 review panels (role reviewers + disagreement gate) | ✅ |
| 4 | Real-data connectors (SDSS photoz + classification) + autonomous discovery driver | ✅ |
| 5 | Human L4-gate mechanism + reproduction bundles | ✅ (mechanism; external reproduction is externally gated) |

## Package map (`src/sapiens/`)

Grouped by layer:

**Core models & contracts**
- `models.py` — immutable `Candidate`, `Evidence`, `AdapterManifest`, `EvidenceLevel` (now picklable for subprocess sandboxing)
- `adapter.py` — `DomainAdapter` protocol + `validate_adapter` (strict synthetic-only **backstop**)
- `budget.py` — cooperative `ExecutionContext` (step/time budgets), `BudgetExceeded`, `Preempted`

**Trust & admission (Phase 1)**
- `trust.py` — `TrustTier` (SYNTHETIC / VETTED), `AdapterRegistry`; a non-synthetic adapter is admitted only at VETTED tier with an approver + declared capabilities
- `sandbox.py` — `sandboxed_validate`: runs an adapter's `validate` in a spawned child process with hard termination on timeout

**Evidence & promotion spine**
- `ledger.py` — append-only hash-chained evidence ledger; L0→L4 transition guard; `checkpoint(signer)` integrity anchors
- `kernel.py` — `DiscoveryKernel`: `register`, `validate_next` (autonomous, caps at **L3**), `promote_to_l4` (human gate)
- `bridge.py` — cross-domain `transfer`; always resets the target candidate to **L0**

**Real statistics (Phase 2)**
- `validation.py` — regularized incomplete beta; exact Clopper–Pearson `proportion_ci`; `pearson` (r + p-value); Benjamini–Hochberg `multiple_comparison`; leakage-safe `holdout_split`; `PassPolicy` + `evaluate` gate

**Review (Phase 3)**
- `review.py` — `Objection`, `ReviewOpinion`, `Reviewer` protocol; `StatisticianReviewer`, `MethodologistReviewer`, `DevilsAdvocateReviewer`; `ReviewPanel` (unanimous-endorsement disagreement gate, multi-round); `review_evidence`; `catch_rate`

**Autonomy & external review**
- `queue.py` — bounded SQLite `WorkQueue` (leases, idempotency, retries)
- `daemon.py` — `DiscoveryDaemon.run_bounded` (leases jobs, runs handlers under budgets)
- `discovery.py` — `DiscoveryDriver`: proposes candidates, enqueues one climb job each, runs them through the daemon; `DiscoveryReport`
- `external_review.py` — `HumanSignature`, `ReproductionBundle`, `build_reproduction_bundle`

**Adapters** (`adapters/`) — synthetic demos + real connectors
- `linear.py`, `threshold.py`, `photometry.py` — synthetic Phase-0 plumbing adapters
- `regression.py` — synthetic adapter that uses *real* held-out statistics (not rigged)
- `sdss_photoz.py`, `sdss_classification.py` — **real-data** connectors (read ASTRA-dev's SDSS caches read-only); VETTED tier

**Dependency rule:** core modules never import `sapiens.adapters`; adapter *instances* are injected (`tests/test_boundaries.py` enforces this).

## The evidence ladder (the spine)

Every belief transition is an append-only, hash-chained ledger event. Candidates climb one
rung at a time through explicit gates:

- **L0 Candidate** — traceable only; not believed.
- **L1 Internal** — passed internal/synthetic consistency (`validate_next`, autonomous).
- **L2 Replication** — reproduced on independent/held-out evidence (autonomous).
- **L3 Review** — passed structured review (autonomous max; the `ReviewPanel` or the adapter's review stage).
- **L4 External-ready** — **requires an explicit human gate** (`kernel.promote_to_l4`, reviewer non-empty). Autonomous promotion to L4 is impossible.

The ledger's transition guard enforces, per promotion: exactly one rung, passing
candidate-local evidence of the required kind (`internal`/`replication`/`review`/`external`),
and `human_gate=True` for L4.

## Key invariants (non-negotiable)

1. **Honesty in claims** — no AGI/superintelligence claims; `scientific_discoveries_claimed` stays 0 until a human signs L4.
2. **Clean-room boundary** — no code copied from ASTRA-dev / ASTRA / GEODISC / BIODISC / SLATE without licence + owner permission.
3. **ASTRA-dev is permanently read-only** — connectors read its bundled data at runtime; the ASTRA-dev folder is never modified.
4. **Boundary discipline** — core never imports adapters; only the kernel promotes; cross-domain transfer resets to L0; the autonomous kernel caps at L3.
5. **Bounded autonomy** — all background work goes through `run_bounded` (budgets, leases, preemption); VETTED adapters may be run under the subprocess sandbox.

## End-to-end discovery flow

```
adapter.propose  ->  kernel.register (L0)  ->  kernel.validate_next x{internal, replication, review}  ->  L3
                                  (autonomous, bounded daemon may drive this via DiscoveryDriver)
L3  ->  build_reproduction_bundle  ->  human examines  ->  kernel.promote_to_l4(reviewer, passed)  ->  L4
```

Statistics produced by `sapiens.validation` (real CIs / p-values / FDR) feed the gates and
the review panel; nothing is a planted score except the Phase-0 synthetic plumbing adapters,
which exist only to exercise the pipeline.

## Real-data connectors (Phase 4)

`SDSSPhotozAdapter` and `SDSSClassificationAdapter` load ASTRA-dev's bundled SDSS caches
(`photoz_sdss_cache.csv`, `sdss_class_cache.csv`) **read-only** at runtime and validate
candidates with real held-out statistics (Pearson r + p-value; learned-threshold accuracy
with a Clopper–Pearson CI). They are non-synthetic, admitted at VETTED tier. On real SDSS
data the autonomous driver climbs genuine candidates to L3 (e.g. u-band ↔ redshift r≈0.76;
r-i star/galaxy separation ≈0.78 accuracy) — real, validated, but **not** claimed
discoveries.

## Integrity & isolation

- The ledger is hash-chained and tamper-evident; `checkpoint(signer)` anchors the tip
  (provenance, not cryptography — external anchoring is a roadmap item).
- `sandboxed_validate` isolates a VETTED adapter's `validate` in a spawned process with a
  wall-clock timeout and hard termination; full cgroup/memory isolation is a roadmap item.
