"""Repeated joint process recovery across consecutive commit-before-publish crashes."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _read_ready_line(process: subprocess.Popen[str]) -> dict[str, Any]:
    assert process.stdout is not None
    line = process.stdout.readline()
    assert line, f"worker exited before publishing listener coordinates: returncode={process.poll()}"
    return json.loads(line)


def _wait_json_file(
    path: Path,
    process: subprocess.Popen[str],
    timeout: float = 30.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    value = None
    while value is None and process.poll() is None and time.monotonic() < deadline:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            value = loaded if isinstance(loaded, dict) else None
        except (FileNotFoundError, PermissionError, json.JSONDecodeError):
            time.sleep(0.01)
    assert value is not None, f"worker did not publish {path.name}: returncode={process.poll()}"
    return value


def _start_server(
    root: Path,
    worker: Path,
    mode: str,
    checkpoint: Path,
    marker_or_result: Path,
) -> tuple[subprocess.Popen[str], dict[str, Any]]:
    process = subprocess.Popen(
        [sys.executable, str(worker), mode, str(checkpoint), str(marker_or_result)],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    return process, _read_ready_line(process)


def _start_client(
    root: Path,
    worker: Path,
    mode: str,
    ports: dict[str, Any],
    checkpoint: Path,
    marker_or_result: Path,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            str(worker),
            mode,
            str(ports["request_port"]),
            str(ports["response_port"]),
            str(checkpoint),
            str(marker_or_result),
        ],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def _hard_kill(processes: tuple[subprocess.Popen[str], ...]) -> None:
    for process in processes:
        if process.poll() is None:
            process.kill()
    for process in processes:
        if process.poll() is None:
            process.communicate(timeout=10)
        assert process.returncode is not None and process.returncode != 0


def test_joint_process_recovery_survives_two_consecutive_commit_before_publish_crashes(
    tmp_path: Path,
) -> None:
    """Commit one operation, kill both peers twice, then replay and accept fresh work."""
    repository_root = Path(__file__).resolve().parents[1]
    worker = repository_root / "tests" / "helpers" / "repeated_joint_process_recovery_worker.py"

    server_checkpoint = tmp_path / "repeated-receiver-session.json"
    client_checkpoint = tmp_path / "repeated-requester-channels.json"
    first_server_marker = tmp_path / "first-server-cut.json"
    first_client_marker = tmp_path / "first-client-cut.json"
    second_server_marker = tmp_path / "second-server-cut.json"
    second_client_marker = tmp_path / "second-client-cut.json"
    final_server_result = tmp_path / "final-server-result.json"
    final_client_result = tmp_path / "final-client-result.json"

    processes: list[subprocess.Popen[str]] = []
    try:
        # Generation 0: execute sequence 1, durably checkpoint, then kill both
        # original interpreters before the result is published.
        original_server, ports = _start_server(
            repository_root, worker, "server-initial", server_checkpoint, first_server_marker
        )
        processes.append(original_server)
        original_client = _start_client(
            repository_root, worker, "client-initial", ports, client_checkpoint, first_client_marker
        )
        processes.append(original_client)
        client_cut_1 = _wait_json_file(first_client_marker, original_client)
        server_cut_1 = _wait_json_file(first_server_marker, original_server)

        assert client_cut_1["request_pending"] == [1]
        assert client_cut_1["response_receive_cursor"] == 1
        assert server_cut_1["fault_stage"] == "after_execution_commit"
        assert server_cut_1["backend_calls"] == 1
        assert server_cut_1["request_head"] == 1
        assert server_cut_1["request_receive_cursor"] == 1
        assert server_cut_1["response_pending"] == []
        assert server_cut_1["journal_valid"] is True
        assert server_checkpoint.is_file() and client_checkpoint.is_file()
        _hard_kill((original_client, original_server))

        # Generation 1: restore both independently. The client retransmits the
        # same identity; the receiver finds the committed effect and reaches
        # the same cut again without entering its replacement backend.
        middle_server, middle_ports = _start_server(
            repository_root, worker, "server-restored", server_checkpoint, second_server_marker
        )
        processes.append(middle_server)
        middle_client = _start_client(
            repository_root, worker, "client-restored", middle_ports, client_checkpoint, second_client_marker
        )
        processes.append(middle_client)
        client_cut_2 = _wait_json_file(second_client_marker, middle_client)
        server_cut_2 = _wait_json_file(second_server_marker, middle_server)

        assert client_cut_2["request_pending"] == [1]
        assert client_cut_2["response_receive_cursor"] == 1
        assert server_cut_2["fault_stage"] == "after_execution_commit"
        assert server_cut_2["backend_calls"] == 0
        assert server_cut_2["request_head"] == 1
        assert server_cut_2["request_receive_cursor"] == 1
        assert server_cut_2["response_pending"] == []
        assert server_cut_2["journal_valid"] is True
        _hard_kill((middle_client, middle_server))

        # Generation 2: restore a third requester/receiver pair. The same
        # committed operation now publishes and ACKs; sequence 2 proves new
        # computation still works on the recovered path.
        final_server, final_ports = _start_server(
            repository_root, worker, "server-final", server_checkpoint, final_server_result
        )
        processes.append(final_server)
        final_client = _start_client(
            repository_root, worker, "client-final", final_ports, client_checkpoint, final_client_result
        )
        processes.append(final_client)

        client_stdout, client_stderr = final_client.communicate(timeout=60)
        assert final_client.returncode == 0, (
            f"final requester failed with exit={final_client.returncode}\n"
            f"stdout:\n{client_stdout}\nstderr:\n{client_stderr}"
        )
        server_stdout, server_stderr = final_server.communicate(timeout=60)
        assert final_server.returncode == 0, (
            f"final receiver failed with exit={final_server.returncode}\n"
            f"stdout:\n{server_stdout}\nstderr:\n{server_stderr}"
        )

        client_result = json.loads(final_client_result.read_text(encoding="utf-8"))
        server_result = json.loads(final_server_result.read_text(encoding="utf-8"))
        assert original_server.pid != middle_server.pid != final_server.pid
        assert original_client.pid != middle_client.pid != final_client.pid
        assert client_result["origin_client_pid"] == original_client.pid
        assert client_result["client_pid"] == final_client.pid
        assert client_result["sequence_1_answer"] == 12
        assert client_result["sequence_1_first_delivery"] is True
        assert client_result["sequence_1_semantic_duplicate"] is False
        assert client_result["sequence_2_answer"] == 42
        assert client_result["sequence_2_replayed"] is False
        assert client_result["request_pending"] == []
        assert client_result["response_receive_cursor"] == 3
        assert client_result["response_seen"] == 2

        assert server_result["server_pid"] == final_server.pid
        assert server_result["sequence_1_replayed"] is True
        assert server_result["sequence_1_answer"] == 12
        assert server_result["backend_calls_after_sequence_1_replay"] == 0
        assert server_result["sequence_2_replayed"] is False
        assert server_result["sequence_2_answer"] == 42
        assert server_result["backend_calls_after_restore"] == 1
        assert server_result["request_receive_cursor"] == 3
        assert server_result["response_pending"] == []
        assert server_result["journal_valid"] is True

        # One backend execution before the first death, none across two replay
        # generations, and one fresh execution after the final restore.
        assert server_cut_1["backend_calls"] + server_cut_2["backend_calls"] + server_result["backend_calls_after_restore"] == 2
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
