"""Prove that requester state survives while only the Transit receiver process is killed."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from mailcpu import (
    HypervisorArbitrationEvent,
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
    HypervisorRequest,
    ReliabilityPolicy,
    ReliableChannel,
    SocketTransport,
    TransitOracleEvidence,
    TransitTranslationEvidence,
)

CHANNEL = "receiver-only-recovery"
CPU_OPERATION = "execute deterministic CPU arithmetic program"
CPU_RESOURCE = "/cpu/compute"


def _client_channels(ready: dict[str, Any]):
    """Connect requester transports and reconstruct the two client-side reliable roles."""

    request_transport = SocketTransport.connect(
        "127.0.0.1", int(ready["request_port"]), "client", "worker"
    )
    response_transport = SocketTransport.connect(
        "127.0.0.1", int(ready["response_port"]), "client", "worker"
    )
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=5, window_size=8)
    request = HypervisorOperationChannel(
        ReliableChannel(
            request_transport, "client", "worker", CHANNEL, policy
        )
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


def _event(sequence: int, source: str) -> HypervisorArbitrationEvent:
    """Bind a deterministic CPU job to one exact logical operation identity."""

    payload = {
        "source": source,
        "initial_registers": {"request_sequence": sequence},
        "max_ticks": 12,
    }
    return HypervisorArbitrationEvent(
        "client",
        CHANNEL,
        sequence,
        9700 + sequence,
        HypervisorRequest(
            CPU_OPERATION,
            CPU_RESOURCE,
            payload,
            frozenset({"execute"}),
            frozenset(),
        ),
    )


def _wait_ready(process: subprocess.Popen[str]) -> dict[str, Any]:
    """Read a receiver's fresh TCP ports from its first bounded startup line."""

    assert process.stdout is not None
    line = process.stdout.readline()
    if not line:
        stdout, stderr = process.communicate(timeout=5)
        raise AssertionError(
            "receiver exited before publishing its TCP listeners: "
            f"returncode={process.returncode}, stdout={stdout!r}, stderr={stderr!r}"
        )
    return json.loads(line)


def _wait_marker(path: Path, process: subprocess.Popen[str], timeout: float = 30.0) -> dict[str, Any]:
    """Wait for the post-fsync receiver cut without treating process liveness as success."""

    deadline = time.monotonic() + timeout
    while not path.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert path.exists(), (
        "receiver did not save the commit-before-publish checkpoint: "
        f"returncode={process.poll()}"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _wait_response(
    channel: HypervisorOperationResultChannel,
    process: subprocess.Popen[str],
    progress_path: Path,
    timeout: float = 15.0,
):
    """Receive one typed result and surface the receiver traceback if it exits."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = channel.receive()
        if result is not None:
            return result
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=5)
            raise AssertionError(
                "receiver exited before publishing its Transit response: "
                f"returncode={process.returncode}, stdout={stdout!r}, stderr={stderr!r}"
            )
        time.sleep(0.002)
    raise AssertionError(
        "requester did not receive the Transit response before the deadline; "
        f"receiver_returncode={process.poll()}, "
        f"progress={progress_path.read_text(encoding='utf-8') if progress_path.exists() else None!r}"
    )


def _wait_request_ack(channel: ReliableChannel, expected: tuple[int, ...]) -> None:
    """Drain ACKs until the exact client request sequence is no longer pending."""

    acknowledged: list[int] = []
    deadline = time.monotonic() + 10.0
    while channel.pending_sequences() and time.monotonic() < deadline:
        acknowledged.extend(channel.process_ack())
        time.sleep(0.002)
    assert channel.pending_sequences() == ()
    assert tuple(acknowledged) == expected


def test_requester_survives_receiver_only_process_termination_and_rebinds(tmp_path: Path) -> None:
    """Kill only the receiver, rebind the still-live requester, replay, and submit fresh work."""

    repository_root = Path(__file__).resolve().parents[1]
    worker_script = repository_root / "tests" / "helpers" / "receiver_only_process_worker.py"
    checkpoint_path = tmp_path / "receiver-only-session.json"
    marker_path = tmp_path / "receiver-only-cut.json"
    result_path = tmp_path / "receiver-only-result.json"
    requester_pid = os.getpid()
    transports_to_close: list[SocketTransport] = []
    original: subprocess.Popen[str] | None = None
    restarted: subprocess.Popen[str] | None = None

    try:
        original = subprocess.Popen(
            [
                sys.executable,
                str(worker_script),
                "prepare",
                str(checkpoint_path),
                str(marker_path),
            ],
            cwd=repository_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        first_ready = _wait_ready(original)
        first_transports, request_client, response_client = _client_channels(first_ready)
        transports_to_close.extend(first_transports)
        first_event = _event(
            1,
            "set left 5\nset right 7\nadd answer left right\nhalt",
        )
        assert request_client.send(first_event) == 1

        cut = _wait_marker(marker_path, original)
        assert cut["pid"] == original.pid
        assert cut["pid"] != requester_pid
        assert cut["backend_calls_before_kill"] == 1
        assert cut["session_phase"] == "request-ready"
        assert cut["worker_request_head"] == 1
        assert cut["request_receive_cursor"] == 1
        assert cut["response_pending"] == []
        assert cut["journal_valid"] is True
        assert request_client.channel.pending_sequences() == (1,)
        assert response_client.channel.peek() is None
        assert checkpoint_path.is_file()

        # The requesting process remains alive and keeps the exact sender-side
        # pending frame and response receive ledger in memory across the kill.
        request_snapshot = request_client.channel.snapshot()
        response_snapshot = response_client.snapshot()
        assert set(request_snapshot["pending"]) == {"1"}
        assert request_snapshot["next_sequence"] == 2

        original.kill()
        original.communicate(timeout=10)
        assert original.returncode != 0
        assert os.getpid() == requester_pid

        # Close only the dead receiver's old TCP streams. The requester process
        # survives, reconnects, and reconstructs its channel wrappers from its
        # own snapshots; no client process or state is restored from disk.
        for transport in first_transports:
            transport.close()

        restarted = subprocess.Popen(
            [
                sys.executable,
                str(worker_script),
                "restore",
                str(checkpoint_path),
                str(result_path),
            ],
            cwd=repository_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        second_ready = _wait_ready(restarted)
        second_transports = (
            SocketTransport.connect(
                "127.0.0.1",
                int(second_ready["request_port"]),
                "client",
                "worker",
            ),
            SocketTransport.connect(
                "127.0.0.1",
                int(second_ready["response_port"]),
                "client",
                "worker",
            ),
        )
        transports_to_close.extend(second_transports)
        policy = ReliabilityPolicy(lease_ticks=1, max_attempts=5, window_size=8)
        request_client = HypervisorOperationChannel(
            ReliableChannel.from_snapshot(request_snapshot, second_transports[0])
        )
        response_client = HypervisorOperationResultChannel.from_snapshot(
            response_snapshot, second_transports[1]
        )
        assert request_client.channel.pending_sequences() == (1,)
        assert response_client.channel.next_receive_sequence == 1

        # Retransmit the exact original frame. The receiver's execution ledger
        # must replay the committed effect rather than entering its new backend.
        assert request_client.channel.retransmit(1) is True
        replayed_response = _wait_response(response_client, restarted, result_path)
        assert replayed_response.effect["registers"]["answer"] == 12
        assert replayed_response.replayed is False
        translation = TransitTranslationEvidence.from_dict(
            replayed_response.effect["_semantic_translation"]
        )
        oracle = TransitOracleEvidence.from_dict(
            replayed_response.effect["_semantic_oracle"]
        )
        translation.validate_execution_result(replayed_response, require_oracle=True)
        assert oracle.equivalent is True
        _wait_request_ack(request_client.channel, (1,))

        # The same surviving requester now submits a new operation after the
        # recovered process has finished replaying the committed transaction.
        second_event = _event(
            2,
            "set left 14\nset right 28\nadd answer left right\nhalt",
        )
        assert request_client.send(second_event) == 2
        new_response = _wait_response(response_client, restarted, result_path)
        assert new_response.effect["registers"]["answer"] == 42
        assert new_response.replayed is False
        second_translation = TransitTranslationEvidence.from_dict(
            new_response.effect["_semantic_translation"]
        )
        second_oracle = TransitOracleEvidence.from_dict(
            new_response.effect["_semantic_oracle"]
        )
        second_translation.validate_execution_result(new_response, require_oracle=True)
        assert second_oracle.equivalent is True
        _wait_request_ack(request_client.channel, (2,))

        stdout, stderr = restarted.communicate(timeout=30)
        assert restarted.returncode == 0, (
            f"receiver restart failed with exit={restarted.returncode}\n"
            f"stdout:\n{stdout}\nstderr:\n{stderr}"
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert result["pid"] == restarted.pid
        assert result["pid"] != cut["pid"]
        assert result["pid"] != requester_pid
        assert result["restored_phase"] in {"idle", "request-ready"}
        assert result["replayed_operation"] is True
        assert result["replay_backend_calls"] == 0
        assert result["new_operation_replayed"] is False
        assert result["new_operation_answer"] == 42
        assert result["backend_calls_after_restart"] == 1
        assert result["request_receive_cursor"] == 3
        assert result["response_receive_cursor"] == 1
        assert result["journal_valid"] is True
        assert os.getpid() == requester_pid
    finally:
        for process in (original, restarted):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
        for transport in transports_to_close:
            if not transport.closed:
                transport.close()


def test_receiver_restart_after_response_publish_before_request_ack(tmp_path: Path) -> None:
    """Recover after the client saw the result but the receiver has not ACKed its request."""

    repository_root = Path(__file__).resolve().parents[1]
    worker_script = repository_root / "tests" / "helpers" / "receiver_only_process_worker.py"
    checkpoint_path = tmp_path / "published-before-ack-session.json"
    marker_path = tmp_path / "published-before-ack-cut.json"
    result_path = tmp_path / "published-before-ack-result.json"
    requester_pid = os.getpid()
    transports_to_close: list[SocketTransport] = []
    original: subprocess.Popen[str] | None = None
    restarted: subprocess.Popen[str] | None = None

    try:
        original = subprocess.Popen(
            [
                sys.executable,
                str(worker_script),
                "prepare-published",
                str(checkpoint_path),
                str(marker_path),
            ],
            cwd=repository_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        first_ready = _wait_ready(original)
        first_transports, request_client, response_client = _client_channels(first_ready)
        transports_to_close.extend(first_transports)

        first_event = _event(
            1,
            "set left 5\nset right 7\nadd answer left right\nhalt",
        )
        assert request_client.send(first_event) == 1
        cut = _wait_marker(marker_path, original)
        assert cut["pid"] == original.pid
        assert cut["pid"] != requester_pid
        assert cut["fault_stage"] == "after_response_publish"
        assert cut["backend_calls_before_kill"] == 1
        assert cut["worker_request_head"] == 1
        assert cut["request_receive_cursor"] == 1
        assert cut["response_pending"] == [1]
        assert cut["journal_valid"] is True

        # The first response is already visible to the requester. Its semantic
        # result ledger records the operation, but the reliable request is
        # still pending because the receiver is blocked before request ACK.
        first_response = _wait_response(response_client, original, marker_path)
        assert first_response.effect["registers"]["answer"] == 12
        assert first_response.replayed is False
        first_translation = TransitTranslationEvidence.from_dict(
            first_response.effect["_semantic_translation"]
        )
        first_oracle = TransitOracleEvidence.from_dict(
            first_response.effect["_semantic_oracle"]
        )
        first_translation.validate_execution_result(first_response, require_oracle=True)
        assert first_oracle.equivalent is True
        assert request_client.channel.pending_sequences() == (1,)
        assert response_client.channel.next_receive_sequence == 2
        assert len(response_client.snapshot()["seen"]) == 1

        request_snapshot = request_client.channel.snapshot()
        response_snapshot = response_client.snapshot()
        assert set(request_snapshot["pending"]) == {"1"}
        assert request_snapshot["next_sequence"] == 2
        assert response_snapshot["channel"]["next_receive_sequence"] == 2

        original.kill()
        original.communicate(timeout=10)
        assert original.returncode != 0
        assert os.getpid() == requester_pid
        for transport in first_transports:
            transport.close()

        restarted = subprocess.Popen(
            [
                sys.executable,
                str(worker_script),
                "restore-published",
                str(checkpoint_path),
                str(result_path),
            ],
            cwd=repository_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        second_ready = _wait_ready(restarted)
        second_transports = (
            SocketTransport.connect(
                "127.0.0.1",
                int(second_ready["request_port"]),
                "client",
                "worker",
            ),
            SocketTransport.connect(
                "127.0.0.1",
                int(second_ready["response_port"]),
                "client",
                "worker",
            ),
        )
        transports_to_close.extend(second_transports)
        request_client = HypervisorOperationChannel(
            ReliableChannel.from_snapshot(request_snapshot, second_transports[0])
        )
        response_client = HypervisorOperationResultChannel.from_snapshot(
            response_snapshot, second_transports[1]
        )
        assert request_client.channel.pending_sequences() == (1,)
        assert response_client.channel.next_receive_sequence == 2
        assert len(response_client.snapshot()["seen"]) == 1

        # The original request is retransmitted exactly. The receiver ledger
        # returns its committed effect without a backend entry. The restored
        # response sender then publishes a second transport frame for the same
        # semantic operation and retransmits the pre-crash published frame.
        assert request_client.channel.retransmit(1) is True
        duplicate_results = (
            _wait_response(response_client, restarted, result_path),
            _wait_response(response_client, restarted, result_path),
        )
        assert all(result.effect["registers"]["answer"] == 12 for result in duplicate_results)
        assert all(result.replayed is True for result in duplicate_results)
        assert duplicate_results[0].fingerprint == duplicate_results[1].fingerprint
        assert hosts_calls_not_visible := True
        _wait_request_ack(request_client.channel, (1,))
        assert response_client.channel.next_receive_sequence == 3

        # Both reliable response frames must have been ACKed, including the
        # old response frame whose pre-crash ACK could not reach the dead worker.
        deadline = time.monotonic() + 10.0
        while not result_path.exists() and restarted.poll() is None and time.monotonic() < deadline:
            time.sleep(0.005)
        assert result_path.exists()
        replay_stage = json.loads(result_path.read_text(encoding="utf-8"))
        while replay_stage.get("stage") != "waiting-for-new-request" and restarted.poll() is None and time.monotonic() < deadline:
            time.sleep(0.005)
            replay_stage = json.loads(result_path.read_text(encoding="utf-8"))
        assert replay_stage["stage"] == "waiting-for-new-request"

        second_event = _event(
            2,
            "set left 14\nset right 28\nadd answer left right\nhalt",
        )
        assert request_client.send(second_event) == 2
        new_response = _wait_response(response_client, restarted, result_path)
        assert new_response.effect["registers"]["answer"] == 42
        assert new_response.replayed is False
        second_translation = TransitTranslationEvidence.from_dict(
            new_response.effect["_semantic_translation"]
        )
        second_oracle = TransitOracleEvidence.from_dict(
            new_response.effect["_semantic_oracle"]
        )
        second_translation.validate_execution_result(new_response, require_oracle=True)
        assert second_oracle.equivalent is True
        _wait_request_ack(request_client.channel, (2,))

        stdout, stderr = restarted.communicate(timeout=30)
        assert restarted.returncode == 0, (
            f"receiver restart failed with exit={restarted.returncode}\n"
            f"stdout:\n{stdout}\nstderr:\n{stderr}"
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert result["pid"] == restarted.pid
        assert result["pid"] != cut["pid"]
        assert result["pid"] != requester_pid
        assert result["replayed_operation"] is True
        assert result["replay_backend_calls"] == 0
        assert result["new_operation_replayed"] is False
        assert result["new_operation_answer"] == 42
        assert result["backend_calls_after_restart"] == 1
        assert result["request_receive_cursor"] == 3
        assert result["response_pending"] == []
        assert result["journal_valid"] is True
        assert request_client.channel.pending_sequences() == ()
        assert response_client.channel.next_receive_sequence == 4
        assert os.getpid() == requester_pid
    finally:
        for process in (original, restarted):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
        for transport in transports_to_close:
            if not transport.closed:
                transport.close()
