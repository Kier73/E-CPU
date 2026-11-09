"""Hard-killable terminal peer C for federated forwarding recovery tests."""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mailcpu import (  # noqa: E402
    Capability,
    ComputationalFabricDirectory,
    ComputationalFabricForwardingRecoveryStore,
    ComputationalFabricForwardingServer,
    ComputationalHostAdvertisement,
    ComputationalHostCatalogue,
    ComputationalHostLocus,
    ComputationalPeerSnapshot,
    DistributedRecoveryLineageCoordinator,
    HeadlessOS,
    HypervisorPolicy,
    OperatorRegistry,
    OperatorSpec,
    RecoveryLineageAuthority,
    RecoveryLineagePeerClient,
    RouteMetric,
    SeedCommitMembership,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
    VirtualLayerRuntime,
)
from mailcpu.computational_fabric_forwarding import COMPUTATIONAL_FABRIC_EXECUTE_RESOURCE  # noqa: E402
from mailcpu.mtls_transport import accept_mutual_tls  # noqa: E402
from mailcpu.socket_transport import SocketTransport, SocketTransportClosed  # noqa: E402


GENESIS = hashlib.sha256(b"mailcpu-federated-terminal-peer-c-process-recovery-v1").hexdigest()
GROUND_FP = "a" * 64
PROGRAM_FP = "b" * 64
IMPLEMENTATION_FP = "c" * 64


def _write_json_durable(path: Path, value: dict[str, Any]) -> None:
    """Fsync one marker before exposing a named terminal-process recovery cut."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _membership(path: Path) -> SeedCommitMembership:
    return SeedCommitMembership.from_snapshot(json.loads(path.read_text(encoding="utf-8")))


def _open_store(config: dict[str, Any], checkpoint_directory: str):
    membership = _membership(Path(config["membership_path_c"]))
    journal_root = Path(config["lineage_root_c"]) / "authorities"
    owner = RecoveryLineageAuthority(
        membership,
        "peer-c",
        journal_root / "peer-c.jsonl",
    )
    anchor_e = RecoveryLineagePeerClient.connect(
        membership, "anchor-e", "127.0.0.1", int(config["anchor_e_port"]), timeout=5.0
    )
    anchor_f = RecoveryLineagePeerClient.connect(
        membership, "anchor-f", "127.0.0.1", int(config["anchor_f_port"]), timeout=5.0
    )
    coordinator = DistributedRecoveryLineageCoordinator(
        membership,
        {"peer-c": owner, "anchor-e": anchor_e, "anchor-f": anchor_f},
    )
    return ComputationalFabricForwardingRecoveryStore(checkpoint_directory, coordinator), coordinator


def _directory(config: dict[str, Any]) -> ComputationalFabricDirectory:
    snapshots = {
        peer_id: ComputationalPeerSnapshot.from_dict(raw)
        for peer_id, raw in config["peer_snapshots"].items()
    }
    directory = ComputationalFabricDirectory(
        "peer-c",
        {"peer-b": snapshots["peer-b"].endpoint.tls_server_name},
    )
    directory.register_local_snapshot(snapshots["peer-c"])
    directory._merge_verified_peer_snapshot(
        snapshots["peer-b"],
        authenticated_peer_id="peer-b",
        authenticated_server_name=snapshots["peer-b"].endpoint.tls_server_name,
    )
    return directory


def _server_context(config: dict[str, Any]) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(config["peer_c_cert"], config["peer_c_key"])
    context.load_verify_locations(cafile=config["ca_cert"])
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _spec() -> OperatorSpec:
    return OperatorSpec(
        operator_id="core.sum_pair",
        version=1,
        description="Add two integers from a JSON object",
        input_kind="object",
        output_kind="integer",
        substrates=("cpu", "gpu"),
        required_rights=frozenset({"compute"}),
        base_energy=8,
        energy_per_byte=1,
        max_input_bytes=4096,
        max_output_bytes=64,
        deterministic=True,
        effect_mode="pure",
    )


def _catalogue(
    operating_system: HeadlessOS,
    compute_pid: int,
    calls_path: Path,
) -> ComputationalHostCatalogue:
    registry = OperatorRegistry()
    spec = _spec()

    def execute(value, workload):
        """Record test-observed operator entry separately from the replay ledger."""
        calls_path.parent.mkdir(parents=True, exist_ok=True)
        record = json.dumps(
            {"workload_id": workload.workload_id, "left": value["left"], "right": value["right"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        descriptor = os.open(str(calls_path), os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, record)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return value["left"] + value["right"]

    registry.register(spec, execute)
    runtime = VirtualLayerRuntime(registry, "node-c", frozenset({"cpu"}))
    locus = ComputationalHostLocus.from_runtime(
        host_id="logical-host-c",
        runtime=runtime,
        authority_pid=compute_pid,
        operator_id="core.sum_pair",
        computational_ground_fingerprints=(GROUND_FP,),
        program_fingerprints=(PROGRAM_FP,),
        costs=(
            RouteMetric("latency", "ticks", 3),
            RouteMetric("energy", "units", 20),
            RouteMetric("bytes", "bytes", 128),
            RouteMetric("risk", "score", 0),
        ),
        implementation_fingerprint=IMPLEMENTATION_FP,
    )
    return ComputationalHostCatalogue((locus,))


def _initial_runtime(config: dict[str, Any]):
    operating_system = HeadlessOS()
    operating_system.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
    )
    system_identity = SystemIdentity("federated-process-recovery-system", 1)
    seed = SystemSeed.from_system(operating_system)
    seed_envelope = SystemSeedEnvelope(
        system_identity,
        "federated-process-recovery",
        "federated-process-recovery",
        seed,
    )
    if not operating_system.seed_admission.admit(seed_envelope).accepted:
        raise RuntimeError("terminal peer seed admission was refused")
    compute_pid = operating_system.environment.kernel.spawn(
        "federated-terminal-compute",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=operating_system.environment.init_pid,
    )
    execute_pid = operating_system.environment.kernel.spawn(
        "federated-terminal-network-gate",
        capabilities=(Capability(COMPUTATIONAL_FABRIC_EXECUTE_RESOURCE, frozenset({"execute"})),),
        parent_pid=operating_system.environment.init_pid,
    )
    _write_json_durable(Path(config["runtime_path"]), {
        "compute_pid": compute_pid,
    })
    catalogue = _catalogue(operating_system, compute_pid, Path(config["calls_path"]))
    advertisement = ComputationalHostAdvertisement.from_locus(catalogue.loci[0], "peer-c")
    return operating_system, execute_pid, catalogue, advertisement


def main(arguments: list[str]) -> int:
    if len(arguments) != 5:
        raise ValueError("terminal worker requires mode, config, cut, marker/result path, and checkpoint directory")
    mode, config_path, cut, marker_or_result, checkpoint_directory = arguments
    if mode not in {"prepare", "live_idle", "restore", "restore_latest"}:
        raise ValueError(f"unsupported terminal worker mode {mode!r}")
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    directory = _directory(config)
    store, coordinator = _open_store(config, checkpoint_directory)
    verified = store.load_latest() if mode in {"restore", "restore_latest"} else None
    if mode == "restore" and verified is not None and verified.manifest.capture_cut != cut:
        raise ValueError("terminal restart cut differs from the quorum-anchored capture cut")

    runtime_payload = (
        json.loads(Path(config["runtime_path"]).read_text(encoding="utf-8"))
        if mode in {"restore", "restore_latest"}
        else None
    )
    listener = SocketTransport.listen("127.0.0.1", int(config["peer_c_port"]))
    print(json.dumps({
        "pid": os.getpid(),
        "peer": "peer-c",
        "port": int(config["peer_c_port"]),
        "mode": mode,
    }, sort_keys=True), flush=True)

    transport = None
    server = None
    try:
        transport = accept_mutual_tls(
            listener,
            "peer-c",
            "peer-b",
            _server_context(config),
            expected_peer_dns=directory.trusted_peers["peer-b"],
            handshake_timeout=8.0,
        )
        if mode in {"prepare", "live_idle"}:
            operating_system, execute_pid, catalogue, advertisement = _initial_runtime(config)
            expected_snapshot = ComputationalPeerSnapshot.from_dict(
                config["peer_snapshots"]["peer-c"]
            )
            if not expected_snapshot.hosts or advertisement.digest != expected_snapshot.hosts[0].digest:
                raise RuntimeError("terminal runtime advertisement differs from the configured peer snapshot")
            server = ComputationalFabricForwardingServer(
                "peer-c",
                "peer-b",
                transport,
                directory,
                operating_system,
                execute_pid,
                origin_peer_id="peer-a",
                origin_channel="application.batch",
                catalogue=catalogue,
                timeout=8.0,
            )

            if mode == "live_idle":
                deadline = time.monotonic() + 90.0
                while time.monotonic() < deadline:
                    server.serve_once()
                    if (
                        server.inbound.channel.next_receive_sequence >= 2
                        and not server.outbound.channel.pending_sequences()
                    ):
                        checkpoint = store.seal(server, "idle")
                        _write_json_durable(Path(marker_or_result), {
                            "stage": "idle_checkpoint",
                            "pid": os.getpid(),
                            "cut": "idle",
                            "generation": checkpoint.generation,
                            "manifest_digest": checkpoint.manifest.digest,
                            "execution_count": len(
                                server.operating_system.hypervisor_arbitration.snapshot()["executions"]
                            ),
                            "request_receive_cursor": server.inbound.channel.next_receive_sequence,
                            "response_pending": list(server.outbound.channel.pending_sequences()),
                            "journal_valid": server.operating_system.environment.kernel.journal.verify(),
                        })
                        while True:
                            time.sleep(60)
                    time.sleep(0.002)
                raise TimeoutError("terminal peer did not reach an acknowledged idle checkpoint")

            def stop_at_cut(stage: str) -> None:
                if stage != cut:
                    return
                checkpoint = store.seal(server, stage)
                _write_json_durable(Path(marker_or_result), {
                    "stage": "cut",
                    "pid": os.getpid(),
                    "cut": stage,
                    "generation": checkpoint.generation,
                    "manifest_digest": checkpoint.manifest.digest,
                    "execution_count": len(
                        server.operating_system.hypervisor_arbitration.snapshot()["executions"]
                    ),
                    "request_receive_cursor": server.inbound.channel.next_receive_sequence,
                    "response_pending": list(server.outbound.channel.pending_sequences()),
                    "journal_valid": server.operating_system.environment.kernel.journal.verify(),
                })
                while True:
                    time.sleep(60)

            deadline = time.monotonic() + 60.0
            while time.monotonic() < deadline:
                server.serve_once(fault_hook=stop_at_cut)
                time.sleep(0.002)
            raise TimeoutError(f"terminal peer did not reach crash cut {cut!r}")

        assert verified is not None and runtime_payload is not None

        def restore_catalogue(restored_os: HeadlessOS) -> ComputationalHostCatalogue:
            return _catalogue(
                restored_os,
                int(runtime_payload["compute_pid"]),
                Path(config["calls_path"]),
            )

        server = verified.restore_server(
            transport,
            directory,
            catalogue_factory=restore_catalogue,
        )
        deadline = time.monotonic() + 90.0
        post_recovery_checkpointed = False
        while time.monotonic() < deadline:
            try:
                server.serve_once()
            except SocketTransportClosed:
                # The authenticated peer stream is replaceable; the terminal
                # operation and response ledger are not. Accept a fresh
                # mutual-TLS adjacency and rebind the same reliable state.
                transport = accept_mutual_tls(
                    listener,
                    "peer-c",
                    "peer-b",
                    _server_context(config),
                    expected_peer_dns=directory.trusted_peers["peer-b"],
                    handshake_timeout=8.0,
                )
                server.rebind_transport(transport)
                continue
            if (
                mode == "restore"
                and config.get("checkpoint_after_first_recovery") is True
                and not post_recovery_checkpointed
                and server.inbound.channel.next_receive_sequence >= 2
                and not server.outbound.channel.pending_sequences()
            ):
                checkpoint = store.seal(server, "idle")
                marker = config.get("post_recovery_checkpoint_marker")
                if not isinstance(marker, str) or not marker:
                    raise ValueError("post-recovery checkpoint marker path is required")
                _write_json_durable(Path(marker), {
                    "stage": "post_recovery_idle",
                    "pid": os.getpid(),
                    "generation": checkpoint.generation,
                    "manifest_digest": checkpoint.manifest.digest,
                    "request_receive_cursor": server.inbound.channel.next_receive_sequence,
                    "response_pending": list(server.outbound.channel.pending_sequences()),
                    "execution_count": len(
                        server.operating_system.hypervisor_arbitration.snapshot()["executions"]
                    ),
                    "journal_valid": server.operating_system.environment.kernel.journal.verify(),
                })
                post_recovery_checkpointed = True
            if (
                server.inbound.channel.next_receive_sequence >= 3
                and not server.outbound.channel.pending_sequences()
            ):
                state = server.operating_system.hypervisor_arbitration.snapshot()
                calls = Path(config["calls_path"]).read_text(encoding="utf-8").splitlines()
                _write_json_durable(Path(marker_or_result), {
                    "stage": "restored_complete",
                    "pid": os.getpid(),
                    "cut": cut,
                    "execution_count": len(state["executions"]),
                    "request_receive_cursor": server.inbound.channel.next_receive_sequence,
                    "response_pending": list(server.outbound.channel.pending_sequences()),
                    "call_count": len(calls),
                    "journal_valid": server.operating_system.environment.kernel.journal.verify(),
                })
                return 0
            time.sleep(0.002)
        raise TimeoutError("terminal peer did not settle two operations after restart")
    finally:
        if server is not None:
            try:
                server.close()
            except Exception:
                pass
        elif transport is not None and not transport.closed:
            transport.close()
        listener.close()
        coordinator.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
