"""SAB-010: compile authorized primitive observations into formed Ground-native hosts.

This finite affine Ground experiment admits both (a) composed active gate
primitives distributed over logical loci and (b) E-CPU source installed into a
receiver-owned interpreter. Names and advertisements do not grant execution;
all callable bindings are installed by the receiver, challenged, and rechecked.
No arbitrary remote source or physical-host attestation is implied.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from .active_host_formation import (
    FormationPolicy, FormationRefused, ReceivingSurface, actively_form,
)
from .ground_native_realization import (
    AffineGround, GroundIntention, GroundRealizer, RealizationPolicy,
    RealizationReceipt, RealizationRefused, _receipt, realize_under_contract,
)
from .runtime_qualification import canonical, digest

SCHEMA = "mailcpu.sab010.capability-construction.v1"
COMPOSE = "affine.compose"
APPLY = "affine.apply"
STAGE = "program.stage"
ACTIVATE = "program.activate"
PRIMITIVES = frozenset({COMPOSE, APPLY, STAGE, ACTIVATE})


class ConstructionRefused(RealizationRefused):
    """The requested construction lacks current evidence, permission or a valid realization."""


def _identity(name: Any, description: str) -> str:
    if (type(name) is not str or not 1 <= len(name) <= 100
            or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-" for ch in name)):
        raise ConstructionRefused("invalid " + description)
    return name


def _int(value: Any, description: str, minimum: int = 0, maximum: int = 10**18) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ConstructionRefused("invalid " + description)
    return value


class AffinePort(Protocol):
    """A receiver-controlled arithmetic port; not an arbitrary network address."""
    modulus: int

    def invoke(self, opcode: str, frame: Mapping[str, Any]) -> tuple[int, int] | int:
        ...


@dataclass(frozen=True)
class PrimitiveBinding:
    """One observed primitive and its exact locally installed implementation.

    Evidence of an installation interface is not evidence that an installed
    program executes: SAB-009 challenges the installed seed before admission.
    """
    locus: str
    operation: str
    observed_at: int
    expires_at: int
    estimated_quanta: int
    evidence_kind: str
    evidence_digest: str
    implementation: Any = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _identity(self.locus, "locus")
        if self.operation not in PRIMITIVES:
            raise ConstructionRefused("unknown primitive operation")
        _int(self.observed_at, "observation coordinate")
        _int(self.expires_at, "primitive expiry", self.observed_at)
        _int(self.estimated_quanta, "declared cost", 1, 100000)
        if self.evidence_kind not in {"challenged_gate", "receiver_owned_interface"}:
            raise ConstructionRefused("unsupported evidence grade")
        if ((self.operation in {COMPOSE, APPLY}) != (self.evidence_kind == "challenged_gate")):
            raise ConstructionRefused("evidence grade incompatible with primitive")
        if (type(self.evidence_digest) is not str or len(self.evidence_digest) != 64
                or any(c not in "0123456789abcdef" for c in self.evidence_digest)):
            raise ConstructionRefused("invalid observation digest")
        if self.operation in {COMPOSE, APPLY}:
            if not callable(getattr(self.implementation, "invoke", None)):
                raise ConstructionRefused("gate implementation is not locally callable")
        elif self.operation in {STAGE, ACTIVATE}:
            method = "stage" if self.operation == STAGE else "activate"
            if not callable(getattr(self.implementation, method, None)):
                raise ConstructionRefused("receiver-owned installation primitive missing")
            _identity(getattr(self.implementation, "surface_id", None), "receiving surface")
            _identity(getattr(self.implementation, "engine", None), "interpreter engine")

    @property
    def fingerprint(self) -> str:
        """Bind the declared primitive, lease, observation, and cost, not a Python object pointer."""
        return digest({"schema": SCHEMA + ".primitive", "locus": self.locus,
                       "operation": self.operation, "observed_at": self.observed_at,
                       "expires_at": self.expires_at,
                       "estimated_quanta": self.estimated_quanta,
                       "evidence_kind": self.evidence_kind,
                       "evidence_digest": self.evidence_digest})


def _gate_challenge(port: AffinePort, operation: str) -> dict[str, Any]:
    """Check a real bounded primitive transition before creating a gate offer."""
    m = getattr(port, "modulus", None)
    _int(m, "port modulus", 2, 2**31 - 1)
    if operation == COMPOSE:
        frame = {"first": [2 % m, 3 % m], "second": [5 % m, 7 % m]}
        expected: tuple[int, int] | int = (10 % m, 22 % m)
        actual = port.invoke("compose", frame)
    elif operation == APPLY:
        frame = {"map": [5 % m, 7 % m], "input": 11 % m}
        expected = (5 * (11 % m) + 7) % m
        actual = port.invoke("apply", frame)
    else:
        raise ConstructionRefused("not an active gate primitive")
    if (type(actual) is not type(expected) or actual != expected):
        raise ConstructionRefused("gate did not demonstrate its declared primitive")
    return {"role": operation, "modulus": m, "input": frame,
            "expected": list(expected) if isinstance(expected, tuple) else expected}


def observe_gate(port: AffinePort, *, locus: str, operation: str,
                 coordinate: int, lease_until: int, cost: int = 2) -> PrimitiveBinding:
    """Record finite *active* evidence for a locally owned gate primitive."""
    if operation not in {COMPOSE, APPLY}:
        raise ConstructionRefused("gate can advertise only its actual arithmetic transition")
    challenge = _gate_challenge(port, operation)
    return PrimitiveBinding(locus, operation, coordinate, lease_until, cost,
                            "challenged_gate", digest(challenge), port)


def bind_receiving_surface(surface: ReceivingSurface, *, locus: str,
                           operation: str, coordinate: int,
                           lease_until: int, cost: int = 2) -> PrimitiveBinding:
    """Bind a receiver-owned installation interface, never claim pre-execution proof."""
    if operation not in {STAGE, ACTIVATE}:
        raise ConstructionRefused("installation adapter binds stage/activate only")
    _identity(surface.surface_id, "receiving surface")
    _identity(surface.engine, "engine")
    marker = {"kind": "locally_pinned_candidate", "surface": surface.surface_id,
              "engine": surface.engine, "operation": operation}
    return PrimitiveBinding(locus, operation, coordinate, lease_until, cost,
                            "receiver_owned_interface", digest(marker), surface)


@dataclass(frozen=True)
class ConstructionPolicy:
    """Receiver-owned exact construction permissions, logical lease and resource ceilings."""
    allowed: frozenset[tuple[str, str]]
    expires_at: int
    max_quanta: int = 1000
    max_events: int = 256
    max_bytes: int = 8192

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, frozenset) or not self.allowed:
            raise ConstructionRefused("construction needs exact permissions")
        for item in self.allowed:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ConstructionRefused("malformed primitive permission")
            _identity(item[0], "permission locus")
            if item[1] not in PRIMITIVES:
                raise ConstructionRefused("unknown primitive permission")
        _int(self.expires_at, "permission expiry")
        _int(self.max_quanta, "construction budget", 1, 1000000)
        _int(self.max_events, "event bound", 1, 2048)
        _int(self.max_bytes, "frame limit", 256, 8192)

    @property
    def fingerprint(self) -> str:
        return digest({"schema": SCHEMA + ".authority", "allowed": [list(x) for x in sorted(self.allowed)],
                       "expires_at": self.expires_at, "max_quanta": self.max_quanta,
                       "max_events": self.max_events, "max_bytes": self.max_bytes})


@dataclass(frozen=True)
class ConstructionInventory:
    """Locally bound primitive observations; names alone contain no callable code."""
    bindings: tuple[PrimitiveBinding, ...]

    def __post_init__(self) -> None:
        if not 1 <= len(self.bindings) <= 64:
            raise ConstructionRefused("primitive inventory outside finite bound")
        if any(not isinstance(x, PrimitiveBinding) for x in self.bindings):
            raise ConstructionRefused("inventory contains an invalid binding")
        keys = [(b.locus, b.operation) for b in self.bindings]
        if len(set(keys)) != len(keys):
            raise ConstructionRefused("ambiguous primitive at one locus")

    @property
    def fingerprint(self) -> str:
        return digest({"schema": SCHEMA + ".inventory",
                       "primitives": [b.fingerprint for b in sorted(self.bindings, key=lambda x:(x.locus,x.operation))]})


@dataclass(frozen=True)
class ConstructionPlan:
    """A non-authoritative recipe pinned to exact Ground, observed primitives, and grants."""
    intention_digest: str
    inventory_digest: str
    authority_digest: str
    recipe: str
    bindings: tuple[tuple[str, str], ...]
    declared_quanta: int
    coordinate: int

    @property
    def fingerprint(self) -> str:
        return digest({"schema": SCHEMA + ".plan", "intention": self.intention_digest,
                       "inventory": self.inventory_digest, "authority": self.authority_digest,
                       "recipe": self.recipe, "bindings": [list(x) for x in self.bindings],
                       "quanta": self.declared_quanta, "coordinate": self.coordinate})


class SplitReceivingSurface:
    """Compose independently bound stage/activation interfaces into one logical formed host.

    Shared artifact visibility is a precondition checked by the activation
    implementation; no remote shared filesystem or data-plane claim is made.
    """
    def __init__(self, stage: ReceivingSurface, activation: ReceivingSurface) -> None:
        if (stage.surface_id != activation.surface_id or stage.engine != activation.engine):
            raise ConstructionRefused("stage and activation do not name one compatible receiving surface")
        self.surface_id = stage.surface_id
        self.engine = stage.engine
        self._stage, self._activation = stage, activation

    def stage(self, manifest: Any, source: bytes) -> None:
        return self._stage.stage(manifest, source)

    def activate(self, manifest: Any, request: Mapping[str, Any],
                 *, timeout: float, max_bytes: int) -> Mapping[str, Any]:
        return self._activation.activate(manifest, request, timeout=timeout, max_bytes=max_bytes)


class SplitGateRealizer:
    """Construct an affine navigator out of independently bound compose and apply ports."""
    method = "constructed.gate-algebra"

    def __init__(self, locus: str, compose: PrimitiveBinding, apply: PrimitiveBinding,
                 construction: ConstructionPolicy) -> None:
        self.locus = _identity(locus, "virtual locus")
        self.compose = compose
        self.apply = apply
        self.construction = construction

    def observe(self, intention: GroundIntention, policy: RealizationPolicy) -> RealizationReceipt:
        policy.permits(self.locus, self.method, intention.coordinate)
        if intention.coordinate > self.construction.expires_at:
            raise ConstructionRefused("construction grant expired")
        for b in (self.compose, self.apply):
            if ((b.locus,b.operation) not in self.construction.allowed or
                    not b.observed_at <= intention.coordinate <= b.expires_at or
                    getattr(b.implementation,"modulus",None) != intention.ground.modulus):
                raise ConstructionRefused("missing current gate primitive or incompatible Ground")
            _gate_challenge(b.implementation,b.operation)
        n = intention.coordinate
        accumulator: tuple[int,int] = (1,0)
        base: tuple[int,int] = (intention.ground.a,intention.ground.c)
        events: list[dict[str,Any]] = []
        def invoke(binding: PrimitiveBinding, opcode: str, data: dict[str,Any]) -> Any:
            if len(events) >= self.construction.max_events:
                raise ConstructionRefused("constructed navigation exceeds event budget")
            if len(canonical({"opcode":opcode,"payload":data})) > self.construction.max_bytes:
                raise ConstructionRefused("constructed frame exceeds byte budget")
            answer = binding.implementation.invoke(opcode,data)
            events.append({"index":len(events)+1,"locus":binding.locus,"primitive":binding.operation,
                           "input_digest":digest(data),"output_digest":digest(answer)})
            return answer
        modulus=intention.ground.modulus
        def composed(first:tuple[int,int], second:tuple[int,int]) -> tuple[int,int]:
            """Independently check each bounded gate step, not only the final observation."""
            got=invoke(self.compose,"compose",{"first":list(first),"second":list(second)})
            expected=((second[0]*first[0])%modulus,(second[0]*first[1]+second[1])%modulus)
            if (type(got) is not tuple or len(got)!=2 or
                    any(type(x) is not int for x in got) or got!=expected):
                raise ConstructionRefused("gate composition contradicts its admitted algebra")
            return got
        while n:
            if n & 1:
                accumulator=composed(accumulator,base)
            base=composed(base,base)
            n >>= 1
        value=invoke(self.apply,"apply",{"map":list(accumulator),"input":intention.ground.seed})
        if type(value) is not int or value != (accumulator[0]*intention.ground.seed+accumulator[1])%modulus:
            raise ConstructionRefused("gate application contradicts its admitted algebra")
        evidence = {"schema":SCHEMA,"formed_from":[self.compose.fingerprint,self.apply.fingerprint],
                    "port_count":len({self.compose.locus,self.apply.locus}),
                    "construction_policy":self.construction.fingerprint,
                    "physical_hosts_attested":False}
        return _receipt(intention,policy,locus=self.locus,method=self.method,
                        value=value,events=events,evidence=evidence)


class CapabilityConstructionCompiler:
    """Select a bounded cheapest admissible recipe and form its runtime on demand."""

    def __init__(self, inventory: ConstructionInventory, authority: ConstructionPolicy) -> None:
        self.inventory, self.authority = inventory, authority

    def _current(self, intention: GroundIntention) -> dict[str, list[PrimitiveBinding]]:
        if intention.coordinate > self.authority.expires_at:
            raise ConstructionRefused("construction authority expired")
        available: dict[str,list[PrimitiveBinding]] = {x:[] for x in PRIMITIVES}
        for b in self.inventory.bindings:
            if ((b.locus,b.operation) in self.authority.allowed and
                    b.observed_at <= intention.coordinate <= b.expires_at):
                available[b.operation].append(b)
        for role in available:
            available[role].sort(key=lambda b:(b.estimated_quanta,b.locus,b.fingerprint))
        return available

    def compile(self, intention: GroundIntention) -> ConstructionPlan:
        """Search finite primitive conjunctions without assuming a substrate type."""
        if not isinstance(intention,GroundIntention):
            raise ConstructionRefused("construction requires a typed Ground intention")
        inv = self._current(intention)
        choices: list[tuple[int,str,tuple[PrimitiveBinding,...]]] = []
        operations = intention.coordinate.bit_length()+intention.coordinate.bit_count()+1
        for compose in inv[COMPOSE]:
            for apply in inv[APPLY]:
                if (getattr(compose.implementation,"modulus",None) == intention.ground.modulus
                        and getattr(apply.implementation,"modulus",None) == intention.ground.modulus
                        and operations <= self.authority.max_events):
                    cost = compose.estimated_quanta*(operations-1)+apply.estimated_quanta
                    choices.append((cost,"gate-algebra",(compose,apply)))
        for stage in inv[STAGE]:
            for activate in inv[ACTIVATE]:
                surface_a=stage.implementation
                surface_b=activate.implementation
                if (surface_a.surface_id == surface_b.surface_id and surface_a.engine == surface_b.engine):
                    cost=stage.estimated_quanta+4*activate.estimated_quanta
                    choices.append((cost,"formed-seed",(stage,activate)))
        choices=[x for x in choices if x[0]<=self.authority.max_quanta]
        if not choices:
            raise ConstructionRefused("no authorized constructible Ground navigator in observed primitive algebra")
        cost,recipe,bindings=min(choices,key=lambda x:(x[0],x[1],tuple((b.locus,b.operation) for b in x[2])))
        return ConstructionPlan(intention.fingerprint,self.inventory.fingerprint,
                                self.authority.fingerprint,recipe,
                                tuple((b.locus,b.operation) for b in bindings),cost,intention.coordinate)

    def form(self, intention: GroundIntention, plan: ConstructionPlan,
             *, formation_policy: FormationPolicy | None = None) -> tuple[GroundRealizer,RealizationReceipt]:
        """Recompile before mutation, form the host, then verify one independent observation."""
        fresh = self.compile(intention)
        if not isinstance(plan,ConstructionPlan) or plan.fingerprint != fresh.fingerprint:
            raise ConstructionRefused("stale construction plan, evidence or permission changed")
        keyed = {(b.locus,b.operation):b for b in self.inventory.bindings}
        bindings=tuple(keyed[p] for p in fresh.bindings)
        if fresh.recipe == "gate-algebra":
            target="formed.gates."+digest({"bindings":list(map(list,fresh.bindings))})[:18]
            realizer:GroundRealizer=SplitGateRealizer(target,bindings[0],bindings[1],self.authority)
            policy=RealizationPolicy(frozenset({(target,realizer.method)}),self.authority.expires_at,
                                     max_events=self.authority.max_events,max_bytes=self.authority.max_bytes)
        elif fresh.recipe == "formed-seed":
            stage,activate=bindings
            if formation_policy is None:
                raise ConstructionRefused("seed formation requires separate receiver-owned installation grant")
            surface=SplitReceivingSurface(stage.implementation,activate.implementation)
            try:
                realizer=actively_form(surface,intention.ground,formation_policy,coordinate=intention.coordinate)
            except (FormationRefused, OSError, ValueError) as exc:
                raise ConstructionRefused("active installation or Ground qualification failed") from exc
            policy=RealizationPolicy(frozenset({(realizer.locus,realizer.method)}),self.authority.expires_at,
                                     max_events=self.authority.max_events,max_bytes=self.authority.max_bytes)
        else:
            raise ConstructionRefused("unsupported compiled recipe")
        receipt=realize_under_contract(realizer,intention,policy)
        return realizer,receipt
