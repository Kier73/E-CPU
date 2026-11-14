"""USM-002: bounded, receiver-authoritative model system calls into E-CPU.

An isolated model worker may request observe -> propose -> read. It cannot
supply the truth samples, issue admission grants, choose arbitrary methods, or
change the E-CPU registry. The receiver owns the observation source, capability
allowlist, witness checks, and version-pinned result navigation.

This local subprocess ABI is not a security sandbox or a remote transport.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from examples.model_ground_os import GroundPolicyModel, _digest
from mailcpu.structural_memory import StructuralMemoryError, StructuralMemoryRegistry

REQUEST_SCHEMA = "mailcpu.model-syscall-request.v1"
CALL_SCHEMA = "mailcpu.model-syscall.v1"
RESPONSE_SCHEMA = "mailcpu.model-syscall-response.v1"
TRACE_SCHEMA = "mailcpu.model-syscall-trace.v1"
GENESIS = "0" * 64
MAX_COORDINATE = 10**18


class SystemCallRefused(ValueError):
    """A model-facing instruction was not admitted by the receiver."""


def _integer(value: Any, label: str, *, maximum: int = MAX_COORDINATE) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise SystemCallRefused(f"invalid {label}")
    return value


def _identifier(value: Any, label: str) -> str:
    if type(value) is not str or not (1 <= len(value) <= 128) or not value.isascii():
        raise SystemCallRefused(f"invalid {label}")
    if not all(c.isalnum() or c in "-_:.@" for c in value):
        raise SystemCallRefused(f"invalid {label}")
    return value


class GroundSystemCallSession:
    """Receiver-owned capability surface; model proposals are just requests."""

    def __init__(
        self,
        *,
        registry: StructuralMemoryRegistry,
        session_id: str,
        stream_id: str,
        observations: Sequence[int],
        coordinate: int,
        training_count: int,
        context: Mapping[str, Any],
        allowed_ops: frozenset[str] = frozenset({"observe", "propose", "read"}),
    ) -> None:
        self.session_id = _identifier(session_id, "session")
        self.stream_id = _identifier(stream_id, "stream")
        self.coordinate = _integer(coordinate, "coordinate")
        if not isinstance(registry, StructuralMemoryRegistry):
            raise SystemCallRefused("registry must be an E-CPU receiver-owned service")
        if type(training_count) is not int or not 4 <= training_count < len(observations):
            raise SystemCallRefused("invalid observation split")
        if len(observations) > 4096 or any(type(item) is not int for item in observations):
            raise SystemCallRefused("invalid observation source")
        if not isinstance(context, Mapping):
            raise SystemCallRefused("invalid receiver context")
        if not isinstance(allowed_ops, frozenset) or not allowed_ops.issubset(
            {"observe", "propose", "read"}
        ):
            raise SystemCallRefused("unknown system-call capability")
        self.registry = registry
        # Freeze all input values. The model worker cannot replace this truth.
        self.observations = tuple(observations)
        self.training_count = training_count
        self.context = json.loads(json.dumps(context, sort_keys=True, allow_nan=False))
        self.allowed_ops = allowed_ops
        self.phase = "new"
        self.head = GENESIS
        self.events: list[dict[str, Any]] = []
        self.ground_revision: int | None = None
        self.ground_digest: str | None = None

    def _authorize(self, op: str, coordinate: Any) -> None:
        transitions = {"new": {"observe"}, "observed": {"propose", "stop"},
                       "admitted": {"read", "stop"}}
        if op not in transitions.get(self.phase, set()):
            raise SystemCallRefused("system call is not legal in the current phase")
        if op != "stop" and op not in self.allowed_ops:
            raise SystemCallRefused("system-call capability is not granted")
        if op == "read":
            if _integer(coordinate, "read coordinate") != self.coordinate:
                raise SystemCallRefused("read coordinate differs from the user request")
        elif coordinate is not None:
            raise SystemCallRefused("non-read call must not select a coordinate")

    def apply(self, call: Mapping[str, Any]) -> dict[str, Any]:
        """Apply one correlated request and journal even E-CPU refusals.

        Malformed/replayed requests are rejected *before* any registry action.
        """
        required = {"schema", "session_id", "stream_id", "seq", "previous_head",
                    "op", "coordinate"}
        if not isinstance(call, Mapping) or set(call) != required:
            raise SystemCallRefused("invalid call envelope")
        if (call["schema"] != CALL_SCHEMA
                or call["session_id"] != self.session_id
                or call["stream_id"] != self.stream_id
                or type(call["seq"]) is not int or call["seq"] != len(self.events)
                or call["previous_head"] != self.head):
            raise SystemCallRefused("replayed or cross-session call")
        op = call["op"]
        if type(op) is not str:
            raise SystemCallRefused("invalid operation")
        self._authorize(op, call["coordinate"])
        if op == "observe":
            output: dict[str, Any] = {
                "status": "observed",
                "window": list(self.observations[:self.training_count]),
                "window_digest": _digest(list(self.observations[:self.training_count])),
                "withheld_count": len(self.observations) - self.training_count,
            }
            self.phase = "observed"
        elif op == "propose":
            try:
                proposal = self.registry.propose_trace(
                    self.stream_id,
                    self.observations[:self.training_count],
                    self.observations[self.training_count:],
                    domain="model-operated-observed-orbit",
                    context=self.context,
                )
                version = self.registry.admit(proposal.proposal_id, expected_revision=0)
                self.ground_revision = version.spec.revision
                self.ground_digest = version.spec.digest
                output = {"status": "admitted", "ground_digest": version.spec.digest,
                          "certificate_digest": version.certificate.digest,
                          "revision": version.spec.revision,
                          "verification_class": version.certificate.verification_class.value}
                self.phase = "admitted"
            except StructuralMemoryError as exc:
                output = {"status": "refused_by_ecpu", "refusal": type(exc).__name__}
                self.phase = "refused"
        elif op == "read":
            if self.ground_revision is None or self.ground_digest is None:
                raise SystemCallRefused("there is no admitted Ground to read")
            try:
                reading = self.registry.read_revision(
                    self.stream_id, self.ground_revision,
                    self.coordinate, context=self.context,
                )
                if reading.spec_digest != self.ground_digest:
                    raise SystemCallRefused("read changed Ground revision")
                output = {"status": "completed", "value": reading.value,
                          "ground_digest": reading.spec_digest,
                          "read_receipt_id": reading.receipt_id,
                          "verification_class": reading.verification_class.value}
                self.phase = "complete"
            except StructuralMemoryError as exc:
                output = {"status": "refused_by_ecpu", "refusal": type(exc).__name__}
                self.phase = "refused"
        else:  # stop is a model-level scheduling decision, not an E-CPU refusal
            output = {"status": "deferred_by_model"}
            self.phase = "deferred"

        core = {"index": len(self.events), "previous_head": self.head,
                "call": dict(call), "output": output, "next_phase": self.phase}
        event = {**core, "event_digest": _digest(core)}
        self.events.append(event)
        self.head = event["event_digest"]
        return dict(output)

    def trace(self) -> dict[str, Any]:
        """Return reconstructable operation ordering and receiver evidence."""
        core = {
            "schema": TRACE_SCHEMA,
            "session_id": self.session_id,
            "stream_id": self.stream_id,
            "observation_digest": _digest(list(self.observations)),
            "training_count": self.training_count,
            "requested_coordinate": self.coordinate,
            "phase": self.phase,
            "events": self.events,
            "head": self.head,
        }
        return {**core, "trace_digest": _digest(core)}


def verify_system_call_trace(trace: Mapping[str, Any]) -> bool:
    """Independently check chain and request ordering (not source observations).

    A verified trace digest alone does not verify an external source, model
    quality, host policy, or an E-CPU law beyond its attached certificate.
    """
    expected = {"schema", "session_id", "stream_id", "observation_digest",
                "training_count", "requested_coordinate", "phase",
                "events", "head", "trace_digest"}
    if not isinstance(trace, Mapping) or set(trace) != expected or trace["schema"] != TRACE_SCHEMA:
        return False
    try:
        if _digest({k: trace[k] for k in expected - {"trace_digest"}}) != trace["trace_digest"]:
            return False
        head = GENESIS
        phase = "new"
        for index, event in enumerate(trace["events"]):
            fields = {"index", "previous_head", "call", "output", "next_phase", "event_digest"}
            if not isinstance(event, Mapping) or set(event) != fields:
                return False
            core = {k: event[k] for k in fields - {"event_digest"}}
            call = event["call"]
            if (event["index"] != index or event["previous_head"] != head
                    or _digest(core) != event["event_digest"]):
                return False
            if (call["schema"] != CALL_SCHEMA
                    or call["session_id"] != trace["session_id"]
                    or call["stream_id"] != trace["stream_id"]
                    or type(call["seq"]) is not int or call["seq"] != index
                    or call["previous_head"] != head):
                return False
            next_phase = {
                ("new", "observe", "observed"): "observed",
                ("observed", "propose", "admitted"): "admitted",
                ("observed", "propose", "refused_by_ecpu"): "refused",
                ("observed", "stop", "deferred_by_model"): "deferred",
                ("admitted", "read", "completed"): "complete",
                ("admitted", "read", "refused_by_ecpu"): "refused",
                ("admitted", "stop", "deferred_by_model"): "deferred",
            }.get((phase, call["op"], event["output"]["status"]))
            if next_phase is None or next_phase != event["next_phase"]:
                return False
            if call["op"] == "read" and call["coordinate"] != trace["requested_coordinate"]:
                return False
            if call["op"] != "read" and call["coordinate"] is not None:
                return False
            phase = next_phase
            head = event["event_digest"]
        return head == trace["head"] and phase == trace["phase"]
    except (ValueError, TypeError, KeyError, OverflowError):
        return False


def request_model_call(
    model: GroundPolicyModel,
    session: GroundSystemCallSession,
    last_response: Mapping[str, Any] | None,
    *,
    threshold: float = 0.5,
) -> dict[str, Any]:
    """Allow a separate model process to choose one typed system call."""
    if type(threshold) not in (float, int) or not math.isfinite(threshold) or not 0 < threshold < 1:
        raise SystemCallRefused("invalid policy threshold")
    request = {
        "kind": REQUEST_SCHEMA,
        "session_id": session.session_id,
        "stream_id": session.stream_id,
        "seq": len(session.events),
        "previous_head": session.head,
        "phase": session.phase,
        "coordinate": session.coordinate,
        "threshold": threshold,
        "model": model.snapshot(),
        "last_response": last_response,
    }
    try:
        worker = subprocess.run(
            (sys.executable, "-m", "examples.model_system_worker"),
            input=json.dumps(request, sort_keys=True, separators=(",", ":"), allow_nan=False),
            text=True, capture_output=True, timeout=10, check=False, shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemCallRefused("model worker did not complete") from exc
    if worker.returncode or len(worker.stdout) > 4096:
        raise SystemCallRefused("model worker refused or exceeded output budget")
    try:
        result = json.loads(worker.stdout)
    except (ValueError, TypeError) as exc:
        raise SystemCallRefused("model worker returned invalid JSON") from exc
    if not isinstance(result, dict) or set(result) != {
        "kind", "request_digest", "model_digest", "call", "probability"
    }:
        raise SystemCallRefused("invalid model response")
    if (result["kind"] != RESPONSE_SCHEMA
            or result["request_digest"] != _digest(request)
            or result["model_digest"] != model.digest):
        raise SystemCallRefused("model response is not bound to this request")
    probability = result["probability"]
    if probability is not None and (type(probability) not in (float, int)
                                     or not math.isfinite(probability)
                                     or not 0 <= probability <= 1):
        raise SystemCallRefused("invalid model probability")
    # A model response is not an execution grant. The receiver checks the call.
    session.apply(result["call"])
    return result


def run_model_system(
    model: GroundPolicyModel,
    registry: StructuralMemoryRegistry,
    stream_id: str,
    observations: Sequence[int],
    *,
    coordinate: int,
    session_id: str,
    context: Mapping[str, Any],
    training_count: int = 24,
) -> dict[str, Any]:
    """Complete one actual model-driven receive/observe/propose/navigate episode."""
    session = GroundSystemCallSession(
        registry=registry, session_id=session_id, stream_id=stream_id,
        observations=observations, coordinate=coordinate,
        training_count=training_count, context=context,
    )
    last: dict[str, Any] | None = None
    decisions: list[dict[str, Any]] = []
    for _ in range(3):
        if session.phase in {"complete", "deferred", "refused"}:
            break
        reply = request_model_call(model, session, last)
        last = session.events[-1]["output"]
        decisions.append({"call": reply["call"]["op"],
                          "probability": reply["probability"],
                          "request_digest": reply["request_digest"]})
    if session.phase not in {"complete", "deferred", "refused"}:
        raise SystemCallRefused("model did not terminate within three system calls")
    trace = session.trace()
    assert verify_system_call_trace(trace)
    return {"schema": "mailcpu.model-operating-session.v1",
            "model_digest": model.digest, "session": trace,
            "decisions": decisions, "status": session.phase}


if __name__ == "__main__":
    from examples.model_ground_os import sample_stream, train_example_model
    model, training = train_example_model()
    context = {"tenant": "use-system", "purpose": "observed-computation"}
    registry = StructuralMemoryRegistry(
        admission_policy=lambda proposal: (
            proposal.spec.domain == "model-operated-observed-orbit"
            and proposal.spec.context == context
        )
    )
    episodes = []
    for kind, seed in (("affine", 201), ("nonlinear", 207)):
        episodes.append(run_model_system(
            model, registry, f"usm002-{kind}", sample_stream(kind, seed),
            coordinate=10**12 + 137, session_id=f"session-{kind}",
            context=context,
        ))
    report = {"schema": "mailcpu.usm002.report.v1", "training": training,
              "episodes": episodes}
    print(json.dumps({**report, "report_digest": _digest(report)}, sort_keys=True, indent=2))
