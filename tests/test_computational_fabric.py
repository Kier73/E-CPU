from __future__ import annotations

from dataclasses import replace
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from mailcpu import (
    Capability,
    ComputationalAddress,
    ComputationalAddressResolver,
    ComputationalExecutionAdmissionCoordinator,
    ComputationalFabricAuthority,
    ComputationalFabricAuthorityStore,
    ComputationalFabricAuthorityStoreError,
    ComputationalFabricDirectory,
    ComputationalFabricDiscoveryError,
    ComputationalFabricDiscoveryService,
    ComputationalFabricPeerListener,
    ComputationalFabricPeerClient,
    ComputationalFabricPeerServer,
    ComputationalFabricResolver,
    ComputationalFabricStatus,
    ComputationalHostAdvertisement,
    ComputationalHostCatalogue,
    ComputationalHostLocus,
    ComputationalNetworkLink,
    ComputationalPeerEndpoint,
    ComputationalPeerSnapshot,
    HeadlessOS,
    OperatorRegistry,
    OperatorSpec,
    RouteMetric,
    RouteMetricKey,
    RestartPolicy,
    SubprocessServiceSpec,
    SubprocessServiceSupervisor,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
    VirtualBudget,
    VirtualGroundRef,
    VirtualLayerRuntime,
    VirtualLayerWorkload,
    VirtualOperatorRef,
)
from mailcpu.computational_fabric import ComputationalFabricError
from mailcpu.mtls_transport import accept_mutual_tls
from mailcpu.socket_transport import SocketListener, SocketTransport

GROUND_FP = "a" * 64
PROGRAM_FP = "b" * 64
IMPLEMENTATION_FP = "c" * 64
METRICS = (
    RouteMetricKey("latency", "ticks"),
    RouteMetricKey("energy", "units"),
    RouteMetricKey("bytes", "bytes"),
    RouteMetricKey("risk", "score"),
)


def _openssl(tmp_path: Path, *arguments: str) -> None:
    """Mathematics: Run one bounded certificate-generation command and require successful exit."""
    result = subprocess.run(
        ["openssl", *arguments],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"openssl failed: {result.stderr}")


def _make_test_certificates(tmp_path: Path) -> dict[str, Path]:
    """Mathematics: Create one CA and two mutually trusted leaf certificates with distinct DNS SANs."""
    ca_key = tmp_path / "ca.key"
    ca_cert = tmp_path / "ca.pem"
    _openssl(
        tmp_path,
        "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(ca_key), "-out", str(ca_cert),
        "-days", "30", "-sha256", "-subj", "/CN=Computational Fabric Test CA",
        "-addext", "basicConstraints=critical,CA:TRUE",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
    )
    files: dict[str, Path] = {"ca": ca_cert}
    for role, dns_name in (
        ("server", "peer-b.fabric.test"),
        ("server_c", "peer-c.fabric.test"),
        ("client", "peer-a.fabric.test"),
    ):
        key = tmp_path / f"{role}.key"
        csr = tmp_path / f"{role}.csr"
        certificate = tmp_path / f"{role}.pem"
        extensions = tmp_path / f"{role}.ext"
        _openssl(
            tmp_path,
            "req", "-new", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(csr),
            "-subj", f"/CN={dns_name}",
        )
        extensions.write_text(
            "\n".join((
                f"subjectAltName=DNS:{dns_name}",
                "extendedKeyUsage=clientAuth,serverAuth",
                "basicConstraints=critical,CA:FALSE",
                "keyUsage=critical,digitalSignature,keyEncipherment",
            )) + "\n",
            encoding="utf-8",
        )
        _openssl(
            tmp_path,
            "x509", "-req", "-in", str(csr),
            "-CA", str(ca_cert), "-CAkey", str(ca_key), "-CAcreateserial",
            "-out", str(certificate), "-days", "30", "-sha256",
            "-extfile", str(extensions),
        )
        files[f"{role}_cert"] = certificate
        files[f"{role}_key"] = key
    return files


def _server_context(certificates: dict[str, Path]) -> ssl.SSLContext:
    """Mathematics: Build a TLS server context that requires a CA-verified client certificate."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(certificates["server_cert"]), str(certificates["server_key"]))
    context.load_verify_locations(cafile=str(certificates["ca"]))
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _server_context_c(certificates: dict[str, Path]) -> ssl.SSLContext:
    """Mathematics: Build the peer-C TLS server context with a distinct authenticated DNS identity."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(certificates["server_c_cert"]), str(certificates["server_c_key"]))
    context.load_verify_locations(cafile=str(certificates["ca"]))
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _client_context(certificates: dict[str, Path]) -> ssl.SSLContext:
    """Mathematics: Build a TLS client context with CA validation, hostname checking and a client certificate."""
    context = ssl.create_default_context(
        ssl.Purpose.SERVER_AUTH,
        cafile=str(certificates["ca"]),
    )
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(certificates["client_cert"]), str(certificates["client_key"]))
    return context


def _spec() -> OperatorSpec:
    """Mathematics: Declare one deterministic pure object-to-integer operator contract for the fabric tests."""
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


def _runtime(node_id: str = "node-b") -> VirtualLayerRuntime:
    """Mathematics: Build a local deterministic pure handler with a fixed resource profile."""
    registry = OperatorRegistry()
    registry.register(_spec(), lambda value, workload: value["left"] + value["right"])
    return VirtualLayerRuntime(registry, node_id, frozenset({"cpu"}))


def _locus(peer_id: str = "peer-b", host_id: str = "logical-host-b") -> ComputationalHostLocus:
    """Mathematics: Construct a receiver-local locus whose private process binding is omitted from advertisement."""
    return ComputationalHostLocus.from_runtime(
        host_id=host_id,
        runtime=_runtime(),
        authority_pid=17,
        operator_id="core.sum_pair",
        computational_ground_fingerprints=(GROUND_FP,),
        program_fingerprints=(PROGRAM_FP,),
        costs=_host_costs(3),
        implementation_fingerprint=IMPLEMENTATION_FP,
    )


def _host_costs(latency: int, energy: int = 20, bytes_: int = 128, risk: int = 0):
    """Mathematics: Return the host cost vector in the common fabric objective basis."""
    return (
        RouteMetric("latency", "ticks", latency),
        RouteMetric("energy", "units", energy),
        RouteMetric("bytes", "bytes", bytes_),
        RouteMetric("risk", "score", risk),
    )


def _link(source: str, target: str, latency: int, *, max_frame_bytes: int = 1_048_576):
    """Mathematics: Construct a directed peer adjacency in the shared metric basis."""
    return ComputationalNetworkLink(
        source,
        target,
        (
            RouteMetric("latency", "ticks", latency),
            RouteMetric("energy", "units", 1),
            RouteMetric("bytes", "bytes", 64),
            RouteMetric("risk", "score", 0),
        ),
        max_frame_bytes=max_frame_bytes,
    )


def _endpoint(peer_id: str, *, dns: str | None = None, host: str = "127.0.0.1", port: int = 443):
    """Mathematics: Construct one logical peer endpoint with a distinct TLS DNS identity."""
    return ComputationalPeerEndpoint(
        peer_id,
        dns or f"{peer_id}.fabric.test",
        host,
        port,
    )


def _snapshot(peer_id: str, *, hosts=(), links=(), revision: int = 1, lease: int = 60):
    """Mathematics: Build one peer-owned directory snapshot."""
    return ComputationalPeerSnapshot(
        _endpoint(peer_id),
        revision,
        lease,
        tuple(hosts),
        tuple(links),
    )


def _address(*, max_hops: int = 4) -> ComputationalAddress:
    """Mathematics: Bind a typed workload to the exact Ground, program, operator and route objective."""
    operating_system = HeadlessOS()
    identity = SystemIdentity(f"fabric-system-{id(operating_system)}", 1)
    seed = SystemSeed.from_system(operating_system)
    envelope = SystemSeedEnvelope(identity, "fabric-tests", "fabric-tests", seed)
    assert operating_system.seed_admission.admit(envelope).accepted
    workload = VirtualLayerWorkload(
        workload_id="fabric-route-workload",
        system=identity,
        ground=VirtualGroundRef.from_envelope(envelope),
        intention={"goal": {"kind": "sum"}},
        operators=(VirtualOperatorRef("core.sum_pair", 1, "cpu"),),
        input_value={"left": 4, "right": 5},
        budget=VirtualBudget(10_000, 10_000, 10_000),
        logical_time=7,
        eligible_nodes=("node-b",),
        max_hops=max_hops,
    )
    return ComputationalAddress.from_workload(
        workload,
        "core.sum_pair",
        _spec(),
        GROUND_FP,
        program_fingerprint=PROGRAM_FP,
        metric_order=METRICS,
    )


def _merge_test_snapshot(
    directory: ComputationalFabricDirectory,
    snapshot: ComputationalPeerSnapshot,
    peer_id: str,
    server_name: str,
) -> bool:
    """Mathematics: Exercise revision/lease merge logic with a test-supplied already-authenticated peer identity."""
    return directory._merge_verified_peer_snapshot(
        snapshot,
        authenticated_peer_id=peer_id,
        authenticated_server_name=server_name,
    )


def _directory(*snapshots: ComputationalPeerSnapshot, local_peer_id: str = "peer-a"):
    """Mathematics: Admit one local snapshot and direct authenticated test observations for all remote peer revisions."""
    trusted = {
        snapshot.peer_id: snapshot.endpoint.tls_server_name
        for snapshot in snapshots
        if snapshot.peer_id != local_peer_id
    }
    directory = ComputationalFabricDirectory(local_peer_id, trusted)
    for snapshot in snapshots:
        if snapshot.peer_id == local_peer_id:
            directory.register_local_snapshot(snapshot)
        else:
            directory._merge_verified_peer_snapshot(
                snapshot,
                authenticated_peer_id=snapshot.peer_id,
                authenticated_server_name=snapshot.endpoint.tls_server_name,
            )
    return directory


def test_host_advertisement_is_portable_and_strips_receiver_authority() -> None:
    locus = _locus()
    advertisement = ComputationalHostAdvertisement.from_locus(locus, "peer-b")

    restored = ComputationalHostAdvertisement.from_dict(advertisement.to_dict())

    assert restored == advertisement
    assert restored.digest == advertisement.digest
    assert restored.peer_id == "peer-b"
    assert restored.host_id == "logical-host-b"
    assert "authority_pid" not in restored.to_dict()
    assert "runtime_binding" not in restored.to_dict()
    assert "handler_binding" not in restored.to_dict()


def test_peer_snapshot_round_trip_binds_only_peer_owned_hosts_and_outgoing_links() -> None:
    ad = ComputationalHostAdvertisement.from_locus(_locus(), "peer-b")
    snapshot = _snapshot("peer-b", hosts=(ad,), links=(_link("peer-b", "peer-a", 2),))

    restored = ComputationalPeerSnapshot.from_dict(snapshot.to_dict())

    assert restored == snapshot
    assert restored.digest == snapshot.digest
    with pytest.raises(ComputationalFabricError, match="another peer"):
        ComputationalPeerSnapshot(
            _endpoint("peer-c"),
            1,
            60,
            (ad,),
            (),
        )
    with pytest.raises(ComputationalFabricError, match="outgoing"):
        ComputationalPeerSnapshot(
            _endpoint("peer-b"),
            1,
            60,
            (),
            (_link("peer-c", "peer-b", 2),),
        )


def test_peer_authority_snapshot_restores_revisioned_advertisements() -> None:
    endpoint = _endpoint("peer-b")
    authority = ComputationalFabricAuthority(endpoint, lease_seconds=45)
    advertisement = ComputationalHostAdvertisement.from_locus(_locus(), "peer-b")
    authority.register_host(advertisement)
    authority.register_link(_link("peer-b", "peer-c", 7))
    original = authority.snapshot()

    restored = ComputationalFabricAuthority.from_snapshot(
        ComputationalPeerSnapshot.from_dict(original.to_dict())
    )

    assert restored.snapshot() == original
    assert restored.snapshot().digest == original.digest
    assert restored.revision == original.revision
    assert restored.register_host(advertisement) == advertisement.digest
    assert restored.revision == original.revision


def test_directory_requires_direct_peer_identity_and_monotonic_revisions() -> None:
    first = _snapshot("peer-b")
    directory = ComputationalFabricDirectory(
        "peer-a",
        {"peer-b": "peer-b.fabric.test"},
    )
    with pytest.raises(ComputationalFabricError, match="not an explicitly trusted"):
        directory._merge_verified_peer_snapshot(
            first,
            authenticated_peer_id="peer-c",
            authenticated_server_name="peer-c.fabric.test",
        )
    with pytest.raises(ComputationalFabricError, match="DNS identity"):
        directory._merge_verified_peer_snapshot(
            first,
            authenticated_peer_id="peer-b",
            authenticated_server_name="impostor.fabric.test",
        )

    assert directory._merge_verified_peer_snapshot(
        first,
        authenticated_peer_id="peer-b",
        authenticated_server_name="peer-b.fabric.test",
    )
    assert not directory._merge_verified_peer_snapshot(
        first,
        authenticated_peer_id="peer-b",
        authenticated_server_name="peer-b.fabric.test",
    )
    with pytest.raises(ComputationalFabricError, match="rollback"):
        directory._merge_verified_peer_snapshot(
            _snapshot("peer-b", revision=0),
            authenticated_peer_id="peer-b",
            authenticated_server_name="peer-b.fabric.test",
        )
    with pytest.raises(ComputationalFabricError, match="equivocated"):
        directory._merge_verified_peer_snapshot(
            _snapshot("peer-b", revision=1, lease=45),
            authenticated_peer_id="peer-b",
            authenticated_server_name="peer-b.fabric.test",
        )


def test_public_directory_merge_requires_the_authenticated_transport_object() -> None:
    directory = ComputationalFabricDirectory(
        "peer-a",
        {"peer-b": "peer-b.fabric.test"},
    )
    with pytest.raises(TypeError):
        directory.merge_authenticated_snapshot(
            _snapshot("peer-b"),
            authenticated_peer_id="peer-b",
            authenticated_server_name="peer-b.fabric.test",
        )


def test_directory_peer_capacity_reserves_local_identity_before_local_snapshot() -> None:
    directory = ComputationalFabricDirectory(
        "peer-a",
        {"peer-b": "peer-b.fabric.test"},
        max_peers=2,
    )
    directory._merge_verified_peer_snapshot(
        _snapshot("peer-b"),
        authenticated_peer_id="peer-b",
        authenticated_server_name="peer-b.fabric.test",
    )

    assert directory.register_local_snapshot(_snapshot("peer-a"))
    assert tuple(item.peer_id for item in directory.active_snapshots) == ("peer-a", "peer-b")


def test_directory_trust_map_is_detached_from_caller_mutation() -> None:
    configured = {"peer-b": "peer-b.fabric.test"}
    directory = ComputationalFabricDirectory("peer-a", configured)
    configured["peer-b"] = "attacker.fabric.test"
    exposed = directory.trusted_peers
    exposed["peer-b"] = "attacker.fabric.test"

    with pytest.raises(ComputationalFabricError, match="exactly one logical peer"):
        ComputationalFabricDirectory(
            "peer-a",
            {
                "peer-b": "shared.fabric.test",
                "peer-c": "shared.fabric.test",
            },
        )
    broader_trust = ComputationalFabricDirectory(
        "peer-a",
        {
            "peer-b": "peer-b.fabric.test",
            "peer-c": "peer-c.fabric.test",
        },
        max_peers=2,
    )
    assert broader_trust.trusted_peers == {
        "peer-b": "peer-b.fabric.test",
        "peer-c": "peer-c.fabric.test",
    }
    snapshot = _snapshot("peer-b")
    assert directory.trusted_peers == {"peer-b": "peer-b.fabric.test"}
    assert directory._merge_verified_peer_snapshot(
        snapshot,
        authenticated_peer_id="peer-b",
        authenticated_server_name="peer-b.fabric.test",
    )


def test_fabric_resolver_uses_one_lease_validated_directory_view() -> None:
    ticks = iter((90.0, 100.0, 105.0, 200.0, 201.0, 202.0))
    calls: list[float] = []

    def monotonic() -> float:
        value = next(ticks, 300.0)
        calls.append(value)
        return value

    advertisement = ComputationalHostAdvertisement.from_locus(_locus(), "peer-b")
    directory = ComputationalFabricDirectory(
        "peer-a",
        {"peer-b": "peer-b.fabric.test"},
        monotonic=monotonic,
    )
    directory.register_local_snapshot(
        _snapshot("peer-a", links=(_link("peer-a", "peer-b", 1),))
    )
    directory._merge_verified_peer_snapshot(
        _snapshot("peer-b", hosts=(advertisement,), lease=10),
        authenticated_peer_id="peer-b",
        authenticated_server_name="peer-b.fabric.test",
    )
    result = ComputationalFabricResolver().resolve(
        _address(),
        directory,
        origin_peer_id="peer-a",
    )

    assert result.status is ComputationalFabricStatus.FOUND
    assert result.witness is not None
    assert result.witness.peer_path == ("peer-a", "peer-b")
    # Capacity observes the local registration and peer merge once each.
    # The resolver then captures one active view for both directory and
    # topology digests, so a lease cannot expire between those identities.
    assert calls == [90.0, 100.0, 105.0]


def test_directory_leases_expire_on_receiver_monotonic_time() -> None:
    clock = [100.0]
    snapshot = _snapshot("peer-b", lease=5)
    directory = ComputationalFabricDirectory(
        "peer-a",
        {"peer-b": "peer-b.fabric.test"},
        monotonic=lambda: clock[0],
    )
    directory._merge_verified_peer_snapshot(
        snapshot,
        authenticated_peer_id="peer-b",
        authenticated_server_name="peer-b.fabric.test",
    )
    assert tuple(item.peer_id for item in directory.active_snapshots) == ("peer-b",)

    clock[0] = 104.999
    assert directory.expired_peer_ids == ()
    clock[0] = 105.0
    assert directory.expired_peer_ids == ("peer-b",)
    assert directory.active_snapshots == ()
    assert directory.purge_expired() == ("peer-b",)
    assert directory.peer_snapshots == ()


def test_purging_expired_peer_keeps_revision_rollback_high_water() -> None:
    first = _snapshot("peer-b", revision=7, lease=5)
    directory = ComputationalFabricDirectory(
        "peer-a",
        {"peer-b": "peer-b.fabric.test"},
        monotonic=lambda: 100.0,
    )
    assert directory._merge_verified_peer_snapshot(
        first,
        authenticated_peer_id="peer-b",
        authenticated_server_name="peer-b.fabric.test",
    )
    assert directory.peer_revision_high_water == (
        ("peer-b", 7, first.digest),
    )

    clock = [106.0]
    directory._monotonic = lambda: clock[0]
    assert directory.purge_expired() == ("peer-b",)
    assert directory.peer_snapshots == ()
    assert directory.peer_revision_high_water == (
        ("peer-b", 7, first.digest),
    )
    with pytest.raises(ComputationalFabricError, match="rollback"):
        directory._merge_verified_peer_snapshot(
            _snapshot("peer-b", revision=6),
            authenticated_peer_id="peer-b",
            authenticated_server_name="peer-b.fabric.test",
        )
    with pytest.raises(ComputationalFabricError, match="equivocated"):
        directory._merge_verified_peer_snapshot(
            _snapshot("peer-b", revision=7, lease=45),
            authenticated_peer_id="peer-b",
            authenticated_server_name="peer-b.fabric.test",
        )


def test_directory_checkpoint_preserves_anti_rollback_and_requires_fresh_peer_observation() -> None:
    clock = [100.0]
    first = _snapshot("peer-b", revision=7, lease=5)
    directory = ComputationalFabricDirectory(
        "peer-a",
        {"peer-b": "peer-b.fabric.test"},
        monotonic=lambda: clock[0],
    )
    assert directory._merge_verified_peer_snapshot(
        first,
        authenticated_peer_id="peer-b",
        authenticated_server_name="peer-b.fabric.test",
    )

    checkpoint = directory.checkpoint()
    assert checkpoint["schema"] == "mailcpu.computational-fabric-directory-checkpoint.v1"
    assert checkpoint["peer_revision_high_water"] == [
        {"peer_id": "peer-b", "revision": 7, "digest": first.digest},
    ]

    # Restoring a checkpoint restores anti-rollback memory, not a remote
    # snapshot or a lease deadline measured by another process's clock.
    clock[0] = 1_000.0
    restored = ComputationalFabricDirectory.from_checkpoint(
        checkpoint,
        monotonic=lambda: clock[0],
    )
    assert restored.peer_snapshots == ()
    assert restored.active_snapshots == ()
    assert restored.peer_revision_high_water == (("peer-b", 7, first.digest),)

    with pytest.raises(ComputationalFabricError, match="rollback"):
        restored._merge_verified_peer_snapshot(
            _snapshot("peer-b", revision=6),
            authenticated_peer_id="peer-b",
            authenticated_server_name="peer-b.fabric.test",
        )
    with pytest.raises(ComputationalFabricError, match="equivocated"):
        restored._merge_verified_peer_snapshot(
            _snapshot("peer-b", revision=7, lease=45),
            authenticated_peer_id="peer-b",
            authenticated_server_name="peer-b.fabric.test",
        )

    assert restored._merge_verified_peer_snapshot(
        first,
        authenticated_peer_id="peer-b",
        authenticated_server_name="peer-b.fabric.test",
    )
    assert tuple(item.peer_id for item in restored.active_snapshots) == ("peer-b",)

    tampered = dict(checkpoint)
    tampered["max_links"] = checkpoint["max_links"] + 1
    with pytest.raises(ComputationalFabricError, match="digest"):
        ComputationalFabricDirectory.from_checkpoint(tampered)


def test_local_snapshot_registration_checks_restored_revision_high_water() -> None:
    local = _snapshot("peer-a", revision=4)
    directory = ComputationalFabricDirectory("peer-a", {"peer-b": "peer-b.fabric.test"})
    assert directory.register_local_snapshot(local)
    restored = ComputationalFabricDirectory.from_checkpoint(directory.checkpoint())

    with pytest.raises(ComputationalFabricError, match="cannot move backwards"):
        restored.register_local_snapshot(_snapshot("peer-a", revision=3))
    with pytest.raises(ComputationalFabricError, match="equivocated"):
        restored.register_local_snapshot(_snapshot("peer-a", revision=4, lease=45))

    assert restored.register_local_snapshot(local)
    assert tuple(item.peer_id for item in restored.active_snapshots) == ("peer-a",)
    assert not restored.register_local_snapshot(local)


def test_expired_peer_snapshots_do_not_consume_live_directory_capacity() -> None:
    clock = [100.0]
    host_b = ComputationalHostAdvertisement.from_locus(
        _locus("peer-b", "logical-host-b"),
        "peer-b",
    )
    host_c = ComputationalHostAdvertisement.from_locus(
        _locus("peer-c", "logical-host-c"),
        "peer-c",
    )
    directory = ComputationalFabricDirectory(
        "peer-a",
        {
            "peer-b": "peer-b.fabric.test",
            "peer-c": "peer-c.fabric.test",
        },
        monotonic=lambda: clock[0],
        max_peers=2,
        max_hosts=1,
    )
    assert directory._merge_verified_peer_snapshot(
        _snapshot("peer-b", hosts=(host_b,), lease=5),
        authenticated_peer_id="peer-b",
        authenticated_server_name="peer-b.fabric.test",
    )
    clock[0] = 105.0

    # Explicit purge is not required to free active capacity. The expired
    # snapshot may remain as last-known metadata, but it no longer counts as
    # a live peer/host/link advertisement.
    assert directory._merge_verified_peer_snapshot(
        _snapshot("peer-c", hosts=(host_c,), lease=30),
        authenticated_peer_id="peer-c",
        authenticated_server_name="peer-c.fabric.test",
    )
    assert tuple(item.peer_id for item in directory.active_snapshots) == ("peer-c",)
    assert {item.peer_id for item in directory.peer_snapshots} == {"peer-b", "peer-c"}
    assert directory.peer_revision_high_water == (
        ("peer-b", 1, _snapshot("peer-b", hosts=(host_b,), lease=5).digest),
        ("peer-c", 1, _snapshot("peer-c", hosts=(host_c,), lease=30).digest),
    )




def test_directory_rejects_a_second_live_remote_when_local_slot_is_reserved() -> None:
    """Mathematics: max_peers bounds the reserved local identity plus simultaneously live remote leases."""
    directory = ComputationalFabricDirectory(
        "peer-a",
        {
            "peer-b": "peer-b.fabric.test",
            "peer-c": "peer-c.fabric.test",
        },
        max_peers=2,
    )
    assert directory._merge_verified_peer_snapshot(
        _snapshot("peer-b"),
        authenticated_peer_id="peer-b",
        authenticated_server_name="peer-b.fabric.test",
    )
    with pytest.raises(ComputationalFabricError, match="peer bound"):
        directory._merge_verified_peer_snapshot(
            _snapshot("peer-c"),
            authenticated_peer_id="peer-c",
            authenticated_server_name="peer-c.fabric.test",
        )


def test_fabric_resolver_selects_lowest_cost_multi_hop_peer_path() -> None:
    ad = ComputationalHostAdvertisement.from_locus(_locus(), "peer-b")
    peer_a = _snapshot(
        "peer-a",
        links=(
            _link("peer-a", "peer-b", 6),
            _link("peer-a", "peer-c", 1),
        ),
    )
    peer_b = _snapshot("peer-b", hosts=(ad,))
    peer_c = _snapshot(
        "peer-c",
        links=(_link("peer-c", "peer-b", 1),),
    )
    directory = _directory(peer_a, peer_b, peer_c)

    result = ComputationalFabricResolver().resolve(
        _address(),
        directory,
        origin_peer_id="peer-a",
        max_hops=4,
    )

    assert result.status is ComputationalFabricStatus.FOUND
    assert result.authoritative is False
    assert result.witness is not None
    assert result.witness.authoritative is False
    assert result.witness.peer_path == ("peer-a", "peer-c", "peer-b")
    assert len(result.witness.link_ids) == 2
    assert result.witness.target_host.host_id == "logical-host-b"
    assert tuple(item.amount for item in result.witness.network_costs if item.name == "latency") == (2,)
    assert tuple(item.amount for item in result.witness.host_costs if item.name == "latency") == (3,)
    assert tuple(item.amount for item in result.witness.total_costs if item.name == "latency") == (5,)
    assert tuple(item.peer_id for item in result.witness.peer_endpoints) == result.witness.peer_path
    assert result.witness.to_dict()["authoritative"] is False
    restored_witness = type(result.witness).from_dict(result.witness.to_dict())
    restored_result = type(result).from_dict(result.to_dict())
    assert restored_witness == result.witness
    assert restored_witness.digest == result.witness.digest
    assert restored_result.digest == result.digest


def test_fabric_route_uses_stable_path_tie_break_and_never_invents_reverse_edges() -> None:
    ad = ComputationalHostAdvertisement.from_locus(_locus(), "peer-d")
    snapshots = (
        _snapshot("peer-a", links=(_link("peer-a", "peer-c", 1), _link("peer-a", "peer-b", 1))),
        _snapshot("peer-b", links=(_link("peer-b", "peer-d", 1),)),
        _snapshot("peer-c", links=(_link("peer-c", "peer-d", 1),)),
        _snapshot("peer-d", hosts=(ad,)),
    )
    directory = _directory(*snapshots)

    result = ComputationalFabricResolver().resolve(
        _address(),
        directory,
        origin_peer_id="peer-a",
    )

    assert result.status is ComputationalFabricStatus.FOUND
    assert result.witness is not None
    assert result.witness.peer_path == ("peer-a", "peer-b", "peer-d")

    reverse_only = _directory(
        _snapshot("peer-a"),
        _snapshot("peer-d", hosts=(ad,), links=(_link("peer-d", "peer-a", 1),)),
    )
    unreachable = ComputationalFabricResolver().resolve(
        _address(),
        reverse_only,
        origin_peer_id="peer-a",
    )
    assert unreachable.status is ComputationalFabricStatus.UNREACHABLE
    assert unreachable.witness is None


def test_fabric_resolver_enforces_hop_frame_budget_and_implementation_pins() -> None:
    ad = ComputationalHostAdvertisement.from_locus(_locus(), "peer-c")
    snapshots = (
        _snapshot("peer-a", links=(_link("peer-a", "peer-b", 1),)),
        _snapshot("peer-b", links=(_link("peer-b", "peer-c", 1),)),
        _snapshot("peer-c", hosts=(ad,)),
    )
    directory = _directory(*snapshots)
    resolver = ComputationalFabricResolver()

    hop_limited = resolver.resolve(
        _address(),
        directory,
        origin_peer_id="peer-a",
        max_hops=1,
    )
    assert hop_limited.status is ComputationalFabricStatus.BUDGET_EXHAUSTED
    assert any(item.code.value == "hop_limit" for item in hop_limited.blockers)

    ad_unpinned = ComputationalHostAdvertisement(
        ad.host_id, ad.node_id, ad.peer_id, ad.operator_spec, ad.substrates,
        ad.computational_ground_fingerprints, ad.program_fingerprints,
        ad.supports_ground_program_compilation, ad.supports_structural_memory,
        None, ad.costs, ad.virtual_capacity, ad.max_energy, ad.max_bytes,
        ad.max_virtual_ticks,
    )
    unpinned_directory = _directory(
        snapshots[0],
        snapshots[1],
        _snapshot("peer-c", hosts=(ad_unpinned,)),
    )
    unpinned = resolver.resolve(
        _address(),
        unpinned_directory,
        origin_peer_id="peer-a",
    )
    assert unpinned.status is ComputationalFabricStatus.BLOCKED
    assert any(item.code.value == "implementation_missing" for item in unpinned.blockers)

    tiny_link_directory = _directory(
        _snapshot("peer-a", links=(_link("peer-a", "peer-b", 1, max_frame_bytes=8),)),
        snapshots[1],
        snapshots[2],
    )
    tiny = resolver.resolve(
        _address(),
        tiny_link_directory,
        origin_peer_id="peer-a",
    )
    assert tiny.status is ComputationalFabricStatus.BUDGET_EXHAUSTED
    assert any(item.code.value == "resource_limit" for item in tiny.blockers)


def test_fabric_resolver_fails_closed_on_incompatible_computational_ground() -> None:
    good = ComputationalHostAdvertisement.from_locus(_locus(), "peer-b")
    wrong_ground = ComputationalHostAdvertisement(
        good.host_id, good.node_id, good.peer_id, good.operator_spec, good.substrates,
        ("d" * 64,), good.program_fingerprints, good.supports_ground_program_compilation,
        good.supports_structural_memory, good.implementation_fingerprint, good.costs,
        good.virtual_capacity, good.max_energy, good.max_bytes, good.max_virtual_ticks,
    )
    directory = _directory(
        _snapshot("peer-a", links=(_link("peer-a", "peer-b", 1),)),
        _snapshot("peer-b", hosts=(wrong_ground,)),
    )
    blocked = ComputationalFabricResolver().resolve(
        _address(), directory, origin_peer_id="peer-a"
    )
    assert blocked.status is ComputationalFabricStatus.BLOCKED
    assert any(item.code.value == "ground_mismatch" for item in blocked.blockers)


def test_fabric_resolver_requires_ground_bounded_policy_for_unpinned_programs() -> None:
    advertisement = ComputationalHostAdvertisement.from_locus(_locus(), "peer-b")
    workload = _address().workload
    unpinned_address = ComputationalAddress.from_workload(
        workload,
        "core.sum_pair",
        _spec(),
        GROUND_FP,
        program_fingerprint=None,
        metric_order=METRICS,
    )
    no_policy = replace(
        advertisement,
        program_fingerprints=(),
        supports_ground_program_compilation=False,
    )
    dynamic_policy = replace(
        advertisement,
        program_fingerprints=(),
        supports_ground_program_compilation=True,
    )
    no_policy_directory = _directory(
        _snapshot("peer-a", links=(_link("peer-a", "peer-b", 1),)),
        _snapshot("peer-b", hosts=(no_policy,)),
    )
    denied = ComputationalFabricResolver().resolve(
        unpinned_address,
        no_policy_directory,
        origin_peer_id="peer-a",
    )
    assert denied.status is ComputationalFabricStatus.BLOCKED
    assert any(item.code.value == "program_mismatch" for item in denied.blockers)

    dynamic_directory = _directory(
        _snapshot("peer-a", links=(_link("peer-a", "peer-b", 1),)),
        _snapshot("peer-b", hosts=(dynamic_policy,)),
    )
    accepted = ComputationalFabricResolver().resolve(
        unpinned_address,
        dynamic_directory,
        origin_peer_id="peer-a",
    )
    assert accepted.status is ComputationalFabricStatus.FOUND
    assert accepted.witness is not None
    assert accepted.witness.target_host.program_fingerprints == ()


def test_fabric_resolver_applies_aggregate_network_cost_ceilings() -> None:
    advertisement = ComputationalHostAdvertisement.from_locus(_locus(), "peer-b")
    directory = _directory(
        _snapshot("peer-a", links=(_link("peer-a", "peer-b", 4),)),
        _snapshot("peer-b", hosts=(advertisement,)),
    )
    address = replace(
        _address(),
        resource_ceilings=(RouteMetric("latency", "ticks", 3),),
    )

    result = ComputationalFabricResolver().resolve(
        address,
        directory,
        origin_peer_id="peer-a",
    )

    assert result.status is ComputationalFabricStatus.BUDGET_EXHAUSTED
    assert result.witness is None
    assert any(item.code.value == "resource_limit" for item in result.blockers)


def test_fabric_resolver_obeys_workload_hop_budget_and_local_origin_identity() -> None:
    advertisement = ComputationalHostAdvertisement.from_locus(_locus(), "peer-c")
    directory = _directory(
        _snapshot("peer-a", links=(_link("peer-a", "peer-b", 1),)),
        _snapshot("peer-b", links=(_link("peer-b", "peer-c", 1),)),
        _snapshot("peer-c", hosts=(advertisement,)),
    )
    with pytest.raises(ComputationalFabricError, match="origin_peer_id must equal"):
        ComputationalFabricResolver().resolve(
            _address(),
            directory,
            origin_peer_id="peer-b",
        )

    limited = ComputationalFabricResolver().resolve(
        _address(max_hops=1),
        directory,
        origin_peer_id="peer-a",
        max_hops=8,
    )
    assert limited.status is ComputationalFabricStatus.BUDGET_EXHAUSTED
    assert any(item.code.value == "hop_limit" for item in limited.blockers)


def test_fabric_resolver_preserves_shorter_paths_when_the_cheapest_prefix_exceeds_hop_budget() -> None:
    advertisement = ComputationalHostAdvertisement.from_locus(_locus(), "peer-d")
    directory = _directory(
        _snapshot(
            "peer-a",
            links=(
                _link("peer-a", "peer-b", 1),
                _link("peer-a", "peer-c", 5),
            ),
        ),
        _snapshot("peer-b", links=(_link("peer-b", "peer-c", 1),)),
        _snapshot("peer-c", links=(_link("peer-c", "peer-d", 1),)),
        _snapshot("peer-d", hosts=(advertisement,)),
    )

    result = ComputationalFabricResolver().resolve(
        _address(),
        directory,
        origin_peer_id="peer-a",
        max_hops=2,
    )

    assert result.status is ComputationalFabricStatus.FOUND
    assert result.witness is not None
    assert result.witness.peer_path == ("peer-a", "peer-c", "peer-d")
    assert tuple(
        item.amount for item in result.witness.network_costs if item.name == "latency"
    ) == (6,)


def test_fabric_resolver_rejects_program_and_operator_contract_mismatches() -> None:
    advertisement = ComputationalHostAdvertisement.from_locus(_locus(), "peer-b")
    program_mismatch = replace(advertisement, program_fingerprints=("d" * 64,))
    contract_mismatch = replace(
        advertisement,
        operator_spec=replace(
            advertisement.operator_spec,
            description="A different operator contract with the same operator name",
        ),
    )
    for candidate, code in (
        (program_mismatch, "program_mismatch"),
        (contract_mismatch, "contract_mismatch"),
    ):
        directory = _directory(
            _snapshot("peer-a", links=(_link("peer-a", "peer-b", 1),)),
            _snapshot("peer-b", hosts=(candidate,)),
        )
        result = ComputationalFabricResolver().resolve(
            _address(),
            directory,
            origin_peer_id="peer-a",
        )
        assert result.status is ComputationalFabricStatus.BLOCKED
        assert result.witness is None
        assert any(item.code.value == code for item in result.blockers)


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL CLI is required for ephemeral mutual-TLS certificates")
def test_mutual_tls_peer_client_discovers_and_merges_remote_host_snapshot(tmp_path) -> None:
    certificates = _make_test_certificates(tmp_path)
    server_context = _server_context(certificates)
    client_context = _client_context(certificates)
    listener = SocketTransport.listen("127.0.0.1", 0)
    endpoint = ComputationalPeerEndpoint(
        "peer-b",
        "peer-b.fabric.test",
        "127.0.0.1",
        listener.getsockname()[1],
    )
    authority = ComputationalFabricAuthority(endpoint, lease_seconds=30)
    authority.register_host(ComputationalHostAdvertisement.from_locus(_locus(), "peer-b"))

    server_result: dict[str, object] = {}
    server_errors: list[BaseException] = []
    stop = threading.Event()

    def serve() -> None:
        """Mathematics: Accept the one expected peer certificate and service its reliable directory request loop."""
        try:
            transport = accept_mutual_tls(
                listener,
                "peer-b",
                "peer-a",
                server_context,
                expected_peer_dns="peer-a.fabric.test",
            )
            server = ComputationalFabricPeerServer(
                authority,
                transport,
                "peer-a",
                expected_client_dns="peer-a.fabric.test",
            )
            server_result["server"] = server
            server.serve_forever(stop)
        except BaseException as exc:
            server_errors.append(exc)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    client: ComputationalFabricPeerClient | None = None
    try:
        directory = ComputationalFabricDirectory(
            "peer-a",
            {"peer-b": "peer-b.fabric.test"},
        )
        directory.register_local_snapshot(
            _snapshot("peer-a", links=(_link("peer-a", "peer-b", 2),))
        )
        client = ComputationalFabricPeerClient.connect_mutual_tls(
            "peer-a",
            endpoint,
            client_context,
            timeout=3.0,
        )
        assert client.refresh(directory)
        assert tuple(item.peer_id for item in directory.active_snapshots) == ("peer-a", "peer-b")
        assert directory.hosts[0].host_id == "logical-host-b"
        assert directory.hosts[0].implementation_fingerprint == IMPLEMENTATION_FP
        routed = ComputationalFabricResolver().resolve(
            _address(),
            directory,
            origin_peer_id="peer-a",
        )
        assert routed.status is ComputationalFabricStatus.FOUND
        assert routed.witness is not None
        assert routed.witness.peer_path == ("peer-a", "peer-b")
        assert routed.witness.target_host.host_id == "logical-host-b"
        assert server_result.get("server") is not None
    finally:
        stop.set()
        if client is not None:
            client.close()
        listener.close()
        thread.join(timeout=3.0)
    assert not thread.is_alive()
    assert not server_errors, repr(server_errors)


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL CLI is required for ephemeral mutual-TLS certificates")
def test_three_peer_federation_discovers_directly_and_routes_over_two_authenticated_hops(tmp_path) -> None:
    """A preferred remote host fails over to an active peer and returns after its lease is refreshed."""
    certificates = _make_test_certificates(tmp_path)
    client_context = _client_context(certificates)
    listeners = {
        "peer-b": SocketTransport.listen("127.0.0.1", 0),
        "peer-c": SocketTransport.listen("127.0.0.1", 0),
    }
    endpoints = {
        peer_id: ComputationalPeerEndpoint(
            peer_id,
            f"{peer_id}.fabric.test",
            "127.0.0.1",
            listener.getsockname()[1],
        )
        for peer_id, listener in listeners.items()
    }
    authority_b = ComputationalFabricAuthority(endpoints["peer-b"], lease_seconds=10)
    authority_b.register_link(_link("peer-b", "peer-c", 3))
    fallback_locus = replace(
        _locus("peer-b", "logical-host-b"),
        costs=_host_costs(50),
    )
    authority_b.register_host(
        ComputationalHostAdvertisement.from_locus(fallback_locus, "peer-b")
    )
    authority_c = ComputationalFabricAuthority(endpoints["peer-c"], lease_seconds=5)
    authority_c.register_host(
        ComputationalHostAdvertisement.from_locus(
            _locus("peer-c", "logical-host-c"),
            "peer-c",
        )
    )
    contexts = {
        "peer-b": _server_context(certificates),
        "peer-c": _server_context_c(certificates),
    }
    authorities = {"peer-b": authority_b, "peer-c": authority_c}
    server_errors: list[BaseException] = []
    stop = threading.Event()
    servers: dict[str, ComputationalFabricPeerServer] = {}

    def serve(peer_id: str) -> None:
        """Mathematics: Accept one configured peer-A client and service its reliable snapshot requests."""
        try:
            transport = accept_mutual_tls(
                listeners[peer_id],
                peer_id,
                "peer-a",
                contexts[peer_id],
                expected_peer_dns="peer-a.fabric.test",
            )
            server = ComputationalFabricPeerServer(
                authorities[peer_id],
                transport,
                "peer-a",
                expected_client_dns="peer-a.fabric.test",
            )
            servers[peer_id] = server
            server.serve_forever(stop)
        except BaseException as exc:
            server_errors.append(exc)

    threads = [
        threading.Thread(target=serve, args=(peer_id,), daemon=True)
        for peer_id in ("peer-b", "peer-c")
    ]
    for thread in threads:
        thread.start()

    clock = [100.0]
    directory = ComputationalFabricDirectory(
        "peer-a",
        {
            "peer-b": "peer-b.fabric.test",
            "peer-c": "peer-c.fabric.test",
        },
        monotonic=lambda: clock[0],
    )
    directory.register_local_snapshot(
        _snapshot("peer-a", links=(_link("peer-a", "peer-b", 2),))
    )
    clients: dict[str, ComputationalFabricPeerClient] = {}
    try:
        for peer_id in ("peer-b", "peer-c"):
            clients[peer_id] = ComputationalFabricPeerClient.connect_mutual_tls(
                "peer-a",
                endpoints[peer_id],
                client_context,
                timeout=3.0,
            )
            assert clients[peer_id].refresh(directory)

        active_ids = tuple(item.peer_id for item in directory.active_snapshots)
        assert active_ids == ("peer-a", "peer-b", "peer-c")
        first = ComputationalFabricResolver().resolve(
            _address(max_hops=3),
            directory,
            origin_peer_id="peer-a",
        )
        assert first.status is ComputationalFabricStatus.FOUND
        assert first.witness is not None
        assert first.witness.peer_path == ("peer-a", "peer-b", "peer-c")
        assert first.witness.target_host.host_id == "logical-host-c"
        assert tuple(item.amount for item in first.witness.network_costs if item.name == "latency") == (5,)

        # The preferred host on C expires first. B remains live and has a
        # compatible but more expensive host, so the planner must fail over
        # to B rather than declaring the entire operator unreachable.
        clock[0] = 105.0
        assert tuple(item.peer_id for item in directory.active_snapshots) == ("peer-a", "peer-b")
        fallback = ComputationalFabricResolver().resolve(
            _address(max_hops=3),
            directory,
            origin_peer_id="peer-a",
        )
        assert fallback.status is ComputationalFabricStatus.FOUND
        assert fallback.witness is not None
        assert fallback.witness.peer_path == ("peer-a", "peer-b")
        assert fallback.witness.target_host.host_id == "logical-host-b"
        assert tuple(item.amount for item in fallback.witness.total_costs if item.name == "latency") == (52,)

        # Re-observing C's unchanged snapshot over the still-authenticated
        # direct channel renews its receiver-local lease. The planner should
        # return to C because its network+host objective is now lower.
        assert not clients["peer-c"].refresh(directory)
        refreshed = ComputationalFabricResolver().resolve(
            _address(max_hops=3),
            directory,
            origin_peer_id="peer-a",
        )
        assert refreshed.status is ComputationalFabricStatus.FOUND
        assert refreshed.witness is not None
        assert refreshed.witness.peer_path == ("peer-a", "peer-b", "peer-c")
        assert refreshed.witness.target_host.host_id == "logical-host-c"
        assert tuple(item.amount for item in refreshed.witness.total_costs if item.name == "latency") == (8,)
        assert not server_errors
    finally:
        for client in clients.values():
            client.close()
        stop.set()
        for listener in listeners.values():
            listener.close()
        for thread in threads:
            thread.join(timeout=3.0)
    assert all(not thread.is_alive() for thread in threads)
    assert not server_errors, repr(server_errors)


def test_fabric_route_terminates_in_fresh_local_resolution_and_hypervisor_execution() -> None:
    """A non-authoritative remote route locates the destination; only a fresh local witness can enter Hypervisor execution."""
    destination_os = HeadlessOS()
    system_identity = SystemIdentity("federated-execution-system", 1)
    seed = SystemSeed.from_system(destination_os)
    envelope = SystemSeedEnvelope(
        system_identity,
        "federated-execution",
        "federated-execution",
        seed,
    )
    assert destination_os.seed_admission.admit(envelope).accepted
    system_ground = VirtualGroundRef.from_envelope(envelope)

    calls: list[str] = []
    registry = OperatorRegistry()
    spec = _spec()

    def execute(value, workload):
        """Mathematics: Execute the pure sum only after receiver-local Hypervisor admission."""
        calls.append(workload.workload_id)
        return value["left"] + value["right"]

    registry.register(spec, execute)
    runtime = VirtualLayerRuntime(registry, "node-b", frozenset({"cpu"}))
    pid = destination_os.environment.kernel.spawn(
        "federated-compute-host",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=destination_os.environment.init_pid,
    )
    locus = ComputationalHostLocus.from_runtime(
        host_id="logical-host-c",
        runtime=runtime,
        authority_pid=pid,
        operator_id="core.sum_pair",
        computational_ground_fingerprints=(GROUND_FP,),
        program_fingerprints=(PROGRAM_FP,),
        costs=_host_costs(3),
        implementation_fingerprint=IMPLEMENTATION_FP,
    )
    catalogue = ComputationalHostCatalogue((locus,))

    workload = VirtualLayerWorkload(
        workload_id="federated-sum-workload",
        system=system_identity,
        ground=system_ground,
        intention={"goal": {"kind": "sum", "expected": 9}},
        operators=(VirtualOperatorRef("core.sum_pair", 1, "cpu"),),
        input_value={"left": 4, "right": 5},
        budget=VirtualBudget(10_000, 10_000, 10_000),
        logical_time=13,
        eligible_nodes=("node-b",),
        max_hops=3,
    )
    address = ComputationalAddress.from_workload(
        workload,
        "core.sum_pair",
        spec,
        GROUND_FP,
        program_fingerprint=PROGRAM_FP,
        metric_order=METRICS,
    )

    advertisement = ComputationalHostAdvertisement.from_locus(locus, "peer-c")
    directory = _directory(
        _snapshot("peer-a", links=(_link("peer-a", "peer-b", 2),)),
        _snapshot("peer-b", links=(_link("peer-b", "peer-c", 3),)),
        _snapshot("peer-c", hosts=(advertisement,)),
    )
    fabric_result = ComputationalFabricResolver().resolve(
        address,
        directory,
        origin_peer_id="peer-a",
    )

    assert fabric_result.status is ComputationalFabricStatus.FOUND
    assert fabric_result.witness is not None
    assert fabric_result.authoritative is False
    assert fabric_result.witness.peer_path == ("peer-a", "peer-b", "peer-c")
    assert fabric_result.witness.target_host.digest == advertisement.digest
    assert "authority_pid" not in fabric_result.witness.target_host.to_dict()
    assert "runtime_binding" not in fabric_result.witness.target_host.to_dict()
    assert "handler_binding" not in fabric_result.witness.target_host.to_dict()
    assert calls == []

    # The terminal peer does not consume the fabric witness as an execution
    # grant. It resolves the original address against its own live catalogue,
    # current System Ground, process rights, runtime object and handler.
    local_resolution = ComputationalAddressResolver().resolve(
        address,
        catalogue,
        destination_os,
    )
    assert local_resolution.status.value == "found"
    assert local_resolution.witness is not None
    assert local_resolution.authoritative is False

    execution = ComputationalExecutionAdmissionCoordinator(destination_os).execute(
        address,
        local_resolution.witness,
        catalogue,
        runtime,
        source="federated-requester",
        channel="federated.execution",
        sequence=1,
    )
    assert execution.status.value == "executed"
    assert execution.executed
    assert execution.accepted
    assert execution.execution is not None
    assert execution.execution.action.value == "allow"
    assert execution.execution.effect["result"] == 9
    assert calls == ["federated-sum-workload"]


def test_federated_workload_forwards_over_two_authenticated_hops_and_replays_once(tmp_path) -> None:
    """Mathematics: Exercise A→B→C over mutual TLS with local hop admission, terminal re-resolution, and semantic replay."""

    from mailcpu.classifier import HypervisorPolicy
    from mailcpu.computational_fabric_forwarding import (
        ComputationalFabricForwardingClient,
        ComputationalFabricForwardingEnvelope,
        ComputationalFabricForwardingServer,
        ComputationalFabricHopReceipt,
        COMPUTATIONAL_FABRIC_EXECUTE_RESOURCE,
        COMPUTATIONAL_FABRIC_FORWARD_RESOURCE,
    )

    certificates = _make_test_certificates(tmp_path)
    listener_b = SocketTransport.listen("127.0.0.1", 0)
    listener_c = SocketTransport.listen("127.0.0.1", 0)
    port_b = listener_b.getsockname()[1]
    port_c = listener_c.getsockname()[1]

    endpoint_a = ComputationalPeerEndpoint("peer-a", "peer-a.fabric.test", "127.0.0.1", 44001)
    endpoint_b = ComputationalPeerEndpoint("peer-b", "peer-b.fabric.test", "127.0.0.1", port_b)
    endpoint_c = ComputationalPeerEndpoint("peer-c", "peer-c.fabric.test", "127.0.0.1", port_c)

    destination_os = HeadlessOS()
    system_identity = SystemIdentity("federated-forwarding-system", 1)
    seed = SystemSeed.from_system(destination_os)
    seed_envelope = SystemSeedEnvelope(
        system_identity,
        "federated-forwarding",
        "federated-forwarding",
        seed,
    )
    assert destination_os.seed_admission.admit(seed_envelope).accepted
    system_ground = VirtualGroundRef.from_envelope(seed_envelope)

    calls: list[str] = []
    registry = OperatorRegistry()
    spec = _spec()

    def execute(value, workload):
        """Mathematics: Run the terminal pure operation only after local Ground and capability admission."""
        calls.append(workload.workload_id)
        return value["left"] + value["right"]

    registry.register(spec, execute)
    runtime = VirtualLayerRuntime(registry, "node-c", frozenset({"cpu"}))
    compute_pid = destination_os.environment.kernel.spawn(
        "federated-terminal-compute",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=destination_os.environment.init_pid,
    )
    locus = ComputationalHostLocus.from_runtime(
        host_id="logical-host-c",
        runtime=runtime,
        authority_pid=compute_pid,
        operator_id="core.sum_pair",
        computational_ground_fingerprints=(GROUND_FP,),
        program_fingerprints=(PROGRAM_FP,),
        costs=_host_costs(3),
        implementation_fingerprint=IMPLEMENTATION_FP,
    )
    catalogue = ComputationalHostCatalogue((locus,))
    advertisement = ComputationalHostAdvertisement.from_locus(locus, "peer-c")

    workload = VirtualLayerWorkload(
        workload_id="federated-forwarding-sum",
        system=system_identity,
        ground=system_ground,
        intention={"goal": {"kind": "sum", "expected": 9}},
        operators=(VirtualOperatorRef("core.sum_pair", 1, "cpu"),),
        input_value={"left": 4, "right": 5},
        budget=VirtualBudget(10_000, 10_000, 10_000),
        logical_time=23,
        eligible_nodes=("node-c",),
        max_hops=2,
    )
    address = ComputationalAddress.from_workload(
        workload,
        "core.sum_pair",
        spec,
        GROUND_FP,
        program_fingerprint=PROGRAM_FP,
        metric_order=METRICS,
    )

    link_ab = _link("peer-a", "peer-b", 2)
    link_bc = _link("peer-b", "peer-c", 3)
    snapshot_a = ComputationalPeerSnapshot(endpoint_a, 1, 60, (), (link_ab,))
    snapshot_b = ComputationalPeerSnapshot(endpoint_b, 1, 60, (), (link_bc,))
    snapshot_c = ComputationalPeerSnapshot(endpoint_c, 1, 60, (advertisement,), ())
    directory_a = _directory(snapshot_a, snapshot_b, snapshot_c, local_peer_id="peer-a")
    directory_b = _directory(snapshot_a, snapshot_b, snapshot_c, local_peer_id="peer-b")
    directory_c = _directory(snapshot_b, snapshot_c, local_peer_id="peer-c")

    planned = ComputationalFabricResolver().resolve(
        address,
        directory_a,
        origin_peer_id="peer-a",
    )
    assert planned.status is ComputationalFabricStatus.FOUND
    assert planned.witness is not None
    assert planned.witness.peer_path == ("peer-a", "peer-b", "peer-c")
    envelope = ComputationalFabricForwardingEnvelope.begin(
        address,
        planned.witness,
        origin_channel="application.batch",
        origin_sequence=7,
    )

    allow_policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
    )
    relay_os = HeadlessOS()
    relay_os.hypervisor.policy = allow_policy
    relay_pid = relay_os.environment.kernel.spawn(
        "federated-relay",
        capabilities=(Capability(COMPUTATIONAL_FABRIC_FORWARD_RESOURCE, frozenset({"forward"})),),
        parent_pid=relay_os.environment.init_pid,
    )
    execute_pid = destination_os.environment.kernel.spawn(
        "federated-terminal-forwarding-gate",
        capabilities=(Capability(COMPUTATIONAL_FABRIC_EXECUTE_RESOURCE, frozenset({"execute"})),),
        parent_pid=destination_os.environment.init_pid,
    )
    destination_os.hypervisor.policy = allow_policy

    client_context_a = _client_context(certificates)
    client_context_b = ssl.create_default_context(
        ssl.Purpose.SERVER_AUTH,
        cafile=str(certificates["ca"]),
    )
    client_context_b.minimum_version = ssl.TLSVersion.TLSv1_2
    client_context_b.load_cert_chain(
        str(certificates["server_cert"]),
        str(certificates["server_key"]),
    )

    stop_b = threading.Event()
    stop_c = threading.Event()
    failures: list[BaseException] = []
    server_b_holder: dict[str, ComputationalFabricForwardingServer] = {}
    server_c_holder: dict[str, ComputationalFabricForwardingServer] = {}
    client_ab: ComputationalFabricForwardingClient | None = None
    client_bc: ComputationalFabricForwardingClient | None = None
    thread_accept_b: threading.Thread | None = None
    thread_accept_c: threading.Thread | None = None
    thread_b: threading.Thread | None = None
    thread_c: threading.Thread | None = None

    def accept_c() -> None:
        """Mathematics: Accept only peer B's CA-verified certificate and construct C's terminal receiver."""
        try:
            server_c_holder["server"] = ComputationalFabricForwardingServer.accept_mutual_tls(
                listener_c,
                "peer-c",
                "peer-b",
                _server_context_c(certificates),
                directory_c,
                destination_os,
                execute_pid,
                origin_peer_id="peer-a",
                origin_channel="application.batch",
                catalogue=catalogue,
                timeout=4.0,
            )
        except BaseException as exc:
            failures.append(exc)

    def accept_b() -> None:
        """Mathematics: Accept only peer A's CA-verified certificate and construct B's locally admitted relay."""
        try:
            server_b_holder["server"] = ComputationalFabricForwardingServer.accept_mutual_tls(
                listener_b,
                "peer-b",
                "peer-a",
                _server_context(certificates),
                directory_b,
                relay_os,
                relay_pid,
                origin_peer_id="peer-a",
                origin_channel="application.batch",
                next_hop_clients={"peer-c": client_bc},
                timeout=4.0,
            )
        except BaseException as exc:
            failures.append(exc)

    def serve(server: ComputationalFabricForwardingServer, stop: threading.Event) -> None:
        """Mathematics: Repeatedly apply the receiver's one-frame forwarding transition until cleanup."""
        while not stop.is_set():
            try:
                result = server.serve_once()
                if result is None:
                    time.sleep(0.001)
            except BaseException as exc:
                failures.append(exc)
                stop.set()
                return

    try:
        thread_accept_c = threading.Thread(target=accept_c, daemon=True)
        thread_accept_c.start()
        client_bc = ComputationalFabricForwardingClient.connect_mutual_tls(
            "peer-b",
            endpoint_c,
            client_context_b,
            origin_peer_id="peer-a",
            origin_channel="application.batch",
            timeout=4.0,
        )
        thread_accept_c.join(timeout=4.0)
        assert not thread_accept_c.is_alive()
        assert "server" in server_c_holder
        server_c = server_c_holder["server"]

        thread_accept_b = threading.Thread(target=accept_b, daemon=True)
        thread_accept_b.start()
        client_ab = ComputationalFabricForwardingClient.connect_mutual_tls(
            "peer-a",
            endpoint_b,
            client_context_a,
            origin_peer_id="peer-a",
            origin_channel="application.batch",
            timeout=4.0,
        )
        thread_accept_b.join(timeout=4.0)
        assert not thread_accept_b.is_alive()
        assert "server" in server_b_holder
        server_b = server_b_holder["server"]

        thread_c = threading.Thread(target=serve, args=(server_c, stop_c), daemon=True)
        thread_b = threading.Thread(target=serve, args=(server_b, stop_b), daemon=True)
        thread_c.start()
        thread_b.start()

        receipt = client_ab.forward(envelope, directory_a)
        assert receipt.succeeded
        assert receipt.peer_id == "peer-b"
        assert receipt.previous_peer_id == "peer-a"
        assert receipt.next_peer_id == "peer-c"
        assert receipt.downstream is not None
        assert receipt.downstream.peer_id == "peer-c"
        assert receipt.downstream.previous_peer_id == "peer-b"
        assert receipt.downstream.status == "executed"
        assert receipt.downstream.terminal_execution is not None
        terminal = receipt.downstream.terminal_execution
        assert terminal["status"] == "executed"
        assert terminal["execution"]["action"] == "allow"
        assert terminal["execution"]["effect"]["result"] == 9
        assert calls == ["federated-forwarding-sum"]

        restored_receipt = ComputationalFabricHopReceipt.from_dict(receipt.to_dict())
        assert restored_receipt.digest == receipt.digest

        # A per-peer capture includes the Hypervisor effect ledger, inbound
        # request cursor, outbound result queue, and every next-hop client's
        # semantic result ledger under one local service transition lock.
        relay_checkpoint = server_b.snapshot(capture_cut="idle")
        assert relay_checkpoint["capture_cut"] == "idle"
        assert relay_checkpoint["inbound_channel"]["next_receive_sequence"] == 2
        assert len(relay_checkpoint["operating_system"]["hypervisor_arbitration"]["executions"]) == 1
        downstream_checkpoint = relay_checkpoint["next_hop_clients"]["peer-c"]
        assert len(downstream_checkpoint["response_channel"]["seen"]) == 1
        restored_relay_os = HeadlessOS.from_snapshot(relay_checkpoint["operating_system"])
        assert (
            restored_relay_os.hypervisor_arbitration.snapshot()
            == relay_checkpoint["operating_system"]["hypervisor_arbitration"]
        )

        replay = client_ab.forward(envelope, directory_a)
        assert replay.digest == receipt.digest
        assert replay.succeeded
        assert calls == ["federated-forwarding-sum"]

        # Capture the completed per-peer state, terminate all original TLS
        # streams, and independently rebind A, B and C from their own images.
        requester_checkpoint = client_ab.snapshot()
        relay_checkpoint = server_b.snapshot(capture_cut="idle")
        terminal_checkpoint = server_c.snapshot(capture_cut="idle")
        assert relay_checkpoint["inbound_channel"]["next_receive_sequence"] == 3
        assert terminal_checkpoint["inbound_channel"]["next_receive_sequence"] == 2

        stop_b.set()
        stop_c.set()
        client_ab.close()
        client_bc.close()
        server_b.close()
        server_c.close()
        for thread in (thread_b, thread_c):
            if thread is not None:
                thread.join(timeout=3.0)
        listener_b.close()
        listener_c.close()

        from mailcpu.mtls_transport import connect_mutual_tls

        listener_b_rebound = SocketTransport.listen("127.0.0.1", port_b)
        listener_c_rebound = SocketTransport.listen("127.0.0.1", port_c)
        server_b_rebound_holder: dict[str, ComputationalFabricForwardingServer] = {}
        server_c_rebound_holder: dict[str, ComputationalFabricForwardingServer] = {}
        rebound_failures: list[BaseException] = []
        accept_b_rebound: threading.Thread | None = None
        accept_c_rebound: threading.Thread | None = None
        serve_b_rebound: threading.Thread | None = None
        serve_c_rebound: threading.Thread | None = None
        client_ab_rebound: ComputationalFabricForwardingClient | None = None
        transport_bc_rebound: SocketTransport | None = None
        stop_b_rebound = threading.Event()
        stop_c_rebound = threading.Event()

        def accept_c_after_restart() -> None:
            """Restore C's execution ledger and channel cursors on a fresh B↔C TLS stream."""
            try:
                transport = accept_mutual_tls(
                    listener_c_rebound,
                    "peer-c",
                    "peer-b",
                    _server_context_c(certificates),
                    expected_peer_dns="peer-b.fabric.test",
                    handshake_timeout=4.0,
                )
                restored_os = HeadlessOS.from_snapshot(terminal_checkpoint["operating_system"])
                server_c_rebound_holder["server"] = ComputationalFabricForwardingServer.from_snapshot(
                    terminal_checkpoint,
                    transport,
                    directory_c,
                    catalogue=catalogue,
                )
            except BaseException as exc:
                rebound_failures.append(exc)

        def accept_b_after_restart() -> None:
            """Restore B's replay ledger and downstream channel over fresh A↔B and B↔C streams."""
            try:
                transport = accept_mutual_tls(
                    listener_b_rebound,
                    "peer-b",
                    "peer-a",
                    _server_context(certificates),
                    expected_peer_dns="peer-a.fabric.test",
                    handshake_timeout=4.0,
                )
                restored_os = HeadlessOS.from_snapshot(relay_checkpoint["operating_system"])
                server_b_rebound_holder["server"] = ComputationalFabricForwardingServer.from_snapshot(
                    relay_checkpoint,
                    transport,
                    directory_b,
                    next_hop_transports={"peer-c": transport_bc_rebound},
                )
            except BaseException as exc:
                rebound_failures.append(exc)

        try:
            accept_c_rebound = threading.Thread(target=accept_c_after_restart, daemon=True)
            accept_c_rebound.start()
            transport_bc_rebound = connect_mutual_tls(
                endpoint_c.endpoint_host,
                endpoint_c.port,
                "peer-b",
                "peer-c",
                client_context_b,
                server_hostname=endpoint_c.tls_server_name,
                timeout=4.0,
            )
            accept_c_rebound.join(timeout=4.0)
            assert not accept_c_rebound.is_alive()
            assert "server" in server_c_rebound_holder

            accept_b_rebound = threading.Thread(target=accept_b_after_restart, daemon=True)
            accept_b_rebound.start()
            transport_ab = connect_mutual_tls(
                endpoint_b.endpoint_host,
                endpoint_b.port,
                "peer-a",
                "peer-b",
                client_context_a,
                server_hostname=endpoint_b.tls_server_name,
                timeout=4.0,
            )
            client_ab_rebound = ComputationalFabricForwardingClient.from_snapshot(
                requester_checkpoint,
                transport_ab,
            )
            accept_b_rebound.join(timeout=4.0)
            assert not accept_b_rebound.is_alive()
            assert "server" in server_b_rebound_holder

            server_b_rebound = server_b_rebound_holder["server"]
            server_c_rebound = server_c_rebound_holder["server"]
            serve_c_rebound = threading.Thread(
                target=serve,
                args=(server_c_rebound, stop_c_rebound),
                daemon=True,
            )
            serve_b_rebound = threading.Thread(
                target=serve,
                args=(server_b_rebound, stop_b_rebound),
                daemon=True,
            )
            serve_c_rebound.start()
            serve_b_rebound.start()

            replay_after_rebind = client_ab_rebound.forward(envelope, directory_a)
            assert replay_after_rebind.digest == receipt.digest
            assert replay_after_rebind.succeeded
            assert calls == ["federated-forwarding-sum"]
            assert not rebound_failures
        finally:
            stop_b_rebound.set()
            stop_c_rebound.set()
            if client_ab_rebound is not None:
                client_ab_rebound.close()
            if transport_bc_rebound is not None:
                transport_bc_rebound.close()
            for server in server_b_rebound_holder.values():
                server.close()
            for server in server_c_rebound_holder.values():
                server.close()
            listener_b_rebound.close()
            listener_c_rebound.close()
            for thread in (
                serve_b_rebound,
                serve_c_rebound,
                accept_b_rebound,
                accept_c_rebound,
            ):
                if thread is not None:
                    thread.join(timeout=3.0)
        assert not failures
    finally:
        stop_b.set()
        stop_c.set()
        if client_ab is not None:
            client_ab.close()
        if client_bc is not None:
            client_bc.close()
        for server in server_b_holder.values():
            server.close()
        for server in server_c_holder.values():
            server.close()
        listener_b.close()
        listener_c.close()
        for thread in (thread_b, thread_c, thread_accept_b, thread_accept_c):
            if thread is not None:
                thread.join(timeout=3.0)


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL CLI is required for ephemeral mutual-TLS certificates")
def test_discovery_service_reauthenticates_after_transport_loss_and_directory_restart(tmp_path) -> None:
    """A restored directory reacquires only directly authenticated peer leases over new TLS sessions."""
    certificates = _make_test_certificates(tmp_path)
    server_context = _server_context(certificates)
    client_context = _client_context(certificates)
    listener = SocketTransport.listen("127.0.0.1", 0)
    endpoint = ComputationalPeerEndpoint(
        "peer-b",
        "peer-b.fabric.test",
        "127.0.0.1",
        listener.getsockname()[1],
    )
    authority = ComputationalFabricAuthority(endpoint, lease_seconds=30)
    authority.register_host(ComputationalHostAdvertisement.from_locus(_locus(), "peer-b"))

    stop = threading.Event()
    accepted_sessions: list[SocketTransport] = []
    listener_errors: list[Exception] = []
    peer_listener = ComputationalFabricPeerListener(
        authority,
        SocketListener.wrap(listener),
        "peer-a",
        expected_client_dns="peer-a.fabric.test",
        tls_context=server_context,
    )
    server_thread = threading.Thread(
        target=peer_listener.serve_forever,
        args=(stop,),
        kwargs={
            "on_session": lambda server: accepted_sessions.append(server.transport),
            "on_error": listener_errors.append,
        },
        daemon=True,
    )
    server_thread.start()

    directory = ComputationalFabricDirectory(
        "peer-a",
        {"peer-b": "peer-b.fabric.test"},
    )
    directory.register_local_snapshot(
        _snapshot("peer-a", links=(_link("peer-a", "peer-b", 2),))
    )
    service = ComputationalFabricDiscoveryService(
        directory,
        {"peer-b": endpoint},
        client_context,
        timeout=3.0,
        refresh_interval=0.05,
    )
    restored_service = None
    try:
        first = service.refresh_all()
        assert len(first) == 1
        assert first[0].connected and first[0].refreshed and first[0].changed
        assert first[0].active is True
        assert first[0].revision == authority.revision
        assert directory.hosts[0].host_id == "logical-host-b"
        assert service.connected_peer_ids == ("peer-b",)
        assert len(accepted_sessions) == 1

        # The remote endpoint drops the existing TCP/TLS stream. The client
        # manager discards the failed session, then establishes a new one.
        accepted_sessions[-1].close()
        failed = service.refresh_peer("peer-b")
        assert failed.connected is False
        assert failed.refreshed is False
        assert failed.active is True  # last authenticated observation remains leased
        assert failed.error is not None
        assert service.connected_peer_ids == ()

        reconnected = service.refresh_peer("peer-b")
        assert reconnected.connected and reconnected.refreshed
        assert reconnected.active is True
        assert len(accepted_sessions) == 2
        assert service.connected_peer_ids == ("peer-b",)

        # A changed peer-owned advertisement is observed as a new revision.
        authority.register_link(_link("peer-b", "peer-c", 4))
        updated = service.refresh_peer("peer-b")
        assert updated.connected and updated.refreshed and updated.changed
        assert updated.revision == authority.revision
        assert updated.snapshot_digest is not None

        # Simulate a local process restart: persist directory anti-rollback
        # state and discovery bootstrap, then discard all live peer streams.
        directory_checkpoint = directory.checkpoint()
        bootstrap = service.bootstrap_snapshot()
        service.close()
        assert service.connected_peer_ids == ()

        restored_directory = ComputationalFabricDirectory.from_checkpoint(
            directory_checkpoint
        )
        assert restored_directory.active_snapshots == ()
        local_snapshot = _snapshot(
            "peer-a",
            links=(_link("peer-a", "peer-b", 2),),
        )
        assert restored_directory.peer_revision_high_water == (
            ("peer-a", local_snapshot.revision, local_snapshot.digest),
            ("peer-b", authority.revision, updated.snapshot_digest),
        )
        # The runtime owner republishes its own current portable snapshot;
        # local executable bindings are never reconstructed from the directory.
        assert restored_directory.register_local_snapshot(local_snapshot)
        restored_service = ComputationalFabricDiscoveryService.from_bootstrap_snapshot(
            bootstrap,
            restored_directory,
            client_context,
        )
        assert restored_service.configured_peer_ids == ("peer-b",)
        assert restored_service.connected_peer_ids == ()

        after_restart = restored_service.refresh_all()
        assert len(after_restart) == 1
        assert after_restart[0].connected and after_restart[0].refreshed
        assert after_restart[0].changed is False
        assert after_restart[0].active is True
        assert after_restart[0].revision == authority.revision
        assert tuple(item.peer_id for item in restored_directory.active_snapshots) == (
            "peer-a",
            "peer-b",
        )
        assert len(accepted_sessions) == 3

        # Exercise the periodic refresh loop, not just the one-shot API.
        cycles: list[tuple] = []
        loop_stop = threading.Event()

        def observe_cycle(reports) -> None:
            cycles.append(reports)
            if len(cycles) >= 2:
                loop_stop.set()

        loop_thread = threading.Thread(
            target=restored_service.serve_forever,
            args=(loop_stop,),
            kwargs={"on_cycle": observe_cycle},
            daemon=True,
        )
        loop_thread.start()
        loop_thread.join(timeout=5.0)
        loop_stop.set()
        assert not loop_thread.is_alive()
        assert len(cycles) >= 2
        assert all(cycle[0].connected and cycle[0].refreshed for cycle in cycles)
        assert all(cycle[0].changed is False for cycle in cycles)

        tampered = dict(bootstrap)
        tampered["refresh_interval"] = 99.0
        with pytest.raises(ComputationalFabricDiscoveryError, match="digest"):
            ComputationalFabricDiscoveryService.from_bootstrap_snapshot(
                tampered,
                restored_directory,
                client_context,
            )

        # Closing the listener also closes its active TLS session and is not
        # surfaced as an unexpected peer failure.
        peer_listener.close()
        server_thread.join(timeout=5.0)
        assert not server_thread.is_alive()
        assert listener_errors == []
    finally:
        stop.set()
        if restored_service is not None:
            restored_service.close()
        else:
            service.close()
        peer_listener.close()
        server_thread.join(timeout=5.0)
    assert not server_thread.is_alive()



@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL CLI is required for ephemeral mutual-TLS certificates")
def test_supervised_peer_process_restarts_control_listener_without_data_plane_loss(
    tmp_path: Path,
) -> None:
    """A killed discovery sidecar can recover its lease without owning the forwarding endpoint."""

    certificates = _make_test_certificates(tmp_path)

    # Keep an independent data-plane endpoint bound throughout the discovery
    # service kill/restart. It intentionally does not share the control port.
    forwarding_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    forwarding_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    forwarding_listener.bind(("127.0.0.1", 0))
    forwarding_listener.listen(8)
    forwarding_listener.settimeout(1.0)
    forwarding_port = int(forwarding_listener.getsockname()[1])

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        control_port = int(probe.getsockname()[1])
    assert control_port != forwarding_port

    def assert_data_plane_endpoint_alive() -> None:
        """Prove the separately owned forwarding socket remains connectable."""
        connection = socket.create_connection(
            ("127.0.0.1", forwarding_port),
            timeout=1.0,
        )
        accepted, _address = forwarding_listener.accept()
        connection.close()
        accepted.close()

    endpoint = _endpoint("peer-b", port=forwarding_port)
    control_endpoint = _endpoint("peer-b", port=control_port)
    store = ComputationalFabricAuthorityStore(tmp_path / "peer-b" / "authority.json")
    authority = store.open_authority(endpoint, lease_seconds=30)
    authority.register_host(_locus())
    durable_snapshot = store.load(expected_peer_id="peer-b")
    assert durable_snapshot.revision == 1
    assert durable_snapshot.digest == authority.snapshot().digest

    command = (
        sys.executable,
        "-m",
        "mailcpu.computational_fabric_service",
        "--snapshot-store",
        str(store.path),
        "--peer-id",
        "peer-b",
        "--bind-host",
        "127.0.0.1",
        "--listen-port",
        str(control_port),
        "--client-peer-id",
        "peer-a",
        "--expected-client-dns",
        "peer-a.fabric.test",
        "--certificate",
        str(certificates["server_cert"]),
        "--private-key",
        str(certificates["server_key"]),
        "--client-ca",
        str(certificates["ca"]),
    )
    supervisor = SubprocessServiceSupervisor()
    supervisor.register(
        SubprocessServiceSpec(
            name="peer-b-discovery",
            command=command,
            readiness_directory=tmp_path / "readiness",
            restart=RestartPolicy.ON_FAILURE,
            max_restarts=1,
            readiness_timeout=10.0,
            restart_delay=0.02,
            shutdown_timeout=3.0,
            cwd=Path(__file__).resolve().parents[1],
            log_path=tmp_path / "peer-b-discovery-service.log",
        )
    )

    lease_clock = [1_000.0]
    directory = ComputationalFabricDirectory(
        "peer-a",
        {"peer-b": "peer-b.fabric.test"},
        monotonic=lambda: lease_clock[0],
    )
    directory.register_local_snapshot(
        _snapshot("peer-a", links=(_link("peer-a", "peer-b", 2),))
    )
    discovery = ComputationalFabricDiscoveryService(
        directory,
        {"peer-b": control_endpoint},
        _client_context(certificates),
        timeout=2.0,
        refresh_interval=0.05,
    )
    try:
        first_process = supervisor.start("peer-b-discovery")
        assert first_process.state == "running"
        assert first_process.pid is not None
        assert first_process.ready is not None
        assert first_process.ready["peer_id"] == "peer-b"
        assert first_process.ready["revision"] == durable_snapshot.revision
        assert first_process.ready["control_port"] == control_port
        assert first_process.ready["forwarding_port"] == forwarding_port
        assert first_process.ready["port"] == control_port
        first_pid = first_process.pid

        assert_data_plane_endpoint_alive()
        first = discovery.refresh_peer("peer-b")
        assert first.connected and first.refreshed and first.active
        assert first.revision == durable_snapshot.revision
        assert first.snapshot_digest == durable_snapshot.digest
        assert first.changed is True
        assert directory.hosts[0].host_id == "logical-host-b"
        observed = next(
            item for item in directory.active_snapshots
            if item.peer_id == "peer-b"
        )
        assert observed.endpoint == endpoint
        assert observed.endpoint.port != control_endpoint.port

        # Kill only the control-plane process. The last authenticated
        # observation remains valid until its receiver-local lease expires.
        supervisor.kill("peer-b-discovery")
        failed = discovery.refresh_peer("peer-b")
        assert failed.connected is False
        assert failed.refreshed is False
        assert failed.active is True
        assert failed.error is not None
        assert_data_plane_endpoint_alive()

        lease_clock[0] += 31.0
        assert directory.purge_expired() == ("peer-b",)
        assert tuple(item.peer_id for item in directory.active_snapshots) == ("peer-a",)
        assert_data_plane_endpoint_alive()

        restarted = supervisor.reconcile()[0]
        assert restarted.state == "running"
        assert restarted.pid is not None and restarted.pid != first_pid
        assert restarted.restart_count == 1
        assert restarted.ready is not None
        assert restarted.ready["revision"] == durable_snapshot.revision
        assert restarted.ready["snapshot_digest"] == durable_snapshot.digest
        assert restarted.ready["control_port"] == control_port
        assert restarted.ready["forwarding_port"] == forwarding_port

        # The replacement has no old socket or TLS session. A fresh direct
        # mutual-TLS observation renews the expired lease without changing the
        # peer's revision, identity, or advertised forwarding endpoint.
        reconnected = discovery.refresh_peer("peer-b")
        assert reconnected.connected and reconnected.refreshed and reconnected.active
        assert reconnected.changed is False
        assert reconnected.revision == durable_snapshot.revision
        assert reconnected.snapshot_digest == durable_snapshot.digest
        observed = next(
            item for item in directory.active_snapshots
            if item.peer_id == "peer-b"
        )
        assert observed.endpoint == endpoint
        assert observed.endpoint.port == forwarding_port
        assert store.load(expected_peer_id="peer-b").digest == durable_snapshot.digest
        assert_data_plane_endpoint_alive()
    finally:
        discovery.close()
        supervisor.close()
        forwarding_listener.close()


def test_authority_store_detects_tampering_and_authority_mutations_roll_back_on_persist_failure(
    tmp_path: Path,
) -> None:
    """Persisted revision advances are atomic with the durable snapshot write."""

    endpoint = _endpoint("peer-b", port=7443)
    store = ComputationalFabricAuthorityStore(tmp_path / "authority.json")
    authority = store.open_authority(endpoint)
    authority.register_host(_locus())
    committed = store.load(expected_peer_id="peer-b")
    assert committed.revision == 1

    corrupted = {
        "schema": store.SCHEMA,
        "snapshot": committed.to_dict(),
    }
    corrupted["snapshot"]["revision"] = 99
    corrupted["digest"] = store._canonical_digest(
        {"schema": corrupted["schema"], "snapshot": committed.to_dict()}
    )
    store.path.write_text(
        __import__("json").dumps(corrupted, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    with pytest.raises(ComputationalFabricAuthorityStoreError, match="digest"):
        store.load(expected_peer_id="peer-b")

    def fail_write(_snapshot) -> None:
        raise OSError("simulated durable-store failure")

    failing = ComputationalFabricAuthority(endpoint, on_snapshot=fail_write)
    with pytest.raises(OSError, match="simulated"):
        failing.register_host(_locus())
    assert failing.revision == 0
    assert failing.snapshot().hosts == ()


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL CLI is required for ephemeral mutual-TLS certificates")
def test_persistent_vgi_session_transfers_through_fabric_and_replays_once(tmp_path: Path) -> None:
    """Mathematics: Move a quorum-backed VGI checkpoint through A→B→C, admit local M1 pages, continue M4, and prove semantic replay."""

    import hashlib
    import json
    import time

    from vgi import SIGNAL8_GROUND, Signal8Backend
    from mailcpu.classifier import HypervisorPolicy

    from mailcpu.computational_fabric_forwarding import (
        ComputationalFabricForwardingClient,
        ComputationalFabricForwardingEnvelope,
        ComputationalFabricForwardingServer,
    )
    from mailcpu.computational_fabric_vgi import (
        VGIFabricSessionOperator,
        VGI_FABRIC_INPUT_SCHEMA,
    )
    from mailcpu.computational_objects import ComputationalObjectStore
    from mailcpu.computational_session import ComputationalSessionStore
    from mailcpu.recovery_lineage import RecoveryLineageAuthority, RecoveryLineageCoordinator
    from mailcpu.seed_commit_quorum import SeedCommitMembership
    from mailcpu.vgi_session import (
        VGI_SESSION_MEDIA_TYPE,
        VGI_SESSION_STATE_SCHEMA,
        VGICompiledSessionDescriptor,
        VGIPersistentSession,
        vgi_signal8_session_backend_fingerprint,
    )

    class MemoryPageBacking:
        """Mathematics: Keep fixed-geometry content-addressed pages isolated per logical host."""

        def __init__(self, page_size: int = 32) -> None:
            self.page_size = page_size
            self.pages: dict[str, bytes] = {}

        def put_page(self, data: bytes) -> str:
            """Mathematics: Admit one exact padded page under its SHA-256 identity."""
            digest = hashlib.sha256(data).hexdigest()
            self.pages.setdefault(digest, data)
            return digest

        def get_page(self, digest: str) -> bytes:
            """Mathematics: Resolve one page by the content digest in its M1 manifest."""
            return self.pages[digest]

    def make_session_store(root: Path, backing: MemoryPageBacking, lineage, descriptor):
        """Mathematics: Bind one local M1 page table to the shared M3 quorum and exact VGI execution profile."""
        state_limit = 1024 * 1024
        backend = vgi_signal8_session_backend_fingerprint(
            max_quantum_steps=2,
            max_total_steps=100,
            max_state_bytes=state_limit,
        )
        objects = ComputationalObjectStore(backing, chunk_size=32)
        store = ComputationalSessionStore(
            root,
            objects,
            lineage,
            artifact_manifest_digest=descriptor.artifact_manifest_digest,
            backend_fingerprint=backend,
            state_schema_id=VGI_SESSION_STATE_SCHEMA,
            state_media_type=VGI_SESSION_MEDIA_TYPE,
        )
        return store, VGIPersistentSession(
            store,
            descriptor,
            max_quantum_steps=2,
            max_total_steps=100,
            max_state_bytes=state_limit,
        )

    task = {
        "name": "fabric-persistent-add",
        "inputs": ["input.a", "input.b"],
        "outputs": [{
            "label": "sum",
            "expression": {
                "type": "add",
                "left": {"type": "input", "address": "input.a"},
                "right": {"type": "input", "address": "input.b"},
            },
        }],
    }
    descriptor = VGICompiledSessionDescriptor.from_task(task, SIGNAL8_GROUND.fingerprint)
    session_id = "fabric-vgi-session"
    genesis = hashlib.sha256(b"fabric-vgi-session-genesis-v1").hexdigest()
    membership = SeedCommitMembership(
        session_id,
        1,
        ("A", "B", "C"),
        "A",
        1,
        genesis,
    )
    lineage_root = tmp_path / "quorum"
    authorities = {
        member: RecoveryLineageAuthority(
            membership,
            member,
            lineage_root / f"{member}.jsonl",
        )
        for member in membership.member_ids
    }
    lineage = RecoveryLineageCoordinator(membership, authorities)

    source_backing = MemoryPageBacking()
    target_backing = MemoryPageBacking()
    source_store, source_session = make_session_store(tmp_path / "host-a", source_backing, lineage, descriptor)
    target_store, target_session = make_session_store(tmp_path / "host-c", target_backing, lineage, descriptor)

    signal_backend = Signal8Backend()
    initial_memory = {
        "input.a": signal_backend.encode_symbol(2, observer=1),
        "input.b": signal_backend.encode_symbol(3, observer=1),
    }
    source_session.initialize(initial_memory)
    source_base = source_session.advance(2, operation_id="source-quantum-1")
    assert source_base.status == "running"
    export_started = time.perf_counter()
    transfer = source_session.export_transfer().to_dict()
    export_ms = (time.perf_counter() - export_started) * 1000.0
    assert source_store.object_store.verify(source_base.session.checkpoint.state_manifest)

    binding = VGIFabricSessionOperator(target_session)
    registry = OperatorRegistry()
    binding.register(registry)

    certificates_root = tmp_path / "certificates"
    certificates_root.mkdir()
    certificates = _make_test_certificates(certificates_root)
    listener_b = SocketTransport.listen("127.0.0.1", 0)
    listener_c = SocketTransport.listen("127.0.0.1", 0)
    endpoint_a = _endpoint("peer-a", port=44001)
    endpoint_b = _endpoint("peer-b", port=listener_b.getsockname()[1])
    endpoint_c = _endpoint("peer-c", port=listener_c.getsockname()[1])

    destination_os = HeadlessOS()
    system_identity = SystemIdentity("federated-vgi-system", 1)
    seed = SystemSeed.from_system(destination_os)
    seed_envelope = SystemSeedEnvelope(
        system_identity,
        "federated-vgi",
        "federated-vgi",
        seed,
    )
    assert destination_os.seed_admission.admit(seed_envelope).accepted
    system_ground = VirtualGroundRef.from_envelope(seed_envelope)

    runtime = VirtualLayerRuntime(registry, "node-c", frozenset({"cpu"}))
    compute_pid = destination_os.environment.kernel.spawn(
        "federated-vgi-compute",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=destination_os.environment.init_pid,
    )
    locus = ComputationalHostLocus.from_runtime(
        host_id="logical-vgi-host-c",
        runtime=runtime,
        authority_pid=compute_pid,
        operator_id=binding.spec.operator_id,
        computational_ground_fingerprints=(descriptor.ground_fingerprint,),
        program_fingerprints=(descriptor.program_fingerprint,),
        costs=_host_costs(3),
        implementation_fingerprint=descriptor.implementation_fingerprint,
    )
    catalogue = ComputationalHostCatalogue((locus,))
    advertisement = ComputationalHostAdvertisement.from_locus(locus, "peer-c")

    workload = VirtualLayerWorkload(
        workload_id="vgi-session-transfer-quantum",
        system=system_identity,
        ground=system_ground,
        intention={"goal": {"kind": "continue-persistent-vgi-session", "session_id": session_id}},
        operators=(VirtualOperatorRef(binding.spec.operator_id, binding.spec.version, "cpu"),),
        input_value={
            "schema": VGI_FABRIC_INPUT_SCHEMA,
            "transfer": transfer,
            "quantum_steps": 2,
        },
        budget=VirtualBudget(100_000_000, 4_000_000, 100_000),
        logical_time=5,
        eligible_nodes=("node-c",),
        max_hops=2,
    )
    address = ComputationalAddress.from_workload(
        workload,
        binding.spec.operator_id,
        binding.spec,
        descriptor.ground_fingerprint,
        program_fingerprint=descriptor.program_fingerprint,
        metric_order=METRICS,
    )

    snapshot_a = ComputationalPeerSnapshot(
        endpoint_a,
        1,
        60,
        (),
        (_link("peer-a", "peer-b", 2),),
    )
    snapshot_b = ComputationalPeerSnapshot(
        endpoint_b,
        1,
        60,
        (),
        (_link("peer-b", "peer-c", 3),),
    )
    snapshot_c = ComputationalPeerSnapshot(endpoint_c, 1, 60, (advertisement,), ())
    directory_a = _directory(snapshot_a, snapshot_b, snapshot_c, local_peer_id="peer-a")
    directory_b = _directory(snapshot_a, snapshot_b, snapshot_c, local_peer_id="peer-b")
    directory_c = _directory(snapshot_b, snapshot_c, local_peer_id="peer-c")

    resolved = ComputationalFabricResolver().resolve(address, directory_a, origin_peer_id="peer-a")
    assert resolved.status is ComputationalFabricStatus.FOUND
    assert resolved.witness is not None
    assert resolved.witness.peer_path == ("peer-a", "peer-b", "peer-c")
    envelope = ComputationalFabricForwardingEnvelope.begin(
        address,
        resolved.witness,
        origin_channel="application.vgi",
        origin_sequence=1,
    )

    allow_policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
    )
    relay_os = HeadlessOS()
    relay_os.hypervisor.policy = allow_policy
    relay_pid = relay_os.environment.kernel.spawn(
        "federated-vgi-relay",
        capabilities=(Capability("/network/computational-fabric/forward", frozenset({"forward"})),),
        parent_pid=relay_os.environment.init_pid,
    )
    execute_pid = destination_os.environment.kernel.spawn(
        "federated-vgi-terminal-gate",
        capabilities=(Capability("/network/computational-fabric/execute", frozenset({"execute"})),),
        parent_pid=destination_os.environment.init_pid,
    )
    destination_os.hypervisor.policy = allow_policy

    client_context_b = ssl.create_default_context(
        ssl.Purpose.SERVER_AUTH,
        cafile=str(certificates["ca"]),
    )
    client_context_b.minimum_version = ssl.TLSVersion.TLSv1_2
    client_context_b.load_cert_chain(
        str(certificates["server_cert"]),
        str(certificates["server_key"]),
    )

    failures: list[BaseException] = []
    server_b_holder: dict[str, ComputationalFabricForwardingServer] = {}
    server_c_holder: dict[str, ComputationalFabricForwardingServer] = {}
    stop_b = threading.Event()
    stop_c = threading.Event()
    client_ab: ComputationalFabricForwardingClient | None = None
    client_bc: ComputationalFabricForwardingClient | None = None
    threads: list[threading.Thread] = []

    def accept_c() -> None:
        """Mathematics: Accept only peer B's pinned TLS identity and bind C's local VGI operator catalogue."""
        try:
            server_c_holder["server"] = ComputationalFabricForwardingServer.accept_mutual_tls(
                listener_c,
                "peer-c",
                "peer-b",
                _server_context_c(certificates),
                directory_c,
                destination_os,
                execute_pid,
                origin_peer_id="peer-a",
                origin_channel="application.vgi",
                catalogue=catalogue,
                timeout=8.0,
            )
        except BaseException as exc:
            failures.append(exc)

    def accept_b() -> None:
        """Mathematics: Accept only peer A's pinned TLS identity and bind B's local relay capability."""
        try:
            server_b_holder["server"] = ComputationalFabricForwardingServer.accept_mutual_tls(
                listener_b,
                "peer-b",
                "peer-a",
                _server_context(certificates),
                directory_b,
                relay_os,
                relay_pid,
                origin_peer_id="peer-a",
                origin_channel="application.vgi",
                next_hop_clients={"peer-c": client_bc},
                timeout=8.0,
            )
        except BaseException as exc:
            failures.append(exc)

    def serve(server: ComputationalFabricForwardingServer, stop: threading.Event) -> None:
        """Mathematics: Apply receiver-local bounded forwarding transitions until the test releases the peer."""
        while not stop.is_set():
            try:
                served = server.serve_once()
                if served is None:
                    time.sleep(0.001)
            except BaseException as exc:
                failures.append(exc)
                stop.set()
                return

    try:
        accept_c_thread = threading.Thread(target=accept_c, daemon=True)
        threads.append(accept_c_thread)
        accept_c_thread.start()
        client_bc = ComputationalFabricForwardingClient.connect_mutual_tls(
            "peer-b",
            endpoint_c,
            client_context_b,
            origin_peer_id="peer-a",
            origin_channel="application.vgi",
            timeout=8.0,
        )
        accept_c_thread.join(timeout=8.0)
        assert not accept_c_thread.is_alive()
        assert "server" in server_c_holder, repr(failures)

        accept_b_thread = threading.Thread(target=accept_b, daemon=True)
        threads.append(accept_b_thread)
        accept_b_thread.start()
        client_ab = ComputationalFabricForwardingClient.connect_mutual_tls(
            "peer-a",
            endpoint_b,
            _client_context(certificates),
            origin_peer_id="peer-a",
            origin_channel="application.vgi",
            timeout=8.0,
        )
        accept_b_thread.join(timeout=8.0)
        assert not accept_b_thread.is_alive()
        assert "server" in server_b_holder, repr(failures)

        server_b = server_b_holder["server"]
        server_c = server_c_holder["server"]
        serve_c_thread = threading.Thread(target=serve, args=(server_c, stop_c), daemon=True)
        serve_b_thread = threading.Thread(target=serve, args=(server_b, stop_b), daemon=True)
        threads.extend((serve_c_thread, serve_b_thread))
        serve_c_thread.start()
        serve_b_thread.start()

        forward_started = time.perf_counter()
        receipt = client_ab.forward(envelope, directory_a)
        forward_ms = (time.perf_counter() - forward_started) * 1000.0
        assert receipt.succeeded
        assert receipt.peer_id == "peer-b"
        assert receipt.downstream is not None
        assert receipt.downstream.peer_id == "peer-c"
        terminal = receipt.downstream.terminal_execution
        assert terminal is not None
        assert terminal["status"] == "executed"
        result = terminal["execution"]["effect"]["result"]
        assert result["schema"] == "mailcpu.fabric.vgi-quantum-result.v1"
        assert result["session_id"] == session_id
        assert result["descriptor_digest"] == descriptor.descriptor_digest
        assert result["ground_fingerprint"] == descriptor.ground_fingerprint
        assert result["task_digest"] == descriptor.task_digest
        assert result["program_fingerprint"] == descriptor.program_fingerprint
        assert result["interpretation_fingerprint"] == descriptor.interpretation_fingerprint
        assert result["logical_time"] == source_base.session.checkpoint.logical_time + 1
        assert result["backend_fingerprint"] == source_base.session.checkpoint.backend_fingerprint
        assert result["state_schema_id"] == VGI_SESSION_STATE_SCHEMA
        assert result["artifact_manifest_digest"] == descriptor.artifact_manifest_digest
        assert result["revision"] == source_base.revision + 1
        assert result["predecessor_checkpoint_digest"] == source_base.checkpoint_digest
        assert result["total_steps"] == 4
        assert result["status"] == "running"
        assert result["replayed"] is False
        assert result["measurement"]["transfer_bundle_bytes"] > 0
        assert result["measurement"]["state_bytes"] == len(source_base.session.state_bytes)

        target_snapshot = target_session.load().session
        assert target_snapshot.revision == result["revision"]
        assert target_snapshot.checkpoint_digest == result["checkpoint_digest"]
        assert target_snapshot.checkpoint.session_id == source_base.session.checkpoint.session_id
        assert target_snapshot.checkpoint.artifact_manifest_digest == source_base.session.checkpoint.artifact_manifest_digest
        assert target_snapshot.checkpoint.backend_fingerprint == source_base.session.checkpoint.backend_fingerprint
        assert target_store.object_store.verify(target_snapshot.checkpoint.state_manifest)
        assert source_backing.pages
        assert target_backing.pages
        assert source_backing is not target_backing

        after_first_execution_count = len(
            destination_os.hypervisor_arbitration.snapshot()["executions"]
        )
        first_measurement = binding.last_measurement
        replay = client_ab.forward(envelope, directory_a)
        assert replay.digest == receipt.digest
        assert replay.succeeded
        assert target_session.load().revision == source_base.revision + 1
        assert len(destination_os.hypervisor_arbitration.snapshot()["executions"]) == after_first_execution_count
        assert binding.last_measurement == first_measurement

        # The same operation identity is also idempotent at the M3/M4 boundary,
        # including a retry after a lost outer Hypervisor receipt.
        m3_retry = binding.execute(workload.input_value, workload)
        assert m3_retry["replayed"] is True
        assert m3_retry["revision"] == source_base.revision + 1
        assert target_session.load().revision == source_base.revision + 1

        verify_started = time.perf_counter()
        assert target_store.object_store.verify(target_snapshot.checkpoint.state_manifest)
        target_m1_verify_ms = (time.perf_counter() - verify_started) * 1000.0
        measurements = {
            "transfer_export_ms": export_ms,
            "forward_roundtrip_ms": forward_ms,
            "target_m1_verify_ms": target_m1_verify_ms,
            **first_measurement,
        }
        print("FABRIC_VGI_MEASUREMENTS=" + json.dumps(measurements, sort_keys=True), flush=True)
        assert measurements["transfer_bundle_bytes"] > 0
        assert measurements["bundle_decode_ms"] >= 0
        assert measurements["m1_import_and_m3_verification_ms"] >= 0
        assert measurements["m4_quantum_m1_persist_and_m3_commit_ms"] >= 0
        assert measurements["forward_roundtrip_ms"] >= measurements["m4_quantum_m1_persist_and_m3_commit_ms"]
    finally:
        stop_b.set()
        stop_c.set()
        if client_ab is not None:
            client_ab.close()
        if client_bc is not None:
            client_bc.close()
        for server in server_b_holder.values():
            server.close()
        for server in server_c_holder.values():
            server.close()
        listener_b.close()
        listener_c.close()
        for thread in threads:
            thread.join(timeout=5.0)
