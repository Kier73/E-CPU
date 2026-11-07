"""Real-process Semantic Continuity proof for Transit-hosted VGI Signal8."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

HELPERS_DIR = str(Path(__file__).resolve().parent / "helpers")
if HELPERS_DIR not in sys.path:
    sys.path.insert(0, HELPERS_DIR)

pytest.importorskip("vgi")

from mailcpu import (  # noqa: E402
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
    RecoveryCheckpointBundleStore,
    RecoveryLineageAuthority,
    RecoveryLineageCoordinator,
    ReliabilityPolicy,
    ReliableChannel,
    SeedCommitMembership,
    SocketTransport,
    build_vgi_signal8_event,
    virtual_layer_operator_resource,
)
from vgi_continuity_support import make_vgi_workload  # noqa: E402

CHANNEL = "vgi-semantic-continuity"
GENESIS = hashlib.sha256(b"mailcpu-vgi-semantic-continuity-genesis-v1").hexdigest()


def _store(root: Path) -> RecoveryCheckpointBundleStore:
    """Open the three durable authorities backing the fixed-membership recovery proof."""
    membership = SeedCommitMembership(
        "vgi-continuity-machine",
        1,
        ("A", "B", "C"),
        "A",
        1,
        GENESIS,
    )
    authorities = {
        member: RecoveryLineageAuthority(
            membership,
            member,
            root / "authorities" / f"{member}.jsonl",
        )
        for member in ("A", "B", "C")
    }
    return RecoveryCheckpointBundleStore(
        root / "bundles",
        RecoveryLineageCoordinator(membership, authorities),
    )


def _client_channels(ready: dict[str, Any]):
    """Connect requester-side operation and result roles to one receiver process."""
    request_transport = SocketTransport.connect(
        "127.0.0.1", int(ready["request_port"]), "client", "worker"
    )
    response_transport = SocketTransport.connect(
        "127.0.0.1", int(ready["response_port"]), "client", "worker"
    )
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=5, window_size=8)
    request = HypervisorOperationChannel(
        ReliableChannel(
            request_transport,
            "client",
            "worker",
            CHANNEL,
            policy,
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


def _write_json_durable(path: Path, value: dict[str, Any]) -> None:
    """Persist the requester checkpoint before permitting receiver dispatch."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _wait_ready(process: subprocess.Popen[str]) -> dict[str, Any]:
    assert process.stdout is not None
    line = process.stdout.readline()
    if not line:
        stdout, stderr = process.communicate(timeout=5)
        raise AssertionError(
            f"receiver did not publish listeners: exit={process.returncode}, "
            f"stdout={stdout!r}, stderr={stderr!r}"
        )
    return json.loads(line)


def _wait_marker(
    path: Path,
    process: subprocess.Popen[str],
    timeout: float = 45.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while not path.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    if not path.exists():
        exit_code = process.poll()
        child_output = ""
        if exit_code is not None:
            stdout, stderr = process.communicate(timeout=5)
            child_output = f"\nstdout:\n{stdout}\nstderr:\n{stderr}"
        raise AssertionError(
            "receiver did not publish the quorum-sealed post-commit cut: "
            f"exit={exit_code}{child_output}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _wait_response(
    channel: HypervisorOperationResultChannel,
    process: subprocess.Popen[str],
    timeout: float = 30.0,
):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = channel.receive()
        if result is not None:
            return result
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=5)
            raise AssertionError(
                "fresh receiver exited before returning VGI effect: "
                f"exit={process.returncode}, stdout={stdout!r}, stderr={stderr!r}"
            )
        time.sleep(0.002)
    raise AssertionError("requester did not receive the restored VGI effect")


def _wait_request_ack(channel: ReliableChannel, expected: tuple[int, ...]) -> None:
    acknowledged: list[int] = []
    deadline = time.monotonic() + 15.0
    while channel.pending_sequences() and time.monotonic() < deadline:
        acknowledged.extend(channel.process_ack())
        time.sleep(0.005)
    assert channel.pending_sequences() == ()
    assert tuple(acknowledged) == expected


def test_vgi_effect_survives_hard_receiver_death_and_quorum_bundle_restore(
    tmp_path: Path,
) -> None:
    """Kill after commit, restore in a new interpreter, and prove one committed effect without VGI re-entry."""
    repository_root = Path(__file__).resolve().parents[1]
    worker_script = (
        repository_root / "tests" / "helpers" / "vgi_semantic_continuity_worker.py"
    )
    checkpoint_path = tmp_path / "receiver-vgi-session.json"
    requester_path = tmp_path / "requester-vgi-session.json"
    requester_ready = tmp_path / "requester-vgi-ready.json"
    marker_path = tmp_path / "receiver-vgi-committed.json"
    result_path = tmp_path / "receiver-vgi-restored.json"
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
                str(requester_path),
                str(tmp_path),
                str(requester_ready),
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

        workload = make_vgi_workload()
        event = build_vgi_signal8_event(
            workload,
            "client",
            CHANNEL,
            1,
            workload.logical_time,
        )
        assert event.request.resource == virtual_layer_operator_resource(
            "vgi.signal8.execute", 1
        )
        assert request_client.send(event) == 1
        _write_json_durable(
            requester_path,
            {
                "kind": "mailcpu.vgi.requester-checkpoint.v1",
                "event": event.to_dict(),
                "request_channel": request_client.channel.snapshot(),
                "response_channel": response_client.snapshot(),
            },
        )
        _write_json_durable(requester_ready, {"ready": True})

        cut = _wait_marker(marker_path, original)
        assert cut["pid"] == original.pid
        assert cut["pid"] != os.getpid()
        assert cut["capture_cut"] == "after_execution_commit"
        assert cut["bundle_generation"] == 1
        assert cut["backend_calls_before_kill"] == 1
        assert cut["execution_ledger_entries"] == 1
        assert cut["commit_record_count"] == 1
        assert cut["journal_valid"] is True
        assert cut["session_phase"] == "request-ready"
        assert len(cut["bundle_manifest_digest"]) == 64
        assert len(cut["receiver_checkpoint_digest"]) == 64
        assert len(cut["requester_checkpoint_digest"]) == 64
        assert checkpoint_path.is_file()
        assert requester_path.is_file()

        # The bundle has a quorum-backed high-water root and contains the
        # exact VGI receipt/checkpoint under the receiver's execution ledger.
        sealed = _store(tmp_path).load_latest()
        assert sealed.manifest.digest == cut["bundle_manifest_digest"]
        assert sealed.manifest.capture_cut == "after_execution_commit"
        assert sealed.manifest.generation == 1
        receiver_envelope = json.loads(sealed.receiver_checkpoint.decode("utf-8"))
        receiver_state = receiver_envelope["state"]["receiver"]
        executions = receiver_state["hypervisor_arbitration"]["executions"]
        assert len(executions) == 1
        committed_effect = executions[0]["effect"]
        committed_receipt = committed_effect["result"]
        assert receiver_envelope["format"] == "mailcpu-transit-worker-checkpoint-v3"
        implementation_entries = receiver_envelope["state"]["backend_implementation_manifest"]
        vgi_implementation = next(
            item[2]
            for item in implementation_entries
            if item[1] == "/virtual-layer/operators/vgi.signal8.execute/v1"
        )
        assert vgi_implementation == committed_effect["backend_implementation_fingerprint"]
        assert len(vgi_implementation) == 64
        assert committed_receipt["implementation"]["source_fingerprint"]
        assert committed_receipt["execution_digest"] == cut["vgi_execution_digest"]
        assert committed_receipt["checkpoint"]["ground_fingerprint"] == (
            cut["computation_ground_fingerprint"]
        )
        assert committed_receipt["program"]["fingerprint"] == cut["program_fingerprint"]
        assert committed_effect["_semantic_translation"]

        # Persist the requester-side pending frame, kill only the receiver,
        # then rebuild its channels from the still-live requester's snapshot.
        request_snapshot = request_client.channel.snapshot()
        response_snapshot = response_client.snapshot()
        assert request_client.channel.pending_sequences() == (1,)
        assert response_client.channel.peek() is None
        original.kill()
        original.communicate(timeout=10)
        assert original.returncode != 0
        for transport in first_transports:
            transport.close()

        restarted = subprocess.Popen(
            [
                sys.executable,
                str(worker_script),
                "restore",
                str(tmp_path),
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
            response_snapshot,
            second_transports[1],
        )
        assert request_client.channel.pending_sequences() == (1,)
        assert request_client.channel.retransmit(1) is True

        recovered = _wait_response(response_client, restarted)
        assert recovered.action.value == "allow"
        assert recovered.executed is True
        assert recovered.effect == committed_effect
        receipt = recovered.effect["result"]
        assert receipt["kind"] == "vgi.signal8.execution"
        assert receipt["execution_digest"] == cut["vgi_execution_digest"]
        assert receipt["system_ground"] == committed_receipt["system_ground"]
        assert receipt["computation_ground"] == committed_receipt["computation_ground"]
        assert receipt["program"] == committed_receipt["program"]
        assert receipt["execution"] == committed_receipt["execution"]
        assert receipt["checkpoint"] == committed_receipt["checkpoint"]
        assert recovered.replayed is False  # first receipt seen by the still-live requester
        _wait_request_ack(request_client.channel, (1,))

        stdout, stderr = restarted.communicate(timeout=30)
        assert restarted.returncode == 0, (
            f"restored VGI receiver failed: exit={restarted.returncode}\n"
            f"stdout:\n{stdout}\nstderr:\n{stderr}"
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        assert result["pid"] == restarted.pid
        assert result["pid"] != cut["pid"]
        assert result["bundle_generation"] == 1
        assert result["bundle_manifest_digest"] == cut["bundle_manifest_digest"]
        assert result["stage"] == "replayed"
        assert result["replayed"] is True
        assert result["backend_calls_after_restart"] == 0
        assert result["effect_digest"] == cut["effect_digest"]
        assert result["vgi_execution_digest"] == cut["vgi_execution_digest"]
        assert result["execution_ledger_entries"] == 1
        assert result["commit_record_count"] == 1
        assert result["replay_record_count"] == 1
        assert result["journal_valid"] is True
        assert os.getpid() != result["pid"]

        # The high-water proof still admits exactly the same immutable bundle
        # after both the original and restored receiver processes have exited.
        reopened = _store(tmp_path).load_latest()
        assert reopened.manifest == sealed.manifest
        assert reopened.proof.snapshot() == sealed.proof.snapshot()
    finally:
        for process in (original, restarted):
            if process is not None and process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
        for transport in transports_to_close:
            if not transport.closed:
                transport.close()
