from pathlib import Path

import sapiens.ongoing as ongoing
from sapiens.ongoing import run_ongoing


def test_run_ongoing_handles_absent_data(tmp_path: Path, monkeypatch):
    # point the connector at nonexistent paths -> no real data -> graceful no-op
    monkeypatch.setattr(ongoing, "PHOTOZ_CSV", tmp_path / "nope-photoz.csv")
    monkeypatch.setattr(ongoing, "CLASS_CSV", tmp_path / "nope-class.csv")
    result = run_ongoing(tmp_path / "store.db")
    assert result["swept"] == 0
    assert "note" in result
