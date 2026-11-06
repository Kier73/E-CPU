"""OS-process termination and fresh-interpreter recovery for navigable Transit work."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from mailcpu import NavigableComputationCheckpoint


def test_navigable_computation_recovers_after_real_worker_process_kill(tmp_path: Path) -> None:
    """Kill a child interpreter at the commit-before-publish cut and resume from disk in a new interpreter."""
    repository_root = Path(__file__).resolve().parents[1]
    worker_script = repository_root / "tests" / "helpers" / "navigable_process_worker.py"
    checkpoint_path = tmp_path / "process-crash-checkpoint.json"
    ready_path = tmp_path / "worker-committed-before-publish.json"
    result_path = tmp_path / "restored-process-result.json"

    command = [
        sys.executable,
        str(worker_script),
        "prepare",
        str(checkpoint_path),
        str(ready_path),
    ]
    interrupted = subprocess.Popen(
        command,
        cwd=repository_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 60.0
        while not ready_path.exists() and interrupted.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready_path.exists(), (
            "worker did not publish its post-fsync checkpoint marker; "
            f"exit={interrupted.poll()}, stderr={interrupted.stderr.read() if interrupted.poll() is not None else ''}"
        )
        marker = json.loads(ready_path.read_text(encoding="utf-8"))
        assert marker["pid"] == interrupted.pid
        assert marker["pid"] != os.getpid()
        assert marker["initial_backend_calls"] == 2  # branch A and branch B executed before the cut.
        assert marker["session_phase"] == "request-ready"
        assert marker["client_request_pending"] == [3]
        assert marker["worker_request_sequence"] == 3
        assert marker["worker_response_pending"] == []
        assert marker["client_response_has_message"] is False
        assert marker["committed_nodes"] == ["branch-a", "memory"]
        assert marker["ready_nodes"] == ["branch-b", "branch-c"]
        assert checkpoint_path.is_file()

        # The checkpoint is already independently readable while the worker is
        # still blocked inside the post-commit hook. Its atomic temp is gone.
        checkpoint = NavigableComputationCheckpoint.load(checkpoint_path)
        assert checkpoint["digest"] == marker["checkpoint_digest"]
        assert checkpoint["state"]["version"] == 3
        assert checkpoint["state"]["capture_mode"] == "inflight"
        assert not list(tmp_path.glob(f".{checkpoint_path.name}.*.tmp"))

        # Negative control: a changed envelope must be rejected before the
        # restore worker opens replacement transports or reconstructs a runtime.
        tampered_path = tmp_path / "tampered-checkpoint.json"
        tampered_result_path = tmp_path / "must-not-exist.json"
        tampered = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        tampered["state"]["untrusted_extra"] = "mutation"
        tampered_path.write_text(
            json.dumps(tampered, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        rejected = subprocess.run(
            [
                sys.executable,
                str(worker_script),
                "restore",
                str(tampered_path),
                str(tampered_result_path),
            ],
            cwd=repository_root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert rejected.returncode != 0
        assert "digest mismatch" in rejected.stderr
        assert not tampered_result_path.exists()

        # Popen.kill maps to SIGKILL on POSIX and TerminateProcess on Windows:
        # neither path runs Python finally blocks or graceful shutdown handlers.
        interrupted.kill()
        interrupted.communicate(timeout=10)
        assert interrupted.returncode != 0
        assert interrupted.poll() is not None
        # Checkpoint survives the hard process death, not merely the live-child read.
        post_kill_checkpoint = NavigableComputationCheckpoint.load(checkpoint_path)
        assert post_kill_checkpoint["digest"] == marker["checkpoint_digest"]
    finally:
        if interrupted.poll() is None:
            interrupted.kill()
            interrupted.communicate(timeout=10)

    # This is a distinct Python interpreter, not an in-memory object restore.
    restarted = subprocess.run(
        [
            sys.executable,
            str(worker_script),
            "restore",
            str(checkpoint_path),
            str(result_path),
        ],
        cwd=repository_root,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert restarted.returncode == 0, (
        f"restart worker failed with exit={restarted.returncode}\n"
        f"stdout:\n{restarted.stdout}\nstderr:\n{restarted.stderr}"
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["pid"] != marker["pid"]
    assert result["checkpoint_digest"] == marker["checkpoint_digest"]
    assert result["committed_nodes"] == [
        "branch-a", "branch-b", "branch-c", "join", "memory"
    ]
    assert result["branch_values"] == {
        "branch-a": 239,
        "branch-b": 660,
        "branch-c": 447,
    }
    assert result["branch_b_replayed"] is True
    assert result["branch_b_backend_calls_after_restart"] == 0
    assert result["backend_calls_after_restart"] == 2  # only branch C and the join.
    assert result["total_backend_calls"] == marker["initial_backend_calls"] + 2 == 4
    assert result["join_total"] == 1346
    assert result["journal_valid"] is True
