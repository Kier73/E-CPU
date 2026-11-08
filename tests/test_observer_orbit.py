from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu import (
    ContextualOrbitAddress,
    ContextualOrbitNavigator,
    ObserverAggregateReceipt,
    ObserverComposition,
    ObserverContract,
    ObserverOrbitError,
    ObserverReceipt,
    RepresentationRef,
    SchedulerReading,
    StructuralMemoryRegistry,
    VirtualGroundProjection,
    VirtualGroundRef,
    VirtualStructuralMemoryRef,
    compose_observer_receipts,
    contextual_orbit_context,
    structural_memory_spec_representation_ref,
    verify_observer_receipt,
)
from mailcpu.law_certifier import Law
from mailcpu.semantic_translation import ObservationContract, canonical_value_digest
from mailcpu.seed import SystemIdentity
from mailcpu.temporal import TemporalFrame


def _base() -> tuple[SystemIdentity, VirtualGroundRef, RepresentationRef]:
    system = SystemIdentity("orbit-system", 1)
    ground = VirtualGroundRef("a" * 64, "b" * 64, 41, "c" * 64)
    interpretation = RepresentationRef.from_payload(
        "test.computational-ground",
        1,
        {"domain": "integer", "meaning": "counter-state"},
    )
    return system, ground, interpretation


def _admitted_lcg(*, offset: int = 10**12 + 3):
    system, base_ground, interpretation = _base()
    context = contextual_orbit_context(
        system,
        base_ground,
        interpretation,
        scheduler_id="vm-scheduler",
        extensions={"lane": "primary", "purpose": "test"},
    )
    law = Law(
        family="lcg",
        params={"a": 5, "c": 1, "mod": 2**32, "x0": 13},
        order=1,
        verdict="GROUND",
    )
    registry = StructuralMemoryRegistry(admission_policy=lambda proposal: True)
    witnesses = {coordinate: law.navigate(coordinate) for coordinate in range(8)}
    proposal = registry.propose(
        "symbolic-orbit",
        law,
        witnesses,
        domain="contextual-orbit-test",
        context=context,
    )
    version = registry.admit(proposal.proposal_id, expected_revision=0)
    memory_ref = VirtualStructuralMemoryRef.from_version(
        "orbit-generator",
        version,
        offset,
    )
    address = ContextualOrbitAddress(
        system_identity=system,
        base_ground=base_ground,
        computational_ground=interpretation,
        coordinate=SchedulerReading(
            "vm-scheduler",
            base_ground.coordinate + offset,
        ),
        structural_memory=memory_ref,
        context_extensions={"lane": "primary", "purpose": "test"},
    )
    subject = structural_memory_spec_representation_ref(version.spec)
    observer = ObserverContract(
        observer_id="orbit-observer",
        revision=1,
        subject=subject,
        interpretation=interpretation,
        observation=ObservationContract.from_definition(
            "mailcpu.orbit.scalar-value",
            1,
            {"fields": ["coordinate", "offset", "value", "value_digest"]},
        ),
        context_digest=canonical_value_digest(context),
    )
    return registry, law, address, observer


def test_contextual_orbit_address_round_trip_binds_system_ground_clock_and_offset():
    _, _, address, _ = _admitted_lcg()

    restored = ContextualOrbitAddress.from_dict(address.to_dict())

    assert restored.digest == address.digest
    assert restored.orbit_offset == 10**12 + 3
    assert restored.coordinate.tick == address.base_ground.coordinate + restored.orbit_offset


def test_contextual_orbit_address_rejects_misaligned_structural_memory_coordinate():
    _, _, address, _ = _admitted_lcg(offset=17)

    wrong_reference = replace(address.structural_memory, coordinate=18)
    with pytest.raises(ObserverOrbitError, match="relative orbit offset"):
        replace(address, structural_memory=wrong_reference)


def test_symbolic_orbit_navigation_jumps_to_remote_coordinate_without_expansion(monkeypatch):
    registry, law, address, observer = _admitted_lcg()
    calls: list[int] = []
    original = registry.generators.navigate_guarded

    def counted(spec, coordinate):
        calls.append(coordinate)
        return original(spec, coordinate)

    monkeypatch.setattr(registry.generators, "navigate_guarded", counted)
    navigator = ContextualOrbitNavigator(registry)
    expected = law.navigate(address.orbit_offset)

    first = navigator.locate(address, observer, expected_value=expected)
    second = navigator.locate(address, observer, expected_value=expected)

    assert first.projection.value == expected
    assert first.projection.coordinate == address.coordinate
    assert first.projection.base_ground == address.base_ground
    assert first.complexity_bound == "O(log n)"
    assert first.generator_family == "lcg"
    assert first.expanded_states == 0
    assert first.observation.projection["orbit_offset"] == address.orbit_offset
    assert first.projection.projection_digest == second.projection.projection_digest
    assert first.projection.read_receipt.cache_hit is False
    assert second.projection.read_receipt.cache_hit is True
    assert VirtualGroundProjection.from_dict(first.projection.to_dict()) == first.projection
    assert ObserverReceipt.from_dict(first.observation.to_dict()) == first.observation
    assert calls == [address.orbit_offset]


def test_orbit_navigator_refuses_wrong_observer_context_or_interpretation():
    _, _, address, observer = _admitted_lcg(offset=20)
    navigator = ContextualOrbitNavigator(_admitted_lcg(offset=20)[0])

    wrong_context = replace(observer, context_digest="d" * 64)
    with pytest.raises(ObserverOrbitError, match="observer context"):
        navigator.locate(address, wrong_context)

    wrong_interpretation = replace(
        observer,
        interpretation=RepresentationRef.from_payload("other-ground", 1, {"meaning": "other"}),
    )
    with pytest.raises(ObserverOrbitError, match="Computational Ground"):
        navigator.locate(address, wrong_interpretation)


def test_orbit_navigator_requires_matching_typed_scheduler_frame():
    _, _, address, observer = _admitted_lcg(offset=20)
    registry, _, _, _ = _admitted_lcg(offset=20)
    navigator = ContextualOrbitNavigator(registry)
    wrong_frame = TemporalFrame(
        actor_id=observer.observer_id,
        scheduler=SchedulerReading("another-scheduler", address.coordinate.tick),
    )

    with pytest.raises(ObserverOrbitError, match="scheduler coordinate"):
        navigator.locate(address, observer, time_frame=wrong_frame)


def test_observer_receipt_binds_contract_projection_context_and_evidence():
    _, _, _, observer = _admitted_lcg(offset=20)
    evidence = RepresentationRef.from_payload("test.evidence", 1, {"sample": 9})
    receipt = ObserverReceipt.issue(
        observer,
        operation_id="observe-orbit",
        input_digest="e" * 64,
        projection_value={"value": 9, "coordinate": 20},
        time_frame=TemporalFrame(observer.observer_id, scheduler=SchedulerReading("vm-scheduler", 20)),
        evidence=(evidence,),
    )

    assert verify_observer_receipt(observer, receipt)
    assert ObserverContract.from_dict(observer.to_dict()) == observer
    assert ObserverReceipt.from_dict(receipt.to_dict()) == receipt
    assert receipt.digest == canonical_value_digest(receipt.to_dict())
    assert receipt.projection == {"coordinate": 20, "value": 9}
    assert not verify_observer_receipt(
        replace(observer, revision=2),
        receipt,
    )
    with pytest.raises(ObserverOrbitError, match="projection digest"):
        replace(receipt, projection_json='{"value":10}')


def test_observer_composition_preserves_distinct_projections_without_claiming_consensus():
    subject = RepresentationRef.from_payload("test.subject", 1, {"state": "x"})
    interpretation = RepresentationRef.from_payload("test.ground", 1, {"meaning": "x"})
    context_digest = canonical_value_digest({"tenant": "alpha"})
    shared_observation = ObservationContract.from_definition(
        "test.shared-projection-family",
        1,
        {"contract": "bounded observations, distinct schemas"},
    )
    first_contract = ObserverContract(
        "observer-a", 1, subject, interpretation, shared_observation, context_digest
    )
    second_contract = ObserverContract(
        "observer-b", 1, subject, interpretation, shared_observation, context_digest
    )
    composition = ObserverComposition("pair", 1, (first_contract, second_contract))
    scheduler = SchedulerReading("shared-scheduler", 77)
    before = canonical_value_digest({"state": "before"})
    after = canonical_value_digest({"state": "after"})
    first = ObserverReceipt.issue(
        first_contract,
        operation_id="shared-observation",
        input_digest="f" * 64,
        projection_value={"sensor": "temperature", "value": 21},
        time_frame=TemporalFrame("observer-a", scheduler=scheduler),
        subject_state_before_digest=before,
        subject_state_after_digest=after,
    )
    second = ObserverReceipt.issue(
        second_contract,
        operation_id="shared-observation",
        input_digest="f" * 64,
        projection_value={"sensor": "pressure", "value": 101},
        time_frame=TemporalFrame("observer-b", scheduler=scheduler),
        subject_state_before_digest=before,
        subject_state_after_digest=after,
    )

    aggregate = compose_observer_receipts(composition, (second, first))

    assert aggregate.to_dict()["semantics"] == "aggregation-not-consensus"
    assert ObserverComposition.from_dict(composition.to_dict()) == composition
    assert ObserverAggregateReceipt.from_dict(aggregate.to_dict()) == aggregate
    assert [member.observer_id for member in aggregate.members] == ["observer-a", "observer-b"]
    assert aggregate.members[0].projection["sensor"] == "temperature"
    assert aggregate.members[1].projection["sensor"] == "pressure"
    assert aggregate.members[0].projection_digest != aggregate.members[1].projection_digest
    assert aggregate.digest == canonical_value_digest(aggregate.to_dict())


def test_observer_composition_rejects_missing_member_and_disagreeing_scheduler():
    subject = RepresentationRef.from_payload("test.subject", 1, {"state": "x"})
    interpretation = RepresentationRef.from_payload("test.ground", 1, {"meaning": "x"})
    context_digest = canonical_value_digest({"tenant": "alpha"})
    observation = ObservationContract.from_definition("test.observe", 1, {"projection": "x"})
    first_contract = ObserverContract("observer-a", 1, subject, interpretation, observation, context_digest)
    second_contract = ObserverContract("observer-b", 1, subject, interpretation, observation, context_digest)
    composition = ObserverComposition("pair", 1, (first_contract, second_contract))
    first = ObserverReceipt.issue(
        first_contract,
        operation_id="op",
        input_digest="1" * 64,
        projection_value={"value": 1},
        time_frame=TemporalFrame("observer-a", scheduler=SchedulerReading("sched", 4)),
    )
    second = ObserverReceipt.issue(
        second_contract,
        operation_id="op",
        input_digest="1" * 64,
        projection_value={"value": 2},
        time_frame=TemporalFrame("observer-b", scheduler=SchedulerReading("sched", 5)),
    )

    with pytest.raises(ObserverOrbitError, match="exactly match"):
        compose_observer_receipts(composition, (first,))
    with pytest.raises(ObserverOrbitError, match="scheduler coordinates"):
        compose_observer_receipts(composition, (first, second))
