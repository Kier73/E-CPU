from __future__ import annotations

import copy
import itertools

import pytest

from mailcpu.interpreter import QueueInterpreter, ReferenceInterpreter
from mailcpu.model import canonical_result
from mailcpu.transition_space import (
    FiniteTransitionTable,
    TransitionRow,
    TransitionSpaceError,
    apply_table_intervention,
    compile_transition_program,
    compile_transition_table,
    pattern_to_index,
    two_bit_counter_program,
    two_bit_counter_table,
)


def _architectures(table: FiniteTransitionTable) -> tuple[tuple[int, ...], ...]:
    width = len(table.input_names)
    rows = table.row_count
    outputs = len(table.output_names)
    return (
        (width, rows, outputs),
        (width, rows, rows, outputs),
    )


def _initial_registers(table: FiniteTransitionTable, inputs: tuple[int, ...]) -> dict[str, int]:
    return dict(zip(table.input_names, inputs))


def _expected_registers(table: FiniteTransitionTable, outputs: tuple[int, ...]) -> dict[str, int]:
    return dict(zip(table.output_names, outputs))


def test_two_bit_counter_table_is_total_and_deterministic():
    table = two_bit_counter_table()
    assert table.row_count == 16
    assert len({row.inputs for row in table.rows}) == 16

    assert table.row_for((0, 0, 1, 0)).outputs == (0, 1)
    assert table.row_for((0, 1, 1, 0)).outputs == (1, 0)
    assert table.row_for((1, 1, 1, 0)).outputs == (0, 0)
    assert table.row_for((0, 1, 0, 0)).outputs == (0, 1)
    assert table.row_for((0, 1, 1, 1)).outputs == (0, 0)


@pytest.mark.parametrize("architecture_index", (0, 1))
def test_truth_table_compiles_to_distinct_exact_relu_architectures(architecture_index: int):
    table = two_bit_counter_table()
    architecture = _architectures(table)[architecture_index]
    model = compile_transition_table(table, architecture=architecture)

    assert model.architecture == architecture
    assert model.parameter_count == (
        114 if architecture_index == 0 else 386
    )
    for row in table.rows:
        assert model.predict(row.inputs) == row.outputs


def test_mailcpu_program_and_both_execution_backends_match_every_transition():
    table = two_bit_counter_table()
    program = compile_transition_program(table)

    for row in table.rows:
        initial = _initial_registers(table, row.inputs)
        reference = ReferenceInterpreter(program).run(initial_registers=initial)
        queued = QueueInterpreter(program).run(initial_registers=initial)

        assert reference.status.value == "halted"
        assert queued.status.value == "halted"
        assert _expected_registers(table, row.outputs).items() <= reference.state.registers.items()
        assert _expected_registers(table, row.outputs).items() <= queued.state.registers.items()
        assert canonical_result(reference) == canonical_result(queued)


def test_editing_one_transition_row_changes_exactly_one_neural_weight():
    table = two_bit_counter_table()
    changed_inputs = (0, 1, 1, 1)
    changed_outputs = (1, 0)
    target = table.with_output(changed_inputs, changed_outputs)
    row_index = pattern_to_index(changed_inputs)

    for architecture in _architectures(table):
        model = compile_transition_table(table, architecture=architecture)
        before_weights = model.weights
        intervention = apply_table_intervention(model, table, target)
        after_weights = model.weights
        final_layer = len(architecture) - 2

        assert intervention.changed_parameters == 1
        assert [
            (item.layer_index, item.output_index, item.input_index)
            for item in intervention.coordinates
        ] == [(final_layer, 0, row_index)]

        changed_coordinates = [
            (layer, output, input_index)
            for layer, (old_matrix, new_matrix) in enumerate(
                zip(before_weights, after_weights)
            )
            for output, (old_row, new_row) in enumerate(
                zip(old_matrix, new_matrix)
            )
            for input_index, (old, new) in enumerate(zip(old_row, new_row))
            if old != new
        ]
        assert changed_coordinates == [(final_layer, 0, row_index)]
        assert model.table_digest == target.digest

        for row in target.rows:
            assert model.predict(row.inputs) == row.outputs


def test_neural_intervention_changes_only_the_selected_transition():
    source = two_bit_counter_table()
    target = source.with_output((0, 1, 1, 1), (1, 0))
    model = compile_transition_table(source)
    apply_table_intervention(model, source, target)

    for row in source.rows:
        actual = model.predict(row.inputs)
        if row.inputs == (0, 1, 1, 1):
            assert actual == (1, 0)
        else:
            assert actual == row.outputs


def test_edited_transition_program_matches_updated_neural_model():
    source = two_bit_counter_table()
    target = source.with_output((0, 1, 1, 1), (1, 0))
    program = compile_transition_program(target)
    model = compile_transition_table(source)
    apply_table_intervention(model, source, target)

    for row in target.rows:
        result = ReferenceInterpreter(program).run(
            initial_registers=_initial_registers(target, row.inputs)
        )
        assert result.status.value == "halted"
        assert _expected_registers(target, row.outputs).items() <= result.state.registers.items()
        assert model.predict(row.inputs) == row.outputs


def test_snapshot_round_trip_and_detached_payload():
    table = two_bit_counter_table()
    for architecture in _architectures(table):
        model = compile_transition_table(table, architecture=architecture)
        snapshot = model.snapshot()
        restored = type(model).from_snapshot(snapshot)
        assert restored.digest == model.digest
        assert restored.snapshot() == snapshot

        altered = copy.deepcopy(snapshot)
        altered["weights"][-1][0][0] = 99.0
        with pytest.raises(TransitionSpaceError, match="digest mismatch"):
            type(model).from_snapshot(altered)


def test_intervention_rejects_wrong_source_or_changed_interface():
    table = two_bit_counter_table()
    model = compile_transition_table(table)
    target = table.with_output((0, 1, 1, 1), (1, 0))
    wrong_source = table.with_output((0, 0, 0, 0), (1, 1))

    with pytest.raises(TransitionSpaceError, match="source table"):
        apply_table_intervention(model, wrong_source, target)

    different_interface = FiniteTransitionTable(
        target.name,
        target.input_names,
        ("other_output_1", "other_output_0"),
        target.rows,
    )
    with pytest.raises(TransitionSpaceError, match="interface"):
        apply_table_intervention(model, table, different_interface)


def test_transition_table_rejects_missing_or_duplicate_input_patterns():
    with pytest.raises(TransitionSpaceError, match="cover every Boolean input pattern"):
        FiniteTransitionTable(
            "incomplete",
            ("a", "b"),
            ("out",),
            (
                TransitionRow((0, 0), (0,)),
                TransitionRow((0, 1), (0,)),
                TransitionRow((1, 0), (1,)),
            ),
        )

    with pytest.raises(TransitionSpaceError, match="cover every Boolean input pattern"):
        FiniteTransitionTable(
            "duplicate",
            ("a",),
            ("out",),
            (TransitionRow((0,), (0,)), TransitionRow((0,), (1,))),
        )


def test_compiler_refuses_architecture_without_one_hidden_unit_per_row():
    table = two_bit_counter_table()
    with pytest.raises(TransitionSpaceError, match="one hidden neuron per table row"):
        compile_transition_table(table, architecture=(4, 8, 2))


if __name__ == "__main__":
    pytest.main([__file__])


def test_compositional_transition_program_enumerates_the_complete_table():
    program = two_bit_counter_program()
    table = program.to_table()

    assert table == two_bit_counter_table()
    for row in table.rows:
        assert program.evaluate(row.inputs) == row.outputs

    restored = type(program).from_dict(program.to_dict())
    assert restored.digest == program.digest
    assert restored.to_table() == table


def test_compositional_transition_program_rejects_undeclared_inputs():
    from mailcpu.transition_space import (
        BooleanInput,
        BooleanSelect,
        FiniteTransitionProgram,
    )

    with pytest.raises(TransitionSpaceError, match="undeclared inputs"):
        FiniteTransitionProgram(
            "invalid-transition",
            ("state",),
            ("next_state",),
            (BooleanSelect(BooleanInput("missing"), BooleanInput("state"), BooleanInput("state")),),
        )


def test_typed_program_row_override_changes_only_the_selected_transition():
    source_program = two_bit_counter_program()
    source_table = source_program.to_table()
    target_program = source_program.with_row_output(
        (0, 1, 1, 1),
        (1, 0),
        name="two-bit-counter.reset-exception.v1",
    )
    target_table = target_program.to_table()

    assert target_table == source_table.with_output(
        (0, 1, 1, 1),
        (1, 0),
        name="two-bit-counter.reset-exception.v1",
    )
    changed_rows = [
        row.inputs
        for row, target_row in zip(source_table.rows, target_table.rows)
        if row.outputs != target_row.outputs
    ]
    assert changed_rows == [(0, 1, 1, 1)]
