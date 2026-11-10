"""Compare iterative, direct, and inverse navigation over an admitted E-CPU Ground.

The benchmark uses an integer modular progression because the current
ContextualOrbitNavigator has an exact O(1) direct evaluator and inverse for
this admitted family. Direct and inverse paths use the actual E-CPU registry,
address, observer, and receipt implementations.

Timings are local Python implementation measurements. They are not physical
hardware or energy claims. The sequential reference does not construct an
ObserverReceipt, so evidence-construction overhead is reported as part of the
direct and inverse E-CPU timings and is called out in the report.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import platform
import statistics
import time
from typing import Any, Sequence

from mailcpu import (
    ContextualOrbitAddress,
    ContextualOrbitNavigator,
    ObserverContract,
    RepresentationRef,
    SchedulerReading,
    StructuralMemoryRegistry,
    VirtualGroundRef,
    VirtualStructuralMemoryRef,
    contextual_orbit_context,
    structural_memory_spec_representation_ref,
    verify_observer_receipt,
)
from mailcpu.law_certifier import Law
from mailcpu.seed import SystemIdentity
from mailcpu.semantic_translation import ObservationContract, canonical_value_digest


_SCHEMA = "ecpu.state-space-navigation-experiment.v1"
_MODULUS = 1_000_003
_STEP = 37
_ORIGIN = 4
_DEFAULT_SIZES = (32, 256, 2_048, 16_384, 131_072, 524_288)


def _make_ground() -> tuple[
    StructuralMemoryRegistry,
    Law,
    ContextualOrbitAddress,
    ObserverContract,
]:
    """Admit one modular progression and bind it to a system Ground and observer."""
    system = SystemIdentity("state-space-navigation-experiment", 1)
    base_ground = VirtualGroundRef("a" * 64, "b" * 64, 41, "c" * 64)
    computational_ground = RepresentationRef.from_payload(
        "experiment.integer-modular-ground",
        1,
        {
            "domain": "integers-modulo",
            "modulus": _MODULUS,
            "meaning": "state-coordinate",
        },
    )
    extensions = {
        "experiment": "iteration-direct-inverse",
        "role": "navigation-benchmark",
    }
    context = contextual_orbit_context(
        system,
        base_ground,
        computational_ground,
        scheduler_id="state-space-scheduler",
        extensions=extensions,
    )
    law = Law(
        family="int",
        params={"x0": _ORIGIN, "step": _STEP, "mod": _MODULUS},
        order=1,
        verdict="GROUND",
    )
    registry = StructuralMemoryRegistry(admission_policy=lambda _proposal: True)
    proposal = registry.propose(
        "state-space-navigation-progression",
        law,
        {coordinate: law.navigate(coordinate) for coordinate in range(8)},
        domain="state-space-navigation-experiment",
        context=context,
    )
    version = registry.admit(proposal.proposal_id, expected_revision=0)
    memory_ref = VirtualStructuralMemoryRef.from_version(
        "state-space-navigation-generator",
        version,
        0,
    )
    base_address = ContextualOrbitAddress(
        system_identity=system,
        base_ground=base_ground,
        computational_ground=computational_ground,
        coordinate=SchedulerReading("state-space-scheduler", base_ground.coordinate),
        structural_memory=memory_ref,
        context_extensions=extensions,
    )
    observer = ObserverContract(
        observer_id="state-space-navigation-observer",
        revision=1,
        subject=structural_memory_spec_representation_ref(version.spec),
        interpretation=computational_ground,
        observation=ObservationContract.from_definition(
            "ecpu.experiment.integer-state",
            1,
            {
                "fields": [
                    "coordinate",
                    "offset",
                    "value",
                    "value_digest",
                ]
            },
        ),
        context_digest=canonical_value_digest(context),
    )
    return registry, law, base_address, observer


def _address_at(
    base_address: ContextualOrbitAddress,
    coordinate: int,
) -> ContextualOrbitAddress:
    """Construct the exact contextual address for one relative orbit coordinate."""
    memory_ref = replace(base_address.structural_memory, coordinate=coordinate)
    return replace(
        base_address,
        coordinate=SchedulerReading(
            base_address.coordinate.scheduler_id,
            base_address.base_ground.coordinate + coordinate,
        ),
        structural_memory=memory_ref,
    )


def _sequential_value(coordinate: int) -> int:
    """Replay x[t+1]=(x[t]+step) mod m for exactly t transitions."""
    value = _ORIGIN
    for _ in range(coordinate):
        value = (value + _STEP) % _MODULUS
    return value


def _median_ms(samples: Sequence[float]) -> float:
    return statistics.median(samples) * 1_000.0


def run_experiment(
    sizes: Sequence[int] = _DEFAULT_SIZES,
    *,
    repeats: int = 5,
) -> dict[str, Any]:
    """Run correctness and timing comparisons for each target coordinate."""
    if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    normalized_sizes = tuple(sizes)
    if not normalized_sizes:
        raise ValueError("at least one target size is required")
    if any(
        type(size) is not int or size < 0 or size + repeats >= _MODULUS
        for size in normalized_sizes
    ):
        raise ValueError(
            f"each target size must be a non-negative integer with size + repeats < {_MODULUS}"
        )

    setup_started = time.perf_counter()
    registry, law, base_address, observer = _make_ground()
    navigator = ContextualOrbitNavigator(registry)
    setup_ms = (time.perf_counter() - setup_started) * 1_000.0

    rows: list[dict[str, Any]] = []
    for size in normalized_sizes:
        sequential_samples: list[float] = []
        direct_samples: list[float] = []
        inverse_samples: list[float] = []
        direct_results = 0
        inverse_results = 0
        coordinates: list[int] = []

        # Distinct coordinates keep each actual registry observation cold.
        for repeat in range(repeats):
            coordinate = size + repeat
            coordinates.append(coordinate)
            target_value = law.navigate(coordinate)
            expected_coordinate = coordinate

            started = time.perf_counter()
            sequential_value = _sequential_value(coordinate)
            sequential_samples.append(time.perf_counter() - started)
            if sequential_value != target_value:
                raise AssertionError(
                    f"sequential result mismatch at coordinate {coordinate}"
                )

            address = _address_at(base_address, coordinate)
            started = time.perf_counter()
            direct = navigator.locate(
                address,
                observer,
                operation_id=f"state-space-direct-{size}-{repeat}",
                expected_value=target_value,
            )
            direct_samples.append(time.perf_counter() - started)
            if (
                direct.projection.value != target_value
                or direct.projection.orbit_offset != coordinate
                or direct.expanded_states != 0
                or not verify_observer_receipt(observer, direct.observation)
            ):
                raise AssertionError(
                    f"direct navigation failed verification at coordinate {coordinate}"
                )
            direct_results += 1

            started = time.perf_counter()
            inverse = navigator.locate_value(
                base_address,
                observer,
                target_value,
                operation_id=f"state-space-inverse-{size}-{repeat}",
            )
            inverse_samples.append(time.perf_counter() - started)
            if (
                inverse.target_value != target_value
                or inverse.orbit_coordinate != expected_coordinate
                or inverse.navigation.projection.value != target_value
                or inverse.expanded_states != 0
                or inverse.navigation.expanded_states != 0
                or not verify_observer_receipt(observer, inverse.navigation.observation)
            ):
                raise AssertionError(
                    f"inverse navigation failed verification at coordinate {coordinate}"
                )
            inverse_results += 1

        rows.append(
            {
                "target_coordinate": size,
                "sample_coordinates": coordinates,
                "target_values_verified": repeats,
                "sequential_iteration": {
                    "median_ms": _median_ms(sequential_samples),
                    "transition_evaluations_by_sample": coordinates,
                    "expanded_states_by_sample": coordinates,
                    "method": "repeat modular transition from coordinate zero",
                    "complexity": "O(t)",
                },
                "direct_evaluation": {
                    "median_ms": _median_ms(direct_samples),
                    "verified_observations": direct_results,
                    "generator_reads_per_query": 1,
                    "expanded_states_per_query": 0,
                    "complexity": "O(1) for the admitted integer-progression law",
                },
                "inverse_then_observe": {
                    "median_ms": _median_ms(inverse_samples),
                    "verified_observations": inverse_results,
                    "inverse_complexity": "O(1)",
                    "forward_verification": "exact law evaluation before receipt-backed observation",
                    "generator_evaluations_per_query": 2,
                    "expanded_states_per_query": 0,
                    "complexity": "O(1) for the admitted integer-progression law",
                },
                "all_methods_agree": True,
            }
        )

    return {
        "schema": _SCHEMA,
        "status": "PASS",
        "ground": {
            "family": "integer modular progression",
            "x0": _ORIGIN,
            "step": _STEP,
            "modulus": _MODULUS,
            "period": _MODULUS,
            "verification": "eight admitted witness coordinates plus exact query receipts",
        },
        "setup_ms": setup_ms,
        "repeats_per_size": repeats,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "results": rows,
        "measurement_notes": [
            "Ground proposal and admission are reported separately as setup_ms.",
            "Every timed direct and inverse query uses a distinct coordinate to avoid receipt-cache reuse.",
            "The sequential reference counts every recurrence transition and does not build an ObserverReceipt.",
            "Direct and inverse timings include the actual E-CPU navigator, registry, digest, and receipt work.",
            "The inverse path performs an exact forward check and then obtains the normal observer receipt.",
            "Wall-clock values are Python process measurements, not physical hardware or energy measurements.",
            "The complexity claims are specific to this admitted modular progression family.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes",
        default=",".join(str(item) for item in _DEFAULT_SIZES),
        help="comma-separated target coordinates below the modular period",
    )
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--quick", action="store_true", help="run a compact smoke experiment")
    parser.add_argument("--output", help="optional JSON output path")
    args = parser.parse_args()

    sizes = (
        (16, 128, 1_024, 8_192)
        if args.quick
        else tuple(int(item.strip()) for item in args.sizes.split(",") if item.strip())
    )
    report = run_experiment(sizes, repeats=2 if args.quick else args.repeats)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        from pathlib import Path

        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
