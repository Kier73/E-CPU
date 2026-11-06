"""Hard-kill both independent Transit processes at every transaction boundary."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

CUTS = (
    "before_execution",
    "after_execution_commit",
    "after_response_publish",
    "after_request_ack",
)


def _read_ready_line(process: subprocess.Popen[str]) -> dict[str, Any]:
    assert process.stdout is not None
    line = process.stdout.readline()
    assert line, f"worker exited before publishing listener coordinates: returncode={process.poll()}"
    return json.loads(line)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (FileNotFoundError, PermissionError, json.JSONDecodeError):
        return None


def _wait_json_file(
    path: Path,
    process: subprocess.Popen[str],
    timeout: float = 30.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    value = _read_json(path)
    while value is None and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
        value = _read_json(path)
    assert value is not None, f"worker did not publish {path.name}: returncode={process.poll()}"
    return value


def _start_server(
    root: Path,
    worker: Path,
    mode: str,
    cut: str,
    checkpoint: Path,
    marker_or_result: Path,
) -> tuple[subprocess.Popen[str], dict[str, Any]]:
    process = subprocess.Popen(
        [sys.executable, str(worker), mode, cut, str(checkpoint), str(marker_or_result)],
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
    checkpoint: Path,
    marker_or_result: Path,
    ports: dict[str, Any],
    cut: str | None = None,
) -> subprocess.Popen[str]:
    args = [
        sys.executable,
        str(worker),
        mode,
        str(checkpoint),
        str(marker_or_result),
        str(ports["request_port"]),
        str(ports["response_port"]),
    ]
    if cut is not None:
        args.append(cut)
    return subprocess.Popen(
        args,
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


@pytest.mark.parametrize("cut", CUTS)
def test_requester_and_receiver_processes_recover_at_each_transit_crash_cut(
    cut: str,
    tmp_path: Path,
) -> None:
    """Prove joint process recovery at before/after commit, publish, and request ACK."""
    repository_root = Path(__file__).resolve().parents[1]
    worker = repository_root / "tests" / "helpers" / "process_crash_boundary_worker.py"

    server_checkpoint = tmp_path / f"{cut}-receiver.json"
    client_checkpoint = tmp_path / f"{cut}-requester.json"
    server_marker = tmp_path / f"{cut}-server-cut.json"
    client_marker = tmp_path / f"{cut}-client-cut.json"
    server_result_path = tmp_path / f"{cut}-server-result.json"
    client_result_path = tmp_path / f"{cut}-client-result.json"

    processes: list[subprocess.Popen[str]] = []
    try:
        original_server, ports = _start_server(
            repository_root, worker, "server-cut", cut, server_checkpoint, server_marker
        )
        processes.append(original_server)
        original_client = _start_client(
            repository_root, worker, "client-prepare", client_checkpoint, client_marker, ports
        )
        processes.append(original_client)

        client_cut = _wait_json_file(client_marker, original_client)
        server_cut = _wait_json_file(server_marker, original_server)

        assert client_cut["client_pid"] == original_client.pid
        assert client_cut["request_pending"] == [1]
        assert client_cut["request_next_sequence"] == 2
        assert client_cut["response_receive_cursor"] == 1
        assert client_cut["response_seen"] == 0
        assert server_cut["server_pid"] == original_server.pid
        assert server_cut["fault_stage"] == cut
        assert server_cut["backend_calls_before_death"] == (
            0 if cut == "before_execution" else 1
        )
        assert server_cut["journal_valid"] is True

        expected_cursor = 2 if cut == "after_request_ack" else 1
        expected_head = None if cut == "after_request_ack" else 1
        expected_pending = [1] if cut in {
            "after_response_publish",
            "after_request_ack",
        } else []
        assert server_cut["request_receive_cursor"] == expected_cursor
        assert server_cut["request_head"] == expected_head
        assert server_cut["response_pending"] == expected_pending
        assert server_checkpoint.is_file() and client_checkpoint.is_file()

        # The original requester and receiver are both destroyed. Their only
        # surviving protocol state is held in independent durable files.
        _hard_kill((original_client, original_server))

        restored_server, restored_ports = _start_server(
            repository_root,
            worker,
            "server-restore",
            cut,
            server_checkpoint,
            server_result_path,
        )
        processes.append(restored_server)
        # The server mode accepts a new connection and restores before it
        # serves. Its readiness line is emitted before accept/restore.
        restored_client = _start_client(
            repository_root,
            worker,
            "client-restore",
            client_checkpoint,
            client_result_path,
            restored_ports,
            cut,
        )
        processes.append(restored_client)

        client_stdout, client_stderr = restored_client.communicate(timeout=60)
        assert restored_client.returncode == 0, (
            f"restored requester failed for {cut}: exit={restored_client.returncode}\n"
            f"stdout:\n{client_stdout}\nstderr:\n{client_stderr}"
        )
        server_stdout, server_stderr = restored_server.communicate(timeout=60)
        assert restored_server.returncode == 0, (
            f"restored receiver failed for {cut}: exit={restored_server.returncode}\n"
            f"stdout:\n{server_stdout}\nstderr:\n{server_stderr}"
        )

        client_result = _read_json(client_result_path)
        server_result = _read_json(server_result_path)
        assert client_result is not None and server_result is not None

        expected_response_count = 2 if cut in {
            "after_response_publish",
            "after_request_ack",
        } else 1
        expected_execution_replay = cut != "before_execution"
        expected_backend_after_restore = 2 if cut == "before_execution" else 1

        assert restored_client.pid != original_client.pid
        assert restored_server.pid != original_server.pid
        assert client_result["client_pid"] == restored_client.pid
        assert client_result["origin_client_pid"] == original_client.pid
        assert client_result["cut"] == cut
        assert client_result["sequence_1_delivery_count"] == expected_response_count
        assert client_result["sequence_1_first_delivery_fresh"] is True
        assert client_result["sequence_1_second_delivery_duplicate"] is (
            True if expected_response_count == 2 else None
        )
        assert client_result["sequence_2_answer"] == 42
        assert client_result["sequence_2_fresh"] is True
        assert client_result["request_pending"] == []
        assert client_result["response_receive_cursor"] == 2 + expected_response_count
        assert client_result["semantic_results_seen"] == 2

        assert server_result["server_pid"] == restored_server.pid
        assert server_result["cut"] == cut
        assert server_result["sequence_1_execution_replayed"] is expected_execution_replay
        assert server_result["sequence_1_answer"] == 12
        assert server_result["sequence_2_execution_replayed"] is False
        assert server_result["sequence_2_answer"] == 42
        assert server_result["backend_calls_after_restore"] == expected_backend_after_restore
        assert server_result["request_receive_cursor"] == 3
        assert server_result["response_pending"] == []
        assert server_result["journal_valid"] is True

        assert (
            server_cut["backend_calls_before_death"]
            + server_result["backend_calls_after_restore"]
            == 2
        )
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
