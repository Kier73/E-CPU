"""ITR-001: measure intention -> qualified realization using existing E-CPU facilities.

A receiver supplies *capabilities* (a sensor, primitive palette, eligible hosts),
not source coefficients, a selected algorithm, or a processor architecture.

Cold: ONP-001 qualified source -> IPS-003 synthesized primitive program ->
       native Ground verification -> INTENT-001 generated processor -> SAB-001.
Warm: independently requalify retained source evidence -> derive a new goal's
       source law -> INTENT-001 quotient and SAB-001 on current host capacity.
An already verified *identical* goal may use its retained observation directly.

All measurements are end-to-end local monotonic-clock spans, not a claim of
network, proof construction, or hardware independent of the source contracts.
"""
from __future__ import annotations

from dataclasses import dataclass
from .intention_realization_metrics import IntentionReceipt, summarize_campaign
from time import perf_counter_ns
from typing import Any, Callable, Mapping, Sequence

from .intention_formed_fabric import (
    FiniteObserverLaw, FormedRealization, realize_formed_intention,
    verify_formed_machine,
)
from .observation_formed_processor import (
    ObserverConstructionIntention, ObservedProcessorRealization,
    ProbeOffer, realize_observed_processor, verify_observed_processor,
    ObservationFormationRefused,
)
from .generative_ground_construction import AffinePrimitive
from .ground_native_realization import RealizationPolicy
from .substrate_bootstrap import (
    BootstrapPolicy, CarrierBinding, SubstrateObservation,
    verify_bootstrap_report,
)
from .semantic_translation import canonical_value_digest


@dataclass(frozen=True)
class ReceiverCapacity:
    """Available computational resources, not a designated program or CPU."""

    offers: tuple[ProbeOffer, ...]
    primitives: tuple[AffinePrimitive, ...]
    observation_policy: RealizationPolicy
    trusted_keys: Mapping[str, bytes]
    inventory: SubstrateObservation
    fabric_policy: BootstrapPolicy
    carriers: tuple[CarrierBinding, ...]
    admitted_interpreters: tuple[str, ...]
    admitted_observers: tuple[str, ...]
    ingress: str
    observer: str
    coordinate: int
    locus: str = "onp001-local"

    def __post_init__(self) -> None:
        if (not isinstance(self.offers, tuple) or not self.offers
            or not isinstance(self.primitives, tuple) or not self.primitives
            or not isinstance(self.observation_policy, RealizationPolicy)
            or not isinstance(self.inventory, SubstrateObservation)
            or not isinstance(self.fabric_policy, BootstrapPolicy)
            or not isinstance(self.carriers, tuple)):
            raise ObservationFormationRefused("Typed, finite receiver capacities required")




def _same_source(seed: ObserverConstructionIntention,
                 goal: ObserverConstructionIntention) -> bool:
    """Only the requested coordinate may change; no implicit source substitution."""
    return (isinstance(goal, ObserverConstructionIntention)
            and (seed.relation, seed.source_digest, seed.observer_id,
                 seed.authority_digest, seed.modulus)
            == (goal.relation, goal.source_digest, goal.observer_id,
                goal.authority_digest, goal.modulus))


def _derive_source(report: ObservedProcessorRealization) -> FiniteObserverLaw:
    """Translate only already source-verified affine coefficients into a law."""
    m = report.intention.modulus
    observed = report.sufficiency_resolution["result"]
    a, c = observed["multiplier"], observed["offset"]
    if (type(a) is not int or type(c) is not int or not 0 <= a < m or not 0 <= c < m):
        raise ObservationFormationRefused("Invalid recovered source coefficients")
    return FiniteObserverLaw(
        states=tuple(f"v{x:02d}" for x in range(m)),
        actions=("step",),
        fields=("value",),
        transitions=tuple(((a*x+c)%m,) for x in range(m)),
        observations=tuple((x,) for x in range(m)),
    )


def warm_realize(
    source_evidence: ObservedProcessorRealization,
    goal: ObserverConstructionIntention,
    capacity: ReceiverCapacity,
    *, now: int,
    clock_ns: Callable[[], int] = perf_counter_ns,
    reuse_identical_goal: bool = True,
) -> tuple[IntentionReceipt, FormedRealization | None]:
    """Translate one admitted source law into a new goal, without new probes.

    The returned native realization is None for exact cached-goal reuse; then
    a checked retained result, not a newly executed host operation, is used.
    Every call independently checks source signatures, proof, policy and TTL.
    """
    if (not isinstance(source_evidence, ObservedProcessorRealization)
            or not _same_source(source_evidence.intention, goal)):
        raise ObservationFormationRefused("Intention source, observer or authority changed")
    t0 = clock_ns()
    verify_observed_processor(
        source_evidence, source_evidence.intention, capacity.offers,
        capacity.primitives, capacity.observation_policy, capacity.trusted_keys,
        now=now, locus=capacity.locus,
    )
    t1 = clock_ns()
    source = _derive_source(source_evidence)
    t2 = clock_ns()
    if reuse_identical_goal and goal == source_evidence.intention:
        output = source_evidence.realization.output
        expected = source.replay(f"v{goal.query_input:02d}", ["step"], ("value",))["value"]
        if type(output) is not int or output != expected:
            raise ObservationFormationRefused("Retained result disagrees with the verified source")
        t3 = clock_ns()
        receipt = IntentionReceipt(
            "verified-retained-result", goal.digest, source_evidence.digest,
            source.fingerprint, None, None, output, 0,
            {"qualification": t1-t0, "source_translation": t2-t1,
             "retained_realization": t3-t2},
            canonical_value_digest({"original": source_evidence.digest,
                                    "goal": goal.digest, "value": output}),
        )
        return receipt, None

    formed = realize_formed_intention(
        source, ("value",), f"v{goal.query_input:02d}", ("step",),
        capacity.inventory, capacity.fabric_policy, capacity.carriers,
        admitted_interpreters=capacity.admitted_interpreters,
        admitted_observers=capacity.admitted_observers,
        ingress=capacity.ingress, observer=capacity.observer,
        coordinate=capacity.coordinate,
    )
    verify_formed_machine(source, formed.machine)
    verify_bootstrap_report(formed.report, formed.task, formed.plan)
    t3 = clock_ns()
    expected = source.replay(f"v{goal.query_input:02d}", ["step"], ("value",))["value"]
    output = formed.report["output"]["observation"]["value"]
    if (type(output) is not int or output != expected
            or formed.report["output"]["machine_digest"] != formed.machine.fingerprint
            or formed.machine.source_digest != source.fingerprint):
        raise ObservationFormationRefused("Formed host result does not satisfy intention")
    t4 = clock_ns()
    receipt = IntentionReceipt(
        "verified-reformed-processor", goal.digest, source_evidence.digest,
        source.fingerprint, formed.machine.fingerprint,
        formed.plan.fingerprint, output, 0,
        {"qualification": t1-t0, "source_translation": t2-t1,
         "processor_path_and_execution": t3-t2, "final_audit": t4-t3},
        canonical_value_digest({"source": source_evidence.digest,
                                "goal": goal.digest,
                                "machine": formed.machine.fingerprint,
                                "route": formed.plan.fingerprint,
                                "output": formed.report["output"]}),
    )
    return receipt, formed


def cold_realize(
    goal: ObserverConstructionIntention,
    capacity: ReceiverCapacity,
    sensors: Mapping[str, Callable[..., dict[str, Any]]],
    *, now: int,
    nonce_factory: Callable[[], str],
    clock_ns: Callable[[], int] = perf_counter_ns,
) -> tuple[IntentionReceipt, ObservedProcessorRealization, FormedRealization]:
    """Discover the entire sufficient computational structure from observations.

    No inferred source coefficients, chosen program or processor host enter the
    request. Native ONP-001 chooses probes and compiles, IPS-003 chooses the
    instruction sequence, and INTENT-001/SAB-001 choose a valid host/path.
    """
    if not isinstance(goal, ObserverConstructionIntention):
        raise ObservationFormationRefused("Typed intention required")
    t0 = clock_ns()
    found = realize_observed_processor(
        goal, capacity.offers, sensors, capacity.trusted_keys,
        capacity.primitives, capacity.observation_policy,
        locus=capacity.locus, clock=lambda: now,
        nonce_factory=nonce_factory,
    )
    t1 = clock_ns()
    # Do not let the cold path skip the same independent source qualification
    # that the warm path must perform.
    receipt, formed = warm_realize(
        found, goal, capacity, now=now, clock_ns=clock_ns,
        reuse_identical_goal=False,
    )
    t2 = clock_ns()
    if formed is None or receipt.output != found.realization.output:
        raise ObservationFormationRefused("Cold structural realization mismatch")
    return IntentionReceipt(
        "cold-observation-formed", goal.digest, found.digest,
        receipt.derived_source_digest, receipt.machine_digest,
        receipt.route_digest, receipt.output,
        len(found.measurement_witnesses)+1,  # separately checked held-out probe
        {"observation_ground_program": t1-t0,
         "qualified_host_realization": t2-t1},
        canonical_value_digest({"observed": found.digest,
                                "formed": receipt.evidence_digest}),
    ), found, formed
