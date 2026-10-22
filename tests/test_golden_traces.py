from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from mailcpu import QueueInterpreter, ReferenceInterpreter, canonical_result
from mailcpu.programs import addition_program, branch_program, countdown_program, wait_send_program


def _golden_cases():
    """Mathematics: construct the finite corpus relation `C={name↦(P,I,O)}` used by the checked-in witness."""

    return {
        "addition": (addition_program(1, 1), {}, {}),
        "branch_taken": (branch_program(1), {}, {}),
        "branch_not_taken": (branch_program(0), {}, {}),
        "countdown": (countdown_program(3), {}, {}),
        "wait_send": (wait_send_program(), {}, {"inbox": [42]}),
    }


def test_checked_in_golden_traces_match_reference_and_queue() -> None:
    """Mathematics: require `golden[name]=π(reference(P,I))=π(queue(P,I))` for every corpus case."""

    fixture_path = Path(__file__).with_name("golden_traces.json")
    golden = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert set(golden) == set(_golden_cases())
    for name, (program, registers, inputs) in _golden_cases().items():
        reference = canonical_result(ReferenceInterpreter(program).run(registers, inputs))
        queue = canonical_result(QueueInterpreter(program).run(registers, inputs))
        assert reference == golden[name], name
        assert queue == golden[name], name


def test_golden_recorder_verifies_without_rewriting() -> None:
    """Mathematics: default recorder operation is a pure predicate `verify(JSON(path),G)=true`, not an implicit fixture mutation."""

    root = Path(__file__).parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/record_golden.py"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "verified" in result.stdout

