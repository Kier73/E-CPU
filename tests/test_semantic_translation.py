"""Conformance tests for declarative semantic translation contracts."""

from __future__ import annotations

import pytest

from mailcpu import QueueInterpreter, ReferenceInterpreter, canonical_result
from mailcpu.law_certifier import Law
from mailcpu.model import Instruction, Op, Program
from mailcpu.semantic_translation import (
    CapabilityRequirement,
    EffectClass,
    ObservationComparison,
    ObservationContract,
    ReplayClass,
    RepresentationRef,
    ResourceBound,
    SemanticTranslationError,
    TranslationContract,
    canonical_value_digest,
    compare_projected_observations,
    program_representation_ref,
    structural_memory_spec_representation_ref,
)
from mailcpu.structural_memory import StructuralMemorySpec
from mailcpu.programs import addition_program


def _contract(program: Program) -> TranslationContract:
    """Build the exact run-result contract for one reference/queue interpreter pair."""
    program_ref = program_representation_ref(program)
    observation = ObservationContract.from_definition(
        "mailcpu.run-result",
        1,
        {
            "projection": "mailcpu.model.canonical_result",
            "fields": ["status", "state", "trace", "outputs"],
            "comparison": "canonical-json-exact",
        },
    )
    return TranslationContract(
        contract_id="mailcpu.reference-to-queue",
        revision=1,
        source=RepresentationRef(
            "mailcpu.reference-interpreter",
            1,
            program_ref.content_digest,
        ),
        target=RepresentationRef(
            "mailcpu.queue-interpreter",
            1,
            program_ref.content_digest,
        ),
        observation=observation,
        context_digest=canonical_value_digest(
            {"initial_registers": {}, "inputs": {}, "max_steps": 10_000}
        ),
        precondition_digests=(canonical_value_digest({"program": "validated"}),),
        invariant_digests=(canonical_value_digest({"transition": "deterministic"}),),
        resource_bounds=(ResourceBound("steps", 10_000, "instructions"),),
        authority_requirements=(
            CapabilityRequirement("/machine/run", ("execute",)),
        ),
        effect_class=EffectClass.PURE,
        replay_class=ReplayClass.DETERMINISTIC,
    )


def test_reference_and_queue_interpreters_match_under_translation_contract():
    """Mathematics: compare π(run_ref(P)) and π(run_queue(P)) for one exact validated input case."""
    program = addition_program(19, 23)
    contract = _contract(program)
    source = canonical_result(ReferenceInterpreter(program).run())
    target = canonical_result(QueueInterpreter(program).run())

    check = compare_projected_observations(
        contract,
        case_payload={
            "program": program_representation_ref(program).to_dict(),
            "initial_registers": {},
            "inputs": {},
            "max_steps": 10_000,
        },
        source_observation=source,
        target_observation=target,
    )

    assert check.equivalent is True
    assert check.source_observation_digest == check.target_observation_digest
    assert check.contract_digest == contract.digest
    assert ObservationComparison.from_dict(check.to_dict()) == check


def test_translation_contract_round_trips_with_a_stable_digest():
    """Mathematics: from_dict(to_dict(C)) = C and H(C) remains invariant under canonical serialization."""
    contract = _contract(addition_program(2, 5))

    restored = TranslationContract.from_dict(contract.to_dict())

    assert restored == contract
    assert restored.digest == contract.digest
    assert restored.to_dict() == contract.to_dict()


def test_translation_contract_digest_is_independent_of_set_like_input_order():
    """Mathematics: sorting preconditions, invariants, bounds, and rights makes equivalent declarations share H(C)."""
    program_ref = program_representation_ref(addition_program(1, 2))
    observation = ObservationContract.from_definition(
        "mailcpu.run-result",
        1,
        {"fields": ["status", "state", "trace", "outputs"]},
    )
    first = TranslationContract(
        "ordering",
        1,
        program_ref,
        RepresentationRef("mailcpu.queue-program", 1, program_ref.content_digest),
        observation,
        canonical_value_digest({}),
        precondition_digests=(
            canonical_value_digest({"b": 2}),
            canonical_value_digest({"a": 1}),
        ),
        resource_bounds=(
            ResourceBound("bytes", 4096, "bytes"),
            ResourceBound("steps", 100, "instructions"),
        ),
        authority_requirements=(
            CapabilityRequirement("/cpu", ("write", "read")),
            CapabilityRequirement("/memory", ("read",)),
        ),
    )
    second = TranslationContract(
        "ordering",
        1,
        program_ref,
        RepresentationRef("mailcpu.queue-program", 1, program_ref.content_digest),
        observation,
        canonical_value_digest({}),
        precondition_digests=tuple(reversed(first.precondition_digests)),
        resource_bounds=tuple(reversed(first.resource_bounds)),
        authority_requirements=(
            CapabilityRequirement("/memory", ("read",)),
            CapabilityRequirement("/cpu", ("read", "write")),
        ),
    )

    assert first.digest == second.digest


def test_mismatching_observations_are_reported_not_raised_as_success():
    """Mathematics: a paired check is false whenever canonical projected bytes differ."""
    program = addition_program(1, 1)
    contract = _contract(program)
    source = canonical_result(ReferenceInterpreter(program).run())
    target = dict(canonical_result(QueueInterpreter(program).run()))
    target["outputs"] = [["incorrect", 2]]

    check = compare_projected_observations(
        contract,
        case_payload={"program": program_representation_ref(program).to_dict()},
        source_observation=source,
        target_observation=target,
    )

    assert check.equivalent is False
    assert check.source_observation_digest != check.target_observation_digest


def test_program_representation_ref_is_ordered_and_content_addressed():
    """Mathematics: distinct instruction order or operands yields a distinct program representation digest."""
    first = Program((Instruction(Op.SET, ("x", 1)), Instruction(Op.HALT)))
    reordered = Program((Instruction(Op.HALT), Instruction(Op.SET, ("x", 1))))
    changed = Program((Instruction(Op.SET, ("x", 2)), Instruction(Op.HALT)))

    assert program_representation_ref(first).content_digest != program_representation_ref(reordered).content_digest
    assert program_representation_ref(first).content_digest != program_representation_ref(changed).content_digest
    assert RepresentationRef.from_dict(program_representation_ref(first).to_dict()) == program_representation_ref(first)


def test_structural_memory_spec_uses_its_existing_content_identity():
    """Mathematics: H(spec.to_dict()) equals the pre-existing immutable Structural Memory spec digest."""
    spec = StructuralMemorySpec.from_law(
        "translation-fixture",
        1,
        "integer-orbit",
        Law(
            family="int",
            params={"x0": 0, "step": 1, "mod": 97},
            order=1,
            verdict="GROUND",
        ),
        context={"tenant": "test"},
    )

    reference = structural_memory_spec_representation_ref(spec)

    assert reference.type_id == "mailcpu.structural-memory.spec"
    assert reference.content_digest == spec.digest


def test_external_effects_cannot_claim_unledgered_deterministic_replay():
    """Mathematics: EXTERNAL ∧ DETERMINISTIC is rejected because effect repetition is not proven safe."""
    program_ref = program_representation_ref(addition_program(1, 1))
    observation = ObservationContract.from_definition("result", 1, {"fields": ["result"]})

    with pytest.raises(SemanticTranslationError, match="external effects"):
        TranslationContract(
            "external-operation",
            1,
            program_ref,
            RepresentationRef("remote.result", 1, program_ref.content_digest),
            observation,
            canonical_value_digest({}),
            effect_class=EffectClass.EXTERNAL,
            replay_class=ReplayClass.DETERMINISTIC,
        )


def test_canonical_digest_rejects_non_finite_or_opaque_values():
    """Mathematics: canonical digest is defined only over finite JSON-compatible values."""
    with pytest.raises(SemanticTranslationError, match="non-finite"):
        canonical_value_digest({"not_finite": float("nan")})
    with pytest.raises(SemanticTranslationError, match="unsupported type"):
        canonical_value_digest({"opaque": object()})


def test_contract_schema_refuses_unknown_fields_and_unsupported_comparison():
    """Mathematics: the v1 decoder admits exactly its schema field set and exact canonical comparison."""
    contract = _contract(addition_program(3, 4))
    malformed = dict(contract.to_dict())
    malformed["future_unrecognized_field"] = True

    with pytest.raises(SemanticTranslationError, match="schema or fields"):
        TranslationContract.from_dict(malformed)

    with pytest.raises(SemanticTranslationError, match="only canonical-json-exact"):
        ObservationContract(
            "mailcpu.run-result",
            1,
            canonical_value_digest({"fields": ["status"]}),
            comparison="approximate",
        )
