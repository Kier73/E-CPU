"""Repeated hard-kill recovery of one committed Transit operation."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from requester_process_recovery_worker import (
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

from mailcpu import (
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
    ReliableChannel,
    TransitComputeSession,
)


def _serve_until(session: TransitComputeSession, timeout: float = 30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = session.serve_once()
        if result is not None:
            return result
        time.sleep(0.002)
    raise TimeoutError("Transit receiver did not serve the pending operation")


def _host_factory(hosts: list[CountingHost]):
    def create(_operating_system: Any, _authority_pid: int) -> CountingHost:
        host = CountingHost()
        hosts.append(host)
        return host
    return create


def _publish_commit_cut(
    session: TransitComputeSession,
    host: CountingHost,
    checkpoint: Path,
    marker: Path,
    *,
    phase: str,
) -> None:
    digest = session.save_checkpoint(checkpoint, allow_inflight=True)
    request_head = session.request.channel.peek()
    _write_json_durable(marker, {
        "phase": phase,
        "server_pid": __import__("os").getpid(),
        "checkpoint_digest": digest,
        "fault_stage": "after_execution_commit",
        "backend_calls": host.calls,
        "request_head": None if request_head is None else request_head[0],
        "request_receive_cursor": session.request.channel.next_receive_sequence,
        "response_pending": list(session.response.channel.pending_sequences()),
        "journal_valid": session.worker.operating_system.environment.kernel.journal.verify(),
    })
    # The supervisor must hard-kill this interpreter. No Python cleanup path
    # is allowed to publish the response or consume the request.
    while True:
        time.sleep(60)


def server_cut(mode: str, checkpoint: Path, marker: Path) -> None:
    request_listener, response_listener, ports = _open_listeners()
    print(json.dumps({"pid": __import__("os").getpid(), **ports, "phase": mode}), flush=True)
    request_transport, response_transport = _accept_transports(
        request_listener, response_listener
    )
    if mode == "initial":
        session, host = _make_session(request_transport, response_transport)
    elif mode == "restored":
        hosts: list[CountingHost] = []
        session = TransitComputeSession.from_checkpoint(
            checkpoint,
            request_transport,
            response_transport,
            compute_host_factory=_host_factory(hosts),
        )
        assert hosts and hosts[0].calls == 0
        host = hosts[0]
    else:
        raise ValueError(f"unsupported cut mode: {mode}")

    def stop_after_commit(stage: str) -> None:
        if stage == "after_execution_commit":
            _publish_commit_cut(
                session, host, checkpoint, marker, phase=mode
            )

    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        result = session.serve_once(fault_hook=stop_after_commit)
        if result is not None:
            raise AssertionError("receiver crossed the selected commit-before-publish cut")
        time.sleep(0.002)
    raise TimeoutError("receiver did not reach the selected commit-before-publish cut")


def server_complete(checkpoint: Path, result_path: Path) -> None:
    request_listener, response_listener, ports = _open_listeners()
    print(json.dumps({"pid": __import__("os").getpid(), **ports, "phase": "final"}), flush=True)
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

    # Sequence 1 has already committed in the first process generation.
    # Two successive restores must therefore replay it without backend entry.
    replay = _serve_until(session)
    assert replay.replayed is True
    assert replay.effect["registers"]["answer"] == 12
    calls_after_replay = hosts[0].calls
    assert calls_after_replay == 0

    # A new operation proves the recovered path remains live, not replay-only.
    fresh = _serve_until(session)
    assert fresh.replayed is False
    assert fresh.effect["registers"]["answer"] == 42
    assert hosts[0].calls == 1

    deadline = time.monotonic() + 20.0
    while session.response.channel.pending_sequences() and time.monotonic() < deadline:
        session.response.channel.process_ack()
        time.sleep(0.002)
    assert session.response.channel.pending_sequences() == ()
    assert session.request.channel.next_receive_sequence == 3
    assert session.worker.operating_system.environment.kernel.journal.verify()

    _write_json_durable(result_path, {
        "server_pid": __import__("os").getpid(),
        "sequence_1_replayed": replay.replayed,
        "sequence_1_answer": replay.effect["registers"]["answer"],
        "backend_calls_after_sequence_1_replay": calls_after_replay,
        "sequence_2_replayed": fresh.replayed,
        "sequence_2_answer": fresh.effect["registers"]["answer"],
        "backend_calls_after_restore": hosts[0].calls,
        "request_receive_cursor": session.request.channel.next_receive_sequence,
        "response_pending": list(session.response.channel.pending_sequences()),
        "journal_valid": session.worker.operating_system.environment.kernel.journal.verify(),
    })
    request_transport.close()
    response_transport.close()


def _restore_client_state(
    ports: dict[str, Any],
    checkpoint: Path,
):
    envelope = _read_client_checkpoint(checkpoint)
    state = envelope["state"]
    transports, request, response = _connect_client(ports)
    request = HypervisorOperationChannel(
        ReliableChannel.from_snapshot(state["request"], transports[0])
    )
    response = HypervisorOperationResultChannel.from_snapshot(
        state["response"], transports[1]
    )
    return transports, state, request, response


def client_prepare_initial(
    ports: dict[str, Any],
    checkpoint: Path,
    marker: Path,
) -> None:
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
        "response_receive_cursor": response.channel.next_receive_sequence,
    })
    while True:
        time.sleep(60)


def client_prepare_restored(
    ports: dict[str, Any],
    checkpoint: Path,
    marker: Path,
) -> None:
    transports, state, request, response = _restore_client_state(ports, checkpoint)
    assert request.channel.pending_sequences() == (1,)
    assert request.channel.retransmit(1) is True
    updated = {
        "client_pid": state["client_pid"],
        "request": request.channel.snapshot(),
        "response": response.snapshot(),
    }
    digest = _write_client_checkpoint(checkpoint, updated)
    _write_json_durable(marker, {
        "client_pid": __import__("os").getpid(),
        "origin_client_pid": state["client_pid"],
        "checkpoint_digest": digest,
        "request_pending": list(request.channel.pending_sequences()),
        "response_receive_cursor": response.channel.next_receive_sequence,
    })
    while True:
        time.sleep(60)


def client_complete(
    ports: dict[str, Any],
    checkpoint: Path,
    result_path: Path,
) -> None:
    transports, state, request, response = _restore_client_state(ports, checkpoint)
    assert request.channel.pending_sequences() == (1,)
    assert request.channel.retransmit(1) is True

    recovered = _wait_response(response)
    assert recovered.effect["registers"]["answer"] == 12
    # The first response after both commit-before-publish crashes is emitted
    # by the execution ledger's replay, not by another backend invocation.
    assert recovered.replayed is False
    _wait_request_ack(request.channel, (1,))

    assert request.send(_event(
        2, "set left 14\nset right 28\nadd answer left right\nhalt"
    )) == 2
    fresh = _wait_response(response)
    assert fresh.effect["registers"]["answer"] == 42
    assert fresh.replayed is False
    _wait_request_ack(request.channel, (2,))

    assert request.channel.pending_sequences() == ()
    assert response.channel.next_receive_sequence == 3
    assert len(response.snapshot()["seen"]) == 2
    _write_json_durable(result_path, {
        "client_pid": __import__("os").getpid(),
        "origin_client_pid": state["client_pid"],
        "sequence_1_answer": recovered.effect["registers"]["answer"],
        "sequence_1_first_delivery": recovered.replayed is False,
        "sequence_1_semantic_duplicate": recovered.replayed,
        "sequence_2_answer": fresh.effect["registers"]["answer"],
        "sequence_2_replayed": fresh.replayed,
        "request_pending": list(request.channel.pending_sequences()),
        "response_receive_cursor": response.channel.next_receive_sequence,
        "response_seen": len(response.snapshot()["seen"]),
    })
    for transport in transports:
        transport.close()


def main(arguments: list[str]) -> int:
    mode = arguments[0]
    if mode in {"server-initial", "server-restored"}:
        if len(arguments) != 3:
            raise ValueError("server cut mode requires checkpoint and marker paths")
        server_cut(
            "initial" if mode == "server-initial" else "restored",
            Path(arguments[1]),
            Path(arguments[2]),
        )
    elif mode == "server-final":
        if len(arguments) != 3:
            raise ValueError("server-final requires checkpoint and result paths")
        server_complete(Path(arguments[1]), Path(arguments[2]))
    elif mode in {"client-initial", "client-restored"}:
        if len(arguments) != 5:
            raise ValueError("client mode requires ports, checkpoint, and marker paths")
        ports = {
            "request_port": int(arguments[1]),
            "response_port": int(arguments[2]),
        }
        if mode == "client-initial":
            client_prepare_initial(ports, Path(arguments[3]), Path(arguments[4]))
        else:
            client_prepare_restored(ports, Path(arguments[3]), Path(arguments[4]))
    elif mode == "client-final":
        if len(arguments) != 5:
            raise ValueError("client-final requires ports, checkpoint, and result paths")
        ports = {
            "request_port": int(arguments[1]),
            "response_port": int(arguments[2]),
        }
        client_complete(ports, Path(arguments[3]), Path(arguments[4]))
    else:
        raise ValueError(f"unknown worker mode: {mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
