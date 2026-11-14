"""SHN-002: contend many virtual hosts on one interpreter and one/two port lanes.

This is a *logical* chip-model experiment, not a hardware implementation.
The optional active-port observer is a declared device capability; Python still
executes every simulated event. Its work is counted separately, not treated as
free silicon. Port lanes share their bandwidth among nested E-CPU hosts.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .owned_network import NetworkAddress, OwnedNetworkFabric
from .self_hosted_port_network import MAX_COORDINATE, MODULUS, SelfHostedPortNetwork

SCHEMA = "mailcpu.nested-port-fabric.v1"
WIRE = "mailcpu.nested-port-packet.v1"
MAX_PACKET = 2048
_JOB_ID = re.compile(r"[a-z][a-z0-9_-]{0,47}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")


class NestedPortError(ValueError):
    """Malformed state, unauthorized packet, or exhausted finite budget."""


def _require(condition: bool, message: str) -> None:
    """Refuse a malformed or over-budget operation before admitting a transition."""
    if not condition:
        raise NestedPortError(message)


def _canonical(value: Any) -> bytes:
    """Serialize one finite object canonically to bind operation identity."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _hash(value: Any) -> str:
    """Identify one canonical value using an unkeyed SHA-256 digest."""
    return hashlib.sha256(_canonical(value)).hexdigest()


def _packet(job: dict[str, Any], *, kind: str) -> dict[str, Any]:
    """Produce the exact allowed query or answer envelope for one virtual job."""
    return {
        "schema": WIRE, "kind": kind, "job_id": job["job_id"],
        "worker": job["worker"], "lane": job["lane"],
        "coordinate": job["coordinate"],
        "value": job["value"] if kind == "answer" else None,
        "receipt": job["receipt"] if kind == "answer" else None,
    }


def _decode(raw: bytes) -> dict[str, Any]:
    """Admit only canonical, bounded, role-consistent application packets."""
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_PACKET, "invalid frame length")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise NestedPortError("invalid JSON frame") from exc
    _require(type(doc) is dict and set(doc) == {
        "schema", "kind", "job_id", "worker", "lane", "coordinate", "value", "receipt"},
        "unexpected frame fields")
    _require(_canonical(doc) == raw, "noncanonical packet bytes")
    _require(doc["schema"] == WIRE and doc["kind"] in ("query", "answer"),
             "unknown packet contract")
    _require(type(doc["job_id"]) is str and _JOB_ID.fullmatch(doc["job_id"]) is not None,
             "invalid job ID")
    _require(type(doc["worker"]) is int and 0 <= doc["worker"] < 24 and
             type(doc["lane"]) is int and 0 <= doc["lane"] < 2,
             "invalid virtual host or port")
    _require(type(doc["coordinate"]) is int and 0 <= doc["coordinate"] <= MAX_COORDINATE,
             "invalid coordinate")
    if doc["kind"] == "query":
        _require(doc["value"] is None and doc["receipt"] is None,
                 "query cannot assert an answer")
    else:
        _require(type(doc["value"]) is int and 0 <= doc["value"] < MODULUS and
                 type(doc["receipt"]) is str and _HEX.fullmatch(doc["receipt"]) is not None,
                 "invalid answer or receipt")
    return doc


def _observed(job: dict[str, Any]) -> tuple[int, str]:
    """Evaluate the admitted LCG Ground and issue its unsigned result digest."""
    # Independent logical worker description: state orbit then projection.
    value = SelfHostedPortNetwork._projected(
        SelfHostedPortNetwork._navigated(job["coordinate"]))
    receipt = _hash({"job": job["job_id"], "worker": job["worker"],
                     "coordinate": job["coordinate"], "result": value,
                     "law": "lcg_navigate.v1", "projection": "affine_projection.v1"})
    return value, receipt


class NestedPortFabric:
    """A one-interpreter virtual network with shared bounded port lanes.

    Each physical lane is represented by an owned link core.txN <-> portN.in.
    Many virtual-host links attach behind the port namespace, so routed frames
    traverse physical lane and virtual fan-out. Per scheduler quantum: at most
    one interpreter host transition, and at most one port transfer per lane.

    In active_port_observer mode, completion comparison is a port-side observer
    step, charged separately. In conservative mode it consumes interpreter
    service. Neither mode demonstrates actual simultaneous execution in silicon.
    """

    def __init__(self, physical_ports: int, *, virtual_hosts: int = 8,
                 queue_limit: int = 2, active_port_observer: bool = True,
                 max_jobs: int = 64):
        """Create one chip-local network with finite interpreter and lane budgets."""
        _require(type(physical_ports) is int and physical_ports in (1, 2),
                 "physical port lanes must be one or two")
        _require(type(virtual_hosts) is int and 2 <= virtual_hosts <= 24,
                 "virtual host count outside 2..24")
        _require(type(queue_limit) is int and 1 <= queue_limit <= 16,
                 "queue limit outside 1..16")
        _require(type(max_jobs) is int and 1 <= max_jobs <= 64,
                 "job capacity outside 1..64")
        _require(type(active_port_observer) is bool,
                 "port observer mode must be boolean")
        self.physical_ports = physical_ports
        self.virtual_hosts = virtual_hosts
        self.queue_limit = queue_limit
        self.active_port_observer = active_port_observer
        self.max_jobs = max_jobs
        self.fabric = OwnedNetworkFabric(queue_limit=queue_limit)
        self.fabric.create_namespace("core")
        self.core: list[NetworkAddress] = []
        self.ports: list[NetworkAddress] = []
        self.workers: list[NetworkAddress] = []
        for lane in range(physical_ports):
            self.fabric.create_namespace(f"port{lane}")
            c = self.fabric.create_interface("core", f"tx{lane}", mtu=MAX_PACKET)
            p = self.fabric.create_interface(f"port{lane}", "in", mtu=MAX_PACKET)
            self.fabric.connect(f"physical{lane}", c, p)
            self.core.append(c)
            self.ports.append(p)
        for worker in range(virtual_hosts):
            lane = worker % physical_ports
            name = f"guest{worker}"
            self.fabric.create_namespace(name)
            virtual = self.fabric.create_interface(f"port{lane}", f"v{worker}", mtu=MAX_PACKET)
            guest = self.fabric.create_interface(name, "in", mtu=MAX_PACKET)
            self.fabric.connect(f"virtual{worker}", virtual, guest)
            self.workers.append(guest)
        self.jobs: list[dict[str, Any]] = []
        self.tick = 0
        self.interpreter_cursor = 0
        self.lane_cursors = [0] * physical_ports
        self.interpreter_steps = 0
        self.port_observer_steps = 0
        self.port_grants = [0] * physical_ports
        self.bytes_on_paths = 0
        self.backpressure_blocks = 0

    def submit(self, job_id: str, coordinate: int, *, worker: int) -> None:
        """Enqueue intent only; cannot transmit without a later port grant."""
        _require(type(job_id) is str and _JOB_ID.fullmatch(job_id) is not None and
                 all(j["job_id"] != job_id for j in self.jobs), "duplicate or invalid job")
        _require(type(coordinate) is int and 0 <= coordinate <= MAX_COORDINATE,
                 "coordinate outside supported Ground")
        _require(type(worker) is int and 0 <= worker < self.virtual_hosts,
                 "worker outside virtual-host Ground")
        _require(len(self.jobs) < self.max_jobs, "admitted job capacity exhausted")
        self.jobs.append({"job_id": job_id, "coordinate": coordinate,
                          "worker": worker, "lane": worker % self.physical_ports,
                          "phase": "queued", "value": None, "receipt": None,
                          "submitted_tick": self.tick, "completed_tick": None,
                          "request_frame": None, "response_frame": None})

    @property
    def complete(self) -> bool:
        """Report whether all admitted virtual-host jobs have concluded."""
        return bool(self.jobs) and all(job["phase"] == "done" for job in self.jobs)

    def _inspect(self, job: dict[str, Any], kind: str) -> None:
        """Check source, route, exact packet, and content before dequeue."""
        lane = job["lane"]
        source, destination = ((self.core[lane], self.workers[job["worker"]])
                               if kind == "query" else
                               (self.workers[job["worker"]], self.core[lane]))
        frame = self.fabric.peek(destination)
        _require(frame is not None, "expected frame unavailable")
        expected = _packet(job, kind=kind)
        _require(frame.source == source and frame.destination == destination and
                 frame.route == self.fabric.find_route(source, destination) and
                 _decode(frame.payload) == expected,
                 "port observer rejected mismatched packet or route")
        self.fabric.receive(destination)

    def _interpreter_step(self) -> bool:
        """One ordinary interpreter operation, even with many virtual hosts."""
        if not self.jobs:
            return False
        n = len(self.jobs)
        for offset in range(n):
            idx = (self.interpreter_cursor + offset) % n
            job = self.jobs[idx]
            if job["phase"] not in (("sent", "returned") if not self.active_port_observer
                                    else ("sent",)):
                continue
            if job["phase"] == "sent":
                # FIFO may be occupied by an earlier job addressed to this host.
                frame = self.fabric.peek(self.workers[job["worker"]])
                if frame is None or frame.frame_id != job["request_frame"]:
                    continue
                self._inspect(job, "query")
                job["value"], job["receipt"] = _observed(job)
                job["phase"] = "computed"
            else:
                frame = self.fabric.peek(self.core[job["lane"]])
                if frame is None or frame.frame_id != job["response_frame"]:
                    continue
                self._inspect(job, "answer")
                _require((job["value"], job["receipt"]) == _observed(job),
                         "receiver reference refused altered result")
                job["phase"] = "done"
                job["completed_tick"] = self.tick
            self.interpreter_steps += 1
            self.interpreter_cursor = (idx + 1) % n
            return True
        return False

    def _lane_step(self, lane: int) -> bool:
        """Spend at most one grant on this lane using bounded round-robin."""
        if not self.jobs:
            return False
        n = len(self.jobs)
        for offset in range(n):
            idx = (self.lane_cursors[lane] + offset) % n
            job = self.jobs[idx]
            if job["lane"] != lane or job["phase"] not in ("queued", "computed"):
                continue
            to_guest = job["phase"] == "queued"
            source = self.core[lane] if to_guest else self.workers[job["worker"]]
            dest = self.workers[job["worker"]] if to_guest else self.core[lane]
            if self.fabric.queue_available(dest) == 0:
                continue
            kind = "query" if to_guest else "answer"
            wire = _canonical(_packet(job, kind=kind))
            _require(len(wire) <= MAX_PACKET, "internal packet exceeds MTU")
            frame_id = self.fabric.send_routed(source, dest, wire, self.tick)
            self.port_grants[lane] += 1
            self.bytes_on_paths += len(wire)
            self.lane_cursors[lane] = (idx + 1) % n
            if to_guest:
                job["phase"] = "sent"
                job["request_frame"] = frame_id
            else:
                job["phase"] = "returned"
                job["response_frame"] = frame_id
                if self.active_port_observer:
                    # Conditional architecture hypothesis: the active port can
                    # recompute the algebraic result without interpreter dispatch.
                    # This requires nontrivial local port computation, not
                    # merely a passive data wire or free hash comparison.
                    self._inspect(job, "answer")
                    _require((job["value"], job["receipt"]) == _observed(job),
                             "active port refused altered result")
                    job["phase"] = "done"
                    job["completed_tick"] = self.tick
                    self.port_observer_steps += 1
            return True
        self.backpressure_blocks += int(any(job["lane"] == lane and
                                            job["phase"] in ("queued", "computed")
                                            for job in self.jobs))
        return False

    def step(self) -> dict[str, Any]:
        """Advance one logical quantum under separate interpretation and I/O budgets."""
        _require(not self.complete, "all jobs already complete")
        _require(self.tick < 100_000, "logical scheduler horizon exceeded")
        self.tick += 1
        interpreted = self._interpreter_step()
        port_ids: list[int] = []
        for lane in range(self.physical_ports):
            if self._lane_step(lane):
                port_ids.append(lane)
        return {"tick": self.tick, "interpreter_used": interpreted,
                "ports_used": port_ids,
                "outstanding": sum(job["phase"] != "done" for job in self.jobs)}

    def run(self, max_ticks: int = 512) -> dict[str, Any]:
        """Run up to a finite number of quanta, refusing an incomplete result."""
        _require(type(max_ticks) is int and 1 <= max_ticks <= 100_000,
                 "finite scheduler budget required")
        _require(bool(self.jobs), "no submitted work")
        for _ in range(max_ticks):
            if self.complete:
                return self.report()
            self.step()
        _require(self.complete, "budget exhausted with work still pending")
        return self.report()

    def report(self) -> dict[str, Any]:
        """Return only completed observations with separate physical budgets."""
        _require(self.complete, "cannot report unfinished network")
        return {"schema": SCHEMA, "physical_port_lanes": self.physical_ports,
                "virtual_hosts": self.virtual_hosts,
                "logical_observer_hosts": 1 + self.physical_ports + self.virtual_hosts,
                "active_port_observer": self.active_port_observer,
                "one_interpreter_operation_per_tick": True,
                "simulation_ticks": self.tick,
                "interpreter_steps": self.interpreter_steps,
                "port_observer_steps": self.port_observer_steps,
                "port_grants": list(self.port_grants),
                "internal_payload_bytes": self.bytes_on_paths,
                "external_payload_bytes": 0,
                "backpressure_blocks": self.backpressure_blocks,
                "outputs": {j["job_id"]: j["value"] for j in self.jobs},
                "completions": {j["job_id"]: j["completed_tick"] for j in self.jobs},
                "fabric_journal_verified": self.fabric.journal.verify(),
                "physical_hardware_measured": False,
                "parallel_cpu_execution_claimed": False,
                "port_side_completion_is_hardware_assumption": self.active_port_observer}

    def snapshot(self) -> dict[str, Any]:
        """Full continuable snapshot, with self-consistency rather than signatures."""
        data = {"schema": SCHEMA, "physical_ports": self.physical_ports,
                "virtual_hosts": self.virtual_hosts, "queue_limit": self.queue_limit,
                "active_port_observer": self.active_port_observer,
                "max_jobs": self.max_jobs, "jobs": json.loads(_canonical(self.jobs)),
                "tick": self.tick, "interpreter_cursor": self.interpreter_cursor,
                "lane_cursors": list(self.lane_cursors),
                "interpreter_steps": self.interpreter_steps,
                "port_observer_steps": self.port_observer_steps,
                "port_grants": list(self.port_grants),
                "bytes_on_paths": self.bytes_on_paths,
                "backpressure_blocks": self.backpressure_blocks,
                "fabric": self.fabric.snapshot()}
        return {**data, "snapshot_digest": _hash(data)}

    @classmethod
    def from_snapshot(cls, payload: dict[str, Any]) -> "NestedPortFabric":
        """Restore only a fully checked topology, queue, phase and cost vector."""
        _require(type(payload) is dict and set(payload) == {
            "schema", "physical_ports", "virtual_hosts", "queue_limit", "max_jobs",
            "active_port_observer", "jobs", "tick", "interpreter_cursor",
            "lane_cursors", "interpreter_steps", "port_observer_steps",
            "port_grants", "bytes_on_paths", "backpressure_blocks", "fabric",
            "snapshot_digest"}, "invalid snapshot fields")
        bare = {k: v for k, v in payload.items() if k != "snapshot_digest"}
        _require(payload["schema"] == SCHEMA and payload["snapshot_digest"] == _hash(bare),
                 "snapshot digest mismatch")
        node = cls(payload["physical_ports"], virtual_hosts=payload["virtual_hosts"],
                   queue_limit=payload["queue_limit"],
                   active_port_observer=payload["active_port_observer"],
                   max_jobs=payload["max_jobs"])
        _require(type(payload["jobs"]) is list and len(payload["jobs"]) <= node.max_jobs,
                 "invalid restored job set")
        node.jobs = json.loads(_canonical(payload["jobs"]))
        for k in ("tick", "interpreter_cursor", "interpreter_steps",
                  "port_observer_steps", "bytes_on_paths", "backpressure_blocks"):
            _require(type(payload[k]) is int and payload[k] >= 0, f"invalid {k}")
            setattr(node, k, payload[k])
        for k in ("lane_cursors", "port_grants"):
            _require(type(payload[k]) is list and len(payload[k]) == node.physical_ports and
                     all(type(v) is int and v >= 0 for v in payload[k]), f"invalid {k}")
            setattr(node, k, list(payload[k]))
        node.fabric = OwnedNetworkFabric.from_snapshot(payload["fabric"])
        node._verify_restored()
        return node

    def _verify_restored(self) -> None:
        """Recheck exact topology, queue frames, receipts, and costs on restore."""
        reference = NestedPortFabric(self.physical_ports, virtual_hosts=self.virtual_hosts,
                                     queue_limit=self.queue_limit,
                                     active_port_observer=self.active_port_observer,
                                     max_jobs=self.max_jobs)
        _require(self.fabric.namespaces() == reference.fabric.namespaces() and
                 self.fabric.links() == reference.fabric.links(), "restored topology differs")
        def config(items: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
            """Project immutable per-interface admission attributes."""
            return [{k: item[k] for k in ("namespace", "interface", "mtu",
                                         "queue_limit", "link_id", "up")} for item in items]
        _require(config(self.fabric.interfaces()) == config(reference.fabric.interfaces()),
                 "restored interface capabilities changed")
        _require(self.fabric.journal.verify(), "fabric journal failed integrity check")
        _require(self.tick <= 100_000 and self.interpreter_steps <= self.tick and
                 self.backpressure_blocks <= self.tick * self.physical_ports and
                 self.port_observer_steps <= self.tick * self.physical_ports and
                 all(v <= self.tick for v in self.port_grants), "resource counters inconsistent")
        _require(not self.jobs or (0 <= self.interpreter_cursor < len(self.jobs)),
                 "interpreter cursor outside job set")
        _require(all(v < max(1, len(self.jobs)) for v in self.lane_cursors),
                 "lane cursor outside job set")
        phase_weights = {"queued": 0, "sent": 1, "computed": 1,
                         "returned": 2, "done": 2}
        _require(all(type(j) is dict and set(j) == {
            "job_id", "coordinate", "worker", "lane", "phase", "value", "receipt",
            "submitted_tick", "completed_tick", "request_frame", "response_frame"}
                 for j in self.jobs), "restored job fields invalid")
        _require(len({j["job_id"] for j in self.jobs}) == len(self.jobs),
                 "restored duplicate job IDs")
        expected_grants = [0] * self.physical_ports
        expected_interpreter = 0
        expected_port_observers = 0
        expected_queued: dict[int, tuple[dict[str, Any], NetworkAddress, NetworkAddress]] = {}
        for j in self.jobs:
            _require(type(j["job_id"]) is str and _JOB_ID.fullmatch(j["job_id"]) is not None and
                     type(j["coordinate"]) is int and 0 <= j["coordinate"] <= MAX_COORDINATE and
                     type(j["worker"]) is int and 0 <= j["worker"] < self.virtual_hosts and
                     type(j["lane"]) is int and j["lane"] == j["worker"] % self.physical_ports and
                     j["phase"] in phase_weights, "invalid restored job identity/phase")
            _require(type(j["submitted_tick"]) is int and 0 <= j["submitted_tick"] <= self.tick,
                     "job submission outside scheduler time")
            expected_grants[j["lane"]] += phase_weights[j["phase"]]
            if j["phase"] in ("computed", "returned", "done"):
                expected_interpreter += 1
                value, receipt = _observed(j)
                _require(j["value"] == value and j["receipt"] == receipt,
                         "restored answer or receipt changed")
            else:
                _require(j["value"] is None and j["receipt"] is None,
                         "uncomputed job carries a result")
            if j["phase"] == "done":
                _require(type(j["completed_tick"]) is int and
                         j["submitted_tick"] < j["completed_tick"] <= self.tick,
                         "invalid completion time")
                if self.active_port_observer:
                    expected_port_observers += 1
                else:
                    expected_interpreter += 1
            else:
                _require(j["completed_tick"] is None, "unfinished job has completion time")
            if j["phase"] in ("queued",):
                _require(j["request_frame"] is None and j["response_frame"] is None,
                         "unsent job owns a frame")
            elif j["phase"] in ("sent", "computed"):
                _require(type(j["request_frame"]) is int and j["request_frame"] > 0 and
                         j["response_frame"] is None, "request frame identity changed")
            else:
                _require(type(j["request_frame"]) is int and j["request_frame"] > 0 and
                         type(j["response_frame"]) is int and j["response_frame"] > 0,
                         "completed job frame identity changed")
            if j["phase"] == "sent":
                expected_queued[j["request_frame"]] = (
                    _packet(j, kind="query"), self.core[j["lane"]],
                    self.workers[j["worker"]])
            elif j["phase"] == "returned":
                _require(not self.active_port_observer, "active port has unconsumed return")
                expected_queued[j["response_frame"]] = (
                    _packet(j, kind="answer"), self.workers[j["worker"]],
                    self.core[j["lane"]])
        _require(self.port_grants == expected_grants and
                 self.port_observer_steps == expected_port_observers and
                 self.interpreter_steps == expected_interpreter,
                 "restored resource counts differ from admitted jobs")
        actual_queued: dict[int, tuple[dict[str, Any], NetworkAddress, NetworkAddress]] = {}
        for item in self.fabric.snapshot()["queues"]:
            for frame in item["frames"]:
                raw = bytes.fromhex(frame["payload_hex"])
                parsed = _decode(raw)
                src = NetworkAddress.from_dict(frame["source"])
                dst = NetworkAddress.from_dict(frame["destination"])
                _require(tuple(NetworkAddress.from_dict(a) for a in frame["route"]) ==
                         self.fabric.find_route(src, dst), "restored virtual packet route changed")
                fid = frame["frame_id"]
                _require(fid not in actual_queued, "duplicate frame identity")
                actual_queued[fid] = (parsed, src, dst)
        _require(actual_queued == expected_queued, "restored queues differ from job state")
        _require(self.bytes_on_paths == sum(len(_canonical(_packet(j, kind="query")))
                                                 if j["phase"] != "queued" else 0
                                                 for j in self.jobs) +
                 sum(len(_canonical(_packet(j, kind="answer")))
                     if j["phase"] in ("returned", "done") else 0
                     for j in self.jobs), "payload accounting differs")
