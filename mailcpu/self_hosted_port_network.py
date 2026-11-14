"""A one-interpreter, one/two-boundary-port, internally networked E-CPU experiment.

Composes the existing OwnedNetworkFabric and algebraic law navigator. The three
logical observer-hosts (dispatcher, state navigator, projector) execute on ONE
interpreter, not on independent physical execution units. Physical 'port count'
is a declared external I/O constraint; no external I/O occurs in this model.

This deliberately distinguishes virtual-host count from silicon resources.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .law_certifier import lcg_navigate
from .owned_network import NetworkAddress, OwnedNetworkFabric, OwnedNetworkError

SCHEMA = "mailcpu.self-hosted-port-network.v1"
PACKET_SCHEMA = "mailcpu.self-hosted-port-packet.v1"
MODULUS = 65_536
MAX_COORDINATE = 10**18
MAX_PACKET_BYTES = 2_048
_JOB_ID = re.compile(r"[a-z][a-z0-9_-]{0,47}\Z")


class SelfHostedPortError(ValueError):
    """An internal observer-host operation is invalid or fails closed."""


def _canonical(value: object) -> bytes:
    """Encode a JSON value in stable UTF-8 bytes for exact message identity."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _digest(value: object) -> str:
    """Hash a canonical observer event or packet under SHA-256."""
    return hashlib.sha256(_canonical(value)).hexdigest()


def _require(condition: bool, reason: str) -> None:
    """Fail closed when a bounded self-hosted operation violates policy."""
    if not condition:
        raise SelfHostedPortError(reason)


def _packet(job_id: str, coordinate: int, phase: str, value: int | None,
            trace: list[str]) -> dict[str, Any]:
    """Build one typed immutable-by-convention packet description."""
    return {"schema": PACKET_SCHEMA, "job_id": job_id,
            "coordinate": coordinate, "phase": phase, "value": value,
            "trace": list(trace)}


def _decode(raw: bytes) -> dict[str, Any]:
    """Validate a canonical received byte packet without executing it."""
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_PACKET_BYTES,
             "oversized or empty internal frame")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise SelfHostedPortError("invalid internal frame encoding") from exc
    _require(type(value) is dict and set(value) ==
             {"schema", "job_id", "coordinate", "phase", "value", "trace"},
             "invalid packet fields")
    _require(_canonical(value) == raw, "noncanonical internal frame")
    _require(value["schema"] == PACKET_SCHEMA and
             type(value["job_id"]) is str and _JOB_ID.fullmatch(value["job_id"]) is not None,
             "invalid packet identity")
    _require(type(value["coordinate"]) is int and
             0 <= value["coordinate"] <= MAX_COORDINATE,
             "invalid navigable state coordinate")
    _require(value["phase"] in ("request", "navigated", "projected"),
             "invalid packet phase")
    _require(value["value"] is None or
             (type(value["value"]) is int and 0 <= value["value"] < MODULUS),
             "invalid port observation value")
    _require(type(value["trace"]) is list and len(value["trace"]) <= 2 and
             all(type(x) is str and len(x) == 64 and
                 all(ch in "0123456789abcdef" for ch in x) for x in value["trace"]),
             "invalid observer receipt chain")
    return value


class SelfHostedPortNetwork:
    """Finite observer-host ring with zero external I/O and explicit quanta.

    Logical topology:
      dispatcher.tx --> navigator.in
      navigator.out --> projector.in
      projector.out --> dispatcher.rx

    Each virtual port-host has a declared operation. `navigator` jumps to
    coordinate t using E-CPU's O(log t) LCG law without enumerating the orbit;
    `projector` applies a separate affine interpretation of that observation.
    No passive link executes code. Each host transition consumes one ordinary
    interpreter quantum and one bounded message exchange.
    """

    _POINTS = (("dispatcher", "tx"), ("navigator", "in"),
               ("navigator", "out"), ("projector", "in"),
               ("projector", "out"), ("dispatcher", "rx"))
    _EDGES = (("core-nav", 0, 1), ("nav-project", 2, 3),
              ("project-core", 4, 5))

    def __init__(self, physical_ports: int, *, queue_limit: int = 2) -> None:
        """Provision three internal observer-hosts under a 1/2-port exterior budget."""
        _require(type(physical_ports) is int and physical_ports in (1, 2),
                 "experiment admits exactly one or two physical boundary ports")
        _require(type(queue_limit) is int and 1 <= queue_limit <= 32,
                 "bounded internal FIFO capacity required")
        self.physical_ports = physical_ports
        self.fabric = OwnedNetworkFabric(queue_limit=queue_limit)
        for namespace in ("dispatcher", "navigator", "projector"):
            self.fabric.create_namespace(namespace)
        self.addresses = tuple(self.fabric.create_interface(n, interface, mtu=MAX_PACKET_BYTES)
                               for n, interface in self._POINTS)
        for name, left, right in self._EDGES:
            self.fabric.connect(name, self.addresses[left], self.addresses[right])
        self.phase = "idle"
        self.job_id: str | None = None
        self.coordinate: int | None = None
        self.history: list[str] = []
        self.result: int | None = None
        self.interpreter_quanta = 0
        self.internal_payload_bytes = 0
        self.external_payload_bytes = 0

    @staticmethod
    def _navigated(coordinate: int) -> int:
        """Observe the LCG orbit at a coordinate using an existing E-CPU law."""
        return lcg_navigate(5, 1, MODULUS, 7, coordinate)

    @staticmethod
    def _projected(value: int) -> int:
        """Project the received state through a second active observer-host."""
        return (3 * value + 11) % MODULUS

    def _expected_packets(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Derive the only valid three packet states and receipt sequence."""
        _require(self.job_id is not None and self.coordinate is not None,
                 "no admitted internal request")
        first = _packet(self.job_id, self.coordinate, "request", None, [])
        nav_value = self._navigated(self.coordinate)
        nav_receipt = _digest({"host": "navigator", "input_digest": _digest(first),
                               "value": nav_value, "operation": "lcg_navigate.v1"})
        second = _packet(self.job_id, self.coordinate, "navigated", nav_value, [nav_receipt])
        final_value = self._projected(nav_value)
        proj_receipt = _digest({"host": "projector", "input_digest": _digest(second),
                                "value": final_value, "operation": "affine_projection.v1"})
        third = _packet(self.job_id, self.coordinate, "projected", final_value,
                        [nav_receipt, proj_receipt])
        return first, second, third

    def submit(self, job_id: str, coordinate: int) -> None:
        """Admit one finite coordinate and transmit it onto the owned internal fabric."""
        _require(self.phase == "idle", "only one in-flight request is admitted")
        _require(type(job_id) is str and _JOB_ID.fullmatch(job_id) is not None,
                 "invalid request identity")
        _require(type(coordinate) is int and 0 <= coordinate <= MAX_COORDINATE,
                 "invalid navigable state coordinate")
        packet = _packet(job_id, coordinate, "request", None, [])
        raw = _canonical(packet)
        _require(len(raw) <= MAX_PACKET_BYTES, "request exceeds internal MTU")
        self.fabric.send(self.addresses[0], self.addresses[1], raw, 0)
        self.job_id, self.coordinate = job_id, coordinate
        self.phase = "navigator"
        self.internal_payload_bytes += len(raw)

    def _take_expected(self, receiver: int, expected_source: int,
                       packet: dict[str, Any]):
        """Observe the queued frame without consuming a malformed request."""
        frame = self.fabric.peek(self.addresses[receiver])
        _require(frame is not None, "expected internal frame is not ready")
        _require(frame.source == self.addresses[expected_source] and
                 frame.destination == self.addresses[receiver] and
                 frame.route == (frame.source, frame.destination),
                 "internal frame has wrong path identity")
        _require(_decode(frame.payload) == packet, "unexpected port-host observation")
        return frame

    def step(self) -> str:
        """Advance exactly one interpreter-dispatched host transition.

        Validates the entire current packet before enqueueing its successor.
        The receiving host never gains an independent CPU by being named.
        """
        _require(self.phase in ("navigator", "projector", "dispatcher"),
                 "no dispatchable virtual-host transition")
        first, second, third = self._expected_packets()
        if self.phase == "navigator":
            self._take_expected(1, 0, first)
            raw = _canonical(second)
            self.fabric.send(self.addresses[2], self.addresses[3], raw, 1)
            self.fabric.receive(self.addresses[1])
            self.history.append(second["trace"][0])
            self.phase = "projector"
            self.internal_payload_bytes += len(raw)
        elif self.phase == "projector":
            self._take_expected(3, 2, second)
            raw = _canonical(third)
            self.fabric.send(self.addresses[4], self.addresses[5], raw, 2)
            self.fabric.receive(self.addresses[3])
            self.history.append(third["trace"][1])
            self.phase = "dispatcher"
            self.internal_payload_bytes += len(raw)
        else:
            self._take_expected(5, 4, third)
            self.fabric.receive(self.addresses[5])
            self.result = third["value"]
            self.phase = "done"
        self.interpreter_quanta += 1
        return self.phase

    def run(self) -> dict[str, Any]:
        """Dispatch at most three virtual-host quanta until the result is accepted."""
        for _ in range(3):
            if self.phase == "done":
                break
            self.step()
        _require(self.phase == "done", "internal computation did not complete in budget")
        return self.report()

    def report(self) -> dict[str, Any]:
        """Return the observed value and explicitly accounted logical resources."""
        _require(self.phase == "done" and self.result is not None,
                 "no completed observation")
        return {"schema": SCHEMA, "job_id": self.job_id,
                "requested_coordinate": self.coordinate, "observed_value": self.result,
                "physical_boundary_ports": self.physical_ports,
                "logical_observer_hosts": 3, "internal_virtual_interfaces": 6,
                "internal_link_count": 3, "interpreter_quanta": self.interpreter_quanta,
                "internal_payload_bytes": self.internal_payload_bytes,
                "external_payload_bytes": self.external_payload_bytes,
                "materialized_orbit_intermediate_states": 0,
                "navigation_algorithm": "mailcpu.law_certifier.lcg_navigate",
                "observer_receipts": list(self.history),
                "journal_verified": self.fabric.journal.verify(),
                "independent_physical_execution_claimed": False,
                "hardware_port_emulation_verified": False}

    def snapshot(self) -> dict[str, Any]:
        """Capture internal topology, FIFO bytes, receipts, and dispatch cursor."""
        return {"schema": SCHEMA, "physical_ports": self.physical_ports,
                "phase": self.phase, "job_id": self.job_id,
                "coordinate": self.coordinate, "history": list(self.history),
                "result": self.result, "interpreter_quanta": self.interpreter_quanta,
                "internal_payload_bytes": self.internal_payload_bytes,
                "external_payload_bytes": self.external_payload_bytes,
                "fabric": self.fabric.snapshot()}

    def _validate_restored(self) -> None:
        """Reject a restored network that violates topology, receipt, or cost invariants."""
        expected = SelfHostedPortNetwork(self.physical_ports, queue_limit=self.fabric.queue_limit)
        _require(self.fabric.namespaces() == expected.fabric.namespaces() and
                 self.fabric.links() == expected.fabric.links(), "restored topology changed")
        def config(interfaces):
            """Project the immutable virtual-interface contract independently of queue occupancy."""
            return tuple(tuple((k, item[k]) for k in
                               ("namespace", "interface", "mtu", "queue_limit", "link_id", "up"))
                         for item in interfaces)
        _require(config(self.fabric.interfaces()) == config(expected.fabric.interfaces()),
                 "restored virtual interface contract changed")
        _require(self.fabric.journal.verify(), "restored fabric event journal corrupt")
        allowed = {"idle": (0, 0), "navigator": (0, 0), "projector": (1, 1),
                   "dispatcher": (2, 2), "done": (3, 2)}
        _require(self.phase in allowed, "invalid restored host phase")
        count, receipts = allowed[self.phase]
        _require(self.interpreter_quanta == count and type(self.external_payload_bytes) is int
                 and self.external_payload_bytes == 0 and
                 type(self.internal_payload_bytes) is int and self.internal_payload_bytes >= 0,
                 "restored resource evidence changed")
        if self.phase == "idle":
            _require(self.job_id is None and self.coordinate is None and
                     self.history == [] and self.result is None and
                     self.internal_payload_bytes == 0,
                     "invalid idle restoration")
            expected_packet = None
        else:
            _require(type(self.job_id) is str and _JOB_ID.fullmatch(self.job_id) is not None
                     and type(self.coordinate) is int and 0 <= self.coordinate <= MAX_COORDINATE,
                     "invalid restored request")
            first, second, third = self._expected_packets()
            packets = (first, second, third)
            expected_trace = (third["trace"][:receipts])
            _require(self.history == expected_trace, "restored observer receipts differ")
            sizes = [len(_canonical(item)) for item in packets]
            expected_total = sum(sizes[: {"navigator": 1, "projector": 2,
                                            "dispatcher": 3, "done": 3}[self.phase]])
            _require(self.internal_payload_bytes == expected_total,
                     "restored internal byte accounting differs")
            _require((self.result == third["value"]) if self.phase == "done"
                     else self.result is None, "restored result differs")
            expected_packet = {"navigator": (1, first, 0),
                               "projector": (3, second, 2),
                               "dispatcher": (5, third, 4)}.get(self.phase)
        for i, address in enumerate(self.addresses):
            queued = self.fabric.peek(address)
            if expected_packet is not None and i == expected_packet[0]:
                _require(queued is not None, "restored frame is missing")
                self._take_expected(expected_packet[0], expected_packet[2],
                                    expected_packet[1])
            else:
                _require(queued is None, "unexpected restored internal frame")

    @classmethod
    def from_snapshot(cls, payload: dict[str, Any]) -> SelfHostedPortNetwork:
        """Reconstruct a chip model from a checked owned-network checkpoint."""
        _require(type(payload) is dict and set(payload) == {
            "schema", "physical_ports", "phase", "job_id", "coordinate", "history",
            "result", "interpreter_quanta", "internal_payload_bytes",
            "external_payload_bytes", "fabric"}, "invalid chip snapshot fields")
        _require(payload["schema"] == SCHEMA, "unsupported chip checkpoint")
        node = cls(payload["physical_ports"], queue_limit=payload["fabric"]["queue_limit"])
        node.fabric = OwnedNetworkFabric.from_snapshot(payload["fabric"])
        node.phase, node.job_id, node.coordinate = (payload[k] for k in
                                                   ("phase", "job_id", "coordinate"))
        node.history = payload["history"]
        node.result = payload["result"]
        node.interpreter_quanta = payload["interpreter_quanta"]
        node.internal_payload_bytes = payload["internal_payload_bytes"]
        node.external_payload_bytes = payload["external_payload_bytes"]
        node._validate_restored()
        return node
