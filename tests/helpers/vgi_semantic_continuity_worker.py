"""Subprocess worker for the quorum-sealed VGI Semantic Continuity experiment."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HELPERS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HELPERS))

from mailcpu import (  # noqa: E402
    Capability,
    RecoveryCheckpointBundleStore,
    RecoveryLineageAuthority,
    RecoveryLineageCoordinator,
    SeedCommitMembership,
    SocketTransport,
    TransitBackendRouter,
    TransitComputeSession,
    TransitComputeWorker,
    TransitVGIHost,
)
from vgi_continuity_support import NODE_ID, configure_receiver  # noqa: E402

CHANNEL = "vgi-semantic-continuity"
GENESIS = hashlib.sha256(b"mailcpu-vgi-semantic-continuity-genesis-v1").hexdigest()


class CountingTransitVGIHost(TransitVGIHost):
    """Count interpreter entries, excluding results returned by the restored effect ledger."""

    def __init__(self, operating_system, authority_pid):
        super().__init__(operating_system, authority_pid, node_id=NODE_ID, max_steps=256)
        self.calls = 0

    def handle(self, event):
        self.calls += 1
        return super().handle(event)


def make_store(root: Path) -> RecoveryCheckpointBundleStore:
    """Reopen the same three durable authority journals for bundle sealing or proof-gated restore."""
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


def write_json_durable(path: Path, value: dict[str, Any]) -> None:
    """Atomically publish canonical JSON only after fsync of its complete contents."""
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


def open_server_sockets():
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


def accept_worker_transports(request_listener, response_listener):
    request_transport = SocketTransport.accept(
        request_listener, "worker", "client"
    )
    response_transport = SocketTransport.accept(
        response_listener, "worker", "client"
    )
    request_listener.close()
    response_listener.close()
    return request_transport, response_transport


def make_session(request_transport, response_transport):
    """Build the exact Transit router relation and receiver-bound channels."""
    operating_system, _envelope = configure_receiver()
    authority_pid = operating_system.environment.kernel.spawn(
        "vgi-transit-worker",
        capabilities=(
            Capability("/virtual-layer/operators", frozenset({"compute"})),
        ),
        parent_pid=operating_system.environment.init_pid,
    )
    host = CountingTransitVGIHost(operating_system, authority_pid)
    router = TransitBackendRouter()
    router.register_backend(host)
    from mailcpu import (
        HypervisorOperationChannel,
        HypervisorOperationResultChannel,
        ReliabilityPolicy,
        ReliableChannel,
    )

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
    session = TransitComputeSession(
        TransitComputeWorker(operating_system, authority_pid, router),
        request,
        response,
    )
    return session, host


def make_restored_router(operating_system, authority_pid, hosts):
    """Rebind the same backend domain to fresh receiver objects after restart."""
    host = CountingTransitVGIHost(operating_system, authority_pid)
    hosts.append(host)
    router = TransitBackendRouter()
    router.register_backend(host)
    return router


def serve_next(session: TransitComputeSession, timeout: float = 30.0):
    """Wait for the requester to retransmit its pending operation onto the rebound socket."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = session.serve_once()
        if result is not None:
            return result
        time.sleep(0.005)
    raise TimeoutError("restored VGI receiver did not receive the requester retry")


def prepare(
    checkpoint_path: Path,
    requester_path: Path,
    root: Path,
    ready_path: Path,
    marker_path: Path,
) -> None:
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

    deadline = time.monotonic() + 30.0
    while not ready_path.exists() and time.monotonic() < deadline:
        time.sleep(0.005)
    if not ready_path.exists():
        raise TimeoutError("requester did not publish its durable checkpoint before dispatch")

    def pause_after_commit(stage: str) -> None:
        if stage != "after_execution_commit":
            return
        checkpoint_digest = session.save_checkpoint(
            str(checkpoint_path),
            allow_inflight=True,
        )
        bundle = make_store(root).seal(
            requester_path,
            checkpoint_path,
            "after_execution_commit",
        )
        executions = session.worker.operating_system.hypervisor_arbitration.snapshot()["executions"]
        if len(executions) != 1:
            raise AssertionError("expected exactly one committed receiver execution")
        effect = executions[0]["effect"]
        receipt = effect["result"]
        records = session.worker.operating_system.environment.kernel.journal.snapshot()
        marker = {
            "pid": os.getpid(),
            "checkpoint_digest": checkpoint_digest,
            "bundle_generation": bundle.generation,
            "bundle_manifest_digest": bundle.manifest.digest,
            "bundle_proof": bundle.proof.snapshot(),
            "receiver_checkpoint_digest": bundle.manifest.receiver_checkpoint_digest,
            "requester_checkpoint_digest": bundle.manifest.requester_checkpoint_digest,
            "capture_cut": bundle.manifest.capture_cut,
            "backend_calls_before_kill": host.calls,
            "execution_ledger_entries": len(executions),
            "commit_record_count": sum(
                1 for item in records if item["kind"] == "hypervisor.execution.commit"
            ),
            "effect_digest": hashlib.sha256(json.dumps(
                effect,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")).hexdigest(),
            "vgi_execution_digest": receipt["execution_digest"],
            "program_fingerprint": receipt["program"]["fingerprint"],
            "system_ground_digest": hashlib.sha256(json.dumps(
                receipt["system_ground"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")).hexdigest(),
            "computation_ground_fingerprint": receipt["computation_ground"]["fingerprint"],
            "journal_valid": session.worker.operating_system.environment.kernel.journal.verify(),
            "session_phase": session.phase,
        }
        write_json_durable(marker_path, marker)
        while True:
            time.sleep(60)

    while time.monotonic() < deadline:
        result = session.serve_once(fault_hook=pause_after_commit)
        if result is not None:
            raise AssertionError("receiver returned beyond the requested post-commit crash cut")
        time.sleep(0.002)
    raise TimeoutError("VGI receiver did not receive the submitted operation")


def restore(root: Path, result_path: Path) -> None:
    request_listener, response_listener, request_port, response_port = open_server_sockets()
    print(json.dumps({
        "pid": os.getpid(),
        "request_port": request_port,
        "response_port": response_port,
        "mode": "restore",
    }, sort_keys=True), flush=True)
    request_transport, response_transport = accept_worker_transports(
        request_listener,
        response_listener,
    )
    bundle = make_store(root).load_latest()
    if bundle.manifest.capture_cut != "after_execution_commit":
        raise AssertionError("quorum bundle is not anchored at the requested commit cut")
    hosts: list[CountingTransitVGIHost] = []
    session = bundle.restore_receiver_session(
        request_transport,
        response_transport,
        compute_host_factory=lambda operating_system, pid: make_restored_router(
            operating_system,
            pid,
            hosts,
        ),
    )
    if len(hosts) != 1 or hosts[0].calls != 0:
        raise AssertionError("fresh backend must start without an interpreter invocation")
    restored_phase = session.phase
    if restored_phase not in {"idle", "request-ready"}:
        raise AssertionError(f"restored session entered an invalid phase: {restored_phase}")
    write_json_durable(result_path, {
        "stage": "restored",
        "pid": os.getpid(),
        "bundle_generation": bundle.generation,
        "bundle_manifest_digest": bundle.manifest.digest,
        "session_phase": restored_phase,
    })

    # The requester retransmits after the restored process publishes its
    # listeners. The restored channel may start idle until that frame arrives;
    # wait for the explicit retry instead of depending on process scheduling.
    replay = serve_next(session)
    if not replay.replayed or not replay.executed:
        raise AssertionError("restored operation did not replay its committed effect")
    if hosts[0].calls != 0:
        raise AssertionError("replayed operation re-entered the VGI interpreter")
    if not isinstance(replay.effect, dict):
        raise AssertionError("restored effect is not a canonical object")
    receipt = replay.effect["result"]
    records = session.worker.operating_system.environment.kernel.journal.snapshot()
    result_marker = {
        "stage": "replayed",
        "pid": os.getpid(),
        "bundle_generation": bundle.generation,
        "bundle_manifest_digest": bundle.manifest.digest,
        "replayed": replay.replayed,
        "backend_calls_after_restart": hosts[0].calls,
        "effect_digest": hashlib.sha256(json.dumps(
            replay.effect,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")).hexdigest(),
        "vgi_execution_digest": receipt["execution_digest"],
        "execution_ledger_entries": len(
            session.worker.operating_system.hypervisor_arbitration.snapshot()["executions"]
        ),
        "commit_record_count": sum(
            1 for item in records if item["kind"] == "hypervisor.execution.commit"
        ),
        "replay_record_count": sum(
            1 for item in records if item["kind"] == "hypervisor.execution.replay"
        ),
        "journal_valid": session.worker.operating_system.environment.kernel.journal.verify(),
    }
    write_json_durable(result_path, result_marker)

    deadline = time.monotonic() + 20.0
    while session.response.channel.pending_sequences() and time.monotonic() < deadline:
        session.response.channel.process_ack()
        time.sleep(0.005)
    if session.response.channel.pending_sequences():
        raise TimeoutError("restored VGI response was not acknowledged by requester")
    request_transport.close()
    response_transport.close()


def main(arguments: list[str]) -> int:
    if not arguments:
        raise SystemExit("expected prepare or restore mode")
    mode = arguments[0]
    if mode == "prepare" and len(arguments) == 6:
        prepare(*(Path(item) for item in arguments[1:]))
        return 0
    if mode == "restore" and len(arguments) == 3:
        restore(Path(arguments[1]), Path(arguments[2]))
        return 0
    raise SystemExit("usage: prepare CHECKPOINT REQUESTER ROOT READY MARKER | restore ROOT RESULT")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
