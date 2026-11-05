"""Coordinate formal navigation analyses into a replayable, non-authoritative plan.

The coordinator joins abstract reachability, optional representation
bisimulation, optional causal dependencies, concrete navigation, and readiness.
It never invokes an executor or grants authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .navigation import (
    NavigationError,
    NavigationResult,
    NavigationStatus,
    ProcessContext,
    ProcessDescriptor,
    ReadinessResult,
    SemanticAddress,
    ContextualNavigator,
    evaluate_readiness,
    verify_navigation_witness,
)
from .navigation_bridge import (
    AbstractNavigationCompiler,
    CompiledNavigation,
    NavigationCompilationError,
    analyze_compiled_navigation,
    verify_abstract_compilation,
)
from .navigation_formal import (
    AbstractReachabilityResult,
    AbstractReachabilityStatus,
    BisimulationResult,
    CausalDependencyGraph,
    CausalDependencyResult,
    FiniteTransitionSystem,
    FormalNavigationError,
    compute_bisimulation,
)
from .temporal import CausalStamp


class NavigationCoordinationError(ValueError):
    """Invalid coordinator inputs or an internally inconsistent coordination record."""


class CoordinationDisposition(str, Enum):
    """Terminal disposition of one coordinated navigation request."""

    READY = "ready"
    ALREADY_SATISFIED = "already_satisfied"
    CAUSAL_BLOCKED = "causal_blocked"
    REPRESENTATION_MISMATCH = "representation_mismatch"
    NOT_READY = "not_ready"
    ABSTRACT_UNREACHABLE = "abstract_unreachable"
    ABSTRACT_CONTRADICTION = "abstract_contradiction"
    RESOURCE_BLOCKED = "resource_blocked"
    BUDGET_EXHAUSTED = "budget_exhausted"
    UNREACHABLE = "unreachable"


def _plain(value: Any) -> Any:
    """Mathematics: detach immutable mappings and tuples into JSON-shaped values."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _canonical_bytes(value: Any) -> bytes:
    """Mathematics: encode a JSON value in its unique sorted compact UTF-8 form."""
    try:
        return json.dumps(
            _plain(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NavigationCoordinationError(f"coordination value is not canonical JSON: {exc}") from exc


def _digest(value: Any) -> str:
    """Mathematics: calculate SHA-256 over the canonical JSON representation."""
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _context_digest(context: ProcessContext) -> str:
    """Mathematics: bind every context coordinate that can affect search, readiness, or temporal interpretation."""
    frame = None if context.temporal_frame is None else context.temporal_frame.to_dict()
    return _digest({
        "process_id": context.process_id,
        "current_state": None if context.current_state is None else _plain(context.current_state),
        "bindings": _plain(context.bindings),
        "resolved_dependencies": sorted(context.resolved_dependencies),
        "resource_capacity": dict(context.resource_capacity),
        "capabilities": sorted(context.capabilities),
        "max_expansions": context.max_expansions,
        "max_depth": context.max_depth,
        "temporal_frame": frame,
    })


def _start_state_digest(descriptor: ProcessDescriptor, context: ProcessContext) -> str:
    """Mathematics: identify the exact concrete state from which both analyses begin."""
    state = context.current_state if context.current_state is not None else descriptor.initial_state
    if state is None:
        raise NavigationCoordinationError("no current or declared initial state is available")
    return _digest(state)


def _causal_observation_digest(observed: Mapping[str, CausalStamp]) -> str:
    """Mathematics: bind event identities to their exact vector-clock stamps."""
    return _digest({
        event: stamp.to_dict()
        for event, stamp in sorted(observed.items())
    })


def _bisimulation_payload(result: BisimulationResult) -> dict[str, Any]:
    """Mathematics: serialize the finite greatest-bisimulation evidence deterministically."""
    return {
        "equivalent": result.equivalent,
        "relation": [list(pair) for pair in result.relation],
        "left_digest": result.left_digest,
        "right_digest": result.right_digest,
        "iterations": result.iterations,
    }


def _causal_payload(result: CausalDependencyResult) -> dict[str, Any]:
    """Mathematics: serialize causal blockers and deterministic graph order."""
    return {
        "ready": result.ready,
        "blockers": list(result.blockers),
        "topological_order": list(result.topological_order),
    }


@dataclass(frozen=True)
class ExecutionAdmissionRequest:
    """Digest-bound proposal for later hypervisor review; it is not an authorization token."""

    descriptor_digest: str
    address_digest: str
    context_digest: str
    start_state_digest: str
    concrete_witness_digest: str
    final_state_digest: str
    readiness_digest: str
    transition_ids: tuple[str, ...]
    resource_envelope: tuple[tuple[str, int], ...]
    compilation_digest: str | None = None
    abstract_result_digest: str | None = None
    causal_graph_digest: str | None = None
    causal_evidence_digest: str | None = None
    bisimulation_digest: str | None = None
    representation_equivalence_required: bool = False

    def __post_init__(self) -> None:
        """Mathematics: validate digest identities and freeze the finite transition/resource proposal."""
        required = (
            "descriptor_digest",
            "address_digest",
            "context_digest",
            "start_state_digest",
            "concrete_witness_digest",
            "final_state_digest",
            "readiness_digest",
        )
        optional = (
            "compilation_digest",
            "abstract_result_digest",
            "causal_graph_digest",
            "causal_evidence_digest",
            "bisimulation_digest",
        )
        for name in required:
            value = getattr(self, name)
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise NavigationCoordinationError(f"{name} must be a lowercase SHA-256 digest")
        for name in optional:
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
            ):
                raise NavigationCoordinationError(f"{name} must be absent or a lowercase SHA-256 digest")
        if not isinstance(self.representation_equivalence_required, bool):
            raise NavigationCoordinationError("representation_equivalence_required must be Boolean")
        if not isinstance(self.transition_ids, (tuple, list)) or any(
            not isinstance(item, str) or not item for item in self.transition_ids
        ):
            raise NavigationCoordinationError("transition_ids must be a finite sequence of non-empty strings")
        object.__setattr__(self, "transition_ids", tuple(self.transition_ids))
        if not isinstance(self.resource_envelope, (tuple, list)):
            raise NavigationCoordinationError("resource_envelope must be a finite sequence")
        envelope: dict[str, int] = {}
        for item in self.resource_envelope:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise NavigationCoordinationError("resource envelope entries must be (name, amount) pairs")
            name, amount = item
            if not isinstance(name, str) or not name:
                raise NavigationCoordinationError("resource names must be non-empty strings")
            if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
                raise NavigationCoordinationError("resource amounts must be non-negative integers")
            if name in envelope:
                raise NavigationCoordinationError("resource envelope contains a duplicate resource")
            envelope[name] = amount
        object.__setattr__(self, "resource_envelope", tuple(sorted(envelope.items())))

    @property
    def authoritative(self) -> bool:
        """Mathematics: distinguish a proposal from a policy decision or capability grant."""
        return False

    @property
    def digest(self) -> str:
        """Mathematics: identify the complete admission proposal by canonical SHA-256."""
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize a plan proposal with an explicit non-authoritative contract."""
        return {
            "schema": "mailcpu.execution-admission-request.v1",
            "authoritative": False,
            "descriptor_digest": self.descriptor_digest,
            "address_digest": self.address_digest,
            "context_digest": self.context_digest,
            "start_state_digest": self.start_state_digest,
            "concrete_witness_digest": self.concrete_witness_digest,
            "final_state_digest": self.final_state_digest,
            "readiness_digest": self.readiness_digest,
            "transition_ids": list(self.transition_ids),
            "resource_envelope": {name: amount for name, amount in self.resource_envelope},
            "compilation_digest": self.compilation_digest,
            "abstract_result_digest": self.abstract_result_digest,
            "causal_graph_digest": self.causal_graph_digest,
            "causal_evidence_digest": self.causal_evidence_digest,
            "bisimulation_digest": self.bisimulation_digest,
            "representation_equivalence_required": self.representation_equivalence_required,
        }


@dataclass(frozen=True)
class NavigationCoordinationResult:
    """Combined formal and concrete evidence for one semantic navigation request."""

    disposition: CoordinationDisposition
    descriptor_digest: str
    address_digest: str
    context_digest: str
    start_state_digest: str
    navigation: NavigationResult
    readiness: ReadinessResult
    compilation_digest: str | None
    compilation_error: str | None
    abstract_reachability: AbstractReachabilityResult | None
    causal_dependencies: CausalDependencyResult | None
    causal_graph_digest: str | None
    causal_evidence_digest: str | None
    bisimulation: BisimulationResult | None
    representation_equivalence_required: bool
    admission_request: ExecutionAdmissionRequest | None

    def __post_init__(self) -> None:
        """Mathematics: enforce typed evidence and require a complete successful plan for READY."""
        try:
            value = self.disposition if isinstance(self.disposition, CoordinationDisposition) else CoordinationDisposition(self.disposition)
        except (TypeError, ValueError) as exc:
            raise NavigationCoordinationError("unknown coordination disposition") from exc
        object.__setattr__(self, "disposition", value)
        for name in ("descriptor_digest", "address_digest", "context_digest", "start_state_digest"):
            digest = getattr(self, name)
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise NavigationCoordinationError(f"{name} must be a lowercase SHA-256 digest")
        if not isinstance(self.navigation, NavigationResult) or not isinstance(self.readiness, ReadinessResult):
            raise NavigationCoordinationError("coordination result requires concrete navigation and readiness evidence")
        if self.compilation_digest is not None and re.fullmatch(r"[0-9a-f]{64}", self.compilation_digest) is None:
            raise NavigationCoordinationError("compilation_digest must be absent or a SHA-256 digest")
        if self.compilation_error is not None and not isinstance(self.compilation_error, str):
            raise NavigationCoordinationError("compilation_error must be text or absent")
        if self.abstract_reachability is not None and not isinstance(self.abstract_reachability, AbstractReachabilityResult):
            raise NavigationCoordinationError("abstract reachability evidence is malformed")
        if self.causal_dependencies is not None and not isinstance(self.causal_dependencies, CausalDependencyResult):
            raise NavigationCoordinationError("causal dependency evidence is malformed")
        if self.bisimulation is not None and not isinstance(self.bisimulation, BisimulationResult):
            raise NavigationCoordinationError("bisimulation evidence is malformed")
        if not isinstance(self.representation_equivalence_required, bool):
            raise NavigationCoordinationError("representation_equivalence_required must be Boolean")
        if self.admission_request is not None and not isinstance(self.admission_request, ExecutionAdmissionRequest):
            raise NavigationCoordinationError("admission_request is malformed")
        if self.disposition is CoordinationDisposition.READY:
            if (
                self.admission_request is None
                or self.navigation.status is not NavigationStatus.FOUND
                or not self.readiness.ready
                or (self.causal_dependencies is not None and not self.causal_dependencies.ready)
                or (
                    self.representation_equivalence_required
                    and (self.bisimulation is None or not self.bisimulation.equivalent)
                )
                or (
                    self.abstract_reachability is not None
                    and self.abstract_reachability.status is AbstractReachabilityStatus.PROVED_UNREACHABLE
                )
            ):
                raise NavigationCoordinationError("READY requires a concrete path and all requested admission gates")
        elif self.admission_request is not None:
            raise NavigationCoordinationError("non-ready coordination results cannot carry an admission request")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize every evidence channel while preserving its independent result meaning."""
        return {
            "schema": "mailcpu.navigation-coordination-result.v1",
            "disposition": self.disposition.value,
            "descriptor_digest": self.descriptor_digest,
            "address_digest": self.address_digest,
            "context_digest": self.context_digest,
            "start_state_digest": self.start_state_digest,
            "navigation": self.navigation.to_dict(),
            "readiness": {
                "ready": self.readiness.ready,
                "blockers": list(self.readiness.blockers),
            },
            "compilation_digest": self.compilation_digest,
            "compilation_error": self.compilation_error,
            "abstract_reachability": None if self.abstract_reachability is None else self.abstract_reachability.to_dict(),
            "causal_dependencies": None if self.causal_dependencies is None else _causal_payload(self.causal_dependencies),
            "causal_graph_digest": self.causal_graph_digest,
            "causal_evidence_digest": self.causal_evidence_digest,
            "bisimulation": None if self.bisimulation is None else _bisimulation_payload(self.bisimulation),
            "representation_equivalence_required": self.representation_equivalence_required,
            "admission_request": None if self.admission_request is None else self.admission_request.to_dict(),
        }

    @property
    def digest(self) -> str:
        """Mathematics: identify the combined coordination record, including every evidence disposition."""
        return _digest(self.to_dict())


class NavigationCoordinator:
    """Compose formal analyses, exact navigation, and readiness into an admission proposal."""

    def coordinate(
        self,
        descriptor: ProcessDescriptor,
        address: SemanticAddress,
        context: ProcessContext,
        *,
        causal_graph: CausalDependencyGraph | None = None,
        causal_observations: Mapping[str, CausalStamp] | None = None,
        representation_pair: tuple[FiniteTransitionSystem, FiniteTransitionSystem] | None = None,
        require_representation_equivalence: bool = False,
        max_abstract_updates: int = 10_000,
        widen_after: int = 3,
    ) -> NavigationCoordinationResult:
        """Mathematics: evaluate independent evidence channels and issue a plan only when all requested gates pass."""
        if not isinstance(descriptor, ProcessDescriptor):
            raise NavigationCoordinationError("descriptor must be a ProcessDescriptor")
        if not isinstance(address, SemanticAddress):
            raise NavigationCoordinationError("address must be a SemanticAddress")
        if not isinstance(context, ProcessContext):
            raise NavigationCoordinationError("context must be a ProcessContext")
        if not isinstance(require_representation_equivalence, bool):
            raise NavigationCoordinationError("require_representation_equivalence must be Boolean")
        if not isinstance(max_abstract_updates, int) or isinstance(max_abstract_updates, bool) or max_abstract_updates < 1:
            raise NavigationCoordinationError("max_abstract_updates must be a positive integer")
        if not isinstance(widen_after, int) or isinstance(widen_after, bool) or widen_after < 1:
            raise NavigationCoordinationError("widen_after must be a positive integer")
        if (descriptor.process_id, descriptor.version) != (address.process_id, address.version):
            raise NavigationCoordinationError("semantic address does not identify this process descriptor version")
        if context.process_id != descriptor.process_id:
            raise NavigationCoordinationError("process context belongs to another process")
        if causal_graph is None and causal_observations is not None:
            raise NavigationCoordinationError("causal observations require a causal dependency graph")
        if causal_graph is not None and not isinstance(causal_graph, CausalDependencyGraph):
            raise NavigationCoordinationError("causal_graph must be a CausalDependencyGraph")
        if causal_observations is None:
            causal_observations = {}
        if not isinstance(causal_observations, Mapping):
            raise NavigationCoordinationError("causal_observations must be a mapping")
        if any(not isinstance(key, str) or not isinstance(value, CausalStamp) for key, value in causal_observations.items()):
            raise NavigationCoordinationError("causal observations must map event IDs to CausalStamp values")
        if representation_pair is not None:
            if (
                not isinstance(representation_pair, (tuple, list))
                or len(representation_pair) != 2
                or any(not isinstance(item, FiniteTransitionSystem) for item in representation_pair)
            ):
                raise NavigationCoordinationError("representation_pair must contain two FiniteTransitionSystem values")
        if require_representation_equivalence and representation_pair is None:
            raise NavigationCoordinationError("a representation pair is required when equivalence is mandatory")

        descriptor_digest = descriptor.digest
        address_digest = address.digest
        context_digest = _context_digest(context)
        start_digest = _start_state_digest(descriptor, context)

        compilation: CompiledNavigation | None = None
        abstract: AbstractReachabilityResult | None = None
        compilation_error: str | None = None
        try:
            compilation = AbstractNavigationCompiler().compile(descriptor, address, context)
            abstract = analyze_compiled_navigation(
                compilation,
                max_updates=max_abstract_updates,
                widen_after=widen_after,
            )
        except (NavigationCompilationError, NavigationError, FormalNavigationError, TypeError, ValueError) as exc:
            compilation_error = f"{type(exc).__name__}: {exc}"

        causal_result: CausalDependencyResult | None = None
        causal_graph_digest: str | None = None
        causal_evidence_digest: str | None = None
        if causal_graph is not None:
            causal_result = causal_graph.evaluate(causal_observations)
            causal_graph_digest = causal_graph.digest
            causal_evidence_digest = _causal_observation_digest(causal_observations)

        bisimulation: BisimulationResult | None = None
        if representation_pair is not None:
            bisimulation = compute_bisimulation(representation_pair[0], representation_pair[1])

        navigation = ContextualNavigator().navigate(descriptor, address, context)
        readiness = evaluate_readiness(descriptor, context)

        if abstract is not None and abstract.status is AbstractReachabilityStatus.PROVED_UNREACHABLE:
            disposition = (
                CoordinationDisposition.ABSTRACT_CONTRADICTION
                if navigation.reached
                else CoordinationDisposition.ABSTRACT_UNREACHABLE
            )
        elif navigation.status is NavigationStatus.BUDGET_EXHAUSTED:
            disposition = CoordinationDisposition.BUDGET_EXHAUSTED
        elif navigation.status is NavigationStatus.RESOURCE_BLOCKED:
            disposition = CoordinationDisposition.RESOURCE_BLOCKED
        elif navigation.status is NavigationStatus.UNREACHABLE:
            disposition = CoordinationDisposition.UNREACHABLE
        elif navigation.status is NavigationStatus.ALREADY_SATISFIED:
            disposition = CoordinationDisposition.ALREADY_SATISFIED
        elif causal_result is not None and not causal_result.ready:
            disposition = CoordinationDisposition.CAUSAL_BLOCKED
        elif (
            require_representation_equivalence
            and (bisimulation is None or not bisimulation.equivalent)
        ):
            disposition = CoordinationDisposition.REPRESENTATION_MISMATCH
        elif not readiness.ready:
            disposition = CoordinationDisposition.NOT_READY
        else:
            disposition = CoordinationDisposition.READY

        admission: ExecutionAdmissionRequest | None = None
        if disposition is CoordinationDisposition.READY:
            assert navigation.witness is not None and navigation.final_state is not None
            readiness_digest = _digest({
                "ready": readiness.ready,
                "blockers": list(readiness.blockers),
            })
            admission = ExecutionAdmissionRequest(
                descriptor_digest=descriptor_digest,
                address_digest=address_digest,
                context_digest=context_digest,
                start_state_digest=start_digest,
                concrete_witness_digest=_digest(navigation.witness.to_dict()),
                final_state_digest=navigation.witness.final_state_digest,
                readiness_digest=readiness_digest,
                transition_ids=navigation.path,
                resource_envelope=tuple(sorted(navigation.resource_envelope.items())),
                compilation_digest=None if compilation is None else compilation.digest,
                abstract_result_digest=None if abstract is None else _digest(abstract.to_dict()),
                causal_graph_digest=causal_graph_digest,
                causal_evidence_digest=causal_evidence_digest,
                bisimulation_digest=None if bisimulation is None else _digest(_bisimulation_payload(bisimulation)),
                representation_equivalence_required=require_representation_equivalence,
            )

        return NavigationCoordinationResult(
            disposition=disposition,
            descriptor_digest=descriptor_digest,
            address_digest=address_digest,
            context_digest=context_digest,
            start_state_digest=start_digest,
            navigation=navigation,
            readiness=readiness,
            compilation_digest=None if compilation is None else compilation.digest,
            compilation_error=compilation_error,
            abstract_reachability=abstract,
            causal_dependencies=causal_result,
            causal_graph_digest=causal_graph_digest,
            causal_evidence_digest=causal_evidence_digest,
            bisimulation=bisimulation,
            representation_equivalence_required=require_representation_equivalence,
            admission_request=admission,
        )


def verify_navigation_coordination(
    descriptor: ProcessDescriptor,
    address: SemanticAddress,
    context: ProcessContext,
    result: NavigationCoordinationResult,
    *,
    causal_graph: CausalDependencyGraph | None = None,
    causal_observations: Mapping[str, CausalStamp] | None = None,
    representation_pair: tuple[FiniteTransitionSystem, FiniteTransitionSystem] | None = None,
    require_representation_equivalence: bool = False,
    max_abstract_updates: int = 10_000,
    widen_after: int = 3,
) -> bool:
    """Mathematics: independently rerun all requested analyses and compare the complete plan/result digests."""
    if not isinstance(result, NavigationCoordinationResult) or result.admission_request is None:
        return False
    try:
        if not verify_navigation_witness(descriptor, address, context, result.navigation):
            return False
        compilation = None
        try:
            compilation = AbstractNavigationCompiler().compile(descriptor, address, context)
        except (NavigationCompilationError, NavigationError, FormalNavigationError, TypeError, ValueError):
            compilation = None
        if compilation is not None and not verify_abstract_compilation(descriptor, address, context, compilation):
            return False
        replayed = NavigationCoordinator().coordinate(
            descriptor,
            address,
            context,
            causal_graph=causal_graph,
            causal_observations=causal_observations,
            representation_pair=representation_pair,
            require_representation_equivalence=require_representation_equivalence,
            max_abstract_updates=max_abstract_updates,
            widen_after=widen_after,
        )
    except (NavigationCoordinationError, NavigationError, FormalNavigationError, TypeError, ValueError):
        return False
    return (
        replayed.disposition is CoordinationDisposition.READY
        and replayed.admission_request is not None
        and replayed.admission_request.digest == result.admission_request.digest
        and replayed.digest == result.digest
    )
