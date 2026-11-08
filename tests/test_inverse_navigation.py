from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu import (
    ConditionOperator,
    ContextualOrbitAddress,
    ContextualOrbitNavigator,
    NavigationError,
    ProcessContext,
    ProcessDescriptor,
    ProcessPathIndex,
    ProcessPathIndexError,
    SemanticAddress,
    StateCondition,
    StatePattern,
    StateUpdate,
    StructuralMemoryRegistry,
    TransitionRule,
    UpdateOperation,
    RepresentationRef,
    SchedulerReading,
    VirtualGroundRef,
    VirtualStructuralMemoryRef,
    contextual_orbit_context,
    structural_memory_spec_representation_ref,
    verify_navigation_witness,
    ObserverContract,
    ObserverOrbitError,
)
from mailcpu.law_certifier import Law, find_coordinate_fgraph, find_coordinate_gf2_bit
from mailcpu.seed import SystemIdentity
from mailcpu.semantic_translation import ObservationContract, canonical_value_digest
from mailcpu.temporal import TemporalFrame


def _admitted_law(law: Law, memory_id: str, offset: int = 0):
    system = SystemIdentity("inverse-system", 1)
    ground = VirtualGroundRef("a" * 64, "b" * 64, 20, "c" * 64)
    interpretation = RepresentationRef.from_payload(
        "test.inverse-computational-ground",
        1,
        {"domain": "integer", "purpose": "inverse-navigation"},
    )
    context = contextual_orbit_context(
        system,
        ground,
        interpretation,
        scheduler_id="inverse-scheduler",
        extensions={"profile": "direct-inverse-test"},
    )
    registry = StructuralMemoryRegistry(admission_policy=lambda proposal: True)
    witnesses = {coordinate: law.navigate(coordinate) for coordinate in range(8)}
    proposal = registry.propose(
        memory_id,
        law,
        witnesses,
        domain="direct-inverse-test",
        context=context,
    )
    version = registry.admit(proposal.proposal_id, expected_revision=0)
    ref = VirtualStructuralMemoryRef.from_version(f"{memory_id}-binding", version, offset)
    address = ContextualOrbitAddress(
        system_identity=system,
        base_ground=ground,
        computational_ground=interpretation,
        coordinate=SchedulerReading("inverse-scheduler", ground.coordinate + offset),
        structural_memory=ref,
        context_extensions={"profile": "direct-inverse-test"},
    )
    observer = ObserverContract(
        observer_id=f"{memory_id}-observer",
        revision=1,
        subject=structural_memory_spec_representation_ref(version.spec),
        interpretation=interpretation,
        observation=ObservationContract.from_definition(
            "mailcpu.orbit.inverse-value",
            1,
            {"projection": "one scalar state"},
        ),
        context_digest=canonical_value_digest(context),
    )
    return registry, version, law, address, observer


def test_gf2_bit_inverse_is_bounded_by_initial_register_not_orbit_period():
    law = Law(
        family="gf2",
        params={"C": [1, 1, 1], "init": [1, 1]},
        order=2,
        verdict="GROUND",
    )

    assert find_coordinate_gf2_bit(law.params["C"], law.params["init"], 1) == 0
    assert find_coordinate_gf2_bit(law.params["C"], law.params["init"], 0) == 2
    assert find_coordinate_gf2_bit(law.params["C"], law.params["init"], 2) is None
    assert law.find(0) == 2
    assert law.find(1) == 0
    assert law.navigate(2) == 0


def test_gf2_inverse_refuses_absent_bit_in_zero_register():
    law = Law(
        family="gf2",
        params={"C": [1, 1, 1], "init": [0, 0]},
        order=2,
        verdict="GROUND",
    )

    assert find_coordinate_gf2_bit(law.params["C"], law.params["init"], 1) is None
    assert law.find(1) is None


def test_finite_graph_inverse_uses_first_occurrence_in_preperiod_and_cycle():
    law = Law(
        family="fgraph",
        params={"mu": 2, "lam": 3, "orbit": [4, 8, 2, 3, 5]},
        order=3,
        verdict="GROUND",
    )

    assert find_coordinate_fgraph(law.params["orbit"], 8) == 1
    assert find_coordinate_fgraph(law.params["orbit"], 5) == 4
    assert find_coordinate_fgraph(law.params["orbit"], 99) is None
    assert law.find(3) == 3
    assert law.navigate(8) == 5


def test_contextual_orbit_navigator_inverts_gf2_and_fgraph_directly():
    gf2 = Law(
        family="gf2",
        params={"C": [1, 1, 1], "init": [1, 1]},
        order=2,
        verdict="GROUND",
    )
    registry, _, law, base_address, observer = _admitted_law(gf2, "gf2-orbit")
    result = ContextualOrbitNavigator(registry).locate_value(
        base_address,
        observer,
        target_value=0,
    )
    assert result.orbit_coordinate == 2
    assert result.inverse_complexity_bound == "O(L)"
    assert result.navigation.projection.value == 0
    assert result.expanded_states == 0

    graph = Law(
        family="fgraph",
        params={"mu": 2, "lam": 3, "orbit": [4, 8, 2, 3, 5]},
        order=3,
        verdict="GROUND",
    )
    registry, _, _, base_address, observer = _admitted_law(graph, "fgraph-orbit")
    result = ContextualOrbitNavigator(registry).locate_value(
        base_address,
        observer,
        target_value=5,
    )
    assert result.orbit_coordinate == 4
    assert result.inverse_complexity_bound == "O(1) after O(N) index compilation"
    assert result.navigation.projection.value == 5


def _linear_process() -> ProcessDescriptor:
    return ProcessDescriptor(
        "indexed-counter",
        "2",
        (
            TransitionRule(
                "increment",
                StatePattern((StateCondition(("count",), ConditionOperator.LT, 5),)),
                (StateUpdate(("count",), UpdateOperation.INCREMENT, 1),),
                {"cpu": 1},
            ),
        ),
        {"count": 0},
        (StatePattern((StateCondition(("count",), ConditionOperator.GE, 0),)),),
    )


def _linear_address(descriptor: ProcessDescriptor) -> SemanticAddress:
    return SemanticAddress(
        descriptor.process_id,
        descriptor.version,
        StatePattern((StateCondition(("count",), ConditionOperator.EQ, 3),)),
    )


def test_process_path_index_directly_locates_state_in_verified_history():
    descriptor = _linear_process()
    context = ProcessContext(descriptor.process_id, resource_capacity={"cpu": 1})
    address = _linear_address(descriptor)
    index = ProcessPathIndex.build(
        descriptor,
        context,
        ("increment", "increment", "increment", "increment"),
    )

    result = index.locate_state(descriptor, address, context, {"count": 3})

    assert result.path == ("increment", "increment", "increment")
    assert result.final_state == {"count": 3}
    assert result.expanded_states == 0
    assert verify_navigation_witness(descriptor, address, context, result)
    restored = ProcessPathIndex.from_dict(index.to_dict())
    assert restored.digest == index.digest
    assert restored.verify(descriptor, context)
    assert restored.locate_state(descriptor, address, context, {"count": 3}).path == result.path


def test_process_path_index_does_not_confuse_missing_state_with_global_unreachability():
    descriptor = _linear_process()
    context = ProcessContext(descriptor.process_id, resource_capacity={"cpu": 1})
    address = _linear_address(descriptor)
    index = ProcessPathIndex.build(descriptor, context, ("increment", "increment"))

    with pytest.raises(ProcessPathIndexError, match="absence is not proof"):
        index.locate_state(descriptor, address, context, {"count": 3})


def test_process_path_index_is_bound_to_descriptor_context_and_supplied_path():
    descriptor = _linear_process()
    context = ProcessContext(descriptor.process_id, resource_capacity={"cpu": 1})
    index = ProcessPathIndex.build(descriptor, context, ("increment", "increment"))
    address = SemanticAddress(
        descriptor.process_id,
        descriptor.version,
        StatePattern((StateCondition(("count",), ConditionOperator.EQ, 2),)),
    )

    with pytest.raises(ProcessPathIndexError, match="descriptor differs"):
        index.locate_state(replace(descriptor, transitions=()), address, context, {"count": 2})
    changed_context = replace(context, bindings={"tenant": "other"})
    with pytest.raises(ProcessPathIndexError, match="context differs"):
        index.locate_state(descriptor, address, changed_context, {"count": 2})
    assert not index.verify(descriptor, changed_context)


def test_process_path_index_rejects_unvalidated_transition_trace():
    descriptor = _linear_process()
    context = ProcessContext(descriptor.process_id, resource_capacity={"cpu": 1})

    with pytest.raises(ProcessPathIndexError, match="not declared"):
        ProcessPathIndex.build(descriptor, context, ("not-a-rule",))
    with pytest.raises(ProcessPathIndexError, match="not enabled"):
        ProcessPathIndex.build(descriptor, context, ("increment",) * 8)
