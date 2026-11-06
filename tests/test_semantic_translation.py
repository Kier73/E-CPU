"""Conformance tests for declarative semantic translation contracts."""

from __future__ import annotations

import pytest

from mailcpu import (\n    HeadlessOS,\n    QueueInterpreter,\n    ReferenceInterpreter,\n    StructuralMemoryFileRef,\n    StructuralMemoryFileProvider,\n    StructuralMemoryPageBacking,\n    VirtualMemory,\n    canonical_result,\n)
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
from mailcpu.structural_memory import StructuralMemorySpec\n
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
    mapping = RepresentationRef.from_payload(
        "mailcpu.interpreter-pairing",
        1,
        {
            "source_backend": "reference",
            "target_backend": "queue",
            "transition_algebra": "mailcpu.T.v1",
            "observation": "canonical_result.v1",
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
        mapping=mapping,
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
    mapping = RepresentationRef.from_payload(
        "mailcpu.interpreter-pairing",
        1,
        {"source": "reference", "target": "queue", "version": 1},
    )
    first = TranslationContract(
        "ordering",
        1,
        program_ref,
        RepresentationRef("mailcpu.queue-program", 1, program_ref.content_digest),
        mapping,
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
        mapping,
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



def test_changing_mapping_definition_changes_translation_contract_digest():
    """Mathematics: H(C[mapping:=M1]) differs from H(C[mapping:=M2]) when the mapping definition digest differs."""
    from dataclasses import replace

    contract = _contract(addition_program(7, 8))
    changed_mapping = RepresentationRef.from_payload(
        "mailcpu.interpreter-pairing",
        1,
        {
            "source_backend": "reference",
            "target_backend": "queue",
            "transition_algebra": "mailcpu.T.v2",
            "observation": "canonical_result.v1",
        },
    )

    changed = replace(contract, mapping=changed_mapping)

    assert changed.mapping.content_digest != contract.mapping.content_digest
    assert changed.digest != contract.digest


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
            RepresentationRef.from_payload("mailcpu.remote-effect-map", 1, {"adapter": "remote"}),
            observation,
            canonical_value_digest({}),
            effect_class=EffectClass.EXTERNAL,
            replay_class=ReplayClass.DETERMINISTIC,
        )




def test_structural_memory_to_vm_page_preserves_bytes_and_coordinate_receipts():
    """Mathematics: π(source Structural Memory range) = π(demand-paged VM realization) for one pinned page."""
    import hashlib

    from mailcpu.law_certifier import Law

    page_size = 8
    operating_system = HeadlessOS(
        structural_memory_admission_policy=lambda proposal: proposal.spec.domain == "byte-stream"
    )
    proposal = operating_system.structural_memory.propose(
        "translation-page",
        Law(
            family="int",
            params={"x0": 65, "step": 1, "mod": 256},
            order=1,
            verdict="GROUND",
        ),
        {coordinate: 65 + coordinate for coordinate in range(page_size)},
        domain="byte-stream",
        context={"dataset": "translation-fixture", "encoding": "raw-byte"},
    )
    version = operating_system.structural_memory.admit(
        proposal.proposal_id,
        expected_revision=0,
    )
    reference = StructuralMemoryFileRef.from_version(
        version,
        coordinate_start=0,
        size=page_size,
    )

    source_receipts = [
        operating_system.structural_memory.read_revision(
            version.spec.memory_id,
            version.spec.revision,
            coordinate,
            context=version.spec.context,
        )
        for coordinate in range(page_size)
    ]
    source_bytes = bytes(receipt.value for receipt in source_receipts)
    page_digest = hashlib.sha256(source_bytes).hexdigest()

    backing = StructuralMemoryPageBacking(operating_system.structural_memory)
    backing.register_page_reference(page_digest, reference)
    memory = VirtualMemory(page_size=page_size, page_backing=backing)
    memory.reserve(
        0,
        page_size,
        writable=False,
        backing_blob_ids=(page_digest,),
    )
    target_bytes = memory.read(0, page_size)
    page_receipt = backing.read_receipt(page_digest)

    assert page_receipt is not None
    assert page_receipt.content_digest == page_digest
    assert page_receipt.spec_digest == version.spec.digest
    assert page_receipt.certificate_digest == version.certificate.digest
    assert page_receipt.context_digest == version.spec.context_digest
    assert page_receipt.value_receipt_ids == tuple(
        receipt.receipt_id for receipt in source_receipts
    )
    assert memory.mapped_pages()[0].blob_id == page_digest

    source_ref = structural_memory_spec_representation_ref(version.spec)
    target_ref = RepresentationRef.from_payload(
        "mailcpu.virtual-memory.page",
        1,
        {"page_digest": page_digest, "page_size": page_size},
    )
    mapping_ref = RepresentationRef.from_payload(
        "mailcpu.structural-memory-page-materializer",
        1,
        {
            "coordinate_rule": "coordinate_start + byte_offset",
            "guards": ["pinned_revision", "exact_context", "unsigned_byte", "range_receipts", "sha256"],
            "vm_transition": "reserved -> resident",
            "copy_on_write": "structural_base_is_immutable",
        },
    )
    observation = ObservationContract.from_definition(
        "mailcpu.byte-page-observation",
        1,
        {
            "fields": ["bytes_hex", "content_digest", "ordered_coordinate_receipt_ids"],
            "comparison": "canonical-json-exact",
        },
    )
    contract = TranslationContract(
        contract_id="structural-memory-to-vm-page",
        revision=1,
        source=source_ref,
        target=target_ref,
        mapping=mapping_ref,
        observation=observation,
        context_digest=version.spec.context_digest,
        precondition_digests=(
            canonical_value_digest({"page_size": page_size, "power_of_two": True}),
        ),
        invariant_digests=(
            canonical_value_digest({"page_digest": "sha256(bytes)", "one_receipt_per_coordinate": True}),
        ),
        resource_bounds=(ResourceBound("page_bytes", page_size, "bytes"),),
        effect_class=EffectClass.JOURNALED,
        replay_class=ReplayClass.DETERMINISTIC,
    )
    case_payload = {
        "memory_id": version.spec.memory_id,
        "revision": version.spec.revision,
        "coordinate_start": reference.coordinate_start,
        "page_size": page_size,
        "page_digest": page_digest,
    }
    source_observation = {
        "bytes_hex": source_bytes.hex(),
        "content_digest": hashlib.sha256(source_bytes).hexdigest(),
        "ordered_coordinate_receipt_ids": [receipt.receipt_id for receipt in source_receipts],
    }
    target_observation = {
        "bytes_hex": target_bytes.hex(),
        "content_digest": page_receipt.content_digest,
        "ordered_coordinate_receipt_ids": list(page_receipt.value_receipt_ids),
    }

    check = compare_projected_observations(
        contract,
        case_payload=case_payload,
        source_observation=source_observation,
        target_observation=target_observation,
    )

    assert check.equivalent is True
    assert check.source_observation_digest == check.target_observation_digest
    assert page_receipt.length == page_size


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
