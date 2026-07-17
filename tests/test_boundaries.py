import ast
from pathlib import Path

import pytest

from sapiens.adapter import validate_adapter
from sapiens.models import AdapterManifest, Candidate, Evidence

ROOT = Path(__file__).resolve().parents[1]


def test_core_does_not_import_adapters():
    for path in (ROOT / "src" / "sapiens").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("sapiens.adapters"), path
            elif isinstance(node, ast.Import):
                assert all(not alias.name.startswith("sapiens.adapters") for alias in node.names), (
                    path
                )


def test_phase0_rejects_non_synthetic_adapter():
    class RealAdapter:
        @property
        def manifest(self):  # type: ignore[override]
            return AdapterManifest("real", "0", "unsafe", ("x",), synthetic_only=False)

        def propose(self, *, seed: int, limit: int):
            return ()

        def validate(self, candidate, *, stage: str, seed: int, context):
            return ()

        def import_structure(self, structure, *, candidate_id: str):
            return Candidate(candidate_id, "unsafe", "claim")

    with pytest.raises(ValueError):
        validate_adapter(RealAdapter())


def test_evidence_rejects_invalid_confidence_score():
    with pytest.raises(ValueError):
        Evidence("e", "c", "internal", True, "p", "d", 1, 1.2)
