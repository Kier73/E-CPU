"""ITR-002: intent-first nonlinear realization using real CIG-017 and E-CPU SAB-001.

Two independently constructed routes for the SAME source-valid observation:
  * CIG-017 globally proves and evaluates a source-qualified decoder;
  * E-CPU builds an exact finite Moore observation machine from an exhaustive
    source-image table, then lets INTENT-001/SAB-001 form and place the machine.
No program, decoder, source state or execution host is supplied in the intention.
The fixture's hidden state is used only by the receiver's independent source
qualification and result oracle, NEVER by the realizing handler.

CIG-017 is a pinned, optional research dependency. It is imported from the
actual In-Formation-Space checkout, not copied or replaced here.
"""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import importlib
import json
from time import perf_counter_ns
from typing import Any, Callable, Mapping, Sequence

from .intention_formed_fabric import FiniteObserverLaw, FormedRealization, realize_formed_intention
from .semantic_translation import canonical_value_digest
from .substrate_bootstrap import (
    AdaptiveBootstrap, BootstrapPolicy, BootstrapRefused, BootstrapTask,
    CarrierBinding, RealizerBinding, SubstrateObservation, digest,
    verify_bootstrap_report,
)

SCHEMA = "mailcpu.itr002.inverse-nonlinear-realization.v1"
DIRECT_OPERATION = "proof.decode.boolean.v1"
OBSERVE_OPERATION = "proof.observe.boolean.v1"
MAX_FORMED_STATES = 64
MAX_ENUMERATED_BITS = 16
MAX_RECEIPT_BYTES = 4 * 1024 * 1024


class NonlinearRealizationRefused(ValueError):
    """Reject unproved intentions, invalid source witnesses and unsafe realizations."""


def _cig():
    """Use exactly the CIG-017 producer and its separate verifier."""
    try:
        producer = importlib.import_module("global_sufficiency")
        checker = importlib.import_module("verify_global_sufficiency")
        source_checker = importlib.import_module("verify_composed_ground")
    except ImportError as exc:
        raise NonlinearRealizationRefused(
            "ITR-002 requires the pinned CIG-017 source modules on PYTHONPATH"
        ) from exc
    return producer, checker, source_checker


def _wire(value: Any) -> bytes:
    """Encode canonical finite JSON for immutable receiver memory."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class NonlinearIntention:
    """Exact original source, observation predicates and desired target (no algorithm)."""
    variables: int
    source: tuple[tuple[int, ...], ...]
    observations: tuple[tuple[int, ...], ...]
    target: tuple[int, ...]

    def __post_init__(self) -> None:
        if (type(self.variables) is not int or not 1 <= self.variables <= 8192
            or not isinstance(self.source, tuple)
            or not isinstance(self.observations, tuple)
            or not isinstance(self.target, tuple)):
            raise NonlinearRealizationRefused("finite typed CNF intention required")
        # The actual independent CIG source contract canonicalizes source and
        # refuses malformed/duplicate observation predicates.
        _, checker, _ = _cig()
        try:
            source, observations, target = checker.contract(
                self.variables, self.source, self.observations, self.target
            )
        except (ValueError, TypeError) as exc:
            raise NonlinearRealizationRefused("invalid original source or intention") from exc
        object.__setattr__(self, "source", tuple(tuple(c) for c in source))
        object.__setattr__(self, "observations", tuple(tuple(c) for c in observations))
        object.__setattr__(self, "target", tuple(target))

    @property
    def fingerprint(self) -> str:
        """Identifies problem semantics independent of chosen host and realizer."""
        return canonical_value_digest({
            "schema": SCHEMA, "variables": self.variables,
            "source": self.source, "observations": self.observations,
            "target": self.target,
        })


@dataclass(frozen=True)
class SourceObservation:
    """One original-source-valid state held at the receiver's checking boundary.

    The state does not appear in any SAB-001 execution request or path receipt.
    This is mathematical source qualification, not physical sensor attestation.
    """
    model: int
    def __post_init__(self) -> None:
        if type(self.model) is not int or self.model < 0:
            raise NonlinearRealizationRefused("nonnegative original-source witness required")


def qualify_observation(goal: NonlinearIntention, observed: SourceObservation) -> int:
    """Independently check source validity and project only the observed code."""
    if not isinstance(goal, NonlinearIntention) or not isinstance(observed, SourceObservation):
        raise NonlinearRealizationRefused("source-bound witnessed observation required")
    if observed.model >= 1 << goal.variables:
        raise NonlinearRealizationRefused("source witness exceeds declared variable scope")
    _, checker, source_checker = _cig()
    if not source_checker.accepted(goal.source, observed.model):
        raise NonlinearRealizationRefused("observed state contradicts original source")
    return sum(checker.value(predicate, observed.model) << i
               for i, predicate in enumerate(goal.observations))


class ReceiverProofMemory:
    """Process-local receiver-admitted CIG receipts; immutable copies on access.

    The actual verifier runs on every newly admitted proof. Already checked
    canonical bytes are reused only in this same trusted process and for the
    exact full problem fingerprint. This is neither durable nor remote authority.
    """
    def __init__(self) -> None:
        self._proofs: dict[str, bytes] = {}

    def get_or_construct(self, goal: NonlinearIntention, *, mode: str = "auto",
                         width: int = 12, cells: int = 2_000_000,
                         decoder_bits: int = 6) -> tuple[dict[str, Any], bool]:
        """Construct and independently check an exact source-bound proof, or reuse admitted bytes."""
        if not isinstance(goal, NonlinearIntention):
            raise NonlinearRealizationRefused("typed intention required")
        if (mode not in ("auto", "paired") or type(width) is not int
            or type(cells) is not int or type(decoder_bits) is not int
            or not 1 <= width <= 12 or not 1 <= cells <= 2_000_000
            or not 0 <= decoder_bits <= 8):
            raise NonlinearRealizationRefused("receiver-selected proof budgets required")
        key = canonical_value_digest({
            "goal": goal.fingerprint, "mode": mode, "width": width,
            "cells": cells, "decoder_bits": decoder_bits,
        })
        stored = self._proofs.get(key)
        if stored is not None:
            return json.loads(stored), False
        producer, checker, _ = _cig()
        receipt = producer.synthesize(
            goal.variables, goal.source, goal.observations, goal.target,
            mode=mode, width=width, cells=cells, decoder_bits=decoder_bits,
        )
        if receipt.get("status") == "UNKNOWN":
            raise NonlinearRealizationRefused("CIG-017 proof budget returned UNKNOWN")
        if not checker.verify(
            goal.variables, goal.source, goal.observations, goal.target,
            receipt, width=width, cells=cells, decoder_bits=decoder_bits,
        ):
            raise NonlinearRealizationRefused("CIG-017 independent verification failed")
        raw = _wire(receipt)
        if len(raw) > MAX_RECEIPT_BYTES:
            raise NonlinearRealizationRefused("proof receipt exceeds receiver budget")
        self._proofs[key] = raw
        return json.loads(raw), True

    def __len__(self) -> int:
        return len(self._proofs)


@dataclass(frozen=True)
class NonlinearCapacity:
    """Receiver-admitted host/path capacity; no designated execution host."""
    inventory: SubstrateObservation
    policy: BootstrapPolicy
    carriers: tuple[CarrierBinding, ...]
    interpreters: tuple[str, ...]
    observers: tuple[str, ...]
    ingress: str
    observer: str
    coordinate: int

    def __post_init__(self) -> None:
        if (not isinstance(self.inventory, SubstrateObservation)
            or not isinstance(self.policy, BootstrapPolicy)
            or not isinstance(self.carriers, tuple)
            or not isinstance(self.interpreters, tuple)
            or not isinstance(self.observers, tuple)
            or type(self.coordinate) is not int or self.coordinate < 0):
            raise NonlinearRealizationRefused("typed, admitted E-CPU host inventory required")


@dataclass(frozen=True)
class NonlinearRealization:
    """Result and exact live E-CPU path/evidence and wall-clock phase measurements."""
    mode: str
    intention_digest: str
    source_code: int
    result: int
    proof_digest: str | None
    machine_digest: str | None
    path_digest: str
    report_digest: str
    spans_ns: Mapping[str, int]
    proof_constructed: bool
    source_probes: int

    @property
    def total_ns(self) -> int:
        """Sum measured inclusive realization phases in nanoseconds."""
        return sum(self.spans_ns.values())


def _source_oracle(goal: NonlinearIntention, observed: SourceObservation, code: int) -> int:
    """Receiver-side source-valid target truth; not exposed to any handler."""
    _, checker, _ = _cig()
    if qualify_observation(goal, observed) != code:
        raise NonlinearRealizationRefused("altered source code")
    return checker.value(goal.target, observed.model)


def direct_realize(goal: NonlinearIntention, observed: SourceObservation,
                   capacity: NonlinearCapacity, archive: ReceiverProofMemory,
                   *, clock_ns: Callable[[], int] = perf_counter_ns,
                   mode: str = "auto", width: int = 12, cells: int = 2_000_000,
                   decoder_bits: int = 6) -> NonlinearRealization:
    """Compile or reuse actual CIG proof, then route its decoder through E-CPU.

    Source model is scoped to this receiver's oracle and never enters the
    decoder, executable task, output, or E-CPU communication path.
    """
    t0 = clock_ns()
    proof, constructed = archive.get_or_construct(
        goal, mode=mode, width=width, cells=cells, decoder_bits=decoder_bits
    )
    if proof["status"] != "SUFFICIENT" or proof.get("decoder") is None:
        raise NonlinearRealizationRefused(
            "source observations are insufficient or executable decoder is unresolved"
        )
    proof_digest = canonical_value_digest(proof)
    t1 = clock_ns()
    code = qualify_observation(goal, observed)
    expected = _source_oracle(goal, observed, code)
    t2 = clock_ns()
    producer, _, _ = _cig()
    # A host sees ONLY the observation code, problem ID and checked proof law.
    ground = canonical_value_digest({"intention": goal.fingerprint, "proof": proof_digest})
    task = BootstrapTask(
        "nonlinear-proof-observation", ground, capacity.ingress,
        "proof.code.v1", capacity.observer, "proof.observed.v1",
        {"code": code, "source": goal.fingerprint}, require_oracle=True,
    )
    def decode(request: Any) -> dict[str, Any]:
        """Evaluate the admitted decoder using only the qualified observation code."""
        if (type(request) is not dict or request !=
            {"code": code, "source": goal.fingerprint}):
            raise BootstrapRefused("substituted source code or intention")
        value = producer.evaluate(goal.observations, goal.target, proof, code)
        if type(value) is not int or value not in (0, 1):
            raise BootstrapRefused("unqualified decoder result")
        return {"value": value, "proof": proof_digest}

    def check_decode(request: Any, result: Any) -> bool:
        """Independently compare the returned bit with original-source truth."""
        return (request == {"code": code, "source": goal.fingerprint}
                and type(result) is dict
                and result == {"value": expected, "proof": proof_digest})

    def project(result: Any) -> dict[str, Any]:
        """Project the verified decoder result onto the requested observation."""
        return {"value": result["value"], "proof": result["proof"]}

    def check_project(prior: Any, result: Any) -> bool:
        """Check that observation projection preserves verified source truth."""
        return (type(prior) is dict and prior ==
                {"value": expected, "proof": proof_digest}
                and result == prior)

    bindings = [
        RealizerBinding(host, DIRECT_OPERATION, decode,
                        digest({"schema": SCHEMA, "host": host,
                                "operation": DIRECT_OPERATION, "proof": proof_digest}),
                        check_decode)
        for host in sorted(set(capacity.interpreters))
    ] + [
        RealizerBinding(host, OBSERVE_OPERATION, project,
                        digest({"schema": SCHEMA, "host": host,
                                "operation": OBSERVE_OPERATION, "proof": proof_digest}),
                        check_project)
        for host in sorted(set(capacity.observers))
    ]
    runtime = AdaptiveBootstrap(capacity.inventory, capacity.policy,
                                bindings, capacity.carriers)
    plan = runtime.plan(task, coordinate=capacity.coordinate)
    t3 = clock_ns()
    report = runtime.execute(task, plan, coordinate=capacity.coordinate)
    verify_bootstrap_report(report, task, plan)
    t4 = clock_ns()
    if report["output"] != {"value": expected, "proof": proof_digest}:
        raise NonlinearRealizationRefused("host output differs from original source")
    t5 = clock_ns()
    return NonlinearRealization(
        "source-qualified-direct-decoder", goal.fingerprint, code, expected,
        proof_digest, None, plan.fingerprint, report["report_digest"],
        {"proof_acquire_and_admit": t1-t0,
         "source_observation_qualification": t2-t1,
         "host_route_discovery": t3-t2,
         "native_execution_and_check": t4-t3,
         "result_audit": t5-t4}, constructed, 0,
    )


def _enumerated_law(goal: NonlinearIntention) -> tuple[FiniteObserverLaw, dict[int, int]]:
    """Independent finite-model source construction for the formed-CPU control.

    This route never calls CIG-017's producer or its inferred decoder.
    It explicitly pays exponential enumeration and refuses larger sources.
    """
    if goal.variables > MAX_ENUMERATED_BITS:
        raise NonlinearRealizationRefused("formed baseline source enumeration budget exceeded")
    _, checker, source_checker = _cig()
    image: dict[int, int] = {}
    for model in range(1 << goal.variables):
        if not source_checker.accepted(goal.source, model):
            continue
        code = sum(checker.value(p, model) << i
                   for i, p in enumerate(goal.observations))
        target = checker.value(goal.target, model)
        if code in image and image[code] != target:
            raise NonlinearRealizationRefused(
                "source observation insufficient; two models need different targets"
            )
        image[code] = target
    if not image:
        raise NonlinearRealizationRefused("empty source admits no observed intention")
    if len(image) > MAX_FORMED_STATES:
        raise NonlinearRealizationRefused("formed source exceeds 64-state quotient envelope")
    codes = tuple(sorted(image))
    law = FiniteObserverLaw(
        states=tuple(f"u{c:05d}" for c in codes),
        actions=("read",), fields=("value",),
        transitions=tuple((i,) for i in range(len(codes))),
        observations=tuple((image[c],) for c in codes),
    )
    return law, image


def formed_realize(goal: NonlinearIntention, observed: SourceObservation,
                   capacity: NonlinearCapacity, *,
                   clock_ns: Callable[[], int] = perf_counter_ns,
                   ) -> tuple[NonlinearRealization, FormedRealization]:
    """Construct finite observation machine from original source, not CIG proof.

    The input code is a witnessed source observation. The one-step 'read'
    transition is an identity read, not an asserted physical temporal law.
    """
    t0 = clock_ns()
    code = qualify_observation(goal, observed)
    expected = _source_oracle(goal, observed, code)
    t1 = clock_ns()
    source, image = _enumerated_law(goal)
    if code not in image or image[code] != expected:
        raise NonlinearRealizationRefused("formed source differs from witnessed intent")
    t2 = clock_ns()
    formed = realize_formed_intention(
        source, ("value",), f"u{code:05d}", ("read",),
        capacity.inventory, capacity.policy, capacity.carriers,
        admitted_interpreters=capacity.interpreters,
        admitted_observers=capacity.observers,
        ingress=capacity.ingress, observer=capacity.observer,
        coordinate=capacity.coordinate,
    )
    t3 = clock_ns()
    verify_bootstrap_report(formed.report, formed.task, formed.plan)
    value = formed.report["output"]["observation"]["value"]
    if type(value) is not int or value != expected:
        raise NonlinearRealizationRefused("formed processor disagrees with independent source")
    t4 = clock_ns()
    return NonlinearRealization(
        "independently-formed-finite-processor", goal.fingerprint, code,
        value, None, formed.machine.fingerprint,
        formed.plan.fingerprint, formed.report["report_digest"],
        {"source_observation_qualification": t1-t0,
         "full_source_image_discovery": t2-t1,
         "processor_route_and_execution": t3-t2,
         "final_audit": t4-t3}, False, 0,
    ), formed


def compare_realizations(direct: NonlinearRealization,
                         formed: NonlinearRealization) -> dict[str, Any]:
    """Reject any comparison with different intention, code or result."""
    if (not isinstance(direct, NonlinearRealization)
        or not isinstance(formed, NonlinearRealization)
        or direct.mode not in ("source-qualified-direct-decoder", "section-derived-direct-decoder")
        or formed.mode != "independently-formed-finite-processor"
        or (direct.intention_digest, direct.source_code, direct.result)
        != (formed.intention_digest, formed.source_code, formed.result)):
        raise NonlinearRealizationRefused("only same-intention verified results may be compared")
    return {"schema": SCHEMA + ".comparison", "source": direct.intention_digest,
            "observation_code": direct.source_code,
            "result": direct.result, "direct_ns": direct.total_ns,
            "formed_ns": formed.total_ns,
            "direct_spans_ns": dict(direct.spans_ns),
            "formed_spans_ns": dict(formed.spans_ns),
            "direct_path": direct.path_digest,
            "formed_path": formed.path_digest,
            "direct_proof_digest": direct.proof_digest,
            "formed_machine_digest": formed.machine_digest}


class ReceiverSourceSectionMemory:
    """CIG-021 independently checked total-image section, retained locally.

    A section establishes mathematical source reachability of an observation
    *code*. It never authenticates a physical sensor measurement or host.
    """
    def __init__(self) -> None:
        self._sections: dict[str, bytes] = {}

    def get_or_construct(self, goal: NonlinearIntention) -> tuple[dict[str, Any], bool]:
        """Construct and independently check source image before reusing it."""
        if not isinstance(goal, NonlinearIntention):
            raise NonlinearRealizationRefused("typed source intention required")
        key = canonical_value_digest({
            "schema": SCHEMA + ".source-section", "n": goal.variables,
            "source": goal.source, "q": goal.observations,
        })
        previous = self._sections.get(key)
        if previous is not None:
            return json.loads(previous), False
        try:
            section = importlib.import_module("source_section")
            verifier = importlib.import_module("verify_source_section")
        except ImportError as exc:
            raise NonlinearRealizationRefused(
                "ITR-002 requires pinned CIG-021 source-section modules"
            ) from exc
        certificate = section.compile_section(
            goal.variables, goal.source, goal.observations
        )
        if certificate is None or not verifier.verify_section(
            goal.variables, goal.source, goal.observations, certificate
        ):
            raise NonlinearRealizationRefused(
                "no verified total observation-image section for original source"
            )
        encoded = _wire(certificate)
        if len(encoded) > MAX_RECEIPT_BYTES:
            raise NonlinearRealizationRefused("source-section proof exceeds receiver budget")
        self._sections[key] = encoded
        return json.loads(encoded), True

    def __len__(self) -> int:
        return len(self._sections)


def realize_from_observation_code(
    goal: NonlinearIntention, code: int, capacity: NonlinearCapacity,
    proofs: ReceiverProofMemory, sections: ReceiverSourceSectionMemory,
    *, clock_ns: Callable[[], int] = perf_counter_ns,
) -> NonlinearRealization:
    """Intention and observed *code* suffice when a source section is proved.

    No source model is passed by the caller. CIG-021 proves surjectivity of q
    on original source models, then constructs a compatible model for the
    receiver's private independent check. CIG-017 proves f=g(q) universally.
    Together they qualify a virtual mathematical observation, not the origin
    or authenticity of an independently arriving physical measurement.
    """
    if (type(code) is not int or not isinstance(goal, NonlinearIntention)
        or not 0 <= code < (1 << len(goal.observations))
        or not isinstance(sections, ReceiverSourceSectionMemory)):
        raise NonlinearRealizationRefused("bounded typed observation code required")
    t0 = clock_ns()
    certificate, _ = sections.get_or_construct(goal)
    section = importlib.import_module("source_section")
    model = section.section_witness(
        goal.variables, goal.observations, certificate, code
    )
    observed = SourceObservation(model)
    if qualify_observation(goal, observed) != code:
        raise NonlinearRealizationRefused("source-section witness did not realize observation code")
    t1 = clock_ns()
    result = direct_realize(goal, observed, capacity, proofs, clock_ns=clock_ns)
    return NonlinearRealization(
        "section-derived-direct-decoder", result.intention_digest,
        result.source_code, result.result, result.proof_digest,
        result.machine_digest, result.path_digest, result.report_digest,
        {"section_construction_and_witness_audit": t1 - t0,
         **result.spans_ns}, result.proof_constructed, 0,
    )
