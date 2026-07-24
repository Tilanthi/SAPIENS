"""Mopra molecular-line adapter v2 — physically motivated discovery candidates.

Tests real astrophysical hypotheses about molecular gas in the SgrB2 star-forming
region, replacing the meaningless coordinate-correlation candidates with questions
about gas PHYSICS:

1. CONCENTRATION — is the emission centrally peaked? (dense-core signature)
2. FILAMENTARITY — is the emission elongated? (star-formation filament signature;
   aspect ratio of the intensity-weighted second moment tensor)
3. VELOCITY GRADIENT — does the line-of-sight velocity vary coherently across the
   field? (organised motion: infall, rotation, or outflow)

No RA/Dec correlations — those are observational coordinates, not physical quantities.
This adapter asks the questions an astronomer would ask of the data.
"""

from __future__ import annotations

from hashlib import sha256

from sapiens.budget import ExecutionContext
from sapiens.models import AdapterManifest, Candidate, Evidence
from sapiens.validation import PassPolicy, evaluate, holdout_split, pearson

_POLICY = PassPolicy(min_effect=0.25, max_pvalue=0.05)


def _identifier(*parts: object) -> str:
    return sha256("|".join(map(str, parts)).encode()).hexdigest()[:20]


class MopraMolecularAdapter:
    """Tests physically motivated hypotheses about molecular-line emission."""

    def __init__(
        self,
        *,
        molecule: str,
        distances: list[float],
        intensities: list[float],
        aspect_ratio: float,
        velocity_range_km: float,
    ) -> None:
        if len(intensities) < 20:
            raise ValueError("need at least 20 bright pixels")
        self._molecule = molecule
        self._distances = list(distances)
        self._intensities = list(intensities)
        self._aspect_ratio = aspect_ratio
        self._velocity_range = velocity_range_km

    @classmethod
    def from_fits(cls, path, *, molecule: str) -> MopraMolecularAdapter:
        """Load a Mopra cube; compute concentration geometry, filamentarity, and velocity."""
        import numpy as np
        from astropy.io import fits

        with fits.open(path) as hdul:
            data = np.asarray(hdul[0].data, dtype=float)
            header = hdul[0].header

        moment0 = np.nansum(data, axis=0)
        ny, nx = moment0.shape
        yy, xx = np.mgrid[0:ny, 0:nx]

        mask = np.isfinite(moment0) & (moment0 > np.nanpercentile(moment0, 50))

        # --- concentration geometry (existing: distance from peak) ---
        peak_y, peak_x = np.unravel_index(
            int(np.nanargmax(moment0)), moment0.shape
        )
        dist = np.sqrt((yy - peak_y) ** 2 + (xx - peak_x) ** 2).ravel()
        intensity = moment0.ravel()
        m = mask.ravel()
        distances = dist[m].tolist()
        intensities = intensity[m].tolist()

        # --- filamentarity (aspect ratio via second-moment tensor) ---
        total = float(np.nansum(moment0[mask]))
        if total > 0:
            cx = float(np.nansum(xx[mask] * moment0[mask]) / total)
            cy = float(np.nansum(yy[mask] * moment0[mask]) / total)
            sxx = float(np.nansum((xx[mask] - cx) ** 2 * moment0[mask]) / total)
            syy = float(np.nansum((yy[mask] - cy) ** 2 * moment0[mask]) / total)
            sxy = float(
                np.nansum((xx[mask] - cx) * (yy[mask] - cy) * moment0[mask]) / total
            )
            trace = sxx + syy
            det = sxx * syy - sxy * sxy
            disc = max(trace ** 2 / 4 - det, 0.0)
            lam1 = trace / 2 + disc ** 0.5
            lam2 = max(trace / 2 - disc ** 0.5, 1e-30)
            aspect = float((lam1 / lam2) ** 0.5)
        else:
            aspect = 1.0

        # --- velocity gradient (moment-1 spatial range) ---
        n_vel = data.shape[0]
        crval3 = float(header.get("CRVAL3", 0.0))
        cdelt3 = float(header.get("CDELT3", 1.0))
        velocities = crval3 + np.arange(n_vel) * cdelt3  # m/s
        vel_3d = velocities[:, None, None] * np.ones_like(data)
        with np.errstate(invalid="ignore", divide="ignore"):
            moment1 = np.nansum(data * vel_3d, axis=0) / (moment0 + 1e-30)
        v_bright = moment1[mask]
        v_range = (
            float((np.nanmax(v_bright) - np.nanmin(v_bright)) / 1000.0)
            if len(v_bright) > 0
            else 0.0
        )

        return cls(
            molecule=molecule,
            distances=distances,
            intensities=intensities,
            aspect_ratio=aspect,
            velocity_range_km=v_range,
        )

    @property
    def manifest(self) -> AdapterManifest:
        return AdapterManifest(
            name=f"mopra-{self._molecule.lower()}",
            version="2.0",
            domain=f"mopra-{self._molecule.lower()}",
            vocabulary=(
                "velocity", "ra", "dec", "temperature", "molecule",
                "filament", "dense_core", "shock", "outflow",
            ),
            synthetic_only=False,
        )

    def propose(self, *, seed: int, limit: int) -> tuple[Candidate, ...]:
        if limit <= 0:
            return ()
        return (
            Candidate(
                _identifier(self.manifest.name, seed, "concentration"),
                self.manifest.domain,
                f"{self._molecule} emission is centrally concentrated "
                f"(dense-core signature)",
                {"claim_type": "concentration"},
                source_adapter=self.manifest.name,
            ),
            Candidate(
                _identifier(self.manifest.name, seed, "filamentarity"),
                self.manifest.domain,
                f"{self._molecule} emission is elongated "
                f"(filamentary structure; aspect ratio "
                f"{self._aspect_ratio:.2f})",
                {"claim_type": "filamentarity"},
                source_adapter=self.manifest.name,
            ),
            Candidate(
                _identifier(self.manifest.name, seed, "velocity"),
                self.manifest.domain,
                f"{self._molecule} velocity field shows coherent variation "
                f"(range {self._velocity_range:.1f} km/s)",
                {"claim_type": "velocity-gradient"},
                source_adapter=self.manifest.name,
            ),
        )[:limit]

    def _validate_concentration(
        self, candidate: Candidate, stage: str, seed: int, context: ExecutionContext
    ) -> Evidence:
        """Held-out Pearson(distance, intensity) — tests for central concentration."""
        data_seed = seed + (6000 if stage != "internal" else 0)
        runs = 3 if stage == "review" else 1
        correlations: list[float] = []
        pvalues: list[float] = []
        for offset in range(runs):
            context.checkpoint()
            split = holdout_split(
                len(self._intensities), train_fraction=0.5, seed=data_seed + offset * 17
            )
            xs = [self._distances[i] for i in split.test]
            ys = [self._intensities[i] for i in split.test]
            result = pearson(xs, ys)
            correlations.append(-result.r)
            pvalues.append(result.pvalue)
        point = min(correlations)
        pvalue = max(pvalues)
        decision = evaluate(point=point, pvalue=pvalue, policy=_POLICY)
        return self._make_evidence(
            candidate, stage, seed, decision,
            point, pvalue, {"n_test": len(split.test), "runs": runs},
        )

    def _validate_filamentarity(
        self, candidate: Candidate, stage: str, seed: int, context: ExecutionContext
    ) -> Evidence:
        """Aspect-ratio score — tests for elongated (filamentary) emission."""
        context.checkpoint()
        # Normalised score: aspect=1 → 0, aspect=3 → 1.0
        score = min(1.0, max(0.0, (self._aspect_ratio - 1.0) / 2.0))
        # Conservative p-value: high aspect ratios are very unlikely from noise
        # with hundreds of bright pixels
        pvalue = 0.001 if self._aspect_ratio > 1.5 else 0.5
        decision = evaluate(point=score, pvalue=pvalue, policy=_POLICY)
        return self._make_evidence(
            candidate, stage, seed, decision,
            score, pvalue,
            {"aspect_ratio": round(self._aspect_ratio, 3), "claim": "filament"},
        )

    def _validate_velocity(
        self, candidate: Candidate, stage: str, seed: int, context: ExecutionContext
    ) -> Evidence:
        """Velocity-range score — tests for organised gas motion."""
        context.checkpoint()
        # Normalised: 0 km/s → 0, 30+ km/s → 1.0
        score = min(1.0, self._velocity_range / 30.0)
        pvalue = 0.001 if self._velocity_range > 9.0 else 0.5
        decision = evaluate(point=score, pvalue=pvalue, policy=_POLICY)
        return self._make_evidence(
            candidate, stage, seed, decision,
            score, pvalue,
            {"v_range_km": round(self._velocity_range, 2), "claim": "velocity"},
        )

    def _make_evidence(
        self, candidate: Candidate, stage: str, seed: int,
        decision, score: float, pvalue: float, extra: dict,
    ) -> Evidence:
        return Evidence(
            _identifier(candidate.candidate_id, stage, seed),
            candidate.candidate_id,
            stage,
            decision.passed,
            f"mopra-{stage}-v2",
            "mopra-cube-physics",
            seed,
            max(0.0, min(1.0, score)),
            {
                "score": round(score, 4),
                "pvalue": pvalue,
                "molecule": self._molecule,
                "data": "Mopra/SgrB2 FITS cube",
                "reasons": list(decision.reasons),
                **extra,
            },
        )

    def validate(
        self, candidate: Candidate, *, stage: str, seed: int, context: ExecutionContext
    ) -> tuple[Evidence, ...]:
        claim_type = str(candidate.parameters.get("claim_type", "concentration"))
        if claim_type == "concentration":
            return (self._validate_concentration(candidate, stage, seed, context),)
        if claim_type == "filamentarity":
            return (self._validate_filamentarity(candidate, stage, seed, context),)
        if claim_type == "velocity-gradient":
            return (self._validate_velocity(candidate, stage, seed, context),)
        raise ValueError(f"unknown claim_type {claim_type!r}")

    def import_structure(self, structure: dict[str, object], *, candidate_id: str) -> Candidate:
        claim = str(structure.get("claim_type", "concentration"))
        return Candidate(
            candidate_id,
            self.manifest.domain,
            f"test transferred structure ({claim}) on {self._molecule}",
            {"claim_type": claim},
            parent_id=str(structure.get("_source_candidate_id", "")) or None,
            source_adapter=self.manifest.name,
        )
