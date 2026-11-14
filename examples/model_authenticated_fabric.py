"""USM-004: operate E-CPU via real mutually authenticated MailCPU channels.

Two independently launched local OS processes exchange model system-call
prompts and model-issued operations over MailCPU SocketTransport/mTLS and
ReliableChannel. The receiving process alone holds StructuralMemoryRegistry,
observations, source-truth and authorization. This is not a secure sandbox,
remote network deployment, or crash-recovery protocol.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import ssl
import sys
import time
from typing import Any, Mapping

from examples.model_ground_os import GroundPolicyModel, _digest, sample_stream, train_example_model
from examples.model_system_calls import (
    REQUEST_SCHEMA, RESPONSE_SCHEMA, GroundSystemCallSession,
    SystemCallRefused, verify_system_call_trace,
)
from examples.model_system_worker import decide
from mailcpu.mtls_transport import accept_mutual_tls, connect_mutual_tls
from mailcpu.reliability import ReliabilityPolicy, ReliableChannel
from mailcpu.socket_transport import SocketTransport
from mailcpu.structural_memory import StructuralMemoryRegistry

PROTOCOL = "mailcpu.model-fabric.v1"
PROMPT_CHANNEL = "model.syscall.prompt"
CALL_CHANNEL = "model.syscall.call"
DONE_SCHEMA = "mailcpu.model-fabric.done.v1"
MODEL_ENDPOINT = "model"
RECEIVER_ENDPOINT = "receiver"
MODEL_DNS = "model-node"
RECEIVER_DNS = "receiver-node"
CONTEXT = {"tenant": "use-system", "purpose": "observed-computation"}
COORDINATE = 10**12 + 137
TIMEOUT = 12.0


class ModelFabricRefused(RuntimeError):
    """Authenticated operation protocol failed before a claimed result."""


def server_tls_context(cert: Path, key: Path, ca: Path) -> ssl.SSLContext:
    """TLS server authenticates the client certificate chain and its DNS SAN."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert), str(key))
    context.load_verify_locations(cafile=str(ca))
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def model_tls_context(cert: Path, key: Path, ca: Path) -> ssl.SSLContext:
    """Client verifies server DNS identity and presents its own certificate."""
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(ca))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(cert), str(key))
    return context


def _channels(transport: SocketTransport, *, model_side: bool) -> tuple[ReliableChannel, ReliableChannel]:
    """Return (outbound, inbound) channels over one MailCPU mTLS stream."""
    policy = ReliabilityPolicy(lease_ticks=4, max_attempts=12, window_size=4)
    if model_side:
        return (
            ReliableChannel(transport, MODEL_ENDPOINT, RECEIVER_ENDPOINT, CALL_CHANNEL, policy),
            ReliableChannel(transport, MODEL_ENDPOINT, MODEL_ENDPOINT, PROMPT_CHANNEL, policy,
                            peer=RECEIVER_ENDPOINT),
        )
    return (
        ReliableChannel(transport, RECEIVER_ENDPOINT, MODEL_ENDPOINT, PROMPT_CHANNEL, policy),
        ReliableChannel(transport, RECEIVER_ENDPOINT, RECEIVER_ENDPOINT, CALL_CHANNEL, policy,
                        peer=MODEL_ENDPOINT),
    )


def _receive(
    incoming: ReliableChannel,
    outgoing: ReliableChannel,
    *,
    commit: Any = None,
    timeout: float = TIMEOUT,
) -> tuple[int, Any]:
    """Drive transport and acknowledgements until one ordered input commits."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        outgoing.process_ack()
        delivered = incoming.receive(commit=commit)
        if delivered is not None:
            return delivered
        time.sleep(0.005)
    raise ModelFabricRefused("authenticated reliable channel receive timeout")


def _ack(outgoing: ReliableChannel, *, timeout: float = TIMEOUT) -> None:
    """Wait for all accepted frames to be acknowledged before dropping TLS."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        outgoing.process_ack()
        if not outgoing.pending_sequences():
            return
        time.sleep(0.005)
    raise ModelFabricRefused("authenticated reliable channel ACK timeout")


def _prompt(
    model: GroundPolicyModel,
    session: GroundSystemCallSession,
    previous: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "kind": REQUEST_SCHEMA,
        "session_id": session.session_id,
        "stream_id": session.stream_id,
        "seq": len(session.events),
        "previous_head": session.head,
        "phase": session.phase,
        "coordinate": session.coordinate,
        "threshold": 0.5,
        "model": model.snapshot(),
        "last_response": previous,
    }


def _validate_response(request: Mapping[str, Any], reply: Any) -> Mapping[str, Any]:
    """Correlate a model-issued request with exact session and checkpoint."""
    expected = {"kind", "request_digest", "model_digest", "call", "probability"}
    if not isinstance(reply, dict) or set(reply) != expected:
        raise ModelFabricRefused("unexpected model response envelope")
    if (reply["kind"] != RESPONSE_SCHEMA
            or reply["request_digest"] != _digest(request)
            or reply["model_digest"] != request["model"]["digest"]):
        raise ModelFabricRefused("model response failed authenticated request correlation")
    probability = reply["probability"]
    if probability is not None and (
        type(probability) not in (int, float)
        or not math.isfinite(probability) or not 0 <= probability <= 1
    ):
        raise ModelFabricRefused("model probability is outside the valid domain")
    return reply


def receiver_session(
    transport: SocketTransport,
    *,
    model: GroundPolicyModel,
    observations: tuple[int, ...],
    session_id: str,
    stream_id: str,
    deny_admission: bool = False,
    allowed_ops: frozenset[str] = frozenset({"observe", "propose", "read"}),
) -> dict[str, Any]:
    """Operate E-CPU's actual registry from a mutually authenticated peer.

    The ReliableChannel commit callback calls the receiver's admission
    endpoint *before* an operation's transport acknowledgement is emitted.
    Crash-durable recovery is a separate milestone.
    """
    registry = StructuralMemoryRegistry(
        admission_policy=None if deny_admission else
        lambda p: p.spec.domain == "model-operated-observed-orbit" and p.spec.context == CONTEXT
    )
    session = GroundSystemCallSession(
        registry=registry, session_id=session_id, stream_id=stream_id,
        observations=observations, coordinate=COORDINATE,
        training_count=24, context=CONTEXT, allowed_ops=allowed_ops,
    )
    outbound, inbound = _channels(transport, model_side=False)
    exchanges = []
    last = None
    for _ in range(3):
        if session.phase in {"complete", "refused", "deferred"}:
            break
        request = _prompt(model, session, last)
        prompt_sequence = outbound.send(request)
        accepted: list[Mapping[str, Any]] = []

        def commit(_sequence: int, reply: Any) -> None:
            validated = _validate_response(request, reply)
            # Admission and the Ground read are owned exclusively by receiver.
            response = session.apply(validated["call"])
            accepted.append({"reply": validated, "result": response})

        response_sequence, _payload = _receive(inbound, outbound, commit=commit)
        if len(accepted) != 1:
            raise ModelFabricRefused("model call was not committed by receiver")
        last = accepted[0]["result"]
        exchanges.append({
            "prompt_sequence": prompt_sequence,
            "call_sequence": response_sequence,
            "request_digest": _digest(request),
            "operation": accepted[0]["reply"]["call"]["op"],
            "result_status": last["status"],
        })
    if session.phase not in {"complete", "refused", "deferred"}:
        raise ModelFabricRefused("model exceeded bounded system call budget")
    trace = session.trace()
    if not verify_system_call_trace(trace):
        raise ModelFabricRefused("receiver could not reconstruct its operation trace")
    done = {"kind": DONE_SCHEMA, "session_id": session.session_id,
            "trace_digest": trace["trace_digest"], "phase": session.phase}
    outbound.send(done)
    _ack(outbound)
    return {
        "schema": "mailcpu.usm004.authenticated-session.v1",
        "protocol": PROTOCOL,
        "transport": "mailcpu-mutual-tls-socket-reliable-channel",
        "peer_dns_verified": MODEL_DNS,
        "tls_version": transport.socket.version(),
        "receiver_process": os.getpid(),
        "session": trace,
        "exchanges": exchanges,
        "status": session.phase,
        "model_digest": model.digest,
    }


def model_host_session(transport: SocketTransport) -> dict[str, Any]:
    """An unprivileged model host receives observations and issues remote calls."""
    outbound, inbound = _channels(transport, model_side=True)
    requests_processed = 0
    final = None
    for _ in range(4):
        _sequence, payload = _receive(inbound, outbound)
        if not isinstance(payload, dict):
            raise ModelFabricRefused("non-object authenticated model prompt")
        if payload.get("kind") == DONE_SCHEMA:
            if set(payload) != {"kind", "session_id", "trace_digest", "phase"}:
                raise ModelFabricRefused("invalid terminal receiver message")
            final = payload
            break
        if payload.get("kind") != REQUEST_SCHEMA:
            raise ModelFabricRefused("unknown authenticated model prompt")
        # This computation runs on the independent model process.
        response = decide(payload)
        if response["request_digest"] != _digest(payload):
            raise ModelFabricRefused("local decision failed request correlation")
        outbound.send(response)
        requests_processed += 1
    if final is None:
        raise ModelFabricRefused("receiver never finalized the model operation")
    _ack(outbound)
    # Allow the final prompt ACK to cross the TLS stream before closure.
    time.sleep(0.02)
    return {
        "schema": "mailcpu.usm004.model-host.v1",
        "protocol": PROTOCOL,
        "model_process": os.getpid(),
        "receiver_dns_verified": RECEIVER_DNS,
        "tls_version": transport.socket.version(),
        "requests_processed": requests_processed,
        "final": final,
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("receiver", "model"))
    parser.add_argument("--ca", type=Path, required=True)
    parser.add_argument("--cert", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-kind", choices=("affine", "nonlinear"), default="affine")
    parser.add_argument("--source-seed", type=int, default=201)
    parser.add_argument("--policy", choices=("high-request", "low-request", "trained"), default="high-request")
    parser.add_argument("--deny-admission", action="store_true")
    parser.add_argument("--deny-propose", action="store_true")
    args = parser.parse_args(argv)
    if args.role == "receiver":
        model = (GroundPolicyModel(bias=30.0) if args.policy == "high-request" else
                 GroundPolicyModel(bias=-30.0) if args.policy == "low-request" else
                 train_example_model()[0])
        allowed = (frozenset({"observe", "read"}) if args.deny_propose
                   else frozenset({"observe", "propose", "read"}))
        listener = SocketTransport.listen(args.host, args.port)
        transport = None
        try:
            print(json.dumps({"ready_port": listener.getsockname()[1], "protocol": PROTOCOL}),
                  flush=True)
            transport = accept_mutual_tls(
                listener, RECEIVER_ENDPOINT, MODEL_ENDPOINT,
                server_tls_context(args.cert, args.key, args.ca),
                expected_peer_dns=MODEL_DNS,
            )
            report = receiver_session(
                transport, model=model, observations=sample_stream(args.source_kind, args.source_seed),
                session_id=f"session-{args.source_kind}-{args.source_seed}",
                stream_id=f"ground-{args.source_kind}-{args.source_seed}",
                deny_admission=args.deny_admission,
                allowed_ops=allowed,
            )
            if args.output:
                args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n",
                                       encoding="utf-8")
            print(json.dumps({"status": report["status"], "trace_digest":
                              report["session"]["trace_digest"]}), flush=True)
            return 0
        finally:
            if transport is not None and not transport.closed:
                transport.close()
            listener.close()
    if args.port <= 0:
        parser.error("model must provide receiver --port")
    transport = connect_mutual_tls(
        args.host, args.port, MODEL_ENDPOINT, RECEIVER_ENDPOINT,
        model_tls_context(args.cert, args.key, args.ca),
        server_hostname=RECEIVER_DNS,
    )
    try:
        report = model_host_session(transport)
        if args.output:
            args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n",
                                   encoding="utf-8")
        print(json.dumps({"status": report["final"]["phase"], "requests":
                          report["requests_processed"]}), flush=True)
        return 0
    finally:
        if not transport.closed:
            transport.close()


if __name__ == "__main__":
    try:
        sys.exit(_main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"authenticated model session refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
