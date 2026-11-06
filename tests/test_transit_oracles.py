"""Independent bounded semantic-oracle tests for receiver-side Transit paths."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mailcpu import (
    HypervisorArbitrationEvent,
    HypervisorRequest,
    StructuralMemoryRegistry,
    TransitComputeHost,
    TransitOracleEvidence,
    canonical_value_digest,
)
from mailcpu.law_certifier import Law
from mailcpu.transit_oracles import (
    MAX_STRUCTURAL_ORACLE_PARAMETER_BYTES,
    TransitOracleError,
    _reference_structural_value,
    build_transit_oracle_evidence,
)
from mailcpu.transit_structural_memory import (
    TRANSIT_STRUCTURAL_MEMORY_OPERATION,
    TRANSIT_STRUCTURAL_MEMORY_RESOURCE,
)


def _cpu_event() -> HypervisorArbitrationEvent:
    source = "\n".join(
        (
            "set left 11",
            "set right 4",
            "compare positive left right",
            "branch positive high",
            "set answer 0",
            "halt",
            "high: add answer left right",
            "halt",
        )
    )
    return HypervisorArbitrationEvent(
        "oracle-client",
        "compute",
        1,
        17,
        HypervisorRequest(
            "execute deterministic CPU arithmetic program",
            "/cpu/compute",
            {
                "source": source,
                "initial_registers": {"seed": 9},
                "max_ticks": 32,
            },
            frozenset({"execute"}),
            frozenset({"execute"}),
        ),
    )


def _structural_event(
    memory_id: str,
    revision: int,
    coordinate: int,
    context: dict[str, object],
    sequence: int,
) -> HypervisorArbitrationEvent:
    return HypervisorArbitrationEvent(
        "oracle-client",
        "structural.read",
        sequence,
        100 + sequence,
        HypervisorRequest(
            TRANSIT_STRUCTURAL_MEMORY_OPERATION,
            TRANSIT_STRUCTURAL_MEMORY_RESOURCE,
            {
                "memory_id": memory_id,
                "revision": revision,
                "context": context,
                "coordinate": coordinate,
            },
            frozenset({"read"}),
            frozenset({"read"}),
        ),
    )


def _admit(
    memory_id: str,
    law: Law,
    witnesses: dict[int, int],
    context: dict[str, object],
):
    registry = StructuralMemoryRegistry(admission_policy=lambda proposal: True)
    proposal = registry.propose(
        memory_id,
        law,
        witnesses,
        domain="integer-orbit",
        context=context,
    )
    version = registry.admit(proposal.proposal_id, expected_revision=0)
    return SimpleNamespace(structural_memory=registry), registry, version


def test_cpu_oracle_matches_scheduled_transit_compute_and_binds_case():
    event = _cpu_event()
    effect = TransitComputeHost().handle(event)

    evidence = build_transit_oracle_evidence(event, effect, SimpleNamespace())

    assert evidence is not None
    assert evidence.oracle.type_id == "mailcpu.transit.semantic-oracle.cpu-arithmetic"
    assert evidence.equivalent is True
    assert evidence.expected_observation == {
        "status": "exited",
        "exit_code": 0,
        "pc": 7,
        "steps": 6,
        "registers": {"answer": 15, "left": 11, "positive": 1, "right": 4, "seed": 9},
    }
    assert evidence.work_units == 6
    assert evidence.work_limit == 32
    assert evidence.request_fingerprint == canonical_value_digest(event.to_dict())
    restored = TransitOracleEvidence.from_dict(evidence.to_dict())
    assert restored == evidence
    assert restored.digest == evidence.digest
    restored.validate_against_effect(
        effect,
        request_fingerprint=evidence.request_fingerprint,
    )


@pytest.mark.parametrize(
    "memory_id,law,witnesses,coordinates",
    [
        (
            "oracle-int",
            Law("int", {"x0": 19, "step": 7, "mod": 113}, 1, "GROUND"),
            {0: 19, 1: 26, 2: 33, 3: 40},
            (0, 1, 2, 17, 100_000),
        ),
        (
            "oracle-lcg",
            Law("lcg", {"a": 7, "c": 5, "mod": 97, "x0": 3}, 1, "GROUND"),
            {0: 3, 1: 26, 2: 90, 3: 53},
            (0, 1, 2, 17, 100_000),
        ),
        (
            "oracle-gf2",
            Law("gf2", {"C": [1, 1, 1], "init": [1, 1]}, 2, "GROUND"),
            {0: 1, 1: 1, 2: 0, 3: 1},
            (0, 1, 2, 17, 100_000),
        ),
        (
            "oracle-fgraph",
            Law("fgraph", {"orbit": [10, 20, 30, 40, 50], "mu": 3, "lam": 2}, 2, "GROUND"),
            {0: 10, 1: 20, 2: 30, 3: 40},
            (0, 1, 2, 17, 100_000),
        ),
    ],
)
def test_structural_oracle_independently_derives_admitted_generator_families(
    memory_id,
    law,
    witnesses,
    coordinates,
):
    context = {"tenant": "oracle", "scope": "test"}
    operating_system, registry, version = _admit(memory_id, law, witnesses, context)

    for sequence, coordinate in enumerate(coordinates, start=1):
        event = _structural_event(
            memory_id,
            version.spec.revision,
            coordinate,
            context,
            sequence,
        )
        receipt = registry.read_revision(
            memory_id,
            version.spec.revision,
            coordinate,
            context=context,
        )
        evidence = build_transit_oracle_evidence(
            event,
            receipt.to_dict(),
            operating_system,
        )

        assert evidence is not None
        assert evidence.oracle.type_id == (
            "mailcpu.transit.semantic-oracle.structural-memory-coordinate"
        )
        assert evidence.equivalent is True
        assert evidence.expected_observation == evidence.observed_observation
        assert 1 <= evidence.work_units <= evidence.work_limit
        assert evidence.request_fingerprint == canonical_value_digest(event.to_dict())
        evidence.validate_against_effect(
            receipt.to_dict(),
            request_fingerprint=evidence.request_fingerprint,
        )


def test_cpu_oracle_rejects_a_backend_effect_with_wrong_register_value():
    event = _cpu_event()
    effect = TransitComputeHost().handle(event)
    evidence = build_transit_oracle_evidence(event, effect, SimpleNamespace())
    assert evidence is not None

    forged_effect = dict(effect)
    forged_effect["registers"] = dict(effect["registers"])
    forged_effect["registers"]["answer"] = 14

    with pytest.raises(ValueError, match="does not match"):
        evidence.validate_against_effect(
            forged_effect,
            request_fingerprint=evidence.request_fingerprint,
        )


def test_structural_oracle_refuses_prefix_coordinates_at_the_exclusive_horizon():
    context = {"tenant": "oracle", "scope": "prefix"}
    law = Law(
        "int",
        {"x0": 0, "step": 1, "mod": 97},
        1,
        "PREFIX-GROUND",
        first_bad=3,
    )
    operating_system, registry, version = _admit(
        "oracle-prefix",
        law,
        {0: 0, 1: 1, 2: 2, 3: 99},
        context,
    )
    event = _structural_event(
        "oracle-prefix",
        version.spec.revision,
        3,
        context,
        1,
    )

    with pytest.raises(TransitOracleError, match="horizon"):
        build_transit_oracle_evidence(event, {}, operating_system)


def test_structural_oracle_bounds_parameter_description_before_parsing():
    class OversizedSpec:
        """Provide an oversized immutable parameter encoding without allowing it to be parsed."""

        family = "int"
        order = 1
        parameters_json = " " * (MAX_STRUCTURAL_ORACLE_PARAMETER_BYTES + 1)

        @property
        def parameters(self):
            """Fail if oracle parses a parameter description before checking its byte bound."""
            raise AssertionError("oversized parameter description was parsed")

    with pytest.raises(TransitOracleError, match="parameter description"):
        _reference_structural_value(OversizedSpec(), 0)


def test_structural_oracle_refuses_unbounded_integer_width_before_evaluation():
    context = {"tenant": "oracle", "scope": "bounded"}
    law = Law("int", {"x0": 0, "step": 1, "mod": 97}, 1, "GROUND")
    operating_system, _registry, version = _admit(
        "oracle-bounded",
        law,
        {0: 0, 1: 1, 2: 2},
        context,
    )
    event = _structural_event(
        "oracle-bounded",
        version.spec.revision,
        1 << 4096,
        context,
        1,
    )

    with pytest.raises(TransitOracleError, match="integer-width"):
        build_transit_oracle_evidence(event, {}, operating_system)
