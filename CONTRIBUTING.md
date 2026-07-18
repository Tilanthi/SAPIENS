# Contributing to SAPIENS

Thanks for your interest. SAPIENS is an experimental research platform with a
deliberately conservative epistemic design — contributions are welcome, but a
few invariants are non-negotiable.

## Ground rules (hard invariants)

1. **Honesty in claims.** No AGI/ASI/superintelligence claims, no
   "discovery achieved" claims. Phase 0 is synthetic-only; the CLI must keep
   reporting `"scientific_discoveries_claimed": 0` until real, externally
   validated results exist (Phase 5, human-gated).
2. **Clean-room boundary.** Do not copy code from ASTRA-dev, ASTRA, GEODISC,
   BIODISC, or SLATE (or any repo without a compatible licence). Reuse is
   gated to Phase 1+ with explicit owner permission. See `PROVENANCE.md`.
3. **Boundary discipline.** Core modules (`sapiens/*.py`) must not import
   `sapiens.adapters`. Only the kernel promotes candidates; promotions go
   through the ledger's transition guard; the bridge always resets transferred
   candidates to L0. Tests enforce these — keep them passing.
4. **No secrets.** Never commit credentials, tokens, or `.env` files.

## Workflow

- Fork / branch from `main`, open a PR. CI must be green
  (ruff + pytest on Python 3.10/3.11/3.12).
- Keep the runtime standard-library only unless a dependency is discussed
  first in an issue.
- New behaviour needs tests; changes to ledger/kernel/bridge semantics need
  updates to `ARCHITECTURE.md` and `VALIDATION.md`.

## Local dev

```bash
python -m pip install -e ".[dev]"
ruff check src tests
pytest
python -m sapiens.cli
```

## Questions / proposals

Open a GitHub issue. For anything touching the legal/licence boundary or the
roadmap phases, expect review by the maintainers (The Beast / ASTRA HQ).
