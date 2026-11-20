"""NCB-003: independently admit and execute NCP-002 constructed controller actions.

A portable, mathematical possibility packet is *not* a capability, executable
program, network route or installed resource. This module independently
reconstructs the NCP-002 finite coupled brief, ranks and selected controller,
then binds its exact requested pure operations to the native E-CPU
ComputationalHostCatalogue, ComputationalAddressResolver,
ComputationalExecutionAdmissionCoordinator and Hypervisor.

Only a receiver-registered runtime can execute. Observed results are checked
against the independently expanded possible successor relation, including
coupled resource capacity and forbidden joint states. This does not enact
stateful external effects: the IPS-008 receiver-owned effect-barrier protocol
remains an independent required authority boundary for such operations.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from itertools import product
from math import prod
import json
from typing import Any, Mapping, Sequence

from .computational_resolver import (
    ComputationalAddress, ComputationalAddressResolver,
    ComputationalHostCatalogue, ComputationalResolutionStatus,
)
from .computational_execution import (
    ComputationalExecutionAdmissionCoordinator, ComputationalExecutionStatus,
)
from .virtual_layer import VirtualLayerRuntime


_SCHEMA = "navigable-compute.coupled-world.v0.1"
_SOURCE = "navigable-compute.coupled-brief.v0.1"
_MAX_PACKET_BYTES = 196608
_MAX_STATES = 256
_MAX_JOINT_ACTIONS = 128


class CoupledControllerAdmissionError(ValueError):
    """Refuse an unrealizable, unauthorised, or incorrectly observed action."""


def _canonical(value: Any) -> bytes:
    """Use the original NCP-002 ASCII JSON canonicalization, not E-CPU's."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise CoupledControllerAdmissionError("noncanonical constructed Ground packet") from exc


def _hash(value: Any) -> str:
    """Reconstruct the source's mathematical identity without trusting metadata."""
    return sha256(_canonical(value)).hexdigest()


def _keys(value: Any, fields: set[str], name: str) -> dict[str, Any]:
    """Reject extra/omitted fields before interpreting untrusted descriptions."""
    if type(value) is not dict or set(value) != fields:
        raise CoupledControllerAdmissionError(f"{name} has an invalid schema")
    return value


def _int(value: Any, lower: int, upper: int, name: str) -> int:
    """Require an exact bounded integer rather than accepting Boolean coercion."""
    if type(value) is not int or not lower <= value <= upper:
        raise CoupledControllerAdmissionError(f"{name} is not an exact bounded integer")
    return value


def _set(value: Any, length: int, name: str, *, allow_empty: bool = True) -> tuple[int, ...]:
    """Revalidate the original sorted unique integer-set representation."""
    if type(value) is not list or (not value and not allow_empty):
        raise CoupledControllerAdmissionError(f"{name} must be a sorted set")
    try:
        items = tuple(_int(x, 0, length - 1, name) for x in value)
    except (TypeError, ValueError) as exc:
        raise CoupledControllerAdmissionError(f"{name} contains an invalid item") from exc
    if tuple(sorted(set(items))) != items:
        raise CoupledControllerAdmissionError(f"{name} is not sorted/unique")
    return items


def _coord(value: Any, width: int, sizes: tuple[int,...], name: str) -> tuple[int,...]:
    """Decode one exact product coordinate without Python integer coercion."""
    if type(value) is not list or len(value) != width:
        raise CoupledControllerAdmissionError(f"{name} is not an exact joint coordinate")
    return tuple(_int(x, 0, size - 1, name) for x,size in zip(value, sizes))


def _decimal(value: Any, name: str, *, positive: bool = False) -> int:
    """Parse a bounded canonical decimal integer used by NCP mixed-radix indices."""
    if (type(value) is not str or not value or not value.isascii()
            or not value.isdecimal() or (len(value)>1 and value[0]=="0")
            or len(value)>1234):
        raise CoupledControllerAdmissionError(f"{name} must be canonical decimal")
    number=int(value)
    if (positive and number==0) or number.bit_length()>4096:
        raise CoupledControllerAdmissionError(f"{name} is outside certificate bounds")
    return number


@dataclass(frozen=True)
class CheckedCoupledController:
    """Receiver-qualified finite Ground; carries mathematical evidence only."""

    packet_digest: str
    source_digest: str
    coordinate: int
    states: tuple[tuple[int,...],...]
    goals: frozenset[int]
    ranks: tuple[int,...]
    policy: tuple[tuple[int,...],...]
    transitions: tuple[dict[tuple[int,...], tuple[int,...]],...]
    action_names: tuple[tuple[str,...],...]
    resources: tuple[tuple[str,int,tuple[tuple[int,str],...]],...]
    convergence_bound: int

    def next_action(self, state: tuple[int,...]) -> "ConstructedAction":
        """Select the exact certified joint action and all allowed next states."""
        if type(state) is not tuple or state not in self.states:
            raise CoupledControllerAdmissionError("state is outside the admitted Ground")
        index=self.states.index(state)
        if index in self.goals:
            raise CoupledControllerAdmissionError("terminal goal has no further action")
        if self.ranks[index]<1:
            raise CoupledControllerAdmissionError("requested source state is not winning")
        selected=self.policy[index]
        outcomes=self.transitions[index].get(selected)
        if not outcomes:
            raise CoupledControllerAdmissionError("selected controller action is not enabled")
        return ConstructedAction(
            packet_digest=self.packet_digest,source_digest=self.source_digest,
            coordinate=self.coordinate,state=state,action=selected,
            names=tuple(self.action_names[i][a] if a>=0 else None
                        for i,a in enumerate(selected)),
            allowed=tuple(self.states[j] for j in outcomes),
            rank=self.ranks[index],
        )


@dataclass(frozen=True)
class ConstructedAction:
    """An inert, source-bound mathematical instruction and possible successors."""

    packet_digest: str
    source_digest: str
    coordinate: int
    state: tuple[int,...]
    action: tuple[int,...]
    names: tuple[str|None,...]
    allowed: tuple[tuple[int,...],...]
    rank: int

    @property
    def digest(self) -> str:
        """Bind the selected observer coordinate and exact requested relation."""
        return _hash({
            "schema":"mailcpu.ncb003.constructed-action.v1",
            "packet":self.packet_digest,"source":self.source_digest,
            "instance_coordinate":str(self.coordinate),
            "state":list(self.state),"action":list(self.action),
            "allowed":[list(s) for s in self.allowed],"rank":self.rank,
        })


@dataclass(frozen=True)
class NativeActionBinding:
    """Trusted local host/capability binding for one specific factor/action."""

    factor: int
    action: str
    host_id: str
    address: ComputationalAddress
    runtime: VirtualLayerRuntime

    def __post_init__(self) -> None:
        """Refuse malformed receiver configuration before any native execution."""
        if (type(self.factor) is not int or self.factor<0
                or type(self.action) is not str or not self.action
                or type(self.host_id) is not str or not self.host_id
                or not isinstance(self.address,ComputationalAddress)
                or not isinstance(self.runtime,VirtualLayerRuntime)):
            raise CoupledControllerAdmissionError("native action binding is not receiver-owned and typed")


@dataclass(frozen=True)
class NativeResourceBinding:
    """Receiver-declared available capacity for a named NCP-002 shared resource.

    This is LOCAL configuration, not a reservation or external capacity
    attestation. A later effectful integration must serialize actual claims
    at the receiving resource before performing state-changing operations.
    """

    name: str
    capacity: int
    claims: tuple[tuple[int,str], ...]

    def __post_init__(self) -> None:
        """Refuse ambiguous receiver resource capabilities."""
        if (type(self.name) is not str or not 1<=len(self.name)<=64
                or type(self.capacity) is not int or not 0<=self.capacity<=128
                or type(self.claims) is not tuple
                or tuple(sorted(set(self.claims)))!=self.claims
                or any(type(p) is not tuple or len(p)!=2
                       or type(p[0]) is not int or p[0]<0
                       or type(p[1]) is not str or not p[1]
                       for p in self.claims)):
            raise CoupledControllerAdmissionError("invalid trusted receiver resource policy")


@dataclass(frozen=True)
class QualifiedConstructedStep:
    """One checked step with independent E-CPU host and Hypervisor receipts."""

    action: ConstructedAction
    observed: tuple[int,...]
    native_receipts: tuple[dict[str,Any],...]
    status: str
    digest: str

    def to_dict(self) -> dict[str,Any]:
        """Return a portable receipt without exporting capability-bearing PIDs."""
        return {
            "schema":"mailcpu.ncb003.qualified-step.v1",
            "selected_action_digest":self.action.digest,
            "packet_digest":self.action.packet_digest,
            "observed":list(self.observed),
            "native_receipts":[dict(r) for r in self.native_receipts],
            "status":self.status,"digest":self.digest,
        }


def verify_coupled_controller(packet: Mapping[str,Any]) -> CheckedCoupledController:
    """Independently check NCP-002 source expansion, optimality and instance.

    Does not import Navigable-Compute, execute user-supplied code or delegate
    to NCP's constructor/checker. This is a bounded separate implementation
    of the declared two-to-four-factor possibility semantics.
    """
    if not isinstance(packet,Mapping):
        raise CoupledControllerAdmissionError("typed constructed Ground packet required")
    raw=_canonical(dict(packet))
    if len(raw)>_MAX_PACKET_BYTES:
        raise CoupledControllerAdmissionError("constructed Ground packet exceeds byte bound")
    world=_keys(json.loads(raw),{
        "schema","source","states","rank","optimal","policy",
        "optimal_laws_decimal","worst_steps",
        "instance_coordinate_decimal","sha256",
    },"NCP-002 packet")
    if world["schema"]!=_SCHEMA or world["sha256"]!=_hash({k:v for k,v in world.items() if k!="sha256"}):
        raise CoupledControllerAdmissionError("source controller digest or schema mismatch")
    source=_keys(world["source"],{"schema","factors","resources","unsafe_joint"},"source brief")
    if source["schema"]!=_SOURCE or type(source["factors"]) is not list:
        raise CoupledControllerAdmissionError("unsupported coupled source Ground")
    specs=source["factors"]
    if not 2<=len(specs)<=4 or type(source["resources"]) is not list:
        raise CoupledControllerAdmissionError("unsupported number of coupled factors/resources")
    sizes=[]
    initials=[]
    goals=[]
    unsafes=[]
    names=[]
    tables=[]
    for factor in specs:
        f=_keys(factor,{"states","initial","goal","unsafe","actions"},"factor")
        size=_int(f["states"],2,16,"factor size")
        sizes.append(size)
        initials.append(_set(f["initial"],size,"initial",allow_empty=False))
        goals.append(_set(f["goal"],size,"goal",allow_empty=False))
        unsafes.append(_set(f["unsafe"],size,"unsafe"))
        if set(goals[-1])&set(unsafes[-1]) or set(initials[-1])&set(unsafes[-1]):
            raise CoupledControllerAdmissionError("source initial/goal overlaps unsafe")
        if type(f["actions"]) is not list or not 1<=len(f["actions"])<=16:
            raise CoupledControllerAdmissionError("factor has no bounded action grammar")
        actions=[]
        labels=[]
        for action in f["actions"]:
            a=_keys(action,{"name","cases"},"action sketch")
            if type(a["name"]) is not str or not 1<=len(a["name"])<=64:
                raise CoupledControllerAdmissionError("invalid action name")
            if a["name"] in labels or type(a["cases"]) is not list:
                raise CoupledControllerAdmissionError("ambiguous action grammar")
            labels.append(a["name"])
            by_state=[() for _ in range(size)]
            used=set()
            for case in a["cases"]:
                c=_keys(case,{"first","stop","deltas","absolute"},"effect clause")
                first=_int(c["first"],0,size-1,"effect first")
                stop=_int(c["stop"],first+1,size,"effect stop")
                if type(c["deltas"]) is not list or type(c["absolute"]) is not list:
                    raise CoupledControllerAdmissionError("invalid effect outcomes")
                deltas=tuple(c["deltas"])
                absolute=_set(c["absolute"],size,"absolute effects")
                if (not deltas and not absolute
                        or any(type(d) is not int or abs(d)>4096 for d in deltas)
                        or tuple(sorted(set(deltas)))!=deltas):
                    raise CoupledControllerAdmissionError("ambiguous effect deltas")
                for state in range(first,stop):
                    if state in used:
                        raise CoupledControllerAdmissionError("overlapping effect intervals")
                    used.add(state)
                    by_state[state]=tuple(sorted(set(absolute)|{
                        max(0,min(size-1,state+d)) for d in deltas
                    }))
            actions.append(tuple(by_state))
        names.append(tuple(labels))
        tables.append(tuple(actions))
    sizes=tuple(sizes)
    count=prod(sizes)
    if count>_MAX_STATES or prod(len(x) for x in names)>_MAX_JOINT_ACTIONS:
        raise CoupledControllerAdmissionError("coupled Ground requires larger bounded solver")
    resource_rules=[]
    resource_names=set()
    for resource in source["resources"]:
        r=_keys(resource,{"name","capacity","claims"},"shared resource")
        if (type(r["name"]) is not str or not 1<=len(r["name"])<=64
                or r["name"] in resource_names or type(r["claims"]) is not list
                or not r["claims"]):
            raise CoupledControllerAdmissionError("shared resource grammar invalid")
        resource_names.add(r["name"])
        capacity=_int(r["capacity"],0,128,"resource capacity")
        claims=[]
        for item in r["claims"]:
            if type(item) is not list or len(item)!=2:
                raise CoupledControllerAdmissionError("invalid resource claim")
            fi=_int(item[0],0,len(specs)-1,"resource factor")
            if type(item[1]) is not str or item[1] not in names[fi]:
                raise CoupledControllerAdmissionError("resource references unknown action")
            claims.append((fi,item[1]))
        if tuple(sorted(set(claims)))!=tuple(claims):
            raise CoupledControllerAdmissionError("resource claims ambiguous")
        resource_rules.append((capacity,frozenset(claims)))
    if type(source["unsafe_joint"]) is not list:
        raise CoupledControllerAdmissionError("joint unsafe coordinates missing")
    unsafe_joint=tuple(_coord(s,len(sizes),sizes,"unsafe joint") for s in source["unsafe_joint"])
    if tuple(sorted(set(unsafe_joint)))!=unsafe_joint:
        raise CoupledControllerAdmissionError("unsafe joint coordinates ambiguous")
    basis=tuple(product(*(range(n) for n in sizes)))
    position={state:i for i,state in enumerate(basis)}
    if world["states"]!=[list(s) for s in basis]:
        raise CoupledControllerAdmissionError("source joint state enumeration differs")
    # Python considers bool equal to 0/1 and some floats equal to integers.
    # Neither may enter a typed mathematical witness as a rank or action.
    if (type(world["rank"]) is not list
            or any(type(v) is not int for v in world["rank"])
            or type(world["optimal"]) is not list
            or type(world["policy"]) is not list
            or any(type(row) is not list
                   or any(type(action) is not list
                          or any(type(item) is not int for item in action)
                          for action in row)
                   for row in world["optimal"])
            or any(type(action) is not list
                   or any(type(item) is not int for item in action)
                   for action in world["policy"])
            or type(world["worst_steps"]) is not int):
        raise CoupledControllerAdmissionError("witness rank/action types are not exact integers")
    unsafe=set(unsafe_joint)
    safe={i for i,s in enumerate(basis)
          if s not in unsafe and all(s[j] not in unsafes[j] for j in range(len(sizes)))}
    target={i for i,s in enumerate(basis)
            if i in safe and all(s[j] in goals[j] for j in range(len(sizes)))}
    initial=tuple(position[x] for x in product(*initials))
    if any(i not in safe for i in initial):
        raise CoupledControllerAdmissionError("admitted initial state is unsafe")
    relations=[]
    for index,state in enumerate(basis):
        choices={}
        if index in safe and index not in target:
            menus=tuple((-1,) if state[j] in goals[j] else tuple(
                k for k,a in enumerate(tables[j]) if a[state[j]]
            ) for j in range(len(sizes)))
            for action in product(*menus):
                if any(sum((j,names[j][a]) in claims for j,a in enumerate(action) if a>=0)>capacity
                       for capacity,claims in resource_rules):
                    continue
                destinations=tuple(
                    position[successor] for successor in product(*(
                        (state[j],) if action[j]<0 else tables[j][action[j]][state[j]]
                        for j in range(len(sizes))
                    ))
                )
                if destinations:
                    choices[action]=destinations
        relations.append(choices)
    ranks=[-1]*len(basis)
    for g in target:
        ranks[g]=0
    for depth in range(1,len(basis)+1):
        added=[i for i in sorted(safe) if ranks[i]<0 and
               any(all(0<=ranks[j]<depth for j in successors)
                   for successors in relations[i].values())]
        if not added:
            break
        for i in added:
            ranks[i]=depth
    if any(ranks[i]<0 for i in initial):
        raise CoupledControllerAdmissionError("the declared joint intention is unrealizable")
    optimal=[]
    total=1
    for i in range(len(basis)):
        if ranks[i]<1:
            optimal.append(())
            continue
        eligible=tuple(sorted(a for a,successors in relations[i].items()
                              if all(ranks[j]>=0 for j in successors)
                              and max(ranks[j] for j in successors)==ranks[i]-1))
        if not eligible:
            raise CoupledControllerAdmissionError("rank has no valid descent action")
        optimal.append(eligible)
        total*=len(eligible)
    if total.bit_length()>4096:
        raise CoupledControllerAdmissionError("too many controller policies")
    coordinate=_decimal(world["instance_coordinate_decimal"],"instance coordinate")
    policies=[]
    remainder=coordinate
    for row in optimal:
        if row:
            policies.append(row[remainder%len(row)])
            remainder//=len(row)
        else:
            policies.append(())
    if (remainder or world["optimal_laws_decimal"]!=str(total)
            or world["worst_steps"]!=max(ranks[i] for i in initial)
            or world["rank"]!=ranks
            or world["optimal"]!=[[list(x) for x in row] for row in optimal]
            or world["policy"]!=[list(x) for x in policies]):
        raise CoupledControllerAdmissionError("Bellman ranks, controller or instance coordinate mismatch")
    return CheckedCoupledController(
        packet_digest=world["sha256"],source_digest=_hash(source),
        coordinate=coordinate,states=basis,goals=frozenset(target),
        ranks=tuple(ranks),policy=tuple(policies),
        transitions=tuple(relations),action_names=tuple(names),
        resources=tuple((r["name"],r["capacity"],
                         tuple((pair[0],pair[1]) for pair in r["claims"]))
                        for r in source["resources"]),
        convergence_bound=world["worst_steps"],
    )


def execute_constructed_action(
    controller: CheckedCoupledController,
    state: tuple[int,...],
    bindings: Sequence[NativeActionBinding],
    catalogue: ComputationalHostCatalogue,
    coordinator: ComputationalExecutionAdmissionCoordinator,
    *,
    resources: Sequence[NativeResourceBinding],
    source: str="ncp002-controller",
    sequence: int=1,
) -> QualifiedConstructedStep:
    """Run only mathematically selected pure actions under native E-CPU authority.

    Preflight re-resolves *every* required live host before dispatching any
    pure operation. E-CPU's execution coordinator re-resolves again and
    delegates to its native Hypervisor; success is checked against the exact
    declared successor relation. There is deliberately NO external mutation.
    """
    if (not isinstance(controller,CheckedCoupledController)
            or not isinstance(catalogue,ComputationalHostCatalogue)
            or not isinstance(coordinator,ComputationalExecutionAdmissionCoordinator)
            or type(sequence) is not int or sequence<1):
        raise CoupledControllerAdmissionError("native controller execution configuration invalid")
    action=controller.next_action(state)
    if (not isinstance(resources,Sequence)
            or any(not isinstance(r,NativeResourceBinding) for r in resources)
            or tuple(sorted((r.name,r.capacity,r.claims) for r in resources))
               != tuple(sorted(controller.resources))):
        raise CoupledControllerAdmissionError(
            "receiver has not qualified the exact constructed resource capacities"
        )
    for resource in resources:
        count=sum((i,name) in resource.claims
                  for i,name in enumerate(action.names) if name is not None)
        if count>resource.capacity:
            raise CoupledControllerAdmissionError(
                "selected joint operation exceeds receiver resource capacity"
            )
    required={(i,name) for i,name in enumerate(action.names) if name is not None}
    if (not isinstance(bindings,Sequence)
            or len(bindings)!=len(required)
            or any(not isinstance(b,NativeActionBinding) for b in bindings)
            or {(b.factor,b.action) for b in bindings}!=required):
        raise CoupledControllerAdmissionError("missing or extra receiver-owned action binding")
    ordered=sorted(bindings,key=lambda b:b.factor)
    resolved=[]
    for b in ordered:
        if b.address.computational_ground_fingerprint!=controller.packet_digest or b.address.program_fingerprint!=controller.packet_digest:
            raise CoupledControllerAdmissionError("host has not pinned the constructed Ground and controller")
        input_value=dict(b.address.workload.input_value)
        expected={
            "controller_digest":controller.packet_digest,
            "action_digest":action.digest,
            "factor_index":b.factor,
            "source_state":action.state[b.factor],
            "action_name":b.action,
        }
        if input_value!=expected:
            raise CoupledControllerAdmissionError("runtime workload input is not bound to the requested action")
        outcome=coordinator.resolver.resolve(b.address,catalogue,coordinator.operating_system)
        if (outcome.status is not ComputationalResolutionStatus.FOUND
                or outcome.witness is None or outcome.witness.host_id!=b.host_id):
            raise CoupledControllerAdmissionError("native host capability or exact route is unavailable")
        resolved.append((b,outcome.witness))
    observed=list(state)
    receipts=[]
    for offset,(binding,witness) in enumerate(resolved):
        result=coordinator.execute(
            binding.address,witness,catalogue,binding.runtime,
            source=source,channel="constructed.controller.step",
            sequence=sequence+offset,
        )
        if (result.status not in (ComputationalExecutionStatus.EXECUTED,
                                  ComputationalExecutionStatus.REPLAYED)
                or result.execution is None or result.execution.effect is None):
            raise CoupledControllerAdmissionError(
                f"native Hypervisor or admission refused factor {binding.factor}: {result.status.value}"
            )
        output=result.execution.effect.get("result")
        if type(output) is not int:
            raise CoupledControllerAdmissionError("native handler returned no typed state")
        allowed={s[binding.factor] for s in action.allowed}
        if output not in allowed:
            raise CoupledControllerAdmissionError("host observation violates declared Ground successor relation")
        observed[binding.factor]=output
        receipts.append({
            "factor":binding.factor,
            "operator_id":binding.address.operator_id,
            "host_id":witness.host_id,
            "route_digest":witness.digest,
            "admission_receipt":result.admission_receipt,
            "hypervisor_fingerprint":result.execution.fingerprint,
            "status":result.status.value,
        })
    final=tuple(observed)
    if final not in action.allowed:
        raise CoupledControllerAdmissionError("combined observed transition violates coupled Ground")
    end_index=controller.states.index(final)
    if controller.ranks[end_index]>=action.rank:
        raise CoupledControllerAdmissionError("observed outcome did not decrease certified rank")
    report={
        "schema":"mailcpu.ncb003.qualified-step.v1",
        "selected_action_digest":action.digest,
        "packet_digest":controller.packet_digest,
        "observed":list(final),
        "native_receipts":receipts,
        "status":"verified_native_pure_step",
    }
    return QualifiedConstructedStep(action,final,tuple(receipts),
                                    "verified_native_pure_step",_hash(report))
