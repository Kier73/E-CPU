"""Measure operation-frontier time by endpoint and execution phase.

This benchmark compares the same typed MailCPU MUL DAG in three placements:
local CPU, remote CPU, and remote E-GPU. Remote runs use a one-hop mutual-TLS
computational fabric over loopback TCP. They are local transport experiments,
not wide-area network measurements.

OpenSSL is required to create ephemeral mutual-TLS test certificates.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import subprocess
import tempfile
import threading
import time
from typing import Any

from mailcpu import (
    Capability,
    ComputationalFabricForwardingClient,
    ComputationalFabricForwardingServer,
    ComputationalHostAdvertisement,
    ComputationalHostCatalogue,
    ComputationalHostLocus,
    ComputationalNetworkLink,
    ComputationalPeerEndpoint,
    ComputationalPeerSnapshot,
    EGPUHost,
    HeadlessOS,
    OperationTimingProbe,
    OperatorRegistry,
    PlacementObservation,
    PlacementProfile,
    PlacementProfileKey,
    rank_placement_profiles,
    RouteMetric,
    RouteMetricKey,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
    VirtualBudget,
    VirtualGroundRef,
    VirtualLayerRuntime,
    assemble,
    compare_dataflow_with_reference,
    dataflow_multiply_operator_spec,
    evaluate_dataflow,
    execute_dataflow_operation_native,
    make_cpu_dataflow_multiply_handler,
    make_egpu_dataflow_multiply_handler,
)
from mailcpu.computational_fabric import ComputationalFabricDirectory
from mailcpu.classifier import HypervisorPolicy
from mailcpu.computational_fabric_forwarding import COMPUTATIONAL_FABRIC_EXECUTE_RESOURCE
from mailcpu.law_certifier import Law
from mailcpu.observer_orbit import (
    ContextualOrbitAddress,
    ObserverContract,
    contextual_orbit_context,
    structural_memory_spec_representation_ref,
)
from mailcpu.orbit_fabric import (
    ContextualOrbitDataflowInput,
    ContextualOrbitLocateValueReceipt,
    ContextualOrbitLocateValueRequest,
)
from mailcpu.program_dataflow import MailCPUDataflowCompiler
from mailcpu.program_dataflow_fabric import (
    ComputationalFabricDataflowMultiplyDispatcher,
)
from mailcpu.semantic_translation import (
    ObservationContract,
    RepresentationRef,
    canonical_value_digest,
)
from mailcpu.socket_transport import SocketTransport
from mailcpu.structural_memory import StructuralMemoryRegistry
from mailcpu.temporal import SchedulerReading
from mailcpu.virtual_layer import VirtualStructuralMemoryRef


_GROUND_FP = "a" * 64
_METRICS = (
    RouteMetricKey("latency", "ticks"),
    RouteMetricKey("energy", "units"),
    RouteMetricKey("bytes", "bytes"),
    RouteMetricKey("risk", "score"),
)


def _openssl(directory: Path, *arguments: str) -> None:
    result = subprocess.run(
        ["openssl", *arguments],
        cwd=directory,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"openssl certificate generation failed: {result.stderr.strip()}")


def _make_certificates(directory: Path) -> dict[str, Path]:
    ca_key = directory / "ca.key"
    ca_cert = directory / "ca.pem"
    _openssl(
        directory,
        "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(ca_key), "-out", str(ca_cert),
        "-days", "2", "-sha256", "-subj", "/CN=ECPU Timing Benchmark CA",
        "-addext", "basicConstraints=critical,CA:TRUE",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
    )
    files: dict[str, Path] = {"ca": ca_cert}
    for role, dns_name in (
        ("server", "peer-b.fabric.test"),
        ("client", "peer-a.fabric.test"),
    ):
        key = directory / f"{role}.key"
        csr = directory / f"{role}.csr"
        cert = directory / f"{role}.pem"
        extensions = directory / f"{role}.ext"
        _openssl(
            directory,
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
            directory,
            "x509", "-req", "-in", str(csr),
            "-CA", str(ca_cert), "-CAkey", str(ca_key), "-CAcreateserial",
            "-out", str(cert), "-days", "2", "-sha256",
            "-extfile", str(extensions),
        )
        files[f"{role}_cert"] = cert
        files[f"{role}_key"] = key
    return files


def _server_context(files: dict[str, Path]) -> Any:
    import ssl

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(files["server_cert"]), str(files["server_key"]))
    context.load_verify_locations(cafile=str(files["ca"]))
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _client_context(files: dict[str, Path]) -> Any:
    import ssl

    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(files["ca"]))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(files["client_cert"]), str(files["client_key"]))
    return context


def _host_costs(latency: int, energy: int, bytes_: int) -> tuple[RouteMetric, ...]:
    return (
        RouteMetric("latency", "ticks", latency),
        RouteMetric("energy", "units", energy),
        RouteMetric("bytes", "bytes", bytes_),
        RouteMetric("risk", "score", 0),
    )


def _link() -> ComputationalNetworkLink:
    return ComputationalNetworkLink(
        "peer-a",
        "peer-b",
        (
            RouteMetric("latency", "ticks", 2),
            RouteMetric("energy", "units", 1),
            RouteMetric("bytes", "bytes", 64),
            RouteMetric("risk", "score", 0),
        ),
        max_frame_bytes=1_048_576,
    )


def _endpoint_a() -> ComputationalPeerEndpoint:
    return ComputationalPeerEndpoint("peer-a", "peer-a.fabric.test", "127.0.0.1", 443)


def _directory(*snapshots: ComputationalPeerSnapshot, local_peer_id: str) -> ComputationalFabricDirectory:
    trusted = {
        item.peer_id: item.endpoint.tls_server_name
        for item in snapshots
        if item.peer_id != local_peer_id
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


def _make_predecessor() -> ContextualOrbitDataflowInput:
    """Create typed selected-coordinate evidence for the benchmark's provenance path."""
    system = SystemIdentity("operation-frontier-benchmark-system", 1)
    base_ground = VirtualGroundRef("b" * 64, "c" * 64, 41, "d" * 64)
    interpretation = RepresentationRef.from_payload(
        "benchmark.integer-ground",
        1,
        {"domain": "integer", "meaning": "orbit-coordinate"},
    )
    extensions = {"purpose": "operation-frontier-timing", "lane": "benchmark"}
    context = contextual_orbit_context(
        system,
        base_ground,
        interpretation,
        scheduler_id="benchmark-scheduler",
        extensions=extensions,
    )
    law = Law(
        family="int",
        params={"step": 7, "mod": 101, "x0": 4},
        order=1,
        verdict="GROUND",
    )
    registry = StructuralMemoryRegistry(admission_policy=lambda _proposal: True)
    proposal = registry.propose(
        "operation-frontier-timing-orbit",
        law,
        {index: law.navigate(index) for index in range(8)},
        domain="operation-frontier-benchmark",
        context=context,
    )
    version = registry.admit(proposal.proposal_id, expected_revision=0)
    memory = VirtualStructuralMemoryRef.from_version("benchmark-orbit", version, 0)
    address = ContextualOrbitAddress(
        system_identity=system,
        base_ground=base_ground,
        computational_ground=interpretation,
        coordinate=SchedulerReading("benchmark-scheduler", base_ground.coordinate),
        structural_memory=memory,
        context_extensions=extensions,
    )
    observer = ObserverContract(
        observer_id="operation-frontier-benchmark-observer",
        revision=1,
        subject=structural_memory_spec_representation_ref(version.spec),
        interpretation=interpretation,
        observation=ObservationContract.from_definition(
            "mailcpu.orbit.scalar-value",
            1,
            {"fields": ["coordinate", "offset", "value", "value_digest"]},
        ),
        context_digest=canonical_value_digest(context),
    )
    coordinate = 37
    target_value = law.navigate(coordinate)
    request = ContextualOrbitLocateValueRequest(address, observer, target_value)
    from mailcpu.observer_orbit import ContextualOrbitNavigator

    result = ContextualOrbitNavigator(registry).locate_value(
        address,
        observer,
        target_value,
        operation_id=request.operation_id,
    )
    receipt = ContextualOrbitLocateValueReceipt(
        request_digest=request.digest,
        result=result,
        host_id="logical-host-b-cpu",
        peer_id="peer-b",
        peer_path=("peer-a", "peer-b"),
        route_witness_digest="1" * 64,
        forwarding_receipt_digest="2" * 64,
        operator_effect_digest=canonical_value_digest({
            "request_digest": request.digest,
            "result": result.to_dict(),
        }),
        implementation_fingerprint="3" * 64,
    )
    return ContextualOrbitDataflowInput(request, receipt, field="coordinate")


def _make_plan(lanes: int, multiplier_bits: int):
    if type(lanes) is not int or not 1 <= lanes <= 64:
        raise ValueError("lanes must be in [1, 64]")
    if type(multiplier_bits) is not int or not 1 <= multiplier_bits <= 3000:
        raise ValueError("multiplier_bits must be in [1, 3000]")
    multiplier = (1 << multiplier_bits) - 1
    lines = [f"set multiplier {multiplier}"]
    lines.extend(
        f"mul product_{index} orbit_coordinate multiplier"
        for index in range(lanes)
    )
    lines.append("halt")
    program = assemble("\n".join(lines))
    predecessor = _make_predecessor()
    plan = MailCPUDataflowCompiler().compile_program(
        program,
        contextual_orbit_inputs={"orbit_coordinate": predecessor},
    )
    mul_ids = {
        node.node_id
        for node in plan.nodes
        if node.payload.get("opcode") == "MUL"
    }
    frontier_index = next(
        index
        for index, frontier in enumerate(plan.frontiers)
        if mul_ids.intersection(frontier)
    )
    return program, plan, frontier_index, multiplier, predecessor.value


class _RemoteFabric:
    def __init__(self, files: dict[str, Path], receiver_probes: dict[str, OperationTimingProbe]) -> None:
        self.origin_channel = "benchmark.operation-frontier"
        self.os = HeadlessOS()
        self.os.hypervisor.policy = HypervisorPolicy(
            review_confidence=0.0,
            automatic_confidence=0.0,
            destructive_confidence=0.0,
            danger_review_probability=1.0,
        )
        self.authority_pid = self.os.environment.kernel.spawn(
            "operation-frontier-benchmark-receiver",
            capabilities=(
                Capability(COMPUTATIONAL_FABRIC_EXECUTE_RESOURCE, frozenset({"execute"})),
                Capability("/virtual-layer/operators", frozenset({"compute"})),
            ),
            parent_pid=self.os.environment.init_pid,
        )
        seed_source = HeadlessOS()
        self.system = SystemIdentity("operation-frontier-benchmark-virtual-system", 1)
        envelope = SystemSeedEnvelope(
            self.system,
            "operation-frontier-benchmark",
            "operation-frontier-benchmark",
            SystemSeed.from_system(seed_source),
        )
        if not self.os.seed_admission.admit(envelope).accepted:
            raise RuntimeError("benchmark receiver refused the shared Virtual Ground seed")
        self.ground = VirtualGroundRef.from_envelope(envelope)
        self.operator_spec = dataflow_multiply_operator_spec()

        self.cpu_probe = receiver_probes["cpu"]
        self.gpu_probe = receiver_probes["gpu"]
        cpu_registry = OperatorRegistry()
        cpu_registry.register(
            self.operator_spec,
            make_cpu_dataflow_multiply_handler(timing_probe=self.cpu_probe),
        )
        gpu_registry = OperatorRegistry()
        egpu = EGPUHost(host_id="egpu.operation-frontier")
        gpu_registry.register(
            self.operator_spec,
            make_egpu_dataflow_multiply_handler(egpu, timing_probe=self.gpu_probe),
        )
        self.cpu_runtime = VirtualLayerRuntime(
            cpu_registry,
            "node-b-cpu",
            frozenset({"cpu"}),
            timing_probe=self.cpu_probe,
        )
        self.gpu_runtime = VirtualLayerRuntime(
            gpu_registry,
            "node-b-egpu",
            frozenset({"gpu"}),
            timing_probe=self.gpu_probe,
        )
        self.catalogue = ComputationalHostCatalogue((
            ComputationalHostLocus.from_runtime(
                host_id="logical-host-b-cpu",
                runtime=self.cpu_runtime,
                authority_pid=self.authority_pid,
                operator_id=self.operator_spec.operator_id,
                computational_ground_fingerprints=(_GROUND_FP,),
                costs=_host_costs(2, 10, 256),
                supports_ground_program_compilation=True,
                implementation_fingerprint="4" * 64,
            ),
            ComputationalHostLocus.from_runtime(
                host_id="logical-host-b-egpu",
                runtime=self.gpu_runtime,
                authority_pid=self.authority_pid,
                operator_id=self.operator_spec.operator_id,
                computational_ground_fingerprints=(_GROUND_FP,),
                costs=_host_costs(2, 12, 256),
                supports_ground_program_compilation=True,
                implementation_fingerprint="5" * 64,
            ),
        ))
        advertisements = tuple(
            ComputationalHostAdvertisement.from_locus(locus, "peer-b")
            for locus in self.catalogue.loci
        )

        listener = SocketTransport.listen("127.0.0.1", 0)
        port = listener.getsockname()[1]
        self.endpoint_b = ComputationalPeerEndpoint(
            "peer-b", "peer-b.fabric.test", "127.0.0.1", port
        )
        snapshot_a = ComputationalPeerSnapshot(
            _endpoint_a(), 1, 60, (), (_link(),)
        )
        snapshot_b = ComputationalPeerSnapshot(
            self.endpoint_b, 1, 60, advertisements, ()
        )
        self.directory_a = _directory(snapshot_a, snapshot_b, local_peer_id="peer-a")
        directory_b = _directory(snapshot_a, snapshot_b, local_peer_id="peer-b")

        self.server = None
        self.client = None
        self.failures: list[BaseException] = []
        self.stop = threading.Event()
        self.threads: list[threading.Thread] = []

        def accept_server() -> None:
            try:
                self.server = ComputationalFabricForwardingServer.accept_mutual_tls(
                    listener,
                    "peer-b",
                    "peer-a",
                    _server_context(files),
                    directory_b,
                    self.os,
                    self.authority_pid,
                    origin_peer_id="peer-a",
                    origin_channel=self.origin_channel,
                    catalogue=self.catalogue,
                    timeout=10.0,
                    timing_probe=receiver_probes["network"],
                )
            except BaseException as exc:
                self.failures.append(exc)

        accept_thread = threading.Thread(target=accept_server, daemon=True)
        self.threads.append(accept_thread)
        accept_thread.start()
        try:
            self.client = ComputationalFabricForwardingClient.connect_mutual_tls(
                "peer-a",
                self.endpoint_b,
                _client_context(files),
                origin_peer_id="peer-a",
                origin_channel=self.origin_channel,
                timeout=10.0,
                timing_probe=receiver_probes["origin"],
            )
            accept_thread.join(timeout=10.0)
            if accept_thread.is_alive() or self.server is None:
                raise RuntimeError(f"mutual-TLS receiver startup failed: {self.failures!r}")
        except Exception:
            listener.close()
            raise

        self.listener = listener

        def serve() -> None:
            assert self.server is not None
            while not self.stop.is_set():
                try:
                    result = self.server.serve_once()
                    if result is None:
                        time.sleep(0.001)
                except BaseException as exc:
                    if self.stop.is_set():
                        return
                    self.failures.append(exc)
                    self.stop.set()
                    return

        thread = threading.Thread(target=serve, daemon=True)
        self.threads.append(thread)
        thread.start()

    def run(
        self,
        plan: Any,
        frontier_index: int,
        *,
        target: str,
        origin_probe: OperationTimingProbe,
        first_sequence: int,
        logical_time: int,
    ):
        node = {
            "cpu": "node-b-cpu",
            "egpu": "node-b-egpu",
        }[target]
        dispatcher = ComputationalFabricDataflowMultiplyDispatcher(
            origin_peer_id="peer-a",
            directory=self.directory_a,
            forwarding_clients={"peer-b": self.client},
            system=self.system,
            ground=self.ground,
            operator_spec=self.operator_spec,
            computational_ground_fingerprint=_GROUND_FP,
            budget=VirtualBudget(10_000_000, 262_144, 100_000),
            eligible_nodes_by_frontier={frontier_index: (node,)},
            origin_channel=self.origin_channel,
            first_sequence=first_sequence,
            logical_time=logical_time,
            max_hops=1,
            metric_order=_METRICS,
            timing_probe=origin_probe,
        )
        return execute_dataflow_operation_native(
            plan,
            operation_dispatchers={"MUL": dispatcher},
            timing_probe=origin_probe,
        )

    def close(self) -> None:
        self.stop.set()
        if self.client is not None:
            self.client.close()
        if self.server is not None:
            self.server.close()
        self.listener.close()
        for thread in self.threads:
            thread.join(timeout=3.0)
        if self.failures:
            raise RuntimeError(f"remote forwarding worker failed: {self.failures!r}")


def _probe_report(probes: dict[str, OperationTimingProbe]) -> dict[str, Any]:
    return {
        actor: {
            "actor_id": probe.actor_id,
            "summary": probe.summary(),
            "samples": [sample.to_dict() for sample in probe.samples],
        }
        for actor, probe in probes.items()
    }


def _verification_digest(plan: Any, program: Any, report: Any, expected: int, lanes: int) -> str:
    comparison = compare_dataflow_with_reference(plan, report, program)
    registers = report.observation["registers"]
    products = tuple(registers[f"product_{lane}"] for lane in range(lanes))
    if not comparison.equivalent or any(value != expected for value in products):
        raise AssertionError("placement sample failed reference or scalar product verification")
    return canonical_value_digest({
        "schema": "mailcpu.placement-sample-verification.v1",
        "plan_digest": plan.digest,
        "execution_digest": report.digest,
        "reference_equivalent": comparison.equivalent,
        "scalar_product_expected": expected,
        "verified_products": list(products),
    })


def _build_placement_profile(
    key: PlacementProfileKey,
    samples: list[Any],
    run_evidence: list[tuple[str, str, Any]],
    *,
    workload_digest: str,
) -> PlacementProfile:
    if len(samples) != len(run_evidence) or not samples:
        raise RuntimeError("placement timing samples and verified execution evidence are misaligned")
    observations = []
    for sample, (execution_digest, verification_digest, route_receipt) in zip(samples, run_evidence):
        observations.append(PlacementObservation.from_timing_sample(
            key,
            sample,
            workload_digest=workload_digest,
            execution_digest=execution_digest,
            verification_digest=verification_digest,
            verification_method="mailcpu-reference-and-scalar-product-oracle",
            route_receipt=route_receipt,
        ))
    return PlacementProfile(key, tuple(observations))


def run_benchmark(
    *,
    warmups: int,
    iterations: int,
    lanes: int,
    multiplier_bits: int,
) -> dict[str, Any]:
    program, plan, frontier_index, multiplier, coordinate = _make_plan(lanes, multiplier_bits)
    expected = coordinate * multiplier
    local_probe = OperationTimingProbe("origin/local-cpu")
    origin_probe = OperationTimingProbe("peer-a/origin")
    network_probe = OperationTimingProbe("peer-b/network")
    cpu_probe = OperationTimingProbe("peer-b/cpu")
    gpu_probe = OperationTimingProbe("peer-b/egpu")

    local_comparison = compare_dataflow_with_reference(
        plan,
        evaluate_dataflow(plan, max_work_units=len(plan.nodes)),
        program,
    )
    if not local_comparison.equivalent:
        raise AssertionError("local reference baseline did not preserve the MailCPU observation")
    local_probe.clear()
    local_report = None
    local_run_evidence: list[tuple[str, str, Any]] = []
    for index in range(warmups + iterations):
        with local_probe.measure("total_completion", correlation_id=plan.digest):
            measured_report = evaluate_dataflow(
                plan,
                max_work_units=len(plan.nodes),
                timing_probe=local_probe,
            )
        if not compare_dataflow_with_reference(plan, measured_report, program).equivalent:
            raise AssertionError("local CPU timing run changed the result")
        local_registers = measured_report.observation["registers"]
        if any(local_registers[f"product_{lane}"] != expected for lane in range(lanes)):
            raise AssertionError("local CPU output does not match the scalar product oracle")
        local_report = measured_report
        if index >= warmups:
            local_run_evidence.append((
                measured_report.digest,
                _verification_digest(plan, program, measured_report, expected, lanes),
                None,
            ))
        if index == warmups - 1:
            local_probe.clear()
    assert local_report is not None
    local_times: dict[str, Any] = {
        "actor_id": local_probe.actor_id,
        "measured_iterations": iterations,
        "summary": local_probe.summary(),
        "samples": [sample.to_dict() for sample in local_probe.samples],
    }

    remote_probes = {
        "origin": origin_probe,
        "network": network_probe,
        "cpu": cpu_probe,
        "egpu": gpu_probe,
    }
    remote_run_evidence: dict[str, list[tuple[str, str, Any]]] = {}
    remote_total_samples: dict[str, list[Any]] = {}
    results: dict[str, Any] = {
        "local_cpu": {
            "correct": True,
            "execution_digest": local_report.digest,
            "timing": local_times,
        }
    }

    with tempfile.TemporaryDirectory(prefix="ecpu-operation-frontier-") as temporary:
        files = _make_certificates(Path(temporary))
        fabric = _RemoteFabric(files, remote_probes)
        try:
            for mode in ("cpu", "egpu"):
                probes_for_mode = {
                    "origin": origin_probe,
                    "network": network_probe,
                    mode: cpu_probe if mode == "cpu" else gpu_probe,
                }
                for probe in probes_for_mode.values():
                    probe.clear()
                last_report = None
                measured_count = 0
                mode_run_evidence: list[tuple[str, str, Any]] = []
                for index in range(warmups + iterations):
                    report = fabric.run(
                        plan,
                        frontier_index,
                        target=mode,
                        origin_probe=origin_probe,
                        first_sequence=100 + index * 10 + (0 if mode == "cpu" else 1_000_000),
                        logical_time=1_000 + index,
                    )
                    if not compare_dataflow_with_reference(plan, report.execution, program).equivalent:
                        raise AssertionError(f"remote {mode} result differs from the MailCPU reference observation")
                    registers = report.execution.observation["registers"]
                    if any(registers[f"product_{lane}"] != expected for lane in range(lanes)):
                        raise AssertionError(f"remote {mode} returned an incorrect product lane")
                    last_report = report
                    if index >= warmups:
                        if len(report.frontier_receipts) != 1:
                            raise AssertionError("placement profile requires exactly one remote MUL frontier receipt")
                        mode_run_evidence.append((
                            report.digest,
                            _verification_digest(plan, program, report.execution, expected, lanes),
                            report.frontier_receipts[0],
                        ))
                    if index == warmups - 1:
                        for probe in probes_for_mode.values():
                            probe.clear()
                    if index >= warmups:
                        measured_count += 1
                assert last_report is not None
                remote_run_evidence[mode] = mode_run_evidence
                remote_total_samples[mode] = [
                    sample for sample in origin_probe.samples
                    if sample.phase == "total_completion" and sample.correlation_id == plan.digest
                ]
                results[f"remote_{mode}"] = {
                    "correct": True,
                    "execution_digest": last_report.execution.digest,
                    "operation_digest": last_report.digest,
                    "target_host": "logical-host-b-cpu" if mode == "cpu" else "logical-host-b-egpu",
                    "route": ["peer-a", "peer-b"],
                    "measured_iterations": measured_count,
                    "timing": _probe_report(probes_for_mode),
                }
        finally:
            fabric.close()

    operator_spec = dataflow_multiply_operator_spec()
    workload_class_digest = canonical_value_digest({
        "profile": "mailcpu.operation-frontier.mul.v1",
        "compiler_semantics": "mailcpu-dataflow-v4",
        "operator_id": operator_spec.operator_id,
        "operator_version": operator_spec.version,
        "lanes": lanes,
        "multiplier_bits": multiplier_bits,
        "predecessor_kind": "contextual-orbit",
        "computational_ground_fingerprint": _GROUND_FP,
    })
    origin_environment_digest = canonical_value_digest({
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    })
    local_implementation_fingerprint = canonical_value_digest({
        "implementation_id": "mailcpu.program_dataflow.evaluate_dataflow",
        "implementation_profile": "reference-register-dag",
        "profile_version": 1,
        "compiler_semantics": "mailcpu-dataflow-v4",
    })
    local_key = PlacementProfileKey(
        workload_class_digest=workload_class_digest,
        operator_id=operator_spec.operator_id,
        operator_version=operator_spec.version,
        operator_contract_digest=operator_spec.digest,
        computational_ground_fingerprint=_GROUND_FP,
        origin_environment_digest=origin_environment_digest,
        target_host_id="local/origin-cpu",
        implementation_fingerprint=local_implementation_fingerprint,
    )
    local_total_samples = [
        sample for sample in local_probe.samples
        if sample.phase == "total_completion" and sample.correlation_id == plan.digest
    ]
    profiles = [
        _build_placement_profile(
            local_key,
            local_total_samples,
            local_run_evidence,
            workload_digest=plan.digest,
        )
    ]
    for mode in ("cpu", "egpu"):
        evidence = remote_run_evidence[mode]
        receipts = [item[2] for item in evidence]
        first_receipt = receipts[0]
        if any(
            item.host_id != first_receipt.host_id
            or item.implementation_fingerprint != first_receipt.implementation_fingerprint
            or item.peer_path != first_receipt.peer_path
            or item.route_witness_digest != first_receipt.route_witness_digest
            for item in receipts
        ):
            raise AssertionError(f"remote {mode} placement identity changed during the profile window")
        total_samples = remote_total_samples[mode]
        key = PlacementProfileKey(
            workload_class_digest=workload_class_digest,
            operator_id=operator_spec.operator_id,
            operator_version=operator_spec.version,
            operator_contract_digest=operator_spec.digest,
            computational_ground_fingerprint=_GROUND_FP,
            origin_environment_digest=origin_environment_digest,
            target_host_id=first_receipt.host_id,
            implementation_fingerprint=first_receipt.implementation_fingerprint,
            peer_path=first_receipt.peer_path,
            route_witness_digest=first_receipt.route_witness_digest,
        )
        profiles.append(_build_placement_profile(
            key,
            total_samples,
            evidence,
            workload_digest=plan.digest,
        ))
    placement_ranking = rank_placement_profiles(profiles, minimum_observations=3)

    return {
        "schema": "mailcpu.operation-frontier-timing-benchmark.v1",
        "benchmark": "same compiled MailCPU MUL frontier across local CPU, remote CPU and remote E-GPU",
        "configuration": {
            "warmups": warmups,
            "iterations": iterations,
            "lanes": lanes,
            "multiplier_bits": multiplier_bits,
            "product_bit_length": expected.bit_length(),
            "compiled_plan_digest": plan.digest,
            "compiled_frontier_index": frontier_index,
            "operator_id": "mailcpu.dataflow.multiply_frontier",
            "operator_version": 1,
            "route": ["peer-a", "peer-b"],
            "transport": "mutual-TLS over loopback TCP",
        },
        "results": results,
        "placement_profiles": {
            "profiles": [profile.to_dict() for profile in profiles],
            "ranking": placement_ranking.to_dict(),
            "selection_policy": (
                "Complete profiles are ranked by origin total_completion median, p95, "
                "mean, then stable host/implementation/route identity. Every sample "
                "must retain a typed execution receipt where remote and a separate "
                "reference-interpreter plus scalar-oracle verification digest."
            ),
            "authority": "advisory-only; the fabric resolver, receiver admission and Hypervisor remain authoritative",
        },
        "phase_semantics": {
            "total_completion": "Origin-local end-to-end duration for the complete DAG execution and verified commit.",
            "fabric_route_resolution": "Origin-local semantic host and route selection.",
            "origin_round_trip": "Origin-local interval around the full authenticated forwarding RPC; it includes receiver work and is not one-way network latency.",
            "transport_request_send": "Origin-local reliable request enqueue/send interval.",
            "transport_response_wait": "Origin-local wait until the corresponding response is observed.",
            "transport_request_ack_wait": "Origin-local wait for the exact request transport acknowledgement.",
            "receiver_peer_admission": "Receiver-local per-hop envelope/path and Hypervisor network authority preparation.",
            "receiver_route_dispatch": "Receiver-local inclusive dispatch interval; includes terminal semantic execution and therefore nests other receiver phases.",
            "receiver_semantic_resolution": "Receiver-local fresh semantic resolution of the exact advertised host locus.",
            "receiver_admission": "Receiver-local Virtual Layer contract, Ground, and input validation/preparation before Hypervisor policy arbitration.",
            "receiver_hypervisor_execution": "Receiver-local Hypervisor policy arbitration and effect/execution commit after Virtual Layer preparation.",
            "receiver_provenance_validation": "Receiver-local typed operand, contextual-orbit evidence and bounded integer input validation.",
            "backend_compute": "Receiver-local scalar CPU multiplication or E-GPU vector.multiply invocation.",
            "receiver_backend_verification": "Receiver-local independent scalar verification of the E-GPU result.",
            "origin_verification": "Origin-local independent scalar verification of each returned lane and its pinned inputs.",
            "local_compute": "Local CPU multiplication in the local DAG evaluator.",
        },
        "measurement_rules": [
            "All elapsed durations are measured with each actor's process-local monotonic clock.",
            "Causal stamps bind local event order and are not used as physical durations.",
            "Scheduler ticks and SystemEpoch coordinates are not converted into nanoseconds.",
            "Receiver durations are independent endpoint measurements and are not subtracted from origin time.",
            "Origin round-trip and receiver route-dispatch intervals are inclusive/nested; do not sum them as disjoint costs.",
            "The benchmark uses loopback TCP and does not establish WAN latency, physical GPU acceleration or a general speedup.",
        ],
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "openssl_available": True,
            "git_revision": _git_revision(),
        },
    }


def _git_revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--lanes", type=int, default=64)
    parser.add_argument("--multiplier-bits", type=int, default=2048)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.warmups < 0 or args.iterations < 1:
        parser.error("warmups must be non-negative and iterations must be positive")
    result = run_benchmark(
        warmups=args.warmups,
        iterations=args.iterations,
        lanes=args.lanes,
        multiplier_bits=args.multiplier_bits,
    )
    encoded = json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
