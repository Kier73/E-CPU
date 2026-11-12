from __future__ import annotations

import ast
import copy
import importlib.util
import itertools
import sys
from pathlib import Path

import pytest

from mailcpu.stateful_transition import (
    SCHEMA,
    StatefulTransitionError,
    StatefulTransitionRuntime,
)
from mailcpu.transition_space import (
    BooleanConstant,
    BooleanInput,
    FiniteTransitionProgram,
    two_bit_counter_program,
)


def _edited_program():
    """Build the one-row counter override used by transition runtime tests."""
    return two_bit_counter_program().with_row_output(
        (0, 1, 1, 1),
        (1, 0),
        name="two-bit-counter.reset-exception.v1",
    )


def test_runtime_steps_match_typed_transition_program_over_all_single_inputs():
    program = two_bit_counter_program()
    for state_1, state_0, advance, reset in itertools.product((0, 1), repeat=4):
        runtime = StatefulTransitionRuntime(program, (state_1, state_0))
        expected = program.evaluate((state_1, state_0, advance, reset))
        result = runtime.step({"advance": advance, "reset": reset})

        assert result.state == expected
        assert runtime.state == expected
        assert runtime.tick == 1
        assert runtime.revision == 0
        assert result.tick == 1
        assert result.program_digest == program.digest
        assert result.model_digest == runtime.model_digest
        assert result.event_digest == runtime.chain_head_digest


def test_model_revision_preserves_live_state_and_tick_then_changes_behavior():
    runtime = StatefulTransitionRuntime(two_bit_counter_program(), (0, 1))

    first = runtime.step({"advance": 0, "reset": 0})
    assert first.state == (0, 1)
    assert runtime.tick == 1
    assert runtime.revision == 0

    preserved_state = runtime.state
    preserved_tick = runtime.tick
    source_model_digest = runtime.model_digest
    revision_event = runtime.revise(_edited_program())

    assert runtime.state == preserved_state
    assert runtime.tick == preserved_tick
    assert runtime.revision == 1
    assert runtime.model_digest != source_model_digest
    assert revision_event["kind"] == "revision"
    assert revision_event["state_preserved"] == [0, 1]
    assert revision_event["revision_before"] == 0
    assert revision_event["revision_after"] == 1

    second = runtime.step({"advance": 1, "reset": 1})
    assert second.state == (1, 0)
    assert second.tick == 2
    assert second.revision == 1
    assert runtime.events[-1]["program_digest"] == runtime.program_digest


def test_runtime_snapshot_round_trip_replays_steps_and_model_revisions():
    runtime = StatefulTransitionRuntime(two_bit_counter_program(), (0, 1))
    runtime.step({"advance": 0, "reset": 0})
    runtime.revise(_edited_program())
    runtime.step({"advance": 1, "reset": 1})
    runtime.step({"advance": 0, "reset": 0})

    snapshot = runtime.snapshot()
    restored = StatefulTransitionRuntime.from_snapshot(snapshot)

    assert isinstance(snapshot["events"], list)
    assert snapshot["schema"] == SCHEMA
    assert restored.snapshot() == snapshot
    assert restored.state == runtime.state
    assert restored.tick == 3
    assert restored.revision == 1
    assert restored.event_count == 4
    assert restored.chain_head_digest == runtime.chain_head_digest


def test_event_chain_rejects_modified_event_payload_and_terminal_digest():
    runtime = StatefulTransitionRuntime(two_bit_counter_program(), (0, 1))
    runtime.step({"advance": 0, "reset": 0})
    runtime.revise(_edited_program())
    runtime.step({"advance": 1, "reset": 1})
    snapshot = runtime.snapshot()

    modified_payload = copy.deepcopy(snapshot)
    modified_payload["events"][0]["controls"]["advance"] = 1
    with pytest.raises(StatefulTransitionError, match="replay or digest"):
        StatefulTransitionRuntime.from_snapshot(modified_payload)

    modified_head = copy.deepcopy(snapshot)
    modified_head["chain_head_digest"] = "0" * 64
    with pytest.raises(StatefulTransitionError, match="chain head digest"):
        StatefulTransitionRuntime.from_snapshot(modified_head)


def test_event_chain_rejects_reordered_or_removed_events():
    runtime = StatefulTransitionRuntime(two_bit_counter_program(), (0, 1))
    runtime.step({"advance": 0, "reset": 0})
    runtime.revise(_edited_program())
    snapshot = runtime.snapshot()

    reordered = copy.deepcopy(snapshot)
    reordered["events"].reverse()
    with pytest.raises(StatefulTransitionError):
        StatefulTransitionRuntime.from_snapshot(reordered)

    removed = copy.deepcopy(snapshot)
    removed["events"].pop()
    with pytest.raises(StatefulTransitionError):
        StatefulTransitionRuntime.from_snapshot(removed)


def test_revision_rejects_incompatible_interface_without_mutating_runtime():
    runtime = StatefulTransitionRuntime(two_bit_counter_program(), (0, 1))
    before = runtime.snapshot()
    incompatible = FiniteTransitionProgram(
        "different-interface",
        ("state_1", "state_0", "advance"),
        ("next_state_1", "next_state_0"),
        (BooleanInput("state_1"), BooleanInput("state_0")),
    )

    with pytest.raises(StatefulTransitionError, match="preserve the exact interface"):
        runtime.revise(incompatible)

    assert runtime.snapshot() == before


def test_runtime_rejects_noop_revisions_and_invalid_control_values():
    runtime = StatefulTransitionRuntime(two_bit_counter_program(), (0, 1))

    with pytest.raises(StatefulTransitionError, match="no-op"):
        runtime.revise(two_bit_counter_program())
    with pytest.raises(StatefulTransitionError, match="controls do not match"):
        runtime.step({"advance": 1})
    with pytest.raises(StatefulTransitionError, match="Boolean bit"):
        runtime.step({"advance": 1.0, "reset": 0})
    with pytest.raises(StatefulTransitionError, match="controls do not match"):
        runtime.step({"advance": 1, "reset": 0, "unexpected": 0})

    assert runtime.tick == 0
    assert runtime.revision == 0
    assert runtime.event_count == 0


def test_event_accessor_returns_detached_records():
    runtime = StatefulTransitionRuntime(two_bit_counter_program(), (0, 1))
    runtime.step({"advance": 0, "reset": 0})

    exported = runtime.events
    exported[0]["controls"]["advance"] = 1

    assert runtime.events[0]["controls"]["advance"] == 0
    assert StatefulTransitionRuntime.from_snapshot(runtime.snapshot()).state == (0, 1)


def test_runtime_validates_initial_state_width_and_program_outputs():
    with pytest.raises(StatefulTransitionError, match="initial state width"):
        StatefulTransitionRuntime(two_bit_counter_program(), (0,))

    invalid_outputs = FiniteTransitionProgram(
        "bad-output-count",
        ("state_1", "state_0", "advance", "reset"),
        ("next_state",),
        (BooleanConstant(0),),
    )
    with pytest.raises(StatefulTransitionError, match="one next-state output"):
        StatefulTransitionRuntime(invalid_outputs, (0, 1))


def test_new_transition_modules_have_governing_mathematics_annotations():
    root = Path(__file__).resolve().parents[1]
    for module_name in ("weight_space.py", "transition_space.py", "stateful_transition.py"):
        module_path = root / "mailcpu" / module_name
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("__") and node.name.endswith("__"):
                continue
            docstring = ast.get_docstring(node)
            assert docstring is not None, f"{module_name}:{node.lineno} {node.name} has no docstring"
            assert "Mathematics:" in docstring, (
                f"{module_name}:{node.lineno} {node.name} has no governing mathematics annotation"
            )


def test_new_neural_and_runtime_invariants_resolve_in_registry():
    root = Path(__file__).resolve().parents[1]
    registry_path = root / "docs" / "INVARIANTS.md"
    registry_lines = registry_path.read_text(encoding="utf-8").splitlines()
    owned_ids = {"N-7", "N-8", "N-9", "N-10", "N-11", "N-12"}
    owned_lines = {
        index + 1
        for index, line in enumerate(registry_lines)
        if any(f"`{identifier}`" in line for identifier in owned_ids)
    }

    script_path = root / "scripts" / "verify_invariants.py"
    spec = importlib.util.spec_from_file_location(
        "ecpu_verify_invariants_for_transition_tests",
        script_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    problems = module.verify(registry_path)
    unresolved = [
        problem
        for problem in problems
        if problem.line in owned_lines
    ]
    assert unresolved == []
