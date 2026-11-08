from __future__ import annotations

from dataclasses import replace
import json

import pytest

from mailcpu import (
    ComposedComponentAddress,
    ComposedGroundError,
    ComposedVirtualGroundAddress,
    ComposedVirtualGroundNavigator,
    ComposedVirtualGroundProjection,
    ObserverOrbitError,
    ContextualOrbitAddress,
    RepresentationRef,
    SchedulerReading,
    StructuralMemoryRegistry,
    VirtualGroundRef,
    VirtualStructuralMemoryRef,
    composed_component_context,
)
from mailcpu.law_certifier import Law
from mailcpu.seed import SystemIdentity
from mailcpu.semantic_translation import canonical_value_digest
from mailcpu.temporal import TemporalFrame


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _fixture():
    system = SystemIdentity("composed-os", 3)
    ground = VirtualGroundRef("a" * 64, "b" * 64, 500, "c" * 64)
    computational_ground = RepresentationRef.from_payload(
        "mailcpu.computational-ground",
        1,
        {"meaning": "virtual-os-state", "domain": "mixed integer fields"},
    )
    state_schema = RepresentationRef.from_payload(
        "mailcpu.virtual-os-schema",
        1,
        {
            "cpu.pc": "instruction-coordinate",
            "cpu.accumulator": "integer-register",
            "memory.dirty": "bit",
        },
    )
    template = {
        "cpu": {"pc": 0, "accumulator": 0},
        "memory": {"dirty": 0, "resident_pages": 16},
        "scheduler": {"tick": 0},
    }
    laws = (
        (
            "program-counter",
            ("cpu", "pc"),
            RepresentationRef.from_payload("mailcpu.register.pc", 1, {"kind": "uint64", "meaning": "next instruction"}),
            "integer",
            Law("int", {"x0": 7, "step": 3, "mod": 101}, 1, "GROUND"),
        ),
        (
            "accumulator",
            ("cpu", "accumulator"),
            RepresentationRef.from_payload("mailcpu.register.accumulator", 1, {"kind": "uint32", "meaning": "accumulated value"}),
            "integer",
            Law("lcg", {"a": 5, "c": 1, "mod": 2**16, "x0": 13}, 1, "GROUND"),
        ),
        (
            "dirty-bit",
            ("memory", "dirty"),
            RepresentationRef.from_payload("mailcpu.memory.dirty-bit", 1, {"kind": "bit", "meaning": "dirty page indicator"}),
            "bit",
            Law("gf2", {"C": [1, 1, 1], "init": [1, 1]}, 2, "GROUND"),
        ),
    )
    registry = StructuralMemoryRegistry(admission_policy=lambda proposal: True)
    components = []
    offset = 11
    for component_id, path, representation, value_kind, law in laws:
        context = composed_component_context(
            system,
            ground,
            computational_ground,
            state_schema,
            template,
            scheduler_id="os-scheduler",
            component_id=component_id,
            field_path=path,
            representation=representation,
            value_kind=value_kind,
        )
        proposal = registry.propose(
            f"memory-{component_id}",
            law,
            {coordinate: law.navigate(coordinate) for coordinate in range(8)},
            domain="composed-os-component",
            context=context,
        )
        version = registry.admit(proposal.proposal_id, expected_revision=0)
        memory_ref = VirtualStructuralMemoryRef.from_version(
            f"binding-{component_id}",
            version,
            offset,
        )
        orbit_address = ContextualOrbitAddress(
            system_identity=system,
            base_ground=ground,
            computational_ground=computational_ground,
            coordinate=SchedulerReading("os-scheduler", ground.coordinate + offset),
            structural_memory=memory_ref,
            context_extensions=context["extensions"],
        )
        components.append(
            ComposedComponentAddress(
                component_id=component_id,
                field_path=path,
                representation=representation,
                value_kind=value_kind,
                orbit_address=orbit_address,
            )
        )
    address = ComposedVirtualGroundAddress(
        system_identity=system,
        base_ground=ground,
        computational_ground=computational_ground,
        coordinate=SchedulerReading("os-scheduler", ground.coordinate + offset),
        state_schema=state_schema,
        template_json=_canonical(template),
        components=tuple(components),
    )
    return registry, address, laws


def test_composed_virtual_ground_generates_multi_component_state_at_one_coordinate():
    registry, address, laws = _fixture()

    result = ComposedVirtualGroundNavigator(registry).locate(address)

    expected = address.template
    for component_id, path, _, _, law in laws:
        current = expected
        for part in path[:-1]:
            current = current[part]
        current[path[-1]] = law.navigate(address.orbit_offset)

    assert result.projection.state == expected
    assert result.projection.state_digest == canonical_value_digest(expected)
    assert result.projection.base_ground == address.base_ground
    assert result.projection.coordinate == address.coordinate
    assert result.expanded_states == 0
    assert {name for name, _, _ in result.generator_profiles} == {
        "program-counter", "accumulator", "dirty-bit"
    }
    assert [item.address.component_id for item in result.projection.components] == [
        "accumulator", "dirty-bit", "program-counter"
    ]
    assert all(item.projection.read_receipt.coordinate == address.orbit_offset for item in result.projection.components)


def test_composed_virtual_ground_projection_and_address_round_trip():
    registry, address, _ = _fixture()
    result = ComposedVirtualGroundNavigator(registry).locate(address)

    restored_address = ComposedVirtualGroundAddress.from_dict(address.to_dict())
    restored_projection = ComposedVirtualGroundProjection.from_dict(result.projection.to_dict())

    assert restored_address.digest == address.digest
    assert restored_projection == result.projection
    assert restored_projection.projection_digest == result.projection.projection_digest
    assert restored_projection.evidence_digest == result.projection.evidence_digest


def test_composed_virtual_ground_rejects_component_context_or_template_drift():
    _, address, _ = _fixture()
    changed_template = address.template
    changed_template["cpu"]["pc"] = 1

    with pytest.raises(ComposedGroundError, match="context is not bound"):
        replace(address, template_json=_canonical(changed_template))


def test_composed_virtual_ground_rejects_overlapping_field_paths():
    _, address, _ = _fixture()
    first, second, third = address.components
    overlapping = replace(second, field_path=first.field_path)

    with pytest.raises(ComposedGroundError, match="overlapping"):
        replace(address, components=(first, overlapping, third))


def test_composed_virtual_ground_rejects_stale_component_coordinate():
    _, address, _ = _fixture()
    with pytest.raises(ObserverOrbitError):
        replace(address.components[0].orbit_address, coordinate=SchedulerReading("os-scheduler", address.coordinate.tick + 1))


def test_composed_virtual_ground_can_bind_a_target_state_digest():
    registry, address, laws = _fixture()
    result = ComposedVirtualGroundNavigator(registry).locate(address)
    assert ComposedVirtualGroundNavigator(registry).locate(
        address,
        expected_state_digest=result.projection.state_digest,
    ).projection.state_digest == result.projection.state_digest
    with pytest.raises(ComposedGroundError, match="expected_state_digest"):
        ComposedVirtualGroundNavigator(registry).locate(address, expected_state_digest="f" * 64)


def test_composed_projection_embeds_and_verifies_its_complete_source_address():
    registry, address, _ = _fixture()
    projection = ComposedVirtualGroundNavigator(registry).locate(address).projection
    encoded = projection.to_dict()
    tampered = dict(encoded)
    tampered_address = dict(encoded["address"])
    tampered_address["orbit_offset"] += 1
    tampered["address"] = tampered_address

    with pytest.raises(ComposedGroundError):
        ComposedVirtualGroundProjection.from_dict(tampered)
