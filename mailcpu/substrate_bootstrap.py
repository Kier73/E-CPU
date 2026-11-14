"""Substrate-adaptive, resource-agnostic observer-host bootstrap (SAB-001).

Resource observations describe possible contracts but never grant execution.
The bootstrap selects only receiver-local, authorized implementations and
channels; route plans are non-authoritative. No passive medium computes merely
because it appears in the graph.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import heapq
import json
import re
from typing import Any, Callable, Mapping, Sequence


SCHEMA = "mailcpu.observer-substrate-bootstrap.v1"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")


class BootstrapRefused(ValueError):
    """The observed substrate cannot realize the task under local authority."""


def canonical(value: Any) -> bytes:
    """Encode detached finite JSON with one stable content identity."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BootstrapRefused("value is not finite JSON") from exc


def digest(value: Any) -> str:
    """Hash canonical content; a digest is NOT authentication or authority."""
    return hashlib.sha256(canonical(value)).hexdigest()


def name(value: Any, what: str) -> str:
    """Validate one closed, bounded host/operation/representation identifier."""
    if type(value) is not str or _NAME.fullmatch(value) is None:
        raise BootstrapRefused(f"invalid {what}")
    return value


def natural(value: Any, what: str, minimum: int = 0) -> int:
    """Accept an integer, excluding bool, with a declared lower bound."""
    if type(value) is not int or value < minimum:
        raise BootstrapRefused(f"invalid {what}")
    return value


def sha(value: Any, what: str) -> str:
    """Validate a lowercase SHA-256 hexadecimal content reference."""
    if type(value) is not str or _HEX.fullmatch(value) is None:
        raise BootstrapRefused(f"invalid {what} digest")
    return value


@dataclass(frozen=True)
class OperationOffer:
    """Untrusted observation of one named input/output transition."""

    operation: str
    accepts: str
    produces: str
    estimated_quanta: int

    def __post_init__(self) -> None:
        for key in ("operation", "accepts", "produces"):
            name(getattr(self, key), key)
        natural(self.estimated_quanta, "operation cost", 1)

    def to_dict(self) -> dict[str, Any]:
        """Project the non-executable offered contract to canonical JSON."""
        return {"operation": self.operation, "accepts": self.accepts,
                "produces": self.produces, "estimated_quanta": self.estimated_quanta}


@dataclass(frozen=True)
class ResourceObservation:
    """One sensed resource; its substrate hint never determines its authority."""

    resource_id: str
    substrate_hint: str
    observed_at: int
    expires_at: int
    observer_id: str
    evidence_digest: str
    offers: tuple[OperationOffer, ...] = ()

    def __post_init__(self) -> None:
        for key in ("resource_id", "substrate_hint", "observer_id"):
            name(getattr(self, key), key)
        natural(self.observed_at, "observation coordinate")
        natural(self.expires_at, "observation expiry")
        if self.expires_at < self.observed_at:
            raise BootstrapRefused("observation expires before it is made")
        sha(self.evidence_digest, "observation evidence")
        if any(not isinstance(x, OperationOffer) for x in self.offers):
            raise BootstrapRefused("offers must be typed contracts")
        if len({x.operation for x in self.offers}) != len(self.offers):
            raise BootstrapRefused("resource repeats an operation offer")
        if len(self.offers) > 32:
            raise BootstrapRefused("too many offered operations")

    def to_dict(self) -> dict[str, Any]:
        """Preserve source evidence, lease and contracts without embedding code."""
        return {"resource_id": self.resource_id, "substrate_hint": self.substrate_hint,
                "observed_at": self.observed_at, "expires_at": self.expires_at,
                "observer_id": self.observer_id, "evidence_digest": self.evidence_digest,
                "offers": [x.to_dict() for x in self.offers]}


@dataclass(frozen=True)
class ChannelObservation:
    """Observed directed information path, not an automatic execution host."""

    channel_id: str
    source: str
    target: str
    carries: tuple[str, ...]
    estimated_quanta: int
    observed_at: int
    expires_at: int
    evidence_digest: str
    max_payload_bytes: int = 8192

    def __post_init__(self) -> None:
        for key in ("channel_id", "source", "target"):
            name(getattr(self, key), key)
        if self.source == self.target:
            raise BootstrapRefused("a channel must join different loci")
        if not self.carries or len(set(self.carries)) != len(self.carries):
            raise BootstrapRefused("channel must carry distinct typed representations")
        for tag in self.carries:
            name(tag, "representation")
        natural(self.estimated_quanta, "channel cost", 1)
        natural(self.max_payload_bytes, "channel payload bound", 1)
        natural(self.observed_at, "channel observation coordinate")
        natural(self.expires_at, "channel expiry")
        if self.expires_at < self.observed_at:
            raise BootstrapRefused("channel expires before observation")
        sha(self.evidence_digest, "channel observation")

    def to_dict(self) -> dict[str, Any]:
        """Serialize an observed path with a finite payload ceiling."""
        return {"channel_id": self.channel_id, "source": self.source,
                "target": self.target, "carries": list(self.carries),
                "estimated_quanta": self.estimated_quanta,
                "observed_at": self.observed_at, "expires_at": self.expires_at,
                "evidence_digest": self.evidence_digest,
                "max_payload_bytes": self.max_payload_bytes}


@dataclass(frozen=True)
class SubstrateObservation:
    """Immutable, bounded description of a sensed candidate information space."""

    resources: tuple[ResourceObservation, ...]
    channels: tuple[ChannelObservation, ...]

    def __post_init__(self) -> None:
        if not self.resources or len(self.resources) > 128 or len(self.channels) > 512:
            raise BootstrapRefused("resource/channel inventory outside bounds")
        ids = [x.resource_id for x in self.resources]
        if len(set(ids)) != len(ids):
            raise BootstrapRefused("duplicate observed resource")
        if len({x.channel_id for x in self.channels}) != len(self.channels):
            raise BootstrapRefused("duplicate channel identity")
        for edge in self.channels:
            if edge.source not in ids or edge.target not in ids:
                raise BootstrapRefused("channel references unobserved resource")

    @property
    def fingerprint(self) -> str:
        """Identify the complete inventory without claiming the sensors are trustworthy."""
        return digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Serialize observations sorted by stable logical identity."""
        return {"schema": SCHEMA, "resources": [x.to_dict() for x in sorted(self.resources, key=lambda x:x.resource_id)],
                "channels": [x.to_dict() for x in sorted(self.channels, key=lambda x:x.channel_id)]}


@dataclass(frozen=True)
class BootstrapTask:
    """A substrate-independent intention over typed input and output descriptions."""

    intention_id: str
    ground_digest: str
    source: str
    input_kind: str
    target: str
    output_kind: str
    value: Any
    max_quanta: int = 1000
    max_steps: int = 16
    max_bytes: int = 8192
    require_oracle: bool = False

    def __post_init__(self) -> None:
        for key in ("intention_id", "source", "input_kind", "target", "output_kind"):
            name(getattr(self, key), key)
        sha(self.ground_digest, "Ground")
        natural(self.max_quanta, "task quanta", 1)
        natural(self.max_steps, "task step bound", 1)
        natural(self.max_bytes, "task bytes bound", 1)
        if self.max_steps > 128 or self.max_bytes > 1_048_576:
            raise BootstrapRefused("task budget outside fixed bootstrap envelope")
        if type(self.require_oracle) is not bool:
            raise BootstrapRefused("require_oracle must be boolean")
        if len(canonical(self.value)) > self.max_bytes:
            raise BootstrapRefused("input exceeds task byte budget")

    @property
    def fingerprint(self) -> str:
        """Bind task identity to Ground, desired observation and input."""
        return digest({"id": self.intention_id, "ground": self.ground_digest,
                       "from": [self.source, self.input_kind], "to": [self.target, self.output_kind],
                       "value": self.value, "quanta": self.max_quanta, "steps": self.max_steps,
                       "bytes": self.max_bytes, "require_oracle": self.require_oracle})


@dataclass(frozen=True)
class RealizerBinding:
    """Receiver-local trusted implementation; untrusted inventories contain no callable."""

    resource_id: str
    operation: str
    handler: Callable[[Any], Any]
    implementation_digest: str
    oracle: Callable[[Any, Any], bool] | None = None

    def __post_init__(self) -> None:
        name(self.resource_id, "realizer resource")
        name(self.operation, "realizer operation")
        sha(self.implementation_digest, "realizer implementation")
        if not callable(self.handler):
            raise BootstrapRefused("realizer handler must be locally callable")
        if self.oracle is not None and not callable(self.oracle):
            raise BootstrapRefused("independent checking oracle must be callable")


@dataclass(frozen=True)
class CarrierBinding:
    """Locally admitted byte-moving mechanism for one observed path."""

    channel_id: str
    deliver: Callable[[bytes, int], bytes]
    implementation_digest: str

    def __post_init__(self) -> None:
        name(self.channel_id, "carrier channel")
        sha(self.implementation_digest, "carrier implementation")
        if not callable(self.deliver):
            raise BootstrapRefused("carrier must have local byte-moving mechanism")


@dataclass(frozen=True)
class BootstrapPolicy:
    """Explicit receiver-owned allowlist; sensed capability is never permission."""

    allowed_operations: frozenset[tuple[str, str]]
    allowed_channels: frozenset[str]
    authority_id: str

    def __post_init__(self) -> None:
        name(self.authority_id, "local admission authority")
        for resource, operation in self.allowed_operations:
            name(resource, "policy resource")
            name(operation, "policy operation")
        for channel in self.allowed_channels:
            name(channel, "policy channel")

    @property
    def fingerprint(self) -> str:
        """Bind planning to local explicit admission, not remote advertisements."""
        return digest({"authority": self.authority_id,
                       "operations": [list(x) for x in sorted(self.allowed_operations)],
                       "channels": sorted(self.allowed_channels)})


@dataclass(frozen=True)
class BootstrapStep:
    """One scheduled local transform or explicitly bound information transit."""

    kind: str
    locus: str
    destination: str
    operation: str
    accepts: str
    produces: str
    quanta: int
    implementation_digest: str

    def to_dict(self) -> dict[str, Any]:
        """Expose a portable non-authoritative plan transition."""
        return {"kind": self.kind, "locus": self.locus, "destination": self.destination,
                "operation": self.operation, "accepts": self.accepts,
                "produces": self.produces, "quanta": self.quanta,
                "implementation_digest": self.implementation_digest}


@dataclass(frozen=True)
class BootstrapPlan:
    """Content-bound route over admitted, locally implementable observer-hosts."""

    inventory_digest: str
    policy_digest: str
    task_digest: str
    steps: tuple[BootstrapStep, ...]
    estimated_quanta: int

    @property
    def fingerprint(self) -> str:
        """Identify the complete plan, including current observation and policy revisions."""
        return digest({"schema": SCHEMA, "inventory": self.inventory_digest,
                       "policy": self.policy_digest, "task": self.task_digest,
                       "steps": [s.to_dict() for s in self.steps], "quanta": self.estimated_quanta})


class AdaptiveBootstrap:
    """Compile an unfamiliar sensed fabric into a bounded, executable observer graph."""

    def __init__(self, inventory: SubstrateObservation, policy: BootstrapPolicy,
                 realizers: Sequence[RealizerBinding], carriers: Sequence[CarrierBinding]) -> None:
        """Bind locally controlled implementations without delegating authority to probes."""
        if not isinstance(inventory, SubstrateObservation) or not isinstance(policy, BootstrapPolicy):
            raise BootstrapRefused("bootstrap requires inventory and local policy")
        self.inventory = inventory
        self.policy = policy
        self.realizers = {(x.resource_id, x.operation): x for x in realizers}
        self.carriers = {x.channel_id: x for x in carriers}
        if len(self.realizers) != len(realizers) or len(self.carriers) != len(carriers):
            raise BootstrapRefused("duplicated realizer or carrier binding")

    def _graph(self, coordinate: int) -> dict[tuple[str, str], list[tuple[tuple[str, str], BootstrapStep]]]:
        """Intersect observed offers, leases and local permissions to construct executable edges."""
        graph: dict[tuple[str, str], list[tuple[tuple[str, str], BootstrapStep]]] = {}
        for resource in self.inventory.resources:
            if not resource.observed_at <= coordinate <= resource.expires_at:
                continue
            for offer in resource.offers:
                key = (resource.resource_id, offer.operation)
                binding = self.realizers.get(key)
                if binding is None or key not in self.policy.allowed_operations:
                    continue
                origin = (resource.resource_id, offer.accepts)
                destination = (resource.resource_id, offer.produces)
                step = BootstrapStep("realize", resource.resource_id, resource.resource_id,
                                     offer.operation, offer.accepts, offer.produces,
                                     offer.estimated_quanta, binding.implementation_digest)
                graph.setdefault(origin, []).append((destination, step))
        for channel in self.inventory.channels:
            if not channel.observed_at <= coordinate <= channel.expires_at:
                continue
            binding = self.carriers.get(channel.channel_id)
            if binding is None or channel.channel_id not in self.policy.allowed_channels:
                continue
            for tag in channel.carries:
                start = (channel.source, tag)
                end = (channel.target, tag)
                step = BootstrapStep("carry", channel.source, channel.target,
                                     channel.channel_id, tag, tag,
                                     channel.estimated_quanta, binding.implementation_digest)
                graph.setdefault(start, []).append((end, step))
        return graph

    def plan(self, task: BootstrapTask, *, coordinate: int) -> BootstrapPlan:
        """Find the least declared-cost typed realization, deterministically and within budget."""
        natural(coordinate, "bootstrap coordinate")
        ids = {x.resource_id for x in self.inventory.resources}
        if task.source not in ids or task.target not in ids:
            raise BootstrapRefused("task refers to unobserved resource")
        graph = self._graph(coordinate)
        start = (task.source, task.input_kind)
        goal = (task.target, task.output_kind)
        frontier: list[tuple[int, int, tuple[str, ...], tuple[str, str], tuple[BootstrapStep, ...]]] = [(0, 0, (), start, ())]
        seen: dict[tuple[tuple[str, str], int], tuple[int, tuple[str, ...]]] = {}
        while frontier:
            cost, depth, route_key, state, steps = heapq.heappop(frontier)
            if cost > task.max_quanta or depth > task.max_steps:
                continue
            prior = seen.get((state, depth))
            if prior is not None and prior <= (cost, route_key):
                continue
            seen[(state, depth)] = (cost, route_key)
            if state == goal and (not task.require_oracle or any(
                s.kind == "realize" and self.realizers[(s.locus, s.operation)].oracle is not None
                for s in steps
            )):
                return BootstrapPlan(self.inventory.fingerprint, self.policy.fingerprint,
                                     task.fingerprint, steps, cost)
            if depth == task.max_steps:
                continue
            for next_state, step in sorted(graph.get(state, ()), key=lambda x: (x[1].quanta, x[1].kind, x[1].operation, x[0])):
                next_cost = cost + step.quanta
                if next_cost <= task.max_quanta:
                    new_key = route_key + (f"{step.kind}:{step.locus}:{step.operation}:{step.destination}",)
                    heapq.heappush(frontier, (next_cost, depth + 1, new_key,
                                              next_state, steps + (step,)))
        raise BootstrapRefused("no admitted navigable realization within budget")

    def execute(self, task: BootstrapTask, plan: BootstrapPlan, *, coordinate: int) -> dict[str, Any]:
        """Replan/revalidate before execution; bind each observed transition to a local realization."""
        expected = self.plan(task, coordinate=coordinate)
        if not isinstance(plan, BootstrapPlan) or plan.fingerprint != expected.fingerprint:
            raise BootstrapRefused("plan is stale or not admitted by current observer state")
        resource = task.source
        representation = task.input_kind
        value: Any = json.loads(canonical(task.value))
        receipts: list[dict[str, Any]] = []
        checked_steps = 0
        for i, step in enumerate(plan.steps):
            if step.locus != resource or step.accepts != representation:
                raise BootstrapRefused("planned transition has broken input continuity")
            before = digest(value)
            independent_check = False
            if step.kind == "realize":
                binding = self.realizers.get((resource, step.operation))
                if binding is None or binding.implementation_digest != step.implementation_digest:
                    raise BootstrapRefused("trusted handler changed after planning")
                result = binding.handler(json.loads(canonical(value)))
                if binding.oracle is not None:
                    if binding.oracle(json.loads(canonical(value)), json.loads(canonical(result))) is not True:
                        raise BootstrapRefused("receiver-owned independent check rejected transition")
                    checked_steps += 1
                    independent_check = True
            elif step.kind == "carry":
                channel = next((x for x in self.inventory.channels if x.channel_id == step.operation), None)
                binding = self.carriers.get(step.operation)
                if channel is None or binding is None or binding.implementation_digest != step.implementation_digest:
                    raise BootstrapRefused("channel driver changed after planning")
                encoded = canonical(value)
                if len(encoded) > min(task.max_bytes, channel.max_payload_bytes):
                    raise BootstrapRefused("payload exceeds observed channel budget")
                delivered = binding.deliver(encoded, coordinate + i)
                if type(delivered) is not bytes or delivered != encoded:
                    raise BootstrapRefused("carrier altered, lost or substituted information")
                result = json.loads(delivered)
            else:
                raise BootstrapRefused("unsupported transition kind")
            if len(canonical(result)) > task.max_bytes:
                raise BootstrapRefused("result exceeds task byte budget")
            value = json.loads(canonical(result))
            receipts.append({"step": i, "kind": step.kind, "locus": step.locus,
                             "operation": step.operation, "implementation_digest": step.implementation_digest,
                             "input_digest": before, "output_digest": digest(value),
                             "declared_quanta": step.quanta,
                             "receiver_oracle_checked": independent_check})
            resource = step.destination
            representation = step.produces
        if (resource, representation) != (task.target, task.output_kind):
            raise BootstrapRefused("execution did not reach the intended observation")
        if task.require_oracle and checked_steps == 0:
            raise BootstrapRefused("requested independent check was not performed")
        report = {"schema": SCHEMA, "task_digest": task.fingerprint,
                  "inventory_digest": self.inventory.fingerprint,
                  "policy_digest": self.policy.fingerprint,
                  "plan_digest": plan.fingerprint, "ground_digest": task.ground_digest,
                  "output": value, "output_digest": digest(value),
                  "estimated_quanta": plan.estimated_quanta,
                  "receipts": receipts, "receiver_oracle_checked_steps": checked_steps,
                  "physical_independence_attested": False,
                  "execution_authority": "receiver-local-allowlist-and-handler-binding"}
        report["report_digest"] = digest(report)
        return report


def owned_network_probe(fabric: Any, *, coordinate: int,
                        offers: Mapping[str, tuple[OperationOffer, ...]] | None = None,
                        lease_quanta: int = 16,
                        carries: Sequence[str] = ("request", "state", "verified"),
                        max_endpoints: int = 32) -> SubstrateObservation:
    """Observe genuine E-CPU OwnedNetworkFabric routes without inventing compute capabilities.

    The caller must explicitly supply *offered* operations. Even those offers
    remain non-executable until separately allowed and bound on the receiver.
    """
    natural(coordinate, "probe coordinate")
    natural(lease_quanta, "probe lease", 1)
    entries = fabric.interfaces()
    if len(entries) > max_endpoints:
        raise BootstrapRefused("owned fabric probe exceeds finite endpoint bound")
    from .owned_network import NetworkAddress, OwnedNetworkError
    offerings = offers or {}
    endpoints: dict[str, Any] = {}
    resources: list[ResourceObservation] = []
    for entry in entries:
        if not entry["up"]:
            continue
        host = f"{entry['namespace']}/{entry['interface']}"
        address = NetworkAddress(entry["namespace"], entry["interface"])
        endpoints[host] = address
        resources.append(ResourceObservation(
            host, "owned-network-port", coordinate, coordinate + lease_quanta,
            "local-owned-network-probe", digest(entry), tuple(offerings.get(host, ())),
        ))
    channels: list[ChannelObservation] = []
    for left in sorted(endpoints):
        for right in sorted(endpoints):
            if left == right:
                continue
            try:
                route = fabric.find_route(endpoints[left], endpoints[right])
                mtu = fabric.route_mtu(endpoints[left], endpoints[right])
            except OwnedNetworkError:
                continue
            route_id = f"owned-{left.replace('/', '-')}-to-{right.replace('/', '-')}"
            channels.append(ChannelObservation(
                route_id, left, right, tuple(carries), max(1, len(route) - 1),
                coordinate, coordinate + lease_quanta,
                digest({"route": [x.to_dict() for x in route], "mtu": mtu}), mtu,
            ))
    return SubstrateObservation(tuple(resources), tuple(channels))


def owned_network_carriers(fabric: Any, inventory: SubstrateObservation) -> tuple[CarrierBinding, ...]:
    """Bind observed channels to real owned-network send/receive operations.

    This is local physical *simulation* inside E-CPU, not a claim that real
    cables or ports were discovered by the experiment.
    """
    from .owned_network import NetworkAddress
    bindings: list[CarrierBinding] = []
    for channel in inventory.channels:
        source, target = channel.source.split("/"), channel.target.split("/")
        addr_source, addr_target = NetworkAddress(*source), NetworkAddress(*target)
        def deliver(payload: bytes, coordinate: int, *, start=addr_source, end=addr_target) -> bytes:
            """Transmit one exact canonical message over a locally owned fabric path."""
            fabric.send_routed(start, end, payload, coordinate)
            frame = fabric.receive(end)
            if frame is None or frame.source != start or frame.destination != end:
                raise BootstrapRefused("fabric delivery identity mismatch")
            return frame.payload
        bindings.append(CarrierBinding(channel.channel_id, deliver,
                                       digest({"driver": "E-CPU OwnedNetworkFabric", "channel": channel.to_dict()})))
    return tuple(bindings)


def verify_bootstrap_report(report: Mapping[str, Any], task: BootstrapTask,
                            plan: BootstrapPlan) -> bool:
    """Independently recheck report identity and step-digest chain, not handler mathematics.

    The report's SHA-256 is unkeyed and therefore cannot attest the reporter.
    A successful check establishes local record consistency, not physical trust.
    """
    if not isinstance(report, Mapping):
        raise BootstrapRefused("invalid execution report")
    detached = json.loads(canonical(dict(report)))
    given = detached.pop("report_digest", None)
    if given != digest(detached):
        raise BootstrapRefused("execution report content identity mismatch")
    if detached.get("schema") != SCHEMA or detached.get("task_digest") != task.fingerprint or \
       detached.get("plan_digest") != plan.fingerprint or \
       detached.get("inventory_digest") != plan.inventory_digest or \
       detached.get("policy_digest") != plan.policy_digest or \
       detached.get("ground_digest") != task.ground_digest:
        raise BootstrapRefused("report contradicts the admitted task or plan")
    records = detached.get("receipts")
    if not isinstance(records, list) or len(records) != len(plan.steps):
        raise BootstrapRefused("missing operation receipt")
    previous = digest(task.value)
    checked = 0
    for index, (record, step) in enumerate(zip(records, plan.steps)):
        if not isinstance(record, dict) or record.get("step") != index or \
           record.get("kind") != step.kind or record.get("locus") != step.locus or \
           record.get("operation") != step.operation or \
           record.get("implementation_digest") != step.implementation_digest or \
           record.get("declared_quanta") != step.quanta or \
           record.get("input_digest") != previous:
            raise BootstrapRefused("execution receipt continuity mismatch")
        previous = sha(record.get("output_digest"), "receipt output")
        if type(record.get("receiver_oracle_checked")) is not bool:
            raise BootstrapRefused("invalid check evidence field")
        checked += int(record["receiver_oracle_checked"])
    if detached.get("receiver_oracle_checked_steps") != checked or \
       (task.require_oracle and not checked):
        raise BootstrapRefused("missing requested receiver-owned check evidence")
    if previous != digest(detached.get("output")) or \
       detached.get("output_digest") != previous or \
       detached.get("estimated_quanta") != plan.estimated_quanta:
        raise BootstrapRefused("final output or cost differs from recorded path")
    return True