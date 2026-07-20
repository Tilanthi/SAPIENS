import pickle

from sapiens import Candidate, Evidence
from sapiens.sandbox import sandboxed_validate
from sapiens.sandbox_examples import (
    CrashingExampleAdapter,
    FastExampleAdapter,
    SleepyExampleAdapter,
)


def _candidate(adapter):
    return adapter.propose(seed=1, limit=1)[0]


def test_candidate_and_evidence_are_picklable():
    # required for subprocess sandboxing (spawn pickles the candidate + evidence)
    candidate = Candidate("cid", "dom", "claim", {"a": 1}, parent_id="p", source_adapter="s")
    revived = pickle.loads(pickle.dumps(candidate))
    assert revived == candidate
    assert dict(revived.parameters) == {"a": 1}
    evidence = Evidence("eid", "cid", "internal", True, "proto", "data", 7, 0.5, {"x": 9})
    revived_ev = pickle.loads(pickle.dumps(evidence))
    assert revived_ev == evidence
    assert dict(revived_ev.details) == {"x": 9}


def test_sandbox_runs_fast_adapter_and_returns_evidence():
    adapter = FastExampleAdapter()
    result = sandboxed_validate(
        _candidate(adapter),
        adapter=adapter,
        stage="internal",
        seed=1,
        max_steps=10,
        max_seconds=5,
        timeout=15,
    )
    assert result.ok
    assert result.evidence is not None
    assert result.evidence[0].passed is True


def test_sandbox_hard_terminates_on_timeout():
    adapter = SleepyExampleAdapter()
    result = sandboxed_validate(
        _candidate(adapter),
        adapter=adapter,
        stage="internal",
        seed=1,
        max_steps=50,
        max_seconds=10,
        timeout=1.0,
    )
    assert result.timed_out is True
    assert result.evidence is None
    assert not result.ok


def test_sandbox_captures_crash_without_killing_host():
    adapter = CrashingExampleAdapter()
    result = sandboxed_validate(
        _candidate(adapter),
        adapter=adapter,
        stage="internal",
        seed=1,
        max_steps=10,
        max_seconds=5,
        timeout=15,
    )
    assert not result.ok
    assert result.error is not None
    assert "deliberate crash" in result.error
