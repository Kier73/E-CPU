from __future__ import annotations

import copy
import itertools

import pytest

from mailcpu.interpreter import QueueInterpreter, ReferenceInterpreter
from mailcpu.model import canonical_result
from mailcpu.semantic_translation import (
    EffectClass,
    ObservationContract,
    ReplayClass,
    RepresentationRef,
    ResourceBound,
    TranslationContract,
    canonical_value_digest,
    compare_projected_observations,
    program_representation_ref,
)
from mailcpu.weight_space import (
    WeightSpaceError,
    boolean_gate_program,
    compile_boolean_gate,
    decode_boolean_signal,
    edit_boolean_gate,
    encode_boolean_signal,
    evaluate_boolean_gate,
)


def _cases() -> tuple[tuple[int, int], ...]:
    return tuple(itertools.product((0, 1), repeat=2))


def _translation_contract(program, model, left: int, right: int) -> TranslationContract:
    program_ref = program_representation_ref(program)
    observation = ObservationContract.from_definition(
        "mailcpu.boolean-result",
        1,
        {
            "projection": "single-result-register",
            "field": "result",
            "domain": [0, 1],
            "comparison": "canonical-json-exact",
        },
    )
    mapping = RepresentationRef.from_payload(
        "mailcpu.boolean-weight-compiler",
        1,
        {
            "compiler": "mailcpu.weight_space.compile_boolean_gate",
            "architecture": [2, 85, 112, 1],
            "activation": "relu-hidden-linear-output",
        },
    )
    return TranslationContract(
        contract_id="mailcpu.boolean-program-to-weights",
        revision=1,
        source=program_ref,
        target=RepresentationRef.from_payload(
            "mailcpu.relu-network",
            1,
            model.snapshot(),
        ),
        mapping=mapping,
        observation=observation,
        context_digest=canonical_value_digest(
            {"initial_registers": {"a": left, "b": right}}
        ),
        precondition_digests=(
            canonical_value_digest({"input_domain": "{0,1}^2"}),
        ),
        invariant_digests=(
            canonical_value_digest({"output_domain": "{0,1}"}),
        ),
        resource_bounds=(
            ResourceBound("parameters", model.parameter_count, "scalar-parameters"),
            ResourceBound("steps", 10, "instructions"),
        ),
        effect_class=EffectClass.PURE,
        replay_class=ReplayClass.DETERMINISTIC,
    )


def test_compiler_constructs_exact_10000_parameter_relu_network():
    model = compile_boolean_gate("xor")
    assert model.architecture == (2, 85, 112, 1)
    assert model.parameter_count == 10_000
    assert model.active_parameter_count == 9
    for left, right in _cases():
        assert model.predict(left, right) == left ^ right


def test_two_parameter_intervention_changes_xor_to_and_only_on_output_coefficients():
    model = compile_boolean_gate("xor")
    before = model.weights
    intervention = edit_boolean_gate(model, "and")
    after = model.weights

    assert intervention.changed_parameters == 2
    assert [
        (coordinate.layer_index, coordinate.output_index, coordinate.input_index)
        for coordinate in intervention.coordinates
    ] == [(2, 0, 0), (2, 0, 1)]
    all_changes = [
        (layer_index, output_index, input_index)
        for layer_index, (old_layer, new_layer) in enumerate(zip(before, after))
        for output_index, (old_row, new_row) in enumerate(zip(old_layer, new_layer))
        for input_index, (old, new) in enumerate(zip(old_row, new_row))
        if old != new
    ]
    assert all_changes == [(2, 0, 0), (2, 0, 1)]
    assert model.parameter_count == 10_000
    assert model.active_parameter_count == 8
    for left, right in _cases():
        assert model.predict(left, right) == left & right


def test_same_gate_intervention_is_idempotent():
    model = compile_boolean_gate("xor")
    intervention = edit_boolean_gate(model, "xor")
    assert intervention.changed_parameters == 0
    assert intervention.source_digest == intervention.target_digest


def test_network_snapshot_round_trip_is_detached_and_digest_checked():
    model = compile_boolean_gate("xor")
    snapshot = model.snapshot()
    restored = type(model).from_snapshot(snapshot)
    assert restored.digest == model.digest
    assert restored.snapshot() == snapshot

    altered = copy.deepcopy(snapshot)
    altered["weights"][2][0][0] = 9.0
    # The caller's snapshot is detached from the live network.
    assert model.predict(0, 1) == 1
    with pytest.raises(WeightSpaceError, match="digest mismatch"):
        type(model).from_snapshot(altered)


def test_boolean_embedding_in_z8_turns_addition_into_xor():
    for left, right in _cases():
        signal_sum = (
            encode_boolean_signal(left) + encode_boolean_signal(right)
        ) % 8
        assert decode_boolean_signal(signal_sum) == left ^ right


def test_weight_model_matches_mailcpu_interpreters_and_semantic_translation_contract():
    model = compile_boolean_gate("xor")

    for gate in ("xor", "and"):
        if model.compiled_gate != gate:
            edit_boolean_gate(model, gate)
        program = boolean_gate_program(gate)

        for left, right in _cases():
            initial = {"a": left, "b": right}
            reference = ReferenceInterpreter(program).run(
                initial_registers=initial,
            )
            queued = QueueInterpreter(program).run(
                initial_registers=initial,
            )
            expected = evaluate_boolean_gate(gate, left, right)
            predicted = model.predict(left, right)

            assert reference.status.value == "halted"
            assert queued.status.value == "halted"
            assert reference.state.registers["result"] == expected
            assert queued.state.registers["result"] == expected
            assert predicted == expected
            assert canonical_result(reference) == canonical_result(queued)

            contract = _translation_contract(program, model, left, right)
            comparison = compare_projected_observations(
                contract,
                case_payload={
                    "program": program_representation_ref(program).to_dict(),
                    "initial_registers": initial,
                },
                source_observation={"result": reference.state.registers["result"]},
                target_observation={"result": predicted},
            )
            assert comparison.equivalent is True
            assert comparison.contract_digest == contract.digest


def test_model_refuses_inputs_outside_its_declared_domain():
    model = compile_boolean_gate("xor")
    with pytest.raises(WeightSpaceError, match="Boolean bit"):
        model.predict(0, 2)
    with pytest.raises(WeightSpaceError, match="exactly two"):
        model.forward((0,))
    with pytest.raises(WeightSpaceError, match="gate must"):
        compile_boolean_gate("or")
