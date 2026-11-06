"""Independent requester and receiver workers for process-level Transit crash cuts."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mailcpu import (  # noqa: E402
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
    ReliableChannel,
    TransitComputeSession,
)
from requester_process_recovery_worker import (  # noqa: E402
    CHANNEL,
    CountingHost,
    _accept_transports,
    _connect_client,
    _event,
    _make_session,
    _open_listeners,
    _read_client_checkpoint,
    _wait_request_ack,
    _wait_response,
    _write_client_checkpoint,
    _write_json_durable,
)

CUTS = frozenset({
    "before_execution",
    "after_execution_commit",
    "after_response_publish",
    "after_request_ack",
})


def _serve_until(session: TransitComputeSession, timeout: float = 30.0):
    """Wait for one accepted operation transition without advancing host time."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = session.serve_once()
        if result is not None:
            return result
        time.sleep(0.002)
    raise TimeoutError("Transit receiver did not serve the expected operation")


def _host_factory(hosts: list[CountingHost]):
    """Build an instrumented replacement backend without restoring predecessor memory."""

    def create(_operating_system: Any, _authority_pid: int) -> CountingHost:
        host = CountingHost()
        hosts.append(host)
        return host

    return create


def server_cut(cut: str, checkpoint: Path, marker: Path) -> None:
    """Persist the receiver at one selected protocol boundary and await hard process death."""

    if cut not in CUTS:
        raise ValueError(f"unsupported Transit crash cut: {cut}")

    request_listener, response_listener, ports = _open_listeners()
    print(json.dumps({"pid": __import__("os").getpid(), **ports, "phase": "initial"}), flush=True)
    request_transport, response_transport = _accept_transports(
        request_listener, response_listener
    )
    session, host = _make_session(request_transport, response_transport)

    def stop_at_cut(stage: str) -> None:
        if stage != cut:
            return
        digest = session.save_checkpoint(checkpoint, allow_inflight=True)
        request_head = session.request.channel.peek()
        _write_json_durable(marker, {
            "server_pid": __import__("os").getpid(),
            "checkpoint_digest": digest,
            "fault_stage": stage,
            "backend_calls_before_death": host.calls,
            "request_head": None if request_head is None else request_head[0],
            "request_receive_cursor": session.request.channel.next_receive_sequence,
            "response_pending": list(session.response.channel.pending_sequences()),
            "journal_valid": session.worker.operating_system.environment.kernel.journal.verify(),
        })
        while True:
            time.sleep(60)

    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        result = session.serve_once(fault_hook=stop_at_cut)
        if result is not None:
            raise AssertionError(f"receiver crossed crash cut {cut!r} without stopping")
        time.sleep(0.002)
    raise TimeoutError(f"receiver did not reach Transit crash cut {cut!r}")


def server_restore(cut: str, checkpoint: Path, result_path: Path) -> None:
    """Restore an independent receiver checkpoint, replay sequence 1, then execute sequence 2."""

    if cut not in CUTS:
        raise ValueError(f"unsupported Transit crash cut: {cut}")

    request_listener, response_listener, ports = _open_listeners()
    print(json.dumps({"pid": __import__("os").getpid(), **ports, "phase": "restored"}), flush=True)
    request_transport, response_transport = _accept_transports(
        request_listener, response_listener
    )

    hosts: list[CountingHost] = []
    session = TransitComputeSession.from_checkpoint(
        checkpoint,
        request_transport,
        response_transport,
        compute_host_factory=_host_factory(hosts),
    )
    assert hosts and hosts[0].calls == 0
    assert session.worker.operating_system.environment.kernel.journal.verify()

    expected_cursor = 2 if cut == "after_request_ack" else 1
    assert session.request.channel.next_receive_sequence == expected_cursor

    expected_pending_response = (1,) if cut in {
        "after_response_publish",
        "after_request_ack",
    } else ()
    assert session.response.channel.pending_sequences() == expected_pending_response

    # A published but unacknowledged response belongs to the receiver's saved
    # reliable sender window. Restore must retransmit that exact frame before
    # the newly replayed request can produce another transport frame.
    for sequence in session.response.channel.pending_sequences():
        assert session.response.channel.retransmit(sequence) is True

    recovered = _serve_until(session)
    expected_execution_replay = cut != "before_execution"
    assert recovered.replayed is expected_execution_replay
    assert recovered.effect["registers"]["answer"] == 12
    expected_restored_calls = 1 if cut == "before_execution" else 0
    assert hosts[0].calls == expected_restored_calls

    fresh = _serve_until(session)
    assert fresh.replayed is False
    assert fresh.effect["registers"]["answer"] == 42
    assert hosts[0].calls == expected_restored_calls + 1

    deadline = time.monotonic() + 20.0
    while session.response.channel.pending_sequences() and time.monotonic() < deadline:
        session.response.channel.process_ack()
        time.sleep(0.002)
    assert session.response.channel.pending_sequences() == ()
    assert session.request.channel.next_receive_sequence == 3
    assert session.worker.operating_system.environment.kernel.journal.verify()

    _write_json_durable(result_path, {
        "server_pid": __import__("os").getpid(),
        "cut": cut,
        "request_receive_cursor": session.request.channel.next_receive_sequence,
        "sequence_1_execution_replayed": recovered.replayed,
        "sequence_1_answer": recovered.effect["registers"]["answer"],
        "sequence_2_execution_replayed": fresh.replayed,
        "sequence_2_answer": fresh.effect["registers"]["answer"],
        "backend_calls_after_restore": hosts[0].calls,
        "response_pending": list(session.response.channel.pending_sequences()),
        "journal_valid": session.worker.operating_system.environment.kernel.journal.verify(),
    })
    request_transport.close()
    response_transport.close()


def client_prepare(checkpoint: Path, marker: Path, request_port: int, response_port: int) -> None:
    """Send sequence 1 and durably retain requester state before any result is consumed."""

    ports = {"request_port": request_port, "response_port": response_port}
    transports, request, response = _connect_client(ports)
    assert request.send(_event(
        1, "set left 5\nset right 7\nadd answer left right\nhalt"
    )) == 1
    state = {
        "client_pid": __import__("os").getpid(),
        "request": request.channel.snapshot(),
        "response": response.snapshot(),
    }
    digest = _write_client_checkpoint(checkpoint, state)
    _write_json_durable(marker, {
        "client_pid": __import__("os").getpid(),
        "checkpoint_digest": digest,
        "request_pending": list(request.channel.pending_sequences()),
        "request_next_sequence": request.channel.snapshot()["next_sequence"],
        "response_receive_cursor": response.channel.next_receive_sequence,
        "response_seen": len(response.snapshot()["seen"]),
    })
    while True:
        time.sleep(60)


def client_restore(
    checkpoint: Path,
    result_path: Path,
    request_port: int,
    response_port: int,
    cut: str,
) -> None:
    """Restore the requester, consume the expected old result copies, and submit fresh work."""

    ports = {"request_port": request_port, "response_port": response_port}
    envelope = _read_client_checkpoint(checkpoint)
    state = envelope["state"]
    transports, request, response = _connect_client(ports)
    request = HypervisorOperationChannel(
        ReliableChannel.from_snapshot(state["request"], transports[0])
    )
    response = HypervisorOperationResultChannel.from_snapshot(
        state["response"], transports[1]
    )

    assert request.channel.pending_sequences() == (1,)
    assert response.channel.next_receive_sequence == 1
    assert response.snapshot()["seen"] == []
    assert request.channel.retransmit(1) is True

    response_count = 2 if cut in {
        "after_response_publish",
        "after_request_ack",
    } else 1
    recovered_results = [_wait_response(response) for _ in range(response_count)]
    assert all(item.sequence == 1 for item in recovered_results)
    assert all(item.effect["registers"]["answer"] == 12 for item in recovered_results)

    # The requester marks the first observed semantic result as fresh even
    # when the receiver reconstructed it from its execution ledger. A second
    # transport frame for the same semantic operation is a client duplicate.
    assert recovered_results[0].replayed is False
    if response_count == 2:
        assert recovered_results[1].replayed is True

    _wait_request_ack(request.channel, (1,))

    assert request.send(_event(
        2, "set left 14\nset right 28\nadd answer left right\nhalt"
    )) == 2
    fresh = _wait_response(response)
    assert fresh.sequence == 2
    assert fresh.effect["registers"]["answer"] == 42
    assert fresh.replayed is False
    _wait_request_ack(request.channel, (2,))

    assert response.channel.next_receive_sequence == 2 + response_count
    assert request.channel.pending_sequences() == ()
    assert len(response.snapshot()["seen"]) == 2

    _write_json_durable(result_path, {
        "client_pid": __import__("os").getpid(),
        "origin_client_pid": state["client_pid"],
        "cut": cut,
        "sequence_1_delivery_count": response_count,
        "sequence_1_first_delivery_fresh": recovered_results[0].replayed is False,
        "sequence_1_second_delivery_duplicate": (
            recovered_results[1].replayed if response_count == 2 else None
        ),
        "sequence_2_answer": fresh.effect["registers"]["answer"],
        "sequence_2_fresh": fresh.replayed is False,
        "request_pending": list(request.channel.pending_sequences()),
        "response_receive_cursor": response.channel.next_receive_sequence,
        "semantic_results_seen": len(response.snapshot()["seen"]),
    })
    for transport in transports:
        transport.close()


def main(arguments: list[str]) -> int:
    mode = arguments[0]
    if mode == "server-cut":
        if len(arguments) != 4:
            raise ValueError("server-cut requires cut, checkpoint, and marker paths")
        server_cut(arguments[1], Path(arguments[2]), Path(arguments[3]))
    elif mode == "server-restore":
        if len(arguments) != 4:
            raise ValueError("server-restore requires cut, checkpoint, and result paths")
        server_restore(arguments[1], Path(arguments[2]), Path(arguments[3]))
    elif mode == "client-prepare":
        if len(arguments) != 5:
            raise ValueError("client-prepare requires checkpoint, marker, and two ports")
        client_prepare(
            Path(arguments[1]), Path(arguments[2]), int(arguments[3]), int(arguments[4])
        )
    elif mode == "client-restore":
        if len(arguments) != 6:
            raise ValueError("client-restore requires checkpoint, result, two ports, and cut")
        client_restore(
            Path(arguments[1]), Path(arguments[2]), int(arguments[3]), int(arguments[4]), arguments[5]
        )
    else:
        raise ValueError(f"unknown worker mode: {mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
