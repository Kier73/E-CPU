"""Receiver process used by the independent-client crash/restart experiment."""

from __future__ import annotations

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
    ReliabilityPolicy,
    ReliableChannel,
    SocketTransport,
    TransitComputeHost,
    TransitComputeSession,
    TransitComputeWorker,
)

CHANNEL = "receiver-only-recovery"
CPU_RESOURCE = "/cpu/compute"


class CountingHost(TransitComputeHost):
    """Count real backend entries without counting execution-ledger replays."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def handle(self, event: HypervisorArbitrationEvent) -> dict[str, object]:
        self.calls += 1
        return super().handle(event)


def write_json_durable(path: Path, value: dict[str, Any]) -> None:
    """Publish one marker only after its complete JSON contents have been fsynced."""

    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def make_session(
    request_transport: SocketTransport,
    response_transport: SocketTransport,
) -> tuple[TransitComputeSession, CountingHost]:
    """Create a receiver with CPU authority and the exact worker channel identities."""

    operating_system = HeadlessOS()
    authority_pid = operating_system.environment.kernel.spawn(
        "receiver-only-process",
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
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=5, window_size=8)
    request = HypervisorOperationChannel(
        ReliableChannel(
            request_transport,
            "worker",
            "worker",
            CHANNEL,
            policy,
            peer="client",
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


def open_server_sockets() -> tuple[socket.socket, socket.socket, int, int]:
    """Open two independent TCP listeners and return their ephemeral ports."""

    request_listener = SocketTransport.listen("127.0.0.1", 0)
    response_listener = SocketTransport.listen("127.0.0.1", 0)
    request_listener.settimeout(20.0)
    response_listener.settimeout(20.0)
    return (
        request_listener,
        response_listener,
        int(request_listener.getsockname()[1]),
        int(response_listener.getsockname()[1]),
    )


def accept_worker_transports(
    request_listener: socket.socket,
    response_listener: socket.socket,
) -> tuple[SocketTransport, SocketTransport]:
    """Accept a fresh requester connection in each direction."""

    request_transport = SocketTransport.accept(
        request_listener, "worker", "client"
    )
    response_transport = SocketTransport.accept(
        response_listener, "worker", "client"
    )
    request_listener.close()
    response_listener.close()
    return request_transport, response_transport


def serve_next(session: TransitComputeSession, timeout: float = 30.0):
    """Serve exactly one operation, polling only until the bounded deadline."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = session.serve_once()
        if result is not None:
            return result
        time.sleep(0.002)
    raise TimeoutError("receiver did not receive the next requester operation")


def prepare(checkpoint_path: Path, marker_path: Path) -> None:
    """Commit a CPU effect, save receiver-only state, and hold before response/ACK."""

    request_listener, response_listener, request_port, response_port = open_server_sockets()
    print(json.dumps({
        "pid": os.getpid(),
        "request_port": request_port,
        "response_port": response_port,
        "mode": "prepare",
    }, sort_keys=True), flush=True)
    request_transport, response_transport = accept_worker_transports(
        request_listener, response_listener
    )
    session, host = make_session(request_transport, response_transport)

    def pause_after_commit(stage: str) -> None:
        if stage != "after_execution_commit":
            return
        digest = session.save_checkpoint(checkpoint_path, allow_inflight=True)
        request_head = session.request.channel.peek()
        write_json_durable(marker_path, {
            "pid": os.getpid(),
            "checkpoint_digest": digest,
            "backend_calls_before_kill": host.calls,
            "session_phase": session.phase,
            "worker_request_head": None if request_head is None else request_head[0],
            "request_receive_cursor": session.request.channel.next_receive_sequence,
            "response_pending": list(session.response.channel.pending_sequences()),
            "journal_valid": session.worker.operating_system.environment.kernel.journal.verify(),
        })
        while True:
            time.sleep(60)

    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        result = session.serve_once(fault_hook=pause_after_commit)
        if result is not None:
            raise AssertionError("worker returned past the selected commit-before-publish cut")
        time.sleep(0.002)
    raise TimeoutError("prepare worker did not receive the operation before the deadline")


def restore_and_continue(checkpoint_path: Path, result_path: Path) -> None:
    """Restore only the receiver, replay the surviving client's request, then accept new work."""

    request_listener, response_listener, request_port, response_port = open_server_sockets()
    print(json.dumps({
        "pid": os.getpid(),
        "request_port": request_port,
        "response_port": response_port,
        "mode": "restore",
    }, sort_keys=True), flush=True)
    request_transport, response_transport = accept_worker_transports(
        request_listener, response_listener
    )

    hosts: list[CountingHost] = []

    def host_factory(_operating_system: HeadlessOS, _authority_pid: int) -> TransitComputeHost:
        host = CountingHost()
        hosts.append(host)
        return host

    session = TransitComputeSession.from_checkpoint(
        checkpoint_path,
        request_transport,
        response_transport,
        compute_host_factory=host_factory,
    )
    assert session.phase == "idle"
    assert hosts and hosts[0].calls == 0
    write_json_durable(result_path, {
        "stage": "restored",
        "pid": os.getpid(),
        "session_phase": session.phase,
        "request_receive_cursor": session.request.channel.next_receive_sequence,
    })

    replay = serve_next(session)
    assert replay.executed is True and replay.replayed is True
    assert hosts[0].calls == 0
    write_json_durable(result_path, {
        "stage": "replayed",
        "pid": os.getpid(),
        "replayed": replay.replayed,
        "backend_calls": hosts[0].calls,
    })

    deadline = time.monotonic() + 10.0
    while session.response.channel.pending_sequences() and time.monotonic() < deadline:
        session.response.channel.process_ack()
        time.sleep(0.002)
    assert session.response.channel.pending_sequences() == ()

    write_json_durable(result_path, {
        "stage": "waiting-for-new-request",
        "pid": os.getpid(),
        "request_receive_cursor": session.request.channel.next_receive_sequence,
        "response_pending": list(session.response.channel.pending_sequences()),
    })
    new_operation = serve_next(session)
    assert new_operation.executed is True and new_operation.replayed is False
    assert new_operation.effect["registers"]["answer"] == 42
    assert hosts[0].calls == 1
    deadline = time.monotonic() + 10.0
    while session.response.channel.pending_sequences() and time.monotonic() < deadline:
        session.response.channel.process_ack()
        time.sleep(0.002)
    assert session.response.channel.pending_sequences() == ()
    assert session.worker.operating_system.environment.kernel.journal.verify()
    write_json_durable(result_path, {
        "pid": os.getpid(),
        "replayed_operation": replay.replayed,
        "replay_backend_calls": 0,
        "new_operation_replayed": new_operation.replayed,
        "new_operation_answer": new_operation.effect["registers"]["answer"],
        "backend_calls_after_restart": hosts[0].calls,
        "request_receive_cursor": session.request.channel.next_receive_sequence,
        "response_receive_cursor": session.response.channel.next_receive_sequence,
        "journal_valid": session.worker.operating_system.environment.kernel.journal.verify(),
    })
    request_transport.close()
    response_transport.close()


def main(arguments: list[str]) -> int:
    """Dispatch the supervised prepare or fresh-interpreter restore phase."""

    if len(arguments) != 3:
        raise SystemExit("usage: receiver_only_worker.py prepare|restore CHECKPOINT OUTPUT")
    mode, checkpoint_text, output_text = arguments
    checkpoint_path = Path(checkpoint_text)
    output_path = Path(output_text)
    if mode == "prepare":
        prepare(checkpoint_path, output_path)
        return 0
    if mode == "restore":
        restore_and_continue(checkpoint_path, output_path)
        return 0
    raise SystemExit(f"unknown worker mode: {mode}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
