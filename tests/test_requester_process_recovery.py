"""A durable requester process dies while its receiver survives and rebinds its session."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any] | None:
    """Read an atomically replaced progress file, retrying transient Windows locks."""

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
    """Wait for a valid durable child marker while preserving its process diagnostics."""

    deadline = time.monotonic() + timeout
    value = _read_json(path)
    while value is None and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
        value = _read_json(path)
    assert value is not None, (
        f"child did not publish {path.name}: returncode={process.poll()}"
    )
    return value


def _read_ready_line(process: subprocess.Popen[str]) -> dict[str, Any]:
    """Read one flushed server listener record from the persistent receiver process."""

    assert process.stdout is not None
    line = process.stdout.readline()
    assert line, (
        "receiver process exited before publishing listener coordinates: "
        f"returncode={process.poll()}"
    )
    return json.loads(line)


def test_requester_process_death_restores_durable_channel_capsule(tmp_path: Path) -> None:
    """Kill the client after request send, restore its durable channels in a new process."""

    repository_root = Path(__file__).resolve().parents[1]
    worker_script = repository_root / "tests" / "helpers" / "requester_process_recovery_worker.py"
    server_checkpoint = tmp_path / "live-receiver-session.json"
    client_checkpoint = tmp_path / "durable-requester-channels.json"
    cut_marker = tmp_path / "receiver-after-response-publish.json"
    client_marker = tmp_path / "requester-durable-cut.json"
    release_path = tmp_path / "allow-receiver-rebind"
    rebind_ready_path = tmp_path / "receiver-rebind-ready.json"
    server_result_path = tmp_path / "receiver-final-result.json"
    client_result_path = tmp_path / "requester-final-result.json"

    server: subprocess.Popen[str] | None = None
    original_client: subprocess.Popen[str] | None = None
    restored_client: subprocess.Popen[str] | None = None

    try:
        server = subprocess.Popen(
            [
                sys.executable,
                str(worker_script),
                "server",
                str(server_checkpoint),
                str(cut_marker),
                str(release_path),
                str(rebind_ready_path),
                str(server_result_path),
            ],
            cwd=repository_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        initial_ready = _read_ready_line(server)
        server_pid = initial_ready["pid"]
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
        first_client_state = _wait_json_file(client_marker, original_client)
        receiver_cut = _wait_json_file(cut_marker, server)

        assert first_client_state["client_pid"] == original_client.pid
        assert first_client_state["request_pending"] == [1]
        assert first_client_state["request_next_sequence"] == 2
        assert first_client_state["response_receive_cursor"] == 1
        assert first_client_state["response_seen"] == 0
        assert receiver_cut["server_pid"] == server_pid
        assert receiver_cut["fault_stage"] == "after_response_publish"
        assert receiver_cut["backend_calls_before_client_death"] == 1
        assert receiver_cut["request_head"] == 1
        assert receiver_cut["request_receive_cursor"] == 1
        assert receiver_cut["response_pending"] == [1]
        assert receiver_cut["journal_valid"] is True
        assert server_checkpoint.is_file() and client_checkpoint.is_file()

        # Verify that the client capsule is self-consistent before destroying
        # the only interpreter holding its live request and result objects.
        client_envelope = json.loads(client_checkpoint.read_text(encoding="utf-8"))
        assert client_envelope["digest"] == first_client_state["checkpoint_digest"]
        state = client_envelope["state"]
        canonical = json.dumps(
            state, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        assert hashlib.sha256(canonical).hexdigest() == client_envelope["digest"]

        # Tamper with a copy of the durable client capsule. Restore must
        # reject it before opening either replacement TCP connection.
        tampered_checkpoint = tmp_path / "tampered-requester-channels.json"
        tampered_envelope = json.loads(client_checkpoint.read_text(encoding="utf-8"))
        tampered_envelope["state"]["untrusted_extra"] = "mutation"
        tampered_checkpoint.write_text(
            json.dumps(tampered_envelope, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        rejected_result = tmp_path / "tampered-requester-result.json"
        rejected = subprocess.run(
            [
                sys.executable,
                str(worker_script),
                "client-restore",
                str(initial_ready["request_port"]),
                str(initial_ready["response_port"]),
                str(tampered_checkpoint),
                str(rejected_result),
            ],
            cwd=repository_root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert rejected.returncode != 0
        assert "client checkpoint digest mismatch" in rejected.stderr
        assert not rejected_result.exists()

        original_client.kill()
        original_client.communicate(timeout=10)
        assert original_client.returncode != 0
        assert original_client.poll() is not None

        # Release only the receiver's in-process session rebind. The server PID
        # remains alive; it restores its receiver-side session checkpoint over
        # a new pair of TCP streams and publishes a second listener record.
        release_path.write_text("rebind\n", encoding="utf-8")
        rebind = _wait_json_file(rebind_ready_path, server)
        second_ready = _read_ready_line(server)
        assert rebind["server_pid"] == server_pid
        assert second_ready["pid"] == server_pid
        assert second_ready["phase"] == "rebind"

        restored_client = subprocess.Popen(
            [
                sys.executable,
                str(worker_script),
                "client-restore",
                str(second_ready["request_port"]),
                str(second_ready["response_port"]),
                str(client_checkpoint),
                str(client_result_path),
            ],
            cwd=repository_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        client_stdout, client_stderr = restored_client.communicate(timeout=45)
        assert restored_client.returncode == 0, (
            f"restored requester failed with exit={restored_client.returncode}\n"
            f"stdout:\n{client_stdout}\nstderr:\n{client_stderr}"
        )

        server_stdout, server_stderr = server.communicate(timeout=45)
        assert server.returncode == 0, (
            f"surviving receiver failed with exit={server.returncode}\n"
            f"stdout:\n{server_stdout}\nstderr:\n{server_stderr}"
        )
        client_result = _read_json(client_result_path)
        server_result = _read_json(server_result_path)
        assert client_result is not None and server_result is not None

        assert client_result["client_pid"] == restored_client.pid
        assert client_result["client_pid"] != original_client.pid
        assert client_result["original_client_pid"] == original_client.pid
        assert client_result["received_replay_fresh"] is True
        assert client_result["received_replay_duplicate"] is True
        assert client_result["new_operation_answer"] == 42
        assert client_result["new_operation_replayed"] is False
        assert client_result["request_pending"] == []
        assert client_result["response_receive_cursor"] == 4
        assert client_result["response_seen"] == 2

        assert server_result["server_pid"] == server_pid
        assert server_result["backend_calls_before_client_death"] == 1
        assert server_result["backend_calls_after_rebind"] == 1
        assert server_result["total_backend_calls"] == 2
        assert server_result["new_operation_answer"] == 42
        assert server_result["request_receive_cursor"] == 3
        assert server_result["response_pending"] == []
        assert server_result["journal_valid"] is True
        assert server.poll() is not None
    finally:
        for process in (original_client, restored_client, server):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
