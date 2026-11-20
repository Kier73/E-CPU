"""IPS-003: construct finite virtual behavior from a declared intention.

An intended affine law over Z/mZ is *imposed* through two defining values,
not inferred from a time series. The compiler synthesizes a cost-minimal word
over receiver-supplied primitive descriptions, then lowers it into E-CPU's
existing NavigableComputationDAG. A locally admitted TwoPortArithmeticGate
can execute that word and a separate GroundRealizer verifies the observation.

No generated relation enters EvidencePathCatalogue, no Hypervisor rights are
created, and successful local simulation does not imply a real network route.
"""
from __future__ import annotations

from dataclasses import dataclass
import heapq
import re
from typing import Any, Sequence

from .computation_dag import ComputationNode, NavigableComputationDAG
from .ground_native_realization import (
    AffineGround, GroundIntention, PortGroundRealizer, RealizationPolicy,
    TwoPortArithmeticGate, realize_under_contract, verify_receipt,
)
from .inverse_architecture_synthesis import ProposedRelation
from .runtime_qualification import digest as frame_digest
from .semantic_translation import canonical_value_digest

_SCHEMA = "mailcpu.generative-ground-construction.v1"
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_MAX_MODULUS = 257
_MAX_PRIMITIVES = 16
_MAX_STATES = 65536
_MAX_DEPTH = 32


class GroundConstructionError(ValueError):
    """A description, primitive, proof, permission or execution is invalid."""


def _integer(value: Any, label: str, low: int, high: int) -> int:
    """Accept an exact non-Boolean integer in a finite mathematical domain."""
    if type(value) is not int or not low <= value <= high:
        raise GroundConstructionError(f"invalid {label}")
    return value


@dataclass(frozen=True)
class AffineBehaviorIntention:
    """Specify one complete affine law by f(0), f(1), and its finite domain.

    Specifying the affine family is essential: the two anchors would not
    determine an arbitrary function over Z/mZ. Nothing here asserts that
    the desired relation is observed or executable on a remote host.
    """

    relation: ProposedRelation
    modulus: int
    output_at_zero: int
    output_at_one: int
    query_input: int
    challenge_cases: tuple[tuple[int, int], ...] = ()

    def __post_init__(self) -> None:
        """Validate the exact imposed family and optional independent constraints."""
        if not isinstance(self.relation, ProposedRelation):
            raise GroundConstructionError("intention needs a typed IPS-002 proposal")
        _integer(self.modulus, "modulus", 2, _MAX_MODULUS)
        for name in ("output_at_zero", "output_at_one", "query_input"):
            _integer(getattr(self, name), name, 0, self.modulus - 1)
        if type(self.challenge_cases) is not tuple or len(self.challenge_cases) > self.modulus:
            raise GroundConstructionError("challenge cases must be a bounded tuple")
        if any(
            type(pair) is not tuple or len(pair) != 2
            or any(type(value) is not int or not 0 <= value < self.modulus for value in pair)
            for pair in self.challenge_cases
        ):
            raise GroundConstructionError("invalid challenge case")

    @property
    def coefficients(self) -> tuple[int, int]:
        """Recover the unique affine transformation from the imposed anchors."""
        return ((self.output_at_one - self.output_at_zero) % self.modulus,
                self.output_at_zero)

    @property
    def digest(self) -> str:
        """Bind all requested semantics, including IPS-002 representation identity."""
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Encode a full finite affine Ground description without source code."""
        return {
            "schema": _SCHEMA + ".intention",
            "relation": self.relation.to_dict(), "modulus": self.modulus,
            "family": "affine_mod", "output_at_zero": self.output_at_zero,
            "output_at_one": self.output_at_one, "query_input": self.query_input,
            "challenge_cases": [list(p) for p in self.challenge_cases],
        }


@dataclass(frozen=True)
class AffinePrimitive:
    """One receiver-approved, locally callable finite arithmetic map."""

    name: str
    modulus: int
    multiplier: int
    offset: int
    symbolic_cost: int = 1

    def __post_init__(self) -> None:
        """Reject ambiguous names, incompatible coefficients and free operations."""
        if type(self.name) is not str or _NAME.fullmatch(self.name) is None:
            raise GroundConstructionError("invalid primitive name")
        _integer(self.modulus, "primitive modulus", 2, _MAX_MODULUS)
        _integer(self.multiplier, "multiplier", 0, self.modulus - 1)
        _integer(self.offset, "offset", 0, self.modulus - 1)
        _integer(self.symbolic_cost, "symbolic cost", 1, 10**6)

    @property
    def digest(self) -> str:
        """Bind native operator parameters to the receiver-owned palette."""
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Encode one inert, exact primitive description."""
        return {"name": self.name, "modulus": self.modulus,
                "multiplier": self.multiplier, "offset": self.offset,
                "symbolic_cost": self.symbolic_cost}


@dataclass(frozen=True)
class GroundConstructionPlan:
    """The derived word or explicit refusal under a finite operator palette."""

    status: str
    intention_digest: str
    palette_digest: str
    target_multiplier: int
    target_offset: int
    primitive_names: tuple[str, ...]
    symbolic_cost: int | None
    expanded_states: int
    explored_complete: bool
    optimal_within_palette: bool
    detail: str

    @property
    def authoritative(self) -> bool:
        """A synthesized mathematical plan is never an execution permit."""
        return False

    @property
    def digest(self) -> str:
        """Content-address the scoped proof/candidate and search disposition."""
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Export a non-authoritative synthesis result with search accounting."""
        return {
            "schema": _SCHEMA + ".plan", "status": self.status,
            "intention_digest": self.intention_digest,
            "palette_digest": self.palette_digest,
            "target_multiplier": self.target_multiplier,
            "target_offset": self.target_offset,
            "primitive_names": list(self.primitive_names),
            "symbolic_cost": self.symbolic_cost,
            "expanded_states": self.expanded_states,
            "explored_complete": self.explored_complete,
            "optimal_within_palette": self.optimal_within_palette,
            "authoritative": False, "detail": self.detail,
        }


def _palette(
    intention: AffineBehaviorIntention, primitives: Sequence[AffinePrimitive]
) -> tuple[tuple[AffinePrimitive, ...], str]:
    """Freeze an ordered, unique, modulus-compatible native operator palette."""
    if (not isinstance(intention, AffineBehaviorIntention)
            or len(primitives) > _MAX_PRIMITIVES
            or any(not isinstance(p, AffinePrimitive) for p in primitives)):
        raise GroundConstructionError("untyped or oversized primitive palette")
    if (len({p.name for p in primitives}) != len(primitives)
            or any(p.modulus != intention.modulus for p in primitives)):
        raise GroundConstructionError("duplicate or incompatible native primitive")
    ordered = tuple(sorted(primitives, key=lambda p: p.name))
    return ordered, canonical_value_digest({
        "schema": _SCHEMA + ".palette", "items": [p.to_dict() for p in ordered],
    })


def _compose(
    current: tuple[int, int], primitive: AffinePrimitive, modulus: int
) -> tuple[int, int]:
    """Compute primitive AFTER current under exact modular affine composition."""
    a, c = current
    return ((primitive.multiplier * a) % modulus,
            (primitive.multiplier * c + primitive.offset) % modulus)


def synthesize_ground(
    intention: AffineBehaviorIntention,
    primitives: Sequence[AffinePrimitive],
    *,
    max_states: int = 4096,
    max_depth: int = 12,
) -> GroundConstructionPlan:
    """Find the least symbolic-cost primitive composition that realizes the law.

    Dijkstra over the finite affine transformation monoid; order is (cost,
    number of operators, lexical operator word). No independent intermediate
    time orbit or external response is simulated. The output is a mathematical
    candidate only; even its exact universal affine equivalence is not a
    receiver-authorized network transformation.
    """
    _integer(max_states, "state budget", 1, _MAX_STATES)
    _integer(max_depth, "word-depth budget", 1, _MAX_DEPTH)
    ordered, palette_hash = _palette(intention, primitives)
    target = intention.coefficients
    def answer(status: str, word: tuple[str, ...] = (),
               cost: int | None = None, expanded: int = 0,
               complete: bool = False, optimum: bool = False,
               detail: str = "") -> GroundConstructionPlan:
        return GroundConstructionPlan(
            status, intention.digest, palette_hash, target[0], target[1],
            word, cost, expanded, complete, optimum, detail,
        )

    if any((target[0] * x + target[1]) % intention.modulus != y
           for x, y in intention.challenge_cases):
        return answer("contradictory_description",
                      detail="independent desired point contradicts declared affine family")
    identity = (1 % intention.modulus, 0)
    # Every primitive cost is positive; first target popped is globally
    # cheapest over the supplied palette if finite search ceilings admit it.
    heap: list[tuple[int, int, tuple[str, ...], tuple[int, int]]] = [
        (0, 0, (), identity)
    ]
    best = {identity: (0, 0, ())}
    expanded = 0
    depth_cut = False
    while heap:
        if expanded >= max_states:
            return answer("budget_exhausted", expanded=expanded,
                          detail="transformation exploration budget exhausted")
        cost, depth, word, transform = heapq.heappop(heap)
        if best[transform] != (cost, depth, word):
            continue
        expanded += 1
        if transform == target:
            return answer(
                "constructed_exact_affine_ground", word, cost, expanded,
                complete=False, optimum=True,
                detail="exact finite affine equivalence; realization requires local permission",
            )
        if depth >= max_depth:
            if ordered:
                depth_cut = True
            continue
        for primitive in ordered:
            successor = _compose(transform, primitive, intention.modulus)
            candidate = (cost + primitive.symbolic_cost, depth + 1,
                         word + (primitive.name,))
            prior = best.get(successor)
            if prior is None or candidate < prior:
                best[successor] = candidate
                heapq.heappush(heap, (*candidate, successor))
    if depth_cut:
        return answer("budget_exhausted", expanded=expanded,
                      detail="word depth prevents proof of non-derivability")
    return answer("not_derivable_in_supplied_palette", expanded=expanded,
                  complete=True, detail="reachable affine monoid exhausted under supplied primitives")


def verify_ground_plan(
    plan: GroundConstructionPlan,
    intention: AffineBehaviorIntention,
    primitives: Sequence[AffinePrimitive],
    *,
    max_states: int = 4096,
    max_depth: int = 12,
) -> bool:
    """Recompile the requested behavior and compare the entire scoped result."""
    if not isinstance(plan, GroundConstructionPlan):
        raise GroundConstructionError("expected typed Ground plan")
    return plan == synthesize_ground(
        intention, primitives, max_states=max_states, max_depth=max_depth,
    )


def compile_ground_dag(
    plan: GroundConstructionPlan,
    intention: AffineBehaviorIntention,
    primitives: Sequence[AffinePrimitive],
) -> NavigableComputationDAG:
    """Lower a proven finite operator word into the existing E-CPU DAG.

    Every stage is explicitly mapped to the locally described TwoPort apply
    operation and has one predecessor. This is a DAG *description*, not work.
    """
    if (not isinstance(plan, GroundConstructionPlan)
            or plan.status != "constructed_exact_affine_ground"):
        raise GroundConstructionError("only constructed plans can become DAGs")
    palette, palette_digest = _palette(intention, primitives)
    if (plan.intention_digest != intention.digest
            or plan.palette_digest != palette_digest):
        raise GroundConstructionError("plan/description identity mismatch")
    lookup = {p.name: p for p in palette}
    if any(name not in lookup for name in plan.primitive_names):
        raise GroundConstructionError("plan contains an unknown operator")
    transform = (1 % intention.modulus, 0)
    for name in plan.primitive_names:
        transform = _compose(transform, lookup[name], intention.modulus)
    if transform != intention.coefficients:
        raise GroundConstructionError("plan cannot realize intended behavior")
    nodes = []
    for index, name in enumerate(plan.primitive_names):
        primitive = lookup[name]
        nodes.append(ComputationNode(
            f"ips003.stage.{index:03d}", 1, "affine.apply", "ips003.port",
            plan.digest, (f"ips003.stage.{index-1:03d}",) if index else (),
            {"primitive_name": name, "primitive_digest": primitive.digest,
             "map": [primitive.multiplier, primitive.offset],
             "modulus": intention.modulus, "intention_digest": intention.digest},
        ))
    if not nodes:
        nodes.append(ComputationNode(
            "ips003.identity", 1, "affine.identity", "ips003.port",
            plan.digest, (), {"intention_digest": intention.digest,
                              "modulus": intention.modulus},
        ))
    return NavigableComputationDAG(nodes)


@dataclass(frozen=True)
class GroundConstructionReceipt:
    """Local gate execution and independent GroundRealizer observation."""

    intention_digest: str
    plan_digest: str
    dag_snapshot: dict[str, Any]
    port_frames: tuple[dict[str, Any], ...]
    ground_receipt: dict[str, Any]
    output: int
    locus: str
    port_id: str

    @property
    def authoritative(self) -> bool:
        """A local software gate receipt is neither remote attestation nor permission."""
        return False

    @property
    def digest(self) -> str:
        """Detect ordinary content changes, without claiming a signature."""
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Return an auditable local trace, DAG checkpoint and mathematical claim."""
        return {
            "schema": _SCHEMA + ".receipt", "intention_digest": self.intention_digest,
            "plan_digest": self.plan_digest, "dag_snapshot": self.dag_snapshot,
            "port_frames": list(self.port_frames), "ground_receipt": self.ground_receipt,
            "output": self.output, "locus": self.locus, "port_id": self.port_id,
            "authoritative": False, "execution_kind": "simulated_active_two_port_gate",
        }


def _ground_intention(intention: AffineBehaviorIntention) -> GroundIntention:
    """Adapt the synthesized law into SAB-008's existing Ground contract."""
    a, c = intention.coefficients
    return GroundIntention(
        "ips003-synthesized-law",
        AffineGround(a, c, intention.modulus, intention.query_input), 1,
    )


def execute_ground_construction(
    plan: GroundConstructionPlan,
    intention: AffineBehaviorIntention,
    primitives: Sequence[AffinePrimitive],
    gate: TwoPortArithmeticGate,
    policy: RealizationPolicy,
    *,
    locus: str = "ips003-local",
    max_states: int = 4096,
    max_depth: int = 12,
) -> GroundConstructionReceipt:
    """Realize an exact word on a receiver-controlled active two-port gate.

    This invokes real Python gate transitions with strict bounded frames,
    commits them through native DAG readiness, and independently validates
    the output with the existing GroundRealizer + fixed affine oracle.
    Does not dispatch a network request or grant E-CPU Hypervisor authority.
    """
    if not verify_ground_plan(
        plan, intention, primitives, max_states=max_states, max_depth=max_depth
    ) or plan.status != "constructed_exact_affine_ground":
        raise GroundConstructionError("non-current or non-constructive plan")
    if not isinstance(gate, TwoPortArithmeticGate) or gate.modulus != intention.modulus:
        raise GroundConstructionError("gate cannot host intended modulus")
    if gate.sequence != 0:
        raise GroundConstructionError("requires a fresh local gate for unambiguous frames")
    if not isinstance(policy, RealizationPolicy):
        raise GroundConstructionError("local realization policy required")
    policy.permits(locus, "port", 1)
    palette, _ = _palette(intention, primitives)
    by_name = {p.name: p for p in palette}
    graph = compile_ground_dag(plan, intention, primitives)
    value = intention.query_input
    for index, name in enumerate(plan.primitive_names):
        ready = graph.ready_nodes()
        if len(ready) != 1 or ready[0].node_id != f"ips003.stage.{index:03d}":
            raise GroundConstructionError("native DAG frontier differs from compiled word")
        primitive = by_name[name]
        before = value
        value = gate.invoke(
            "apply", {"map": [primitive.multiplier, primitive.offset], "input": before}
        )
        if type(value) is not int:
            raise GroundConstructionError("gate returned an invalid scalar")
        graph.commit(ready[0].node_id, {"input": before, "value": value,
                                        "primitive_digest": primitive.digest})
    if not plan.primitive_names:
        ready = graph.ready_nodes()
        if len(ready) != 1 or ready[0].node_id != "ips003.identity":
            raise GroundConstructionError("native identity frontier unavailable")
        graph.commit(ready[0].node_id, {"input": value, "value": value})
    if not graph.is_complete:
        raise GroundConstructionError("native DAG did not reach completion")
    frames = tuple(dict(item) for item in gate.frames)
    ground_intention = _ground_intention(intention)
    # This is a second local evaluation of the *whole* law under a separate
    # SAB-008 oracle, not a claim of independent off-host measurement.
    oracle = realize_under_contract(
        PortGroundRealizer(locus, gate), ground_intention, policy
    )
    if oracle.payload["output"]["value"] != value:
        raise GroundConstructionError("compiled path and Ground realizer disagree")
    receipt = GroundConstructionReceipt(
        intention.digest, plan.digest, graph.snapshot(), frames,
        dict(oracle.payload), value, locus, gate.port_id,
    )
    if not verify_ground_construction(
        receipt, plan, intention, primitives, policy,
        max_states=max_states, max_depth=max_depth,
    ):
        raise GroundConstructionError("constructed receipt failed independent replay")
    return receipt


def verify_ground_construction(
    receipt: GroundConstructionReceipt,
    plan: GroundConstructionPlan,
    intention: AffineBehaviorIntention,
    primitives: Sequence[AffinePrimitive],
    policy: RealizationPolicy,
    *,
    max_states: int = 4096,
    max_depth: int = 12,
) -> bool:
    """Rebuild the native graph and independent mathematical execution witness.

    This can detect rehashed altered snapshots or forged steps because each
    intermediate result is recomputed from the *original* constrained palette,
    but does not cryptographically authenticate the local port or provider.
    """
    if not isinstance(receipt, GroundConstructionReceipt):
        raise GroundConstructionError("expected typed construction receipt")
    if not verify_ground_plan(
        plan, intention, primitives, max_states=max_states, max_depth=max_depth
    ) or plan.status != "constructed_exact_affine_ground":
        return False
    if receipt.intention_digest != intention.digest or receipt.plan_digest != plan.digest:
        return False
    palette, _ = _palette(intention, primitives)
    by_name = {p.name: p for p in palette}
    graph = compile_ground_dag(plan, intention, primitives)
    value = intention.query_input
    expected_frames = []
    for index, name in enumerate(plan.primitive_names):
        primitive = by_name[name]
        frame = {"map": [primitive.multiplier, primitive.offset], "input": value}
        expected = (primitive.multiplier * value + primitive.offset) % intention.modulus
        expected_frames.append({
            "sequence": index + 1, "opcode": "apply",
            "input_digest": frame_digest(frame), "output_digest": frame_digest(expected),
        })
        graph.commit(f"ips003.stage.{index:03d}", {
            "input": value, "value": expected, "primitive_digest": primitive.digest,
        })
        value = expected
    if not plan.primitive_names:
        graph.commit("ips003.identity", {"input": value, "value": value})
    if receipt.port_frames != tuple(expected_frames):
        return False
    if receipt.dag_snapshot != graph.snapshot() or not graph.is_complete:
        return False
    target_a, target_c = intention.coefficients
    if value != (target_a * intention.query_input + target_c) % intention.modulus:
        return False
    # Exhaustively check the finite Ground, not just the selected query.
    for x in range(intention.modulus):
        check = x
        for name in plan.primitive_names:
            primitive = by_name[name]
            check = (primitive.multiplier * check + primitive.offset) % intention.modulus
        if check != (target_a * x + target_c) % intention.modulus:
            return False
    if receipt.output != value:
        return False
    try:
        from .ground_native_realization import RealizationRefused
        verified = verify_receipt(receipt.ground_receipt, _ground_intention(intention), policy)
        if (verified["locus"] != receipt.locus or verified["method"] != "port"
                or verified["evidence"]["gate"] != receipt.port_id
                or verified["evidence"]["first"] != len(expected_frames) + 1
                or verified["output"]["value"] != value):
            return False
    except (RealizationRefused, KeyError, TypeError, ValueError):
        return False
    return True
