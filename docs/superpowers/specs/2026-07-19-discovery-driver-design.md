# Discovery Driver — Design

- **Date:** 2026-07-19
- **Status:** Approved in brainstorm; pending implementation plan
- **Phase:** SAPIENS Phase 0 (synthetic-only)
- **Branch:** `feat/discovery-driver`

## Purpose

Turn the existing `DiscoveryDaemon` from an empty loop into a working autonomous-discovery
engine. When triggered, the driver generates candidate hypotheses (via each adapter's
`propose`), registers them at L0, and climbs each one up the evidence ladder as far as the
evidence allows — capped at L3. Candidates reaching L3 are reported as **"awaiting human
review"** (L4 stays human-gated). This is the missing *Layer 3* — the autonomous discovery
driver — sitting between the trust substrate (Layer 1, built) and real expertise adapters
(Layer 2, Phase 4).

## Goals

- Make `DiscoveryDaemon.run_bounded` do real discovery work through registered handlers.
- Autonomous propose → validate → promote loop, bounded by budgets.
- Adapter-agnostic: drives any injected `DomainAdapter`.
- Deterministic + seeded, so every run replays against the hash-chained ledger.
- Fully inside Phase 0: synthetic-only, no discovery claims, core-boundary respected.

## Non-goals (Phase 0)

- Real domain expertise / real data (Phase 4).
- L4 autonomous promotion (always human-gated).
- Persistent / periodic background scheduling (Phase 0 has in-process preemption only).
- Dynamic code loading or shell execution from queue payloads (forbidden by the daemon).
- Per-stage job granularity with re-enqueueing (kept simple: one job per candidate).

## Architecture

The driver is the **brain** (decides *what* to discover); the daemon is the **bounded
executor** (does the climbing). The driver proposes candidates, registers them at L0,
enqueues one "climb" job per candidate, and lets `DiscoveryDaemon.run_bounded` process the
queue under step/time budgets. Each job's handler calls `kernel.validate_next` repeatedly
until the candidate fails or reaches L3.

```
plan():  adapter.propose -> kernel.register(L0) -> queue.enqueue(climb job)
run():   handlers{adapter_name -> climb_handler} -> DiscoveryDaemon.run_bounded
         -> read final level per candidate from ledger -> DiscoveryReport
climb:   while level < L3: validate_next; stop on no-promote or budget exhaustion
```

## Components — `src/sapiens/discovery.py` (new, core module)

### `DiscoveryDriver`

Dependencies (all injected; core never imports `sapiens.adapters`):

- `adapters: dict[str, DomainAdapter]`
- `queue: WorkQueue`
- `kernel: DiscoveryKernel`
- `seed: int`

Methods:

- `plan(*, limit_per_adapter: int = 2) -> int`
  For each adapter: `propose(seed, limit)` → `kernel.register(candidate)` (enters ledger
  at L0) → `queue.enqueue(job_id=candidate_id, kind=adapter.manifest.name,
  payload={"candidate_id": cid, "seed": seed}, idempotency_key=candidate_id)`. Returns the
  total number of candidates proposed. Tracks `candidates_by_id` for the handlers.

- `run(*, worker: str, max_jobs: int, max_seconds: float, steps_per_job: int) -> DiscoveryReport`
  Must follow a `plan()` call, which populates `candidates_by_id`. Builds
  `handlers = {adapter.manifest.name: make_climb_handler(kernel, adapter,
  candidates_by_id, seed)}`, constructs `DiscoveryDaemon(queue, handlers)`, calls
  `run_bounded(...)`, then reads `kernel.ledger.state(cid).level` for each tracked
  candidate and assembles the report.

### `make_climb_handler(kernel, adapter, candidates_by_id, seed) -> Handler`

Returns a closure matching `Callable[[Job, ExecutionContext], dict]`. Behaviour:

1. `candidate = candidates_by_id[job.payload["candidate_id"]]`.
2. `level = kernel.ledger.state(candidate.candidate_id).level`.
3. While `level < EvidenceLevel.L3`:
   - `context.checkpoint()`;
   - `new = kernel.validate_next(adapter, candidate, seed=seed, context=context)`;
   - if `new == level` (no promotion) → break; else `level = new`.
4. Wrap steps 2–3 in try/except: on an unexpected exception, return the current level plus
   an `error` string so the daemon loop survives. `Preempted` and `BudgetExceeded` are
   **not** caught — they propagate to the daemon, which handles them (release + count).
5. Return `{"candidate_id": cid, "level": level.name}`.

### `DiscoveryReport` (frozen dataclass)

- `proposed: int`
- `reached_l3: tuple[str, ...]` — candidate ids awaiting human review
- `reached_l2: int`
- `reached_l1: int`
- `stayed_l0: int`
- `exhausted: int` (mirrored from the daemon report)
- `ledger_verified: bool`
- `scientific_discoveries_claimed: int` — constant `0` (honesty invariant)

## Error handling

- **Budget exhaustion mid-climb** — the candidate keeps any already-promoted level
  (promotions are persisted as separate ledger appends); counted in
  `DaemonReport.exhausted`; not re-enqueued by the driver. (The daemon itself releases the
  job back to the queue and retries up to `max_attempts`, then marks it dead — existing,
  tested behaviour, unchanged here.)
- **Adapter raises unexpectedly** — the climb handler catches it, returns the candidate at
  its last level with an `error` field; the daemon loop continues.
- **Idempotency** — `candidate_id` is the job's idempotency key, so re-planning the same
  candidates is a no-op (the queue dedupes).
- **Empty plan** — daemon returns `empty=True`; report shows `proposed=0`.

## Testing — `tests/test_discovery_driver.py`

1. `test_driver_climbs_true_candidate_to_l3` — linear adapter, true candidate → reaches
   L3; `reached_l3` non-empty; `ledger_verified is True`;
   `scientific_discoveries_claimed == 0`.
2. `test_driver_wrong_candidate_stays_l0` — wrong candidate → counted in `stayed_l0`.
3. `test_driver_multiple_adapters` — linear + threshold (+ photometry, if available on the
   base branch) each climb independently; report counts are internally consistent.
4. `test_driver_respects_budget` — tiny `steps_per_job` → some candidates exhausted,
   reported honestly, no crash.
5. `test_driver_adapter_error_is_contained` — an adapter that raises inside `validate`
   does not crash the daemon; the candidate is reported stuck and the run continues.
6. `test_run_discovery_helper` — the CLI helper returns a well-formed `DiscoveryReport`.

The existing `test_core_does_not_import_adapters` covers `discovery.py` automatically (it
globs `src/sapiens/*.py`).

## Phase 0 invariants

- `discovery.py` imports only core modules (`.adapter .kernel .ledger .queue .daemon
  .budget .models`); adapter **instances** are injected, exactly as `cli.py` already does.
- All adapters pass `validate_adapter` (synthetic-only) — also enforced by
  `kernel.validate_next`.
- No discovery is claimed: L3 = "awaiting human review"; `scientific_discoveries_claimed`
  is constant 0; L4 stays human-gated.
- All work is bounded through `DiscoveryDaemon.run_bounded`.

## CLI

Add a subcommand:

```
python -m sapiens.cli discover [--seed N] [--max-jobs M] [--max-seconds S] [--steps-per-job K]
```

It wires the synthetic adapters, runs the driver, and prints the `DiscoveryReport` as JSON.
Default `python -m sapiens.cli` (no subcommand) keeps running the existing demo unchanged;
`run_demo()` and its test are untouched (backward compatible).

## Dependencies & sequencing

The multi-adapter test references the photometry adapter, which currently lives only on
`feat/synthetic-photometry-adapter` (PR #2, open upstream). Two resolutions at
implementation time:

- **(recommended)** merge `feat/synthetic-photometry-adapter` into the fork's `main` first
  (the user owns the `Tilanthi` fork; merging into the fork does not affect upstream PR
  #2), then base `feat/discovery-driver` on that updated main so all three adapters are
  available;
- or base on current main and scope the multi-adapter test to linear + threshold, adding
  photometry once PR #2 lands upstream.

Decide when writing the implementation plan.

## Future work (out of scope)

- Per-stage job granularity + re-enqueueing (finer scheduling).
- Persistent / periodic background execution (needs OS-level isolation — roadmap).
- Real adapters (Phase 4) and a real "Eureka" surfacing workflow at the L4 human gate.
