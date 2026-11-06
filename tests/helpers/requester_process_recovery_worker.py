"""Server/client processes for durable requester restart with a surviving receiver."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mailcpu import (  # noqa: E402
    Capability,
    HeadlessOS,
    HypervisorArbitrationEvent,
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
    HypervisorPolicy,
    HypervisorRequest,
    ReliabilityPolicy,
    ReliableChannel,
    SocketTransport,
    TransitComputeHost,
    TransitComputeSession,
    TransitComputeWorker,
)
from mailcpu import TransitTranslationEvidence, TransitOracleEvidence  # noqa: E402

CHANNEL = "requester-process-recovery"
CPU_OPERATION = "execute deterministic CPU arithmetic program"
CPU_RESOURCE = "/cpu/compute"


class CountingHost(TransitComputeHost):
    """Count backend entries across the receiver's pre- and post-rebind sessions."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def handle(self, event: HypervisorArbitrationEvent) -> dict[str, object]:
        self.calls += 1
        return super().handle(event)


class RebindRequested(Exception):
    """The client process died at a persisted receiver transaction cut."""


def _write_json_durable(path: Path, value: dict[str, Any]) -> None:
    """Atomically publish one JSON record after flushing and fsyncing its contents."""

    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _write_client_checkpoint(path: Path, state: dict[str, Any]) -> str:
    """Persist a digest-bound, typed pair of client reliable-channel snapshots."""

    canonical = json.dumps(
        state, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    _write_json_durable(path, {"version": 1, "digest": digest, "state": state})
    return digest


def _read_client_checkpoint(path: Path) -> dict[str, Any]:
    """Validate the exact client channel envelope before reconstructing either endpoint."""

    envelope = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(envelope, dict) or set(envelope) != {"version", "digest", "state"}:
        raise ValueError("client checkpoint envelope fields are invalid")
    if envelope["version"] != 1 or not isinstance(envelope["state"], dict):
        raise ValueError("client checkpoint envelope version or state is invalid")
    canonical = json.dumps(
        envelope["state"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    expected = hashlib.sha256(canonical).hexdigest()
    if envelope["digest"] != expected:
        raise ValueError("client checkpoint digest mismatch")
    if set(envelope["state"]) != {"client_pid", "request", "response"}:
        raise ValueError("client checkpoint state fields are invalid")
    return envelope


def _event(sequence: int, source: str) -> HypervisorArbitrationEvent:
    """Bind one deterministic pure CPU program to a stable request identity."""

    return HypervisorArbitrationEvent(
        "client",
        CHANNEL,
        sequence,
        9800 + sequence,
        HypervisorRequest(
            CPU_OPERATION,
            CPU_RESOURCE,
            {
                "source": source,
                "initial_registers": {"request_sequence": sequence},
                "max_ticks": 12,
            },
            frozenset({"execute"}),
            frozenset(),
        ),
    )


def _open_listeners() -> tuple[socket.socket, socket.socket, dict[str, int]]:
    """Open fresh server-side TCP listeners for request and response directions."""

    request_listener = SocketTransport.listen("127.0.0.1", 0)
    response_listener = SocketTransport.listen("127.0.0.1", 0)
    request_listener.settimeout(20.0)
    response_listener.settimeout(20.0)
    return (
        request_listener,
        response_listener,
        {
            "request_port": int(request_listener.getsockname()[1]),
            "response_port": int(response_listener.getsockname()[1]),
        },
    )


def _accept_transports(
    request_listener: socket.socket,
    response_listener: socket.socket,
) -> tuple[SocketTransport, SocketTransport]:
    """Accept fresh client streams for both directions."""

    request = SocketTransport.accept(request_listener, "worker", "client")
    response = SocketTransport.accept(response_listener, "worker", "client")
    request_listener.close()
    response_listener.close()
    return request, response


def _make_session(
    request_transport: SocketTransport,
    response_transport: SocketTransport,
) -> tuple[TransitComputeSession, CountingHost]:
    """Construct an initial receiver with exact CPU authority and channel identity."""

    operating_system = HeadlessOS()
    authority_pid = operating_system.environment.kernel.spawn(
        "requester-recovery-receiver",
        capabilities=(Capability(CPU_RESOURCE, frozenset({"execute"})),),
        parent_pid=operating_system.environment.init_pid,
    )
    operating_system.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
        embedding_review_confidence=1.0,
    )
    host = CountingHost()
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=6, window_size=8)
    request = HypervisorOperationChannel(
        ReliableChannel(
            request_transport, "worker", "worker", CHANNEL, policy, peer="client"
        )
    )
    response = HypervisorOperationResultChannel(
        ReliableChannel(
            response_transport,
            "worker",
            "client",
            CHANNEL + ".result",
            policy,
            peer="client",
        ),
        "client",
        CHANNEL,
    )
    return TransitComputeSession(
        TransitComputeWorker(operating_system, authority_pid, host),
        request,
        response,
    ), host


def _serve_until(session: TransitComputeSession, timeout: float = 30.0):
    """Serve until one operation arrives while servicing response ACKs."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = session.serve_once()
        session.response.channel.process_ack()
        if result is not None:
            return result
        time.sleep(0.002)
    raise TimeoutError("receiver did not receive the next client operation")


def _connect_client(ports: dict[str, Any]):
    """Create client-side request and result channels over a fresh TCP pair."""

    request_transport = SocketTransport.connect(
        "127.0.0.1", int(ports["request_port"]), "client", "worker"
    )
    response_transport = SocketTransport.connect(
        "127.0.0.1", int(ports["response_port"]), "client", "worker"
    )
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=6, window_size=8)
    request = HypervisorOperationChannel(
        ReliableChannel(request_transport, "client", "worker", CHANNEL, policy)
    )
    response = HypervisorOperationResultChannel(
        ReliableChannel(
            response_transport,
            "client",
            "client",
            CHANNEL + ".result",
            policy,
            peer="worker",
        ),
        "client",
        CHANNEL,
    )
    return (request_transport, response_transport), request, response


def _wait_response(channel: HypervisorOperationResultChannel, timeout: float = 20.0):
    """Receive one typed operation result before the deadline."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = channel.receive()
        if result is not None:
            return result
        time.sleep(0.002)
    raise TimeoutError("client did not receive the operation response")


def _wait_request_ack(channel: ReliableChannel, expected: tuple[int, ...]) -> None:
    """Require that the exact request sequence was acknowledged after recovery."""

    acknowledged: list[int] = []
    deadline = time.monotonic() + 10.0
    while channel.pending_sequences() and time.monotonic() < deadline:
        acknowledged.extend(channel.process_ack())
        time.sleep(0.002)
    assert channel.pending_sequences() == ()
    assert tuple(acknowledged) == expected


def serve(
    server_checkpoint: Path,
    cut_marker: Path,
    release_path: Path,
    rebind_ready_path: Path,
    result_path: Path,
) -> None:
    """Keep the receiver process alive while replacing its session after client death."""

    request_listener, response_listener, ports = _open_listeners()
    print(json.dumps({"pid": os.getpid(), **ports, "phase": "initial"}), flush=True)
    request_transport, response_transport = _accept_transports(
        request_listener, response_listener
    )
    session, initial_host = _make_session(request_transport, response_transport)

    def pause_after_response(stage: str) -> None:
        if stage != "after_response_publish":
            return
        digest = session.save_checkpoint(server_checkpoint, allow_inflight=True)
        request_head = session.request.channel.peek()
        _write_json_durable(cut_marker, {
            "server_pid": os.getpid(),
            "checkpoint_digest": digest,
            "backend_calls_before_client_death": initial_host.calls,
            "fault_stage": stage,
            "request_head": None if request_head is None else request_head[0],
            "request_receive_cursor": session.request.channel.next_receive_sequence,
            "response_pending": list(session.response.channel.pending_sequences()),
            "journal_valid": session.worker.operating_system.environment.kernel.journal.verify(),
        })
        while not release_path.exists():
            time.sleep(0.01)
        raise RebindRequested()

    try:
        session.serve_once(fault_hook=pause_after_response)
    except RebindRequested:
        pass
    else:
        raise AssertionError("receiver did not reach the response-published/request-unacknowledged cut")

    request_transport.close()
    response_transport.close()

    # Rebind the live receiver process to new TCP connections using its own
    # checkpoint. Only the client interpreter has died; server PID is stable.
    request_listener, response_listener, ports = _open_listeners()
    print(json.dumps({"pid": os.getpid(), **ports, "phase": "rebind"}), flush=True)
    _write_json_durable(rebind_ready_path, {"server_pid": os.getpid(), **ports})
    request_transport, response_transport = _accept_transports(
        request_listener, response_listener
    )
    restored_hosts: list[CountingHost] = []

    def host_factory(_operating_system: HeadlessOS, _authority_pid: int) -> TransitComputeHost:
        host = CountingHost()
        restored_hosts.append(host)
        return host

    session = TransitComputeSession.from_checkpoint(
        server_checkpoint,
        request_transport,
        response_transport,
        compute_host_factory=host_factory,
    )
    assert restored_hosts and restored_hosts[0].calls == 0
    assert session.request.channel.next_receive_sequence == 1
    assert session.response.channel.pending_sequences() == (1,)
    assert session.worker.operating_system.environment.kernel.journal.verify()

    # Deliver the already-published response frame to the restarted client.
    assert session.response.channel.retransmit(1) is True

    replay = _serve_until(session)
    assert replay.executed is True and replay.replayed is True
    assert restored_hosts[0].calls == 0
    _write_json_durable(result_path, {
        "stage": "semantic-replay",
        "server_pid": os.getpid(),
        "replay": replay.replayed,
        "backend_calls_after_rebind": restored_hosts[0].calls,
        "response_pending": list(session.response.channel.pending_sequences()),
    })

    new_operation = _serve_until(session)
    assert new_operation.executed is True and new_operation.replayed is False
    assert new_operation.effect["registers"]["answer"] == 42
    assert restored_hosts[0].calls == 1

    deadline = time.monotonic() + 10.0
    while session.response.channel.pending_sequences() and time.monotonic() < deadline:
        session.response.channel.process_ack()
        time.sleep(0.002)
    assert session.response.channel.pending_sequences() == ()
    assert session.request.channel.next_receive_sequence == 3
    assert session.worker.operating_system.environment.kernel.journal.verify()
    _write_json_durable(result_path, {
        "stage": "complete",
        "server_pid": os.getpid(),
        "replayed_operation": replay.replayed,
        "backend_calls_before_client_death": initial_host.calls,
        "backend_calls_after_rebind": restored_hosts[0].calls,
        "total_backend_calls": initial_host.calls + restored_hosts[0].calls,
        "new_operation_answer": new_operation.effect["registers"]["answer"],
        "request_receive_cursor": session.request.channel.next_receive_sequence,
        "response_pending": list(session.response.channel.pending_sequences()),
        "journal_valid": session.worker.operating_system.environment.kernel.journal.verify(),
    })
    request_transport.close()
    response_transport.close()


def client_prepare(
    ports: dict[str, Any],
    client_checkpoint: Path,
    client_marker: Path,
) -> None:
    """Send a request, fsync client channel snapshots, and wait for hard termination."""

    transports, request, response = _connect_client(ports)
    event = _event(
        1,
        "set left 5\nset right 7\nadd answer left right\nhalt",
    )
    assert request.send(event) == 1
    state = {
        "client_pid": os.getpid(),
        "request": request.channel.snapshot(),
        "response": response.snapshot(),
    }
    digest = _write_client_checkpoint(client_checkpoint, state)
    _write_json_durable(client_marker, {
        "client_pid": os.getpid(),
        "checkpoint_digest": digest,
        "request_pending": list(request.channel.pending_sequences()),
        "request_next_sequence": request.channel.snapshot()["next_sequence"],
        "response_receive_cursor": response.channel.next_receive_sequence,
        "response_seen": len(response.snapshot()["seen"]),
    })
    while True:
        time.sleep(60)


def client_restore(
    ports: dict[str, Any],
    client_checkpoint: Path,
    result_path: Path,
) -> None:
    """Restore durable requester state in a fresh process, receive replay, then send new work."""

    envelope = _read_client_checkpoint(client_checkpoint)
    state = envelope["state"]
    transports, request, response = _connect_client(ports)
    # Rebuild over the newly connected transports, preserving the saved client
    # send sequence, receive cursor, delivered set, and semantic result ledger.
    request = HypervisorOperationChannel(
        ReliableChannel.from_snapshot(state["request"], transports[0])
    )
    response = HypervisorOperationResultChannel.from_snapshot(
        state["response"], transports[1]
    )
    assert request.channel.pending_sequences() == (1,)
    assert request.channel.next_sequence == 2
    assert response.channel.next_receive_sequence == 1
    assert response.snapshot()["seen"] == []

    assert request.channel.retransmit(1) is True
    first = _wait_response(response)
    second = _wait_response(response)
    assert first.effect["registers"]["answer"] == 12
    assert second.effect["registers"]["answer"] == 12
    assert first.replayed is False
    assert second.replayed is True
    assert first.fingerprint == second.fingerprint

    translation = TransitTranslationEvidence.from_dict(
        first.effect["_semantic_translation"]
    )
    oracle = TransitOracleEvidence.from_dict(first.effect["_semantic_oracle"])
    translation.validate_execution_result(first, require_oracle=True)
    assert oracle.equivalent is True
    _wait_request_ack(request.channel, (1,))
    assert response.channel.next_receive_sequence == 3

    new_event = _event(
        2,
        "set left 14\nset right 28\nadd answer left right\nhalt",
    )
    assert request.send(new_event) == 2
    new_result = _wait_response(response)
    assert new_result.effect["registers"]["answer"] == 42
    assert new_result.replayed is False
    new_translation = TransitTranslationEvidence.from_dict(
        new_result.effect["_semantic_translation"]
    )
    new_oracle = TransitOracleEvidence.from_dict(new_result.effect["_semantic_oracle"])
    new_translation.validate_execution_result(new_result, require_oracle=True)
    assert new_oracle.equivalent is True
    _wait_request_ack(request.channel, (2,))

    _write_json_durable(result_path, {
        "client_pid": os.getpid(),
        "original_client_pid": state["client_pid"],
        "received_replay_fresh": first.replayed is False,
        "received_replay_duplicate": second.replayed is True,
        "new_operation_answer": new_result.effect["registers"]["answer"],
        "new_operation_replayed": new_result.replayed,
        "request_pending": list(request.channel.pending_sequences()),
        "response_receive_cursor": response.channel.next_receive_sequence,
        "response_seen": len(response.snapshot()["seen"]),
    })
    for transport in transports:
        transport.close()


def main(arguments: list[str]) -> int:
    """Dispatch the surviving receiver or one of the requester process phases."""

    if len(arguments) != 6:
        raise SystemExit(
            "usage: requester_process_recovery_worker.py "
            "server SERVER_CHECKPOINT CUT_MARKER RELEASE REBIND_READY RESULT"
        )
    mode, first, second, third, fourth, fifth = arguments
    paths = tuple(Path(item) for item in (first, second, third, fourth, fifth))
    if mode == "server":
        serve(*paths)
        return 0
    raise SystemExit(
        "client modes are launched through the dedicated prepare/restore entrypoint"
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
