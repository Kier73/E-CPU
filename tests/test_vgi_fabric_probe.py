"""E-CPU direct authenticated source probe and VGI M3 continuation tests."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import copy
import threading
import time

import pytest
pytest.importorskip("vgi.guarded_reduction")

from mailcpu import (
    Capability, ComputationalAddress, ComputationalFabricResolver,
    ComputationalFabricStatus, ComputationalHostAdvertisement,
    ComputationalHostCatalogue, ComputationalHostLocus,
    ComputationalPeerEndpoint, ComputationalPeerSnapshot, HeadlessOS,
    OperatorRegistry, RouteMetricKey, SystemIdentity, SystemSeed,
    SystemSeedEnvelope, VirtualBudget, VirtualGroundRef, VirtualLayerRuntime,
    VirtualLayerWorkload, VirtualOperatorRef,
)
from mailcpu.classifier import HypervisorPolicy
from mailcpu.computational_fabric_forwarding import (
    COMPUTATIONAL_FABRIC_EXECUTE_RESOURCE,
    ComputationalFabricForwardingClient,
    ComputationalFabricForwardingEnvelope,
    ComputationalFabricForwardingServer,
)
from mailcpu.socket_transport import SocketTransport
from mailcpu.vgi_guarded_recovery import (
    CheckpointSourceObservation, VGIDurableGroundSession, VGIRecoveryError,
)
from mailcpu.vgi_fabric_probe import (
    SOURCE_PROBE_OPERATOR, VGISourceProbeOperator,
    VGIFabricForwardedProbeObserver, _sha, make_probe_query,
    verify_probe_result,
)
from test_computational_fabric import (
    _make_test_certificates, _server_context, _client_context,
    _link, _host_costs, _directory,
)
from test_vgi_guarded_recovery import (
    _runtime_metadata, _store, _put_transfer_pages, fixture_program,
)

GROUND_FP = sha256(b"vgi-probe-test-address-ground").hexdigest()
IMPL_FP = sha256(b"vgi-probe-source-implementation").hexdigest()
METRICS = (
    RouteMetricKey("latency", "ticks"), RouteMetricKey("energy", "units"),
    RouteMetricKey("bytes", "bytes"), RouteMetricKey("risk", "score"),
)


def test_source_operator_verifies_m3_and_minimal_probe(tmp_path):
    program, old, _new = fixture_program(32)
    artifact, backend = _runtime_metadata()
    source = VGIDurableGroundSession(
        _store(tmp_path, "source", artifact=artifact, backend=backend), program)
    state = (0, 1, 1) + (0,) * 29
    initialized = source.initialize(state)
    committed = source.advance(("tick",) * 5, operation_id="initial-five",
        expected_revision=initialized.revision,
        expected_checkpoint_digest=initialized.checkpoint_digest)
    for _ in range(5):
        state = old.step(state, "tick")
    operator = VGISourceProbeOperator(
        source, source_peer_id="peer-b", source_host_id="source-host",
        allowed_requester_peer_id="peer-a",
        source_observer=lambda digest: CheckpointSourceObservation(digest, state))
    registry = OperatorRegistry()
    operator.register(registry)
    assert registry.contract(SOURCE_PROBE_OPERATOR).digest == operator.spec.digest
    context = type("ContextFixture", (), {})()
    context.session_id = committed.checkpoint.session_id
    context.revision = committed.revision
    context.checkpoint_digest = committed.checkpoint_digest
    context.lineage_digest = committed.lineage_manifest.digest
    context.artifact_manifest_digest = artifact
    context.interpretation_fingerprint = program.fingerprint
    context.operation_id = "probe-migration"
    context.logical_time = 3
    context.input_digest = sha256(b"migration-input").hexdigest()
    query = make_probe_query(context, program, 0, 1,
                             tuple(source.inspect()["coordinates"]), "peer-a")
    machine = HeadlessOS()
    identity = SystemIdentity("probe-query-system", 1)
    seed = SystemSeedEnvelope(
        identity, "probe-tests", "probe-tests", SystemSeed.from_system(machine))
    assert machine.seed_admission.admit(seed).accepted
    workload = VirtualLayerWorkload(
        workload_id="probe-typed-unit", system=identity,
        ground=VirtualGroundRef.from_envelope(seed),
        intention={"goal": {"kind": "source-probe"}},
        operators=(VirtualOperatorRef(SOURCE_PROBE_OPERATOR, 1, "cpu"),),
        input_value=query, budget=VirtualBudget(200_000, 20_000, 100),
        logical_time=context.logical_time,
        eligible_nodes=("source-node",), max_hops=1)
    output = operator.execute(query, workload)
    assert len(output["probe_values"]) == 1
    assert output["probe_values"] == [state[2]]
    assert "source_state" not in output
    assert verify_probe_result(query, output, program,
        source_peer_id="peer-b", source_host_id="source-host") == (state[2],)
    for key, wrong in (
        ("checkpoint_digest", "0" * 64),
        ("lineage_digest", "f" * 64),
        ("revision", committed.revision + 1),
        ("probe_basis_digest", "a" * 64),
        ("old_coordinates", [((query["old_coordinates"][0] + 1) % 2)] +
                             query["old_coordinates"][1:]),
        ("requester_peer_id", "peer-z"),
    ):
        changed = copy.deepcopy(query)
        changed[key] = wrong
        with pytest.raises(VGIRecoveryError):
            operator.execute(changed, replace(workload, input_value=changed))
    for key, wrong in (
        ("checkpoint_digest", "0" * 64),
        ("lineage_digest", "f" * 64),
        ("source_host_id", "wrong-host"),
        ("source_peer_id", "peer-z"),
    ):
        forged = copy.deepcopy(output)
        forged[key] = wrong
        forged["result_digest"] = _sha({
            k: v for k, v in forged.items() if k != "result_digest"})
        with pytest.raises(VGIRecoveryError):
            verify_probe_result(query, forged, program,
                source_peer_id="peer-b", source_host_id="source-host")
    forged = copy.deepcopy(output)
    forged["probe_values"][0] ^= 1
    with pytest.raises(VGIRecoveryError, match="digest"):
        verify_probe_result(query, forged, program,
            source_peer_id="peer-b", source_host_id="source-host")


def test_direct_mtls_remote_probe_executes_and_commits_m3_migration(tmp_path):
    """Authenticated direct E-CPU hop, one missing bit, and seven more steps."""
    program, old, new = fixture_program(48)
    artifact, backend = _runtime_metadata()
    source = VGIDurableGroundSession(
        _store(tmp_path, "source", artifact=artifact, backend=backend), program)
    state = (0, 1, 1) + (0,) * 45
    initial = source.initialize(state)
    first = source.advance(("tick",) * 16, operation_id="phase-a-16",
        expected_revision=initial.revision,
        expected_checkpoint_digest=initial.checkpoint_digest)
    for _ in range(16):
        state = old.step(state, "tick")
    target_store = _store(tmp_path, "target", artifact=artifact, backend=backend)
    _put_transfer_pages(source.store, target_store)

    source_operator = VGISourceProbeOperator(
        source, source_peer_id="peer-b", source_host_id="source-probe-host",
        allowed_requester_peer_id="peer-a",
        source_observer=lambda digest: CheckpointSourceObservation(digest, state))
    source_os = HeadlessOS()
    source_os.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0, automatic_confidence=0.0,
        destructive_confidence=0.0, danger_review_probability=1.0)
    identity = SystemIdentity("vgi-source-probe-system", 1)
    seed = SystemSeedEnvelope(
        identity, "probe-source", "probe-source", SystemSeed.from_system(source_os))
    assert source_os.seed_admission.admit(seed).accepted
    ground = VirtualGroundRef.from_envelope(seed)
    registry = OperatorRegistry()
    source_operator.register(registry)
    runtime = VirtualLayerRuntime(registry, "source-node", frozenset({"cpu"}))
    compute_pid = source_os.environment.kernel.spawn(
        "source-probe-compute",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=source_os.environment.init_pid)
    gate_pid = source_os.environment.kernel.spawn(
        "source-probe-gateway",
        capabilities=(Capability(COMPUTATIONAL_FABRIC_EXECUTE_RESOURCE,
                                 frozenset({"execute"})),),
        parent_pid=source_os.environment.init_pid)
    locus = ComputationalHostLocus.from_runtime(
        host_id="source-probe-host", runtime=runtime, authority_pid=compute_pid,
        operator_id=SOURCE_PROBE_OPERATOR,
        computational_ground_fingerprints=(GROUND_FP,),
        program_fingerprints=(program.fingerprint,),
        costs=_host_costs(3), implementation_fingerprint=IMPL_FP)
    catalogue = ComputationalHostCatalogue((locus,))
    ad = ComputationalHostAdvertisement.from_locus(locus, "peer-b")
    listener = SocketTransport.listen("127.0.0.1", 0)
    endpoint_a = ComputationalPeerEndpoint(
        "peer-a", "peer-a.fabric.test", "127.0.0.1", 44001)
    endpoint_b = ComputationalPeerEndpoint(
        "peer-b", "peer-b.fabric.test", "127.0.0.1",
        listener.getsockname()[1])
    snap_a = ComputationalPeerSnapshot(
        endpoint_a, 1, 60, (), (_link("peer-a", "peer-b", 2),))
    snap_b = ComputationalPeerSnapshot(endpoint_b, 1, 60, (ad,), ())
    directory_a = _directory(snap_a, snap_b, local_peer_id="peer-a")
    directory_b = _directory(snap_a, snap_b, local_peer_id="peer-b")
    certs = _make_test_certificates(tmp_path)
    failures, server_holder = [], {}
    stop = threading.Event()

    def accept():
        try:
            server_holder["value"] = ComputationalFabricForwardingServer.accept_mutual_tls(
                listener, "peer-b", "peer-a", _server_context(certs),
                directory_b, source_os, gate_pid,
                origin_peer_id="peer-a", origin_channel="vgi.probe",
                catalogue=catalogue, timeout=4.0)
        except BaseException as exc:
            failures.append(exc)

    accept_thread = threading.Thread(target=accept, daemon=True)
    accept_thread.start()
    client, server, service_thread = None, None, None
    try:
        client = ComputationalFabricForwardingClient.connect_mutual_tls(
            "peer-a", endpoint_b, _client_context(certs),
            origin_peer_id="peer-a", origin_channel="vgi.probe", timeout=4.0)
        accept_thread.join(timeout=4.0)
        assert "value" in server_holder, repr(failures)
        server = server_holder["value"]

        def service():
            while not stop.is_set():
                try:
                    if server.serve_once() is None:
                        time.sleep(0.001)
                except BaseException as exc:
                    if not stop.is_set():
                        failures.append(exc)
                    return

        service_thread = threading.Thread(target=service, daemon=True)
        service_thread.start()
        sequence = [0]

        def build(query):
            sequence[0] += 1
            workload = VirtualLayerWorkload(
                workload_id=f"probe-work-{sequence[0]}", system=identity,
                ground=ground,
                intention={"goal": {"kind": "source-probe",
                                    "request_digest": _sha(query)}},
                operators=(VirtualOperatorRef(SOURCE_PROBE_OPERATOR, 1, "cpu"),),
                input_value=query,
                budget=VirtualBudget(250_000, 65_000, 100),
                logical_time=query["logical_time"],
                eligible_nodes=("source-node",), max_hops=1)
            address = ComputationalAddress.from_workload(
                workload, SOURCE_PROBE_OPERATOR, source_operator.spec,
                GROUND_FP, program_fingerprint=program.fingerprint,
                metric_order=METRICS)
            resolution = ComputationalFabricResolver().resolve(
                address, directory_a, origin_peer_id="peer-a")
            assert resolution.status is ComputationalFabricStatus.FOUND
            return ComputationalFabricForwardingEnvelope.begin(
                address, resolution.witness, origin_channel="vgi.probe",
                origin_sequence=sequence[0])

        observer = VGIFabricForwardedProbeObserver(
            program, client=client, directory=directory_a,
            source_peer_id="peer-b", source_host_id="source-probe-host",
            envelope_builder=build)
        target = VGIDurableGroundSession(
            target_store, program, probe_observer=observer)
        imported = target.restore_export(source.export_latest())
        assert imported.checkpoint_digest == first.checkpoint_digest
        migrated = target.migrate(
            target=1, operation_id="remote-migration",
            expected_revision=imported.revision,
            expected_checkpoint_digest=imported.checkpoint_digest)
        current = target.inspect()
        assert migrated.revision == 3
        assert current["stage"] == 1
        assert current["coordinates"] == list(program.stages[1].admitted.project(state))
        event = current["last_event"]
        assert len(event["probes"]) == 1
        assert event["source_peer_id"] == "peer-b"
        assert event["source_host_id"] == "source-probe-host"
        assert event["source_snapshot_sha256"] is None
        assert source.load().revision == 2
        assert source_os.environment.kernel.journal.verify()
        continued = target.advance(
            ("tick",) * 7, operation_id="continuation-after-probe",
            expected_revision=migrated.revision,
            expected_checkpoint_digest=migrated.checkpoint_digest)
        for _ in range(7):
            state = new.step(state, "tick")
        assert continued.revision == 4
        assert target.inspect()["coordinates"] == list(program.stages[1].admitted.project(state))
        assert not failures, repr(failures)
    finally:
        stop.set()
        if client is not None:
            client.close()
        if server is not None:
            server.close()
        listener.close()
        if service_thread is not None:
            service_thread.join(timeout=4.0)
        accept_thread.join(timeout=4.0)
