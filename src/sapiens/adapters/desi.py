"""DESI connector (Stage E — independent replication set, 10x SDSS depth).

DESI (Dark Energy Spectroscopic Instrument) provides millions of redshifts at
10x SDSS depth — the ideal independent replication set for photo-z candidates.
Public FITS from data.desi.lbl.gov. This connector reads DESI FITS files (via
astropy, same as Mopra) and exposes the same row-based interface as SDSS.
"""

from __future__ import annotations

from dataclasses import dataclass

from sapiens.budget import ExecutionContext
from sapiens.models import AdapterManifest, Candidate, Evidence
from sapiens.validation import PassPolicy, evaluate, holdout_split, pearson


@dataclass(frozen=True)
class DesiRow:
    u: float
    g: float
    r: float
    i: float
    z_mag: float
    z_spec: float


class DesiPhotozAdapter:
    """DESI photometric-redshift connector (independent replication of SDSS photo-z)."""

    manifest = AdapterManifest(
        name="desi-photoz",
        version="1.0",
        domain="desi-photoz",
        vocabulary=("u", "g", "r", "i", "z", "z_spec", "redshift"),
        synthetic_only=False,
    )
    _POLICY = PassPolicy(min_effect=0.5, max_pvalue=0.05)

    def __init__(self, rows: list[DesiRow]) -> None:
        if len(rows) < 10:
            raise ValueError("need at least 10 rows")
        self._rows: tuple[DesiRow, ...] = tuple(rows)

    @classmethod
    def from_fits(cls, path) -> DesiPhotozAdapter:
        """Load DESI redshift catalog from a FITS file (requires astropy)."""
        import numpy as np
        from astropy.io import fits

        with fits.open(path) as hdul:
            data = np.asarray(hdul[1].data)
        rows = []
        for rec in data:
            try:
                rows.append(
                    DesiRow(
                        u=float(rec["FLUX_G"]),  # DESI uses flux; simplified
                        g=float(rec["FLUX_R"]),
                        r=float(rec["FLUX_I"]),
                        i=float(rec["FLUX_Z"]),
                        z_mag=float(rec["FLUX_G"]),
                        z_spec=float(rec["Z"]),
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        if len(rows) < 10:
            raise ValueError(f"insufficient usable rows in {path}")
        return cls(rows)

    def propose(self, *, seed: int, limit: int) -> tuple[Candidate, ...]:
        from hashlib import sha256

        def _id(*p):
            return sha256("|".join(map(str, p)).encode()).hexdigest()[:20]

        if limit <= 0:
            return ()
        return (
            Candidate(
                _id(self.manifest.name, seed, "u"),
                self.manifest.domain,
                "u-band flux correlates with spectroscopic redshift in DESI",
                {"relation": "correlation", "predictor": "u"},
                source_adapter=self.manifest.name,
            ),
        )[:limit]

    def validate(
        self, candidate: Candidate, *, stage: str, seed: int, context: ExecutionContext
    ) -> tuple[Evidence, ...]:
        from hashlib import sha256

        def _id(*p):
            return sha256("|".join(map(str, p)).encode()).hexdigest()[:20]

        context.checkpoint()
        predictor = str(candidate.parameters.get("predictor", "u"))
        split = holdout_split(len(self._rows), train_fraction=0.5, seed=seed)
        xs = [getattr(self._rows[t], predictor) for t in split.test]
        ys = [self._rows[t].z_spec for t in split.test]
        result = pearson(xs, ys)
        decision = evaluate(point=result.r, pvalue=result.pvalue, policy=self._POLICY)
        score = max(0.0, min(1.0, result.r))
        return (
            Evidence(
                _id(candidate.candidate_id, stage, seed),
                candidate.candidate_id,
                stage,
                decision.passed,
                f"desi-{stage}-v1",
                "desi-dr-heldout",
                seed,
                score,
                {"r": result.r, "pvalue": result.pvalue, "n_test": len(split.test)},
            ),
        )

    def import_structure(self, structure, *, candidate_id):
        return Candidate(
            candidate_id, self.manifest.domain, "transferred structure on DESI data",
            {"relation": "correlation", "predictor": "u"},
            source_adapter=self.manifest.name,
        )
