"""Both requester and receiver processes die and restart from durable channel checkpoints."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

def _read_json(path: Path) -> dict[str, Any] | None:
    """Read one durable progress record, tolerating transient file locks."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (FileNotFoundError, PermissionError, json.JSONDecodeError):
        return None


def _read_ready_line(process: subprocess.Popen[str]) -> dict[str, Any]:
    """Read the worker's flushed listener coordinates."""

    assert process.stdout is not None
    line = process.stdout.readline()
    assert line, f"worker exited before publishing listener coordinates: {process.poll()}"
    return json.loads(line)


def _wait_json_file(
    path: Path,
    process: subprocess.Popen[str],
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Wait for a durable marker and fail if its worker exits first."""

    deadline = time.monotonic() + timeout
    value = _read_json(path)
    while value is None and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
        value = _read_json(path)
    assert value is not None, f"worker did not publish {path.name}: returncode={process.poll()}"
    return value


def test_requester_and_receiver_processes_restart_from_their_own_checkpoints(tmp_path: Path) -> None:
    """Kill both peers after response publication and restore both in new interpreters."""

    repository_root = Path(__file__).resolve().parents[1]
    worker_script = repository_root / "tests" / "helpers" / "requester_process_recovery_worker.py"
    server_checkpoint = tmp_path / "joint-receiver-session.json"
    client_checkpoint = tmp_path / "joint-requester-channels.json"
    cut_marker = tmp_path / "joint-crash-cut.json"
    client_marker = tmp_path / "joint-client-cut.json"
    server_result_path = tmp_path / "joint-server-result.json"
    client_result_path = tmp_path / "joint-client-result.json"

    original_server: subprocess.Popen[str] | None = None
    original_client: subprocess.Popen[str] | None = None
    restored_server: subprocess.Popen[str] | None = None
    restored_client: subprocess.Popen[str] | None = None

    try:
        original_server = subprocess.Popen(
            [
                sys.executable,
                str(worker_script),
                "server-cut",
                str(server_checkpoint),
                str(cut_marker),
            ],
            cwd=repository_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        initial_ready = _read_ready_line(original_server)
        original_server_pid = initial_ready["pid"]
        assert initial_ready["phase"] == "initial"

        original_client = subprocess.Popen(
            [
                sys.executable,
                str(worker_script),
                "client-prepare",
                str(initial_ready["request_port"]),
                str(initial_ready["response_port"]),
                str(client_checkpoint),
                str(client_marker),
            ],
            cwd=repository_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        original_client_state = _wait_json_file(client_marker, original_client)
        receiver_cut = _wait_json_file(cut_marker, original_server)

        assert original_client_state["client_pid"] == original_client.pid
        assert original_client_state["request_pending"] == [1]
        assert original_client_state["request_next_sequence"] == 2
        assert original_client_state["response_receive_cursor"] == 1
        assert original_client_state["response_seen"] == 0
        assert receiver_cut["server_pid"] == original_server_pid
        assert receiver_cut["fault_stage"] == "after_response_publish"
        assert receiver_cut["backend_calls_before_joint_death"] == 1
        assert receiver_cut["request_head"] == 1
        assert receiver_cut["request_receive_cursor"] == 1
        assert receiver_cut["response_pending"] == [1]
        assert receiver_cut["journal_valid"] is True
        assert server_checkpoint.is_file() and client_checkpoint.is_file()

        # Both checkpoints are durable before either original interpreter dies.
        original_client.kill()
        original_client.communicate(timeout=10)
        original_server.kill()
        original_server.communicate(timeout=10)
        assert original_client.returncode != 0
        assert original_server.returncode != 0

        # Restart receiver first. It binds new listeners and restores the
        # committed execution ledger plus the still-pending response frame.
        restored_server = subprocess.Popen(
            [
                sys.executable,
                str(worker_script),
                "server-restore",
                str(server_checkpoint),
                str(server_result_path),
            ],
            cwd=repository_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        restored_ready = _read_ready_line(restored_server)
        restored_server_pid = restored_ready["pid"]
        assert restored_ready["phase"] == "restore"
        assert restored_server_pid != original_server_pid

        # Start a fresh requester interpreter from its independent disk
        # checkpoint. It cannot depend on any objects in the dead client.
        restored_client = subprocess.Popen(
            [
                sys.executable,
                str(worker_script),
                "client-restore",
                str(restored_ready["request_port"]),
                str(restored_ready["response_port"]),
                str(client_checkpoint),
                str(client_result_path),
                str(server_result_path),
            ],
            cwd=repository_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        client_stdout, client_stderr = restored_client.communicate(timeout=45)
        assert restored_client.returncode == 0, (
            f"jointly restored requester failed with exit={restored_client.returncode}\n"
            f"stdout:\n{client_stdout}\nstderr:\n{client_stderr}"
        )

        server_stdout, server_stderr = restored_server.communicate(timeout=45)
        assert restored_server.returncode == 0, (
            f"jointly restored receiver failed with exit={restored_server.returncode}\n"
            f"stdout:\n{server_stdout}\nstderr:\n{server_stderr}"
        )

        client_result = _read_json(client_result_path)
        server_result = _read_json(server_result_path)
        assert client_result is not None and server_result is not None

        assert restored_client.pid != original_client.pid
        assert client_result["client_pid"] == restored_client.pid
        assert client_result["original_client_pid"] == original_client.pid
        assert client_result["received_replay_fresh"] is True
        assert client_result["received_replay_duplicate"] is True
        assert client_result["new_operation_answer"] == 42
        assert client_result["new_operation_replayed"] is False
        assert client_result["request_pending"] == []
        assert client_result["response_receive_cursor"] == 4
        assert client_result["response_seen"] == 2

        assert server_result["server_pid"] == restored_server_pid
        assert server_result["replayed_operation"] is True
        assert server_result["backend_calls_after_restore"] == 1
        assert server_result["total_backend_calls"] == 2
        assert server_result["new_operation_answer"] == 42
        assert server_result["request_receive_cursor"] == 3
        assert server_result["response_pending"] == []
        assert server_result["journal_valid"] is True
    finally:
        for process in (
            original_client,
            original_server,
            restored_client,
            restored_server,
        ):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
