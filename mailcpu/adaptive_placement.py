"""SAB-004: compose qualified observer-host fragments into an admitted, recoverable path.

Qualifying a host is finite behavioral evidence, not a remote grant.  This
experiment uses SAB-001 to select a typed route across separately launched
SAB-003 workers, then explicitly executes trusted fixed-vocabulary operations.
The records are content-addressed and immutable; they do not claim hardware
isolation, cryptographic peer authentication, or exactly-once arbitrary effects.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any, Mapping

from .law_certifier import lcg_navigate
from .runtime_qualification import (
    QualificationEndpoint, QualificationPolicy, QualificationRefused, canonical,
    digest, affine_expected, verify_report, REQUEST_KIND, RESPONSE_KIND,
    _check_response,
)
from .substrate_bootstrap import (
    AdaptiveBootstrap, BootstrapPlan, BootstrapPolicy, BootstrapRefused,
    BootstrapTask, CarrierBinding, ChannelObservation, OperationOffer,
    RealizerBinding, ResourceObservation, SubstrateObservation,
)

SCHEMA = "mailcpu.sab004.adaptive-placement.v1"
CHECKPOINT = "mailcpu.sab004.checkpoint.v1"
INGRESS = "sab004.ingress"
_ROLE_TO_OPCODE = {"computational_fragment": "affine_mod", "framed_ipc": "transfer", "retained_state": "retain", "retained_readback": "retrieve"}
_STAGES = (("affine_mod", "request", "computed", "computational_fragment"),
           ("transfer", "computed", "relayed", "framed_ipc"),
           ("retain", "relayed", "committed", "retained_state"))


class PlacementRefused(BootstrapRefused):
    """Reject unauthorized, unqualified, stale, inconsistent or unreachable placement."""


def _integer(value: Any, label: str, minimum: int = 0, maximum: int = 10**18) -> int:
    """Check bounded integer coordinates and budgets without coercion or boolean aliases."""
    if type(value) is not int or not minimum <= value <= maximum:
        raise PlacementRefused(f"invalid {label}")
    return value


@dataclass(frozen=True)
class CompositeIntent:
    """Host-independent mathematical intention with a fixed effect-free law."""

    request_id: str
    a: int
    c: int
    modulus: int
    x0: int
    coordinate: int

    def __post_init__(self) -> None:
        """Validate the exact finite affine-modular domain."""
        if type(self.request_id) is not str or not self.request_id or len(self.request_id) > 100:
            raise PlacementRefused("invalid request identity")
        if any(not (ch.isascii() and (ch.isalnum() or ch in "._:-")) for ch in self.request_id):
            raise PlacementRefused("request identity contains unsupported characters")
        _integer(self.modulus, "modulus", 2, 2**31 - 1)
        for label in ("a", "c", "x0"):
            _integer(getattr(self, label), label, 0, self.modulus - 1)
        _integer(self.coordinate, "coordinate")

    def input(self) -> dict[str, int]:
        """Represent the admitted operation in the SAB-003 fixed request vocabulary."""
        return {"a": self.a, "c": self.c, "mod": self.modulus, "x0": self.x0,
                "coordinate": self.coordinate}

    @property
    def ground(self) -> str:
        """Identify the law without tying it to an execution host."""
        return digest({"family": "affine_mod", "a": self.a, "c": self.c,
                       "mod": self.modulus, "x0": self.x0})

    @property
    def fingerprint(self) -> str:
        """Bind one intention and its Ground independent of physical placement."""
        return digest({"schema": SCHEMA, "request_id": self.request_id,
                       "input": self.input(), "ground": self.ground})

    @property
    def storage_key(self) -> str:
        """Obtain one deterministic immutable replay key for a given intention."""
        return digest({"schema": CHECKPOINT, "intention": self.fingerprint})[:32]

    @property
    def decision_key(self) -> str:
        """Address a separate durable decision, after all required data copies exist."""
        return digest({"schema": CHECKPOINT + ".decision", "intention": self.fingerprint})[:32]


def expected_result(intent: CompositeIntent) -> dict[str, int]:
    """Independently check the resident worker result using native E-CPU navigation."""
    result = lcg_navigate(intent.a, intent.c, intent.modulus, intent.x0, intent.coordinate)
    if result != affine_expected(intent.a, intent.c, intent.modulus, intent.x0, intent.coordinate):
        raise PlacementRefused("two independent affine evaluators disagree")
    return {"coordinate": intent.coordinate, "value": result}


def checkpoint_record(intent: CompositeIntent, result: Mapping[str, Any]) -> dict[str, Any]:
    """Create host-independent, content-bound committed computation data."""
    if not isinstance(result, Mapping) or dict(result) != expected_result(intent):
        raise PlacementRefused("checkpoint differs from independently navigated Ground")
    body = {"kind": CHECKPOINT, "intention": intent.fingerprint,
            "ground": intent.ground, "result": dict(result)}
    body["digest"] = digest(body)
    return body


@dataclass(frozen=True)
class QualifiedHost:
    """One locally pinned endpoint and its separately auditable SAB-003 observation."""

    endpoint: QualificationEndpoint
    report: Mapping[str, Any]
    policy: QualificationPolicy

    def validate(self, *, coordinate: int) -> frozenset[str]:
        """Recheck exact host identity, lease, probe schedule, and empirical roles."""
        if self.endpoint.host_id != self.report.get("host"):
            raise PlacementRefused("host binding and qualification identity differ")
        try:
            verified_at = self.report.get("coordinate")
            verify_report(self.report, self.policy, coordinate=verified_at)
            if (type(coordinate) is not int or coordinate < verified_at or
                    coordinate > self.report["expires_at"]):
                raise PlacementRefused("qualification is outside its observed lease")
        except (QualificationRefused, KeyError, TypeError) as exc:
            raise PlacementRefused("qualification report is not current and valid") from exc
        return frozenset(self.report["verified_roles"])


@dataclass(frozen=True)
class PlacementAuthority:
    """Receiver-controlled exact host/operator grants and bounded placement budget."""

    granted: frozenset[tuple[str, str]]
    expires_at: int
    max_quanta: int = 100
    max_bytes: int = 8192
    max_steps: int = 8

    def __post_init__(self) -> None:
        """Refuse unrecognized operations, wildcard grants and unbounded requests."""
        _integer(self.expires_at, "authority expiry")
        _integer(self.max_quanta, "quanta bound", 1, 100000)
        _integer(self.max_bytes, "byte bound", 256, 8192)
        _integer(self.max_steps, "step bound", 6, 32)
        for host, op in self.granted:
            if (type(host) is not str or not host or len(host) > 128 or
                    type(op) is not str or op not in _ROLE_TO_OPCODE.values()):
                raise PlacementRefused("invalid exact host/operator permission")

    @property
    def fingerprint(self) -> str:
        """Bind exact local grants independently from host-supplied qualification."""
        return digest({"grants": [list(x) for x in sorted(self.granted)],
                       "expiry": self.expires_at, "max_quanta": self.max_quanta,
                       "max_bytes": self.max_bytes, "max_steps": self.max_steps})


@dataclass
class CompiledPlacement:
    """One SAB-001 path and its host-role bindings, pinned to a current inventory."""

    bootstrap: AdaptiveBootstrap
    task: BootstrapTask
    plan: BootstrapPlan
    assignment: tuple[str, str, str]
    active_hosts: tuple[str, ...]
    coordinate: int
    authority_digest: str

    @property
    def fingerprint(self) -> str:
        """Bind the route, active inventory, authority, and requested computation."""
        return digest({"schema": SCHEMA, "plan": self.plan.fingerprint,
                       "hosts": self.assignment, "active": self.active_hosts,
                       "coordinate": self.coordinate, "authority": self.authority_digest})


class AdaptivePlacement:
    """Assemble, execute and recover a multi-process host graph using exact local grants."""

    def __init__(self, hosts: Mapping[str, QualifiedHost], authority: PlacementAuthority,
                 *, quanta: Mapping[tuple[str, str], int] | None = None) -> None:
        """Bind explicit endpoints and local cost estimates, without fetching remote code."""
        if not hosts or any(key != host.endpoint.host_id for key, host in hosts.items()):
            raise PlacementRefused("host identifiers must match pinned endpoint identities")
        self.hosts = dict(hosts)
        self.authority = authority
        self.quanta = dict(quanta or {})
        for (host, op), cost in self.quanta.items():
            if host not in hosts or op not in _ROLE_TO_OPCODE.values():
                raise PlacementRefused("unknown host/operation cost")
            _integer(cost, "declared operation cost", 1, 100000)
        self._next_exchange = 0

    def _roles(self, active: tuple[str, ...], coordinate: int) -> dict[str, frozenset[str]]:
        """Intersect fresh empirical role evidence with active local host bindings."""
        _integer(coordinate, "execution coordinate")
        if coordinate > self.authority.expires_at:
            raise PlacementRefused("local execution grant expired")
        if len(active) != len(set(active)) or any(h not in self.hosts for h in active):
            raise PlacementRefused("active host inventory unknown or duplicated")
        return {host: self.hosts[host].validate(coordinate=coordinate) for host in active}

    def _call(self, host: str, op: str, payload: Mapping[str, Any]) -> Any:
        """Execute only locally granted fixed opcodes, verifying all framing and echoes."""
        if (host, op) not in self.authority.granted or host not in self.hosts:
            raise PlacementRefused("local operator permission missing")
        nonce = digest({"caller": "sab004", "host": host, "op": op,
                        "count": self._next_exchange, "value": dict(payload)})[:32]
        self._next_exchange += 1
        request = {"kind": REQUEST_KIND, "host": host, "nonce": nonce,
                   "operation": op, "payload": dict(payload)}
        try:
            response = self.hosts[host].endpoint.exchange(request, max_bytes=4096)
            _check_response(request, response)
        except (QualificationRefused, KeyError, TypeError) as exc:
            raise PlacementRefused("endpoint response rejected") from exc
        if not response["ok"]:
            raise PlacementRefused(f"qualified host refused admitted opcode {op}")
        return response["result"]

    def _store(self, host: str, intent: CompositeIntent, record: Mapping[str, Any]) -> None:
        """Require immutable acceptance followed by a separate fresh-process readback."""
        reply = self._call(host, "retain", {"key": intent.storage_key, "value": dict(record)})
        if reply != {"key": intent.storage_key, "receipt": digest(record)}:
            raise PlacementRefused("storage commit receipt contradicts requested bytes")
        recovered = self._call(host, "retrieve", {"key": intent.storage_key})
        if recovered != {"key": intent.storage_key, "value": dict(record)}:
            raise PlacementRefused("storage readback differs from acknowledged checkpoint")

    def _mark(self, host: str, intent: CompositeIntent, marker: Mapping[str, Any]) -> None:
        """Publish a host-independent commit decision after all data copies verify."""
        reply = self._call(host, "retain", {"key": intent.decision_key, "value": dict(marker)})
        if reply != {"key": intent.decision_key, "receipt": digest(marker)}:
            raise PlacementRefused("commit-decision acknowledgement differs from written bytes")
        readback = self._call(host, "retrieve", {"key": intent.decision_key})
        if readback != {"key": intent.decision_key, "value": dict(marker)}:
            raise PlacementRefused("commit-decision readback rejected")

    def _read_mark(self, host: str, intent: CompositeIntent, record: Mapping[str, Any]) -> dict[str, Any]:
        """Demand a durable decision binding all required previously prepared copies."""
        marker_reply = self._call(host, "retrieve", {"key": intent.decision_key})
        if (not isinstance(marker_reply, dict) or marker_reply.get("key") != intent.decision_key or
                not isinstance(marker_reply.get("value"), dict)):
            raise PlacementRefused("commit-decision record is missing or malformed")
        marker = marker_reply["value"]
        if set(marker) != {"kind", "intention", "checkpoint_digest", "replicas", "required", "digest"}:
            raise PlacementRefused("commit-decision schema mismatch")
        if (marker["kind"] != CHECKPOINT + ".decision" or marker["intention"] != intent.fingerprint or
                marker["checkpoint_digest"] != digest(record) or type(marker["required"]) is not int or
                not isinstance(marker["replicas"], list) or len(marker["replicas"]) != marker["required"] or
                not all(type(h) is str and h in self.hosts for h in marker["replicas"]) or
                not 1 <= marker["required"] <= 8 or marker["replicas"] != sorted(set(marker["replicas"])) or
                host not in marker["replicas"] or marker["digest"] != digest({k:v for k,v in marker.items() if k != "digest"})):
            raise PlacementRefused("commit decision contradicts checkpoint, replica membership or identity")
        return marker

    def _read(self, host: str, intent: CompositeIntent) -> dict[str, Any]:
        """Read durable state and recheck its entire mathematical meaning and identity."""
        recovered = self._call(host, "retrieve", {"key": intent.storage_key})
        if not isinstance(recovered, dict) or set(recovered) != {"key", "value"} or recovered["key"] != intent.storage_key:
            raise PlacementRefused("storage read result malformed")
        value = recovered["value"]
        if not isinstance(value, dict) or set(value) != {"kind", "intention", "ground", "result", "digest"}:
            raise PlacementRefused("checkpoint schema mismatch")
        canonical(value)
        if value != checkpoint_record(intent, value["result"]):
            raise PlacementRefused("checkpoint provenance or content inconsistent")
        return value

    def _compile_for_storage(self, intent: CompositeIntent, active: tuple[str, ...],
                             roles: Mapping[str, frozenset[str]], storage: str,
                             coordinate: int) -> CompiledPlacement:
        """Compile the SAB-001 typed graph for a fixed eligible durable destination."""
        resources = [ResourceObservation(INGRESS, "logical-input", coordinate,
                         self.authority.expires_at, "receiver", digest({"ingress": intent.fingerprint}))]
        offers: dict[str, list[OperationOffer]] = {host: [] for host in active}
        approved: set[tuple[str, str]] = set()
        realizers: list[RealizerBinding] = []
        for host in active:
            for opcode, accepts, produces, role in _STAGES:
                if role not in roles[host] or (host, opcode) not in self.authority.granted:
                    continue
                if opcode == "retain" and (host, "retrieve") not in self.authority.granted:
                    continue
                cost = self.quanta.get((host, opcode), 3)
                offers[host].append(OperationOffer(opcode, accepts, produces, cost))
                approved.add((host, opcode))
                if opcode == "affine_mod":
                    def compute(value: Any, *, host: str = host) -> dict[str, Any]:
                        """Ask a qualified independent host for one fixed mathematical transition."""
                        if value != intent.input():
                            raise PlacementRefused("compute input changed from admitted intention")
                        reply = self._call(host, "affine_mod", value)
                        if not isinstance(reply, dict) or set(reply) != {"value"}:
                            raise PlacementRefused("compute result outside fixed worker vocabulary")
                        return {"coordinate": intent.coordinate, "value": reply["value"]}
                    def check_compute(value: Any, output: Any) -> bool:
                        """Independently calculate requested observation with native navigation."""
                        return value == intent.input() and output == expected_result(intent)
                    handler, oracle = compute, check_compute
                elif opcode == "transfer":
                    def transfer(value: Any, *, host: str = host) -> Any:
                        """Require a real framed subprocess exchange without changing semantic bytes."""
                        data = canonical(value)
                        if len(data) > 1024:
                            raise PlacementRefused("relay input exceeds SAB-003 fixed port frame")
                        reply = self._call(host, "transfer", {"bytes_hex": data.hex()})
                        if not isinstance(reply, dict) or reply != {"bytes_hex": data.hex()}:
                            raise PlacementRefused("framed IPC changed the transferred bytes")
                        return json.loads(bytes.fromhex(reply["bytes_hex"]))
                    def check_transfer(value: Any, output: Any) -> bool:
                        """Ensure the relay has exactly the same canonical information."""
                        return output == value
                    handler, oracle = transfer, check_transfer
                else:
                    def retain(value: Any, *, host: str = host) -> dict[str, Any]:
                        """Durably store an exact, independently checked mathematical checkpoint."""
                        if value != expected_result(intent):
                            raise PlacementRefused("attempt to retain unverified observation")
                        record = checkpoint_record(intent, value)
                        self._store(host, intent, record)
                        return {"key": intent.storage_key, "record_digest": digest(record),
                                "result": value}
                    def check_retain(value: Any, output: Any) -> bool:
                        """Validate content-identity of the returned committed checkpoint."""
                        return (value == expected_result(intent) and output ==
                                {"key": intent.storage_key, "record_digest": digest(checkpoint_record(intent, value)),
                                 "result": value})
                    handler, oracle = retain, check_retain
                realizers.append(RealizerBinding(host, opcode, handler,
                                  digest({"sab004-opcode": opcode, "host": host,
                                          "profile": self.hosts[host].report["report_digest"]}), oracle))
        for host in active:
            r = self.hosts[host].report
            resources.append(ResourceObservation(host, "empirically-qualified", int(r["coordinate"]),
                             min(self.authority.expires_at, int(r["expires_at"])),
                             str(r["observer"]), str(r["report_digest"]), tuple(offers[host])))

        # Every cross-host transfer is logical orchestration between the caller's
        # fixed subprocess endpoints. The real framed IPC happens at 'transfer'.
        channels: list[ChannelObservation] = []
        carriers: list[CarrierBinding] = []
        compute_hosts = [h for h in active if (h, "affine_mod") in approved]
        relay_hosts = [h for h in active if (h, "transfer") in approved]
        storage_hosts = [h for h in active if (h, "retain") in approved]
        edges = ([(INGRESS, h, "request") for h in compute_hosts] +
                 [(a, b, "computed") for a in compute_hosts for b in relay_hosts if a != b] +
                 [(a, b, "relayed") for a in relay_hosts for b in storage_hosts if a != b])
        for source, target, kind in edges:
            id_ = f"sab004.{source}.{target}.{kind}"
            channels.append(ChannelObservation(id_, source, target, (kind,), 1,
                            coordinate, min(self.authority.expires_at,
                            *[int(self.hosts[h].report["expires_at"]) for h in (source, target) if h in self.hosts]),
                            digest({"edge": id_, "kind": kind}), 8192))
            def relay_wire(data: bytes, tick: int) -> bytes:
                """Preserve bytes at logical orchestration boundaries (not a physical link)."""
                return data
            carriers.append(CarrierBinding(id_, relay_wire,
                             digest({"logical-orchestration": id_, "kind": kind})))
        inventory = SubstrateObservation(tuple(resources), tuple(channels))
        policy = BootstrapPolicy(frozenset(approved), frozenset(x.channel_id for x in channels), "receiver")
        task = BootstrapTask("sab004-" + intent.request_id, intent.ground, INGRESS,
                    "request", storage, "committed", intent.input(),
                    max_quanta=self.authority.max_quanta, max_steps=self.authority.max_steps,
                    max_bytes=self.authority.max_bytes, require_oracle=True)
        boot = AdaptiveBootstrap(inventory, policy, realizers, carriers)
        plan = boot.plan(task, coordinate=coordinate)
        selected = {step.operation: step.locus for step in plan.steps if step.kind == "realize"}
        if set(selected) != {"affine_mod", "transfer", "retain"} or len(set(selected.values())) != 3:
            raise PlacementRefused("route must contain three distinct admitted role realizers")
        return CompiledPlacement(boot, task, plan,
                     (selected["affine_mod"], selected["transfer"], selected["retain"]),
                     active, coordinate, self.authority.fingerprint)

    def compile(self, intent: CompositeIntent, *, active_hosts: tuple[str, ...],
                coordinate: int) -> CompiledPlacement:
        """Choose the least declared-cost permitted three-host path using SAB-001."""
        if not isinstance(intent, CompositeIntent):
            raise PlacementRefused("placement requires typed mathematical intention")
        active = tuple(sorted(active_hosts))
        roles = self._roles(active, coordinate)
        available_storage = [host for host in active if (host, "retain") in self.authority.granted
                             and (host, "retrieve") in self.authority.granted
                             and "retained_state" in roles[host]]
        options: list[CompiledPlacement] = []
        for storage in available_storage:
            try:
                options.append(self._compile_for_storage(intent, active, roles, storage, coordinate))
            except BootstrapRefused:
                continue
        if not options:
            raise PlacementRefused("no admitted three-role path across distinct hosts")
        return min(options, key=lambda p: (p.plan.estimated_quanta, p.assignment, p.plan.fingerprint))

    def execute(self, intent: CompositeIntent, placement: CompiledPlacement, *,
                active_hosts: tuple[str, ...], coordinate: int,
                copies: int = 1) -> dict[str, Any]:
        """Execute a fresh plan, commit immutable storage, optionally replicate, then acknowledge."""
        _integer(copies, "required durable copies", 1, 8)
        fresh = self.compile(intent, active_hosts=active_hosts, coordinate=coordinate)
        if not isinstance(placement, CompiledPlacement) or placement.fingerprint != fresh.fingerprint:
            raise PlacementRefused("stale placement, changed observed resources or grant")
        start = time.perf_counter_ns()
        report = fresh.bootstrap.execute(fresh.task, fresh.plan, coordinate=coordinate)
        result = report["output"]
        if not isinstance(result, dict) or result != {"key": intent.storage_key,
                "record_digest": digest(checkpoint_record(intent, expected_result(intent))),
                "result": expected_result(intent)}:
            raise PlacementRefused("composite stage report differs from admitted result")
        record = self._read(fresh.assignment[2], intent)
        replicas = [fresh.assignment[2]]
        if copies > 1:
            roles = self._roles(fresh.active_hosts, coordinate)
            choices = [h for h in fresh.active_hosts if h not in replicas and
                       "retained_state" in roles[h] and (h, "retain") in self.authority.granted
                       and (h, "retrieve") in self.authority.granted]
            for host in choices[:copies - 1]:
                self._store(host, intent, record)
                replicas.append(host)
            if len(replicas) != copies:
                raise PlacementRefused("required durable replica count cannot be satisfied")
        marker = {"kind": CHECKPOINT + ".decision", "intention": intent.fingerprint,
                  "checkpoint_digest": digest(record), "replicas": sorted(replicas), "required": copies}
        marker["digest"] = digest(marker)
        for host in replicas:
            self._mark(host, intent, marker)
        output = {"kind": SCHEMA, "intention": intent.fingerprint, "ground": intent.ground,
                  "placement_digest": fresh.fingerprint, "plan_digest": fresh.plan.fingerprint,
                  "assignment": list(fresh.assignment), "replicas": sorted(replicas),
                  "checkpoint_digest": digest(record), "decision_digest": digest(marker),
                  "result": record["result"],
                  "bootstrap_report_digest": report["report_digest"],
                  "verified_operation_count": report["receiver_oracle_checked_steps"],
                  "measured_controller_ns": time.perf_counter_ns() - start,
                  "complete": True, "independent_physical_hosts_attested": False,
                  "remote_hypervisor_authority_granted": False}
        output["receipt_digest"] = digest(output)
        return output

    def resume(self, intent: CompositeIntent, *, active_hosts: tuple[str, ...],
               coordinate: int) -> dict[str, Any]:
        """Recover an already-committed result without re-running computation or relay."""
        roles = self._roles(tuple(sorted(active_hosts)), coordinate)
        candidates = [h for h in sorted(roles) if "retained_state" in roles[h]
                      and (h, "retain") in self.authority.granted
                      and (h, "retrieve") in self.authority.granted]
        if not candidates:
            raise PlacementRefused("no admitted retained-state host available for recovery")
        errors: list[str] = []
        for host in candidates:
            try:
                record = self._read(host, intent)
                marker = self._read_mark(host, intent, record)
            except (PlacementRefused, QualificationRefused, ValueError) as exc:
                errors.append(type(exc).__name__)
                continue
            output = {"kind": SCHEMA + ".resume", "intention": intent.fingerprint,
                      "ground": intent.ground, "storage_host": host,
                      "checkpoint_digest": digest(record), "decision_digest": digest(marker),
                      "replicas": marker["replicas"], "result": record["result"],
                      "reexecuted_computation": False,
                      "independent_physical_hosts_attested": False,
                      "remote_hypervisor_authority_granted": False}
            output["receipt_digest"] = digest(output)
            return output
        raise PlacementRefused("no stored checkpoint verified on available hosts: " + ",".join(errors))
