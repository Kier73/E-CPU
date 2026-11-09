"""Navigable E-GPU operational structure built over the SIMT reference host."""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .classifier import HypervisorArbitrationEvent, HypervisorRequest
from .transit_simt import TransitSIMTError, TransitSIMTHost

_OPERATION = "execute deterministic CPU E-GPU method"
_RESOURCE = "/gpu/egpu"
_EXECUTE = frozenset({"execute"})
_METHODS = {
    "simt.kernel": ("simt.execute",),
    "vector.add": ("simt.execute",),
    "vector.multiply": ("simt.execute",),
    "vector.sum": ("reduce.tree",),
    "workgroup.shared_kernel": ("workgroup.execute", "shared.memory"),
}
_HOST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")


def _digest(value: Any) -> str:
    """Mathematics: hash the unique sorted compact JSON projection of value."""

    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class EGPUError(ValueError):
    """Mathematics: refuse operations that violate E-GPU request, route, bound, or verification contracts."""


@dataclass(frozen=True)
class EGPUOperationalLocus:
    """One logical host locus in a composite E-GPU, independent of physical placement."""

    host_id: str
    role: str
    capabilities: frozenset[str]
    transitions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Mathematics: validate stable identity, role, capabilities, and finite directed successor identities."""

        if not isinstance(self.host_id, str) or _HOST_ID.fullmatch(self.host_id) is None:
            raise EGPUError("operational locus host_id is invalid")
        if not isinstance(self.role, str) or not self.role or self.role.strip() != self.role:
            raise EGPUError("operational locus role must be non-empty trimmed text")
        if not isinstance(self.capabilities, (set, frozenset, tuple, list)):
            raise EGPUError("operational locus capabilities must be a finite collection")
        caps = frozenset(self.capabilities)
        if not caps or any(not isinstance(x, str) or not x or x.strip() != x for x in caps):
            raise EGPUError("operational locus capabilities must be non-empty trimmed strings")
        if isinstance(self.transitions, str) or not isinstance(self.transitions, (tuple, list)):
            raise EGPUError("operational locus transitions must be a finite sequence")
        successors = tuple(self.transitions)
        if any(not isinstance(x, str) or not x or x.strip() != x for x in successors):
            raise EGPUError("operational locus transition targets must be non-empty strings")
        if len(set(successors)) != len(successors):
            raise EGPUError("operational locus transition targets must be unique")
        object.__setattr__(self, "capabilities", caps)
        object.__setattr__(self, "transitions", tuple(sorted(successors)))


class EGPUHost:
    """Composite logical host that navigates bounded methods through dispatch, execution, and verification loci."""

    operation_name = _OPERATION
    resource_name = _RESOURCE

    def __init__(
        self,
        *,
        host_id: str = "egpu.default",
        simt_host: TransitSIMTHost | None = None,
        loci: Sequence[EGPUOperationalLocus] | None = None,
    ) -> None:
        """Mathematics: bind one directed operational graph to a bounded SIMT evaluator and unique dispatch/verification loci."""

        if not isinstance(host_id, str) or _HOST_ID.fullmatch(host_id) is None:
            raise EGPUError("E-GPU host identity is invalid")
        if simt_host is not None and not isinstance(simt_host, TransitSIMTHost):
            raise TypeError("E-GPU simt_host must be a TransitSIMTHost")
        self.simt_host = simt_host or TransitSIMTHost()
        if loci is None:
            loci = (
                EGPUOperationalLocus(f"{host_id}.dispatch", "dispatch", frozenset({"egpu.dispatch"}),
                                    (f"{host_id}.simt", f"{host_id}.reduce", f"{host_id}.workgroup")),
                EGPUOperationalLocus(f"{host_id}.simt", "simt-execution", frozenset({"simt.execute"}),
                                    (f"{host_id}.verify",)),
                EGPUOperationalLocus(f"{host_id}.reduce", "tree-reduction", frozenset({"reduce.tree"}),
                                    (f"{host_id}.verify",)),
                EGPUOperationalLocus(f"{host_id}.workgroup", "workgroup-execution", frozenset({"workgroup.execute"}),
                                    (f"{host_id}.shared",)),
                EGPUOperationalLocus(f"{host_id}.shared", "workgroup-shared-memory", frozenset({"shared.memory"}),
                                    (f"{host_id}.verify",)),
                EGPUOperationalLocus(f"{host_id}.verify", "verification", frozenset({"result.verify"}), ()),
            )
        if isinstance(loci, (str, bytes)) or not isinstance(loci, (tuple, list)):
            raise EGPUError("E-GPU loci must be a finite sequence")
        if not loci or any(not isinstance(x, EGPUOperationalLocus) for x in loci):
            raise EGPUError("E-GPU requires typed operational loci")
        ids = [x.host_id for x in loci]
        if len(set(ids)) != len(ids):
            raise EGPUError("E-GPU operational locus identities must be unique")
        self._loci = {x.host_id: x for x in loci}
        for locus in loci:
            missing = sorted(set(locus.transitions) - set(self._loci))
            if missing:
                raise EGPUError(f"unknown successor(s) from {locus.host_id!r}: {missing}")
        self._entry = self._unique_locus("egpu.dispatch")
        self._verify = self._unique_locus("result.verify")
        self.host_id = host_id

    @property
    def available_methods(self) -> tuple[str, ...]:
        """Mathematics: expose the finite method domain in canonical lexical order."""

        return tuple(sorted(_METHODS))

    def resolve_path(self, capability: str) -> tuple[str, ...]:
        """Mathematics: find a deterministic minimum-hop dispatch-to-capability-to-verification path."""

        if not isinstance(capability, str) or not capability:
            raise EGPUError("requested capability must be non-empty text")
        return self._resolve_capabilities((capability,))

    def _resolve_capabilities(self, capabilities: Sequence[str]) -> tuple[str, ...]:
        """Mathematics: navigate an ordered sequence of unique capability hosts before the terminal verification locus."""

        if not isinstance(capabilities, (tuple, list)) or not capabilities:
            raise EGPUError("E-GPU route requires one or more capabilities")
        current = self._entry
        route = (current,)
        for capability in capabilities:
            target = self._unique_locus(capability)
            segment = self._shortest_path(current, target)
            route += segment[1:]
            current = target
        terminal = self._shortest_path(current, self._verify)
        return route + terminal[1:]

    def handle(self, event: HypervisorArbitrationEvent) -> dict[str, Any]:
        """Mathematics: check the outer grant, navigate one fixed method, execute, verify, and return a canonical route receipt."""

        if not isinstance(event, HypervisorArbitrationEvent):
            raise EGPUError("E-GPU requires a typed arbitration event")
        request = event.request
        if request.operation != _OPERATION or request.resource != _RESOURCE:
            raise EGPUError("operation identity is not an E-GPU method request")
        if request.required_rights != _EXECUTE or request.granted_rights != _EXECUTE:
            raise EGPUError("exact receiver-local execute authority is required for /gpu/egpu")
        if request.destructive:
            raise EGPUError("E-GPU reference methods cannot be marked destructive")
        if not isinstance(request.payload, Mapping):
            raise EGPUError("E-GPU payload must be a mapping")
        method = request.payload.get("method")
        capabilities = _METHODS.get(method) if isinstance(method, str) else None
        if capabilities is None:
            raise EGPUError("unsupported E-GPU method")
        route = self._resolve_capabilities(capabilities)
        capability = capabilities[0]
        if method in {"vector.add", "vector.multiply"}:
            result = self._vector(event, method)
        elif method == "vector.sum":
            result = self._reduce(request.payload)
        elif method == "workgroup.shared_kernel":
            result = self._workgroup_kernel(event, request.payload)
        else:
            result = self._kernel(event, request.payload)
        self._verify_result(method, request.payload, result)
        result_digest = _digest(result)
        receipt = {
            "host_id": self.host_id,
            "method": method,
            "capability": capability,
            "capabilities": list(capabilities),
            "route": list(route),
            "result_digest": result_digest,
        }
        return {**receipt, "result": result, "receipt_digest": _digest(receipt)}

    def execute_authorized_method(
        self,
        method: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Mathematics: run one method after outer Virtual Layer Hypervisor admission.

        This adapter is intended for a node-local Virtual Layer handler. The
        caller must already have admitted the workload and exact operator
        contract through the receiver's Hypervisor. The synthetic E-GPU event
        below only preserves EGPUHost's internal typed method interface; it is
        not a transferable grant and must not be used as an external admission
        substitute.
        """
        if not isinstance(method, str) or method not in _METHODS:
            raise EGPUError("unsupported E-GPU method")
        if not isinstance(payload, Mapping) or payload.get("method") != method:
            raise EGPUError("authorized method payload must name the exact E-GPU method")
        internal_request = HypervisorRequest(
            _OPERATION,
            _RESOURCE,
            dict(payload),
            _EXECUTE,
            _EXECUTE,
            False,
        )
        internal_event = HypervisorArbitrationEvent(
            f"virtual-layer:{self.host_id}",
            "egpu.authorized-local-operator",
            1,
            0,
            internal_request,
        )
        return self.handle(internal_event)

    def _unique_locus(self, capability: str) -> str:
        """Mathematics: resolve a capability only when its host-locus preimage has cardinality one."""

        matches = sorted(x.host_id for x in self._loci.values() if capability in x.capabilities)
        if len(matches) != 1:
            raise EGPUError(f"capability {capability!r} must identify exactly one operational locus")
        return matches[0]

    def _shortest_path(self, source: str, target: str) -> tuple[str, ...]:
        """Mathematics: breadth-first search the finite directed host graph with lexically ordered successors."""

        queue = deque([(source, (source,))])
        visited = {source}
        while queue:
            current, path = queue.popleft()
            if current == target:
                return path
            for nxt in self._loci[current].transitions:
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nxt, path + (nxt,)))
        raise EGPUError(f"no operational path exists from {source!r} to {target!r}")

    def _integer_sequence(self, value: Any, label: str) -> list[int]:
        """Mathematics: restrict vectors to a non-empty finite sequence of bounded integers."""

        if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)) or not value:
            raise EGPUError(f"{label} must be a non-empty integer sequence")
        if len(value) > self.simt_host.max_lanes:
            raise EGPUError(f"{label} exceeds the configured lane bound")
        values: list[int] = []
        for item in value:
            if not isinstance(item, int) or isinstance(item, bool):
                raise EGPUError(f"{label} values must be integers")
            self._integer_bound(item)
            values.append(item)
        return values

    def _integer_bound(self, value: int) -> None:
        """Mathematics: require every input and intermediate integer to fit the SIMT host bit bound."""

        if value.bit_length() > self.simt_host.max_integer_bits:
            raise EGPUError("E-GPU integer exceeds the configured bit bound")

    def _vector(self, event: HypervisorArbitrationEvent, method: str) -> dict[str, Any]:
        """Mathematics: compile bounded vector add/multiply into the SIMT transition algebra."""

        payload = event.request.payload
        if set(payload) != {"method", "left", "right", "max_steps"}:
            raise EGPUError("vector method fields are invalid")
        left = self._integer_sequence(payload.get("left"), "left input")
        right = self._integer_sequence(payload.get("right"), "right input")
        if len(left) != len(right):
            raise EGPUError("vector operands must have equal lane counts")
        op = "add" if method == "vector.add" else "mul"
        program = [
            ["load", "a", "left"], ["load", "b", "right"],
            [op, "out", "a", "b"], ["store", "result", "out"], ["halt"],
        ]
        return self._run_simt(event, len(left), {"left": left, "right": right}, program, payload["max_steps"])

    def _kernel(self, event: HypervisorArbitrationEvent, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Mathematics: delegate an explicitly typed custom kernel to the bounded reference SIMT interpreter."""

        if set(payload) != {"method", "lanes", "inputs", "program", "max_steps"}:
            raise EGPUError("SIMT kernel fields are invalid")
        return self._run_simt(event, payload["lanes"], payload["inputs"], payload["program"], payload["max_steps"])

    def _run_simt(self, event: HypervisorArbitrationEvent, lanes: Any, inputs: Any,
                  program: Any, max_steps: Any, shared_buffers: Any = None) -> dict[str, Any]:
        """Mathematics: invoke the inner SIMT evaluator under the already-admitted outer E-GPU execution contract."""

        inner_payload = {"lanes": lanes, "inputs": inputs, "program": program, "max_steps": max_steps}
        if shared_buffers is not None:
            inner_payload["shared_buffers"] = shared_buffers
        inner = HypervisorRequest(
            TransitSIMTHost.operation_name, TransitSIMTHost.resource_name,
            inner_payload,
            _EXECUTE, _EXECUTE, False,
        )
        internal_event = HypervisorArbitrationEvent(
            event.source, event.channel, event.sequence, event.logical_time, inner,
        )
        try:
            return self.simt_host.handle(internal_event)
        except (TransitSIMTError, TypeError, ValueError) as exc:
            raise EGPUError(f"SIMT execution refused: {exc}") from exc


    def _workgroup_kernel(
        self,
        event: HypervisorArbitrationEvent,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Mathematics: execute one bounded workgroup kernel whose shared buffers become visible only at converged barrier epochs."""

        if set(payload) != {"method", "lanes", "inputs", "shared_buffers", "program", "max_steps"}:
            raise EGPUError("workgroup kernel fields are invalid")
        return self._run_simt(
            event,
            payload["lanes"],
            payload["inputs"],
            payload["program"],
            payload["max_steps"],
            payload["shared_buffers"],
        )

    def _reduce(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Mathematics: sum adjacent integer pairs at each level, carrying an odd final element unchanged."""

        if set(payload) != {"method", "values", "max_steps"}:
            raise EGPUError("tree reduction fields are invalid")
        active = self._integer_sequence(payload.get("values"), "reduction input")
        budget = payload.get("max_steps")
        if not isinstance(budget, int) or isinstance(budget, bool) or not 0 < budget <= self.simt_host.max_steps:
            raise EGPUError("reduction step budget is outside configured bounds")
        trace: list[dict[str, int]] = []
        while len(active) > 1:
            nxt = [active[i] + active[i + 1] for i in range(0, len(active) - 1, 2)]
            if len(active) % 2:
                nxt.append(active[-1])
            for value in nxt:
                self._integer_bound(value)
            trace.append({
                "level": len(trace) + 1, "input_width": len(active),
                "pair_count": len(active) // 2, "output_width": len(nxt),
            })
            active = nxt
        if len(trace) > budget:
            raise EGPUError("tree reduction exceeds its requested level budget")
        state = {
            "sum": active[0],
            "levels": len(trace),
            "work_units": sum(item["pair_count"] for item in trace),
            "trace": trace,
        }
        return {**state, "state_digest": _digest(state)}

    def _verify_result(self, method: str, payload: Mapping[str, Any], result: Mapping[str, Any]) -> None:
        """Mathematics: compare vector and reduction results with scalar definitions and recompute backend state digests."""

        if method in {"simt.kernel", "vector.add", "vector.multiply", "workgroup.shared_kernel"}:
            fields = ["lanes", "steps", "registers", "outputs", "mask_trace", "barriers"]
            if method == "workgroup.shared_kernel":
                fields.extend(("shared_memory", "shared_epochs"))
            elif "shared_memory" in result:
                fields.extend(("shared_memory", "shared_epochs"))
            if set(result) != set(fields) | {"state_digest"}:
                raise EGPUError("SIMT result fields are invalid")
            state = {key: result[key] for key in fields}
            if result.get("state_digest") != _digest(state):
                raise EGPUError("SIMT state digest is invalid")
        if method == "vector.add":
            expected = [a + b for a, b in zip(payload["left"], payload["right"])]
            if result["outputs"].get("result") != expected:
                raise EGPUError("vector addition failed its scalar reference check")
        elif method == "vector.multiply":
            expected = [a * b for a, b in zip(payload["left"], payload["right"])]
            if result["outputs"].get("result") != expected:
                raise EGPUError("vector multiplication failed its scalar reference check")
        elif method == "vector.sum":
            state = {k: result[k] for k in ("sum", "levels", "work_units", "trace")}
            if result.get("state_digest") != _digest(state):
                raise EGPUError("tree reduction state digest is invalid")
            if result.get("sum") != sum(payload["values"]):
                raise EGPUError("tree reduction failed its scalar reference check")
