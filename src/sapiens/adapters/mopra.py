"""MOPRA SgrB2 molecular-line connector (Phase 4 — real FITS data).

Connects read-only to Mopra molecular-line spectral cubes (e.g. 13CO, HCO+ of the SgrB2
star-forming region) via astropy/numpy. The heavy dependencies are isolated to FITS
loading (``from_fits``); validation itself is pure-stdlib, reusing SAPIENS's
``holdout_split`` + ``pearson`` + ``evaluate`` so the gate is the same real-statistics
framework as the SDSS connectors.

Candidate: the line emission is spatially concentrated (centrally peaked), which real
molecular cores are. The null candidate is correlation with the RA axis (no physical
reason for a gradient). Non-synthetic -> VETTED tier.
"""

from __future__ import annotations

from hashlib import sha256

from sapiens.budget import ExecutionContext
from sapiens.models import AdapterManifest, Candidate, Evidence
from sapiens.validation import PassPolicy, evaluate, holdout_split, pearson

_POLICY = PassPolicy(min_effect=0.30, max_pvalue=0.05)


def _identifier(*parts: object) -> str:
    return sha256("|".join(map(str, parts)).encode()).hexdigest()[:20]


class MopraMolecularAdapter:
    def __init__(
        self,
        *,
        molecule: str,
        distances: list[float],
        intensities: list[float],
        x_indices: list[float],
    ) -> None:
        if len(intensities) < 20:
            raise ValueError("need at least 20 bright pixels for a held-out test")
        self._molecule = molecule
        self._distances = list(distances)
        self._intensities = list(intensities)
        self._x_indices = list(x_indices)

    @classmethod
    def from_fits(cls, path, *, molecule: str) -> MopraMolecularAdapter:
        """Load a Mopra cube read-only; compute moment-0 + bright-pixel geometry."""
        import numpy as np  # heavy dep, isolated to FITS loading
        from astropy.io import fits

        with fits.open(path) as hdul:
            data = np.asarray(hdul[0].data, dtype=float)
        moment0 = np.nansum(data, axis=0)
        ny, nx = moment0.shape
        yy, xx = np.mgrid[0:ny, 0:nx]
        peak_y, peak_x = np.unravel_index(int(np.nanargmax(moment0)), moment0.shape)
        dist = np.sqrt((yy - peak_y) ** 2 + (xx - peak_x) ** 2).ravel()
        intensity = moment0.ravel()
        x_index = xx.ravel()
        mask = np.isfinite(intensity) & (intensity > np.nanpercentile(intensity, 50))
        return cls(
            molecule=molecule,
            distances=dist[mask].tolist(),
            intensities=intensity[mask].tolist(),
            x_indices=x_index[mask].tolist(),
        )

    @property
    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            name=f"mopra-{self._molecule.lower()}",
            version="1.0",
            domain=f"mopra-{self._molecule.lower()}",
            vocabulary=("velocity", "ra", "dec", "temperature", "molecule"),
            synthetic_only=False,
        )

    def propose(self, *, seed: int, limit: int) -> tuple[Candidate, ...]:
        if limit <= 0:
            return ()
        candidates = (
            Candidate(
                _identifier(self.manifest.name, seed, "concentration"),
                self.manifest.domain,
                f"{self._molecule} emission is spatially concentrated (centrally peaked)",
                {"claim_type": "concentration"},
                source_adapter=self.manifest.name,
            ),
            Candidate(
                _identifier(self.manifest.name, seed, "ra-gradient"),
                self.manifest.domain,
                f"{self._molecule} emission correlates with right ascension",
                {"claim_type": "ra-gradient"},
                source_adapter=self.manifest.name,
            ),
        )
        return candidates[:limit]

    def _heldout_stat(self, claim_type: str, *, seed: int) -> tuple[float, float, int]:
        split = holdout_split(len(self._intensities), train_fraction=0.5, seed=seed)
        intensities = [self._intensities[i] for i in split.test]
        if claim_type == "concentration":
            xs = [self._distances[i] for i in split.test]
            result = pearson(xs, intensities)
            # concentration score (positive => centrally peaked)
            return -result.r, result.pvalue, len(split.test)
        xs = [self._x_indices[i] for i in split.test]
        result = pearson(xs, intensities)
        return abs(result.r), result.pvalue, len(split.test)

    def validate(
        self, candidate: Candidate, *, stage: str, seed: int, context: ExecutionContext
    ) -> tuple[Evidence, ...]:
        context.checkpoint()
        claim_type = str(candidate.parameters.get("claim_type", "concentration"))
        data_seed = seed + (6000 if stage != "internal" else 0)
        runs = 3 if stage == "review" else 1
        points: list[float] = []
        pvalues: list[float] = []
        n_pixels = 0
        for offset in range(runs):
            context.checkpoint()
            point, pvalue, n_pixels = self._heldout_stat(claim_type, seed=data_seed + offset * 17)
            points.append(point)
            pvalues.append(pvalue)
        point = min(points)
        pvalue = max(pvalues)
        decision = evaluate(point=point, pvalue=pvalue, policy=_POLICY)
        score = max(0.0, min(1.0, point))
        return (
            Evidence(
                _identifier(candidate.candidate_id, stage, seed),
                candidate.candidate_id,
                stage,
                decision.passed,
                f"mopra-{stage}-v1",
                "mopra-cube-heldout",
                seed,
                score,
                {
                    "claim_type": claim_type,
                    "stat": point,
                    "pvalue": pvalue,
                    "n_pixels": n_pixels,
                    "molecule": self._molecule,
                    "data": "Mopra/SgrB2 FITS cube",
                    "reasons": list(decision.reasons),
                },
            ),
        )

    def import_structure(self, structure: dict[str, object], *, candidate_id: str) -> Candidate:
        return Candidate(
            candidate_id,
            self.manifest.domain,
            f"test a transferred structure against {self._molecule} emission",
            {"claim_type": "concentration"},
            parent_id=str(structure.get("_source_candidate_id", "")) or None,
            source_adapter=self.manifest.name,
        )
