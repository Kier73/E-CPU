from __future__ import annotations

from dataclasses import replace

import pytest

from mailcpu import (
    Capability,
    HeadlessOS,
    HypervisorAction,
    HypervisorPolicy,
    LexicalDecisionModel,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
    VirtualBudget,
    VirtualGroundRef,
    VirtualLayerError,
    VirtualLayerRuntime,
    VirtualLayerWorkload,
    VirtualOperatorRef,
    OperatorRegistry,
    OperatorSpec,
    HypervisorOperationChannel,
    ReliabilityPolicy,
    ReliableChannel,
    SocketTransport,
)


def _admitted_ground(operating_system: HeadlessOS):
    """Create and admit a real seed envelope for the hosted-system identity."""
    identity = SystemIdentity("virtual-layer-system", 1)
    seed = SystemSeed.from_system(operating_system)
    envelope = SystemSeedEnvelope(identity, "executor", "virtual-layer", seed)
    admission = operating_system.seed_admission.admit(envelope)
    assert admission.accepted
    return identity, envelope, VirtualGroundRef.from_envelope(envelope)


def _workload(identity, ground, *, input_value=None, budget=None, eligible_nodes=("node-a",)):
    """Build a typed one-operator workload against an admitted virtual ground."""
    return VirtualLayerWorkload(
        workload_id="sum-workload-001", system=identity, ground=ground,
        intention={"goal": {"equals": 9}, "constraints": {"non_negative": True}},
        operators=(VirtualOperatorRef("core.sum_pair", 1, "cpu"),),
        input_value={"left": 4, "right": 5} if input_value is None else input_value,
        budget=budget or VirtualBudget(max_energy=5000, max_bytes=5000, max_virtual_ticks=100),
        logical_time=17, eligible_nodes=eligible_nodes, max_hops=4,
    )


def _registry(calls):
    """Create one declarative pure operator and its node-local implementation."""
    registry = OperatorRegistry()
    registry.register(
        OperatorSpec(
            operator_id="core.sum_pair", version=1,
            description="Add two integer values in a JSON object",
            input_kind="object", output_kind="integer", substrates=("cpu", "gpu"),
            required_rights=frozenset({"compute"}), base_energy=8, energy_per_byte=1,
            max_input_bytes=1024, max_output_bytes=64, deterministic=True, effect_mode="pure",
        ),
        lambda value, workload: calls.append(workload.workload_id) or value["left"] + value["right"],
    )
    return registry


def test_workload_round_trip_is_canonical_detached_and_deeply_immutable() -> None:
    """Mathematics: verify `decode(encode(W))=W` and stable `SHA256(JSON(W))`."""
    raw_intention = {"goal": {"target": 4}}
    raw_input = {"vector": [1, 2, 3]}
    ground = VirtualGroundRef("a" * 64, "b" * 64, 12, "c" * 64)
    workload = VirtualLayerWorkload(
        "w-1", SystemIdentity("sys-a", 1), ground, raw_intention,
        (VirtualOperatorRef("identity", 1),), raw_input, VirtualBudget(1000, 1000, 100), 12,
    )
    raw_intention["goal"]["target"] = 99
    raw_input["vector"].append(4)
    restored = VirtualLayerWorkload.from_dict(workload.to_dict())
    assert restored.digest == workload.digest
    assert restored.to_dict() == workload.to_dict()
    assert workload.intention["goal"]["target"] == 4
    assert workload.input_value["vector"] == (1, 2, 3)
    with pytest.raises(TypeError):
        workload.input_value["new"] = "value"
    with pytest.raises(TypeError):
        workload.intention["goal"]["target"] = 8


def test_workload_refuses_non_json_values_bad_digests_and_unlisted_operators() -> None:
    """Mathematics: reject values outside the finite typed workload domain before dispatch."""
    ground = VirtualGroundRef("a" * 64, "b" * 64, 0, "c" * 64)
    with pytest.raises(VirtualLayerError):
        VirtualGroundRef("not-a-digest", "b" * 64, 0, "c" * 64)
    with pytest.raises(VirtualLayerError):
        VirtualLayerWorkload(
            "bad", SystemIdentity("sys-a", 1), ground, {"goal": "sum"},
            (VirtualOperatorRef("only-this"),), {"value": float("nan")}, VirtualBudget(100, 100, 10), 0,
        )
    workload = _workload(SystemIdentity("sys-a", 1), ground)
    with pytest.raises(VirtualLayerError):
        workload.operator_ref("not-listed")


def test_operator_catalog_round_trip_preserves_contract_digest_without_shipping_code() -> None:
    """Mathematics: verify catalog identity depends on specs, not handler object identity."""
    calls = []
    registry = _registry(calls)
    snapshot = registry.snapshot()
    assert "handler" not in str(snapshot).lower()
    restored = OperatorRegistry.from_snapshot(snapshot)
    assert restored.digest == registry.digest
    with pytest.raises(VirtualLayerError, match="no trusted local implementation"):
        restored.resolve("core.sum_pair", 1)
    restored.bind("core.sum_pair", 1, lambda value, workload: value["left"] + value["right"])
    assert restored.resolve("core.sum_pair", 1)[0].to_dict() == registry.specs()[0].to_dict()
    assert restored.digest == registry.digest
    with pytest.raises(VirtualLayerError, match="digest mismatch"):
        OperatorRegistry.from_snapshot(snapshot | {"digest": "0" * 64})


def test_hypervisor_executes_pure_operator_with_local_capability_and_replay_receipt() -> None:
    """Mathematics: verify `ALLOW -> F(x)` once, and exact event replay returns the cached effect."""
    operating_system = HeadlessOS()
    operating_system.hypervisor.classifier = LexicalDecisionModel()
    operating_system.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    identity, _, ground = _admitted_ground(operating_system)
    calls = []
    registry = _registry(calls)
    runtime = VirtualLayerRuntime(registry, "node-a", frozenset({"cpu"}))
    workload = _workload(identity, ground)
    pid = operating_system.environment.kernel.spawn(
        "virtual-layer-worker",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=operating_system.environment.init_pid,
    )
    first = runtime.execute_operator(operating_system, pid, "origin", "virtual-layer", 1, workload.logical_time, workload, "core.sum_pair")
    assert first.action is HypervisorAction.ALLOW
    assert first.executed is True
    assert first.effect["kind"] == "virtual_layer.operator_result"
    assert first.effect["result"] == 9
    assert first.effect["ground"] == ground.to_dict()
    assert first.effect["operator_contract_digest"] == registry.specs()[0].digest
    assert len(calls) == 1
    replay = runtime.execute_operator(operating_system, pid, "origin", "virtual-layer", 1, workload.logical_time, workload, "core.sum_pair")
    assert replay.replayed is True
    assert replay.effect == first.effect
    assert len(calls) == 1
    limited_pid = operating_system.environment.kernel.spawn(
        "limited-virtual-layer-worker", capabilities=(Capability("/safe", frozenset({"read"})),),
        parent_pid=operating_system.environment.init_pid,
    )
    denied = runtime.execute_operator(operating_system, limited_pid, "origin", "virtual-layer", 2, workload.logical_time, workload, "core.sum_pair")
    assert denied.action is HypervisorAction.DENY
    assert denied.executed is False
    assert denied.effect is None
    assert len(calls) == 1
    assert operating_system.environment.kernel.journal.verify()


def test_runtime_refuses_stale_ground_wrong_node_unsupported_substrate_and_budget() -> None:
    """Mathematics: every local execution must match the admitted `(identity, ground, frontier, node, budget)` tuple."""
    operating_system = HeadlessOS()
    identity, _, ground = _admitted_ground(operating_system)
    operating_system.hypervisor.classifier = LexicalDecisionModel()
    calls = []
    registry = _registry(calls)
    runtime = VirtualLayerRuntime(registry, "node-a", frozenset({"cpu"}))
    workload = _workload(identity, ground)
    stale = replace(workload, ground=VirtualGroundRef(ground.origin_digest, ground.state_digest, ground.coordinate, "d" * 64))
    with pytest.raises(VirtualLayerError, match="stale or mismatched"):
        runtime.execute_operator(operating_system, operating_system.environment.init_pid, "origin", "vl", 1, 17, stale, "core.sum_pair")
    wrong_node = VirtualLayerRuntime(registry, "node-b", frozenset({"cpu"}))
    with pytest.raises(VirtualLayerError, match="eligible node set"):
        wrong_node.execute_operator(operating_system, operating_system.environment.init_pid, "origin", "vl", 1, 17, workload, "core.sum_pair")
    gpu_only = VirtualLayerRuntime(registry, "node-a", frozenset({"dpu"}))
    with pytest.raises(VirtualLayerError, match="no substrate supported"):
        gpu_only.execute_operator(operating_system, operating_system.environment.init_pid, "origin", "vl", 1, 17, workload, "core.sum_pair")
    too_small = _workload(identity, ground, budget=VirtualBudget(max_energy=1, max_bytes=5000, max_virtual_ticks=100))
    with pytest.raises(VirtualLayerError, match="energy budget"):
        runtime.execute_operator(operating_system, operating_system.environment.init_pid, "origin", "vl", 1, 17, too_small, "core.sum_pair")
    assert calls == []


def test_runtime_rejects_stateful_or_non_deterministic_operator_contracts() -> None:
    """Mathematics: this distributed executor admits only `deterministic ∧ effect_mode=pure`."""
    operating_system = HeadlessOS()
    identity, _, ground = _admitted_ground(operating_system)
    registry = OperatorRegistry()
    registry.register(
        OperatorSpec("stateful.write", 1, "write state", "object", "object", ("cpu",), deterministic=True, effect_mode="transactional"),
        lambda value, workload: value,
    )
    workload = VirtualLayerWorkload(
        "stateful-workload", identity, ground, {"goal": "write"}, (VirtualOperatorRef("stateful.write"),),
        {}, VirtualBudget(100, 100, 10), 0,
    )
    runtime = VirtualLayerRuntime(registry, "node-a", frozenset({"cpu"}))
    with pytest.raises(VirtualLayerError, match="deterministic pure"):
        runtime.execute_operator(operating_system, operating_system.environment.init_pid, "origin", "vl", 1, 0, workload, "stateful.write")


def _tcp_pair():
    """Create a real AF_INET loopback pair for a request and its peer-bound receiver."""
    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    origin = SocketTransport.connect("127.0.0.1", port, "origin", "replica")
    replica = SocketTransport.accept(listener, "replica", "origin")
    listener.close()
    return origin, replica


def test_virtual_layer_workload_executes_over_reliable_tcp_with_receiver_authority() -> None:
    """Mathematics: one typed workload crosses TCP and only the receiver's local capability can admit its pure operator."""
    origin_transport, replica_transport = _tcp_pair()
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=4)
    origin_channel = HypervisorOperationChannel(ReliableChannel(origin_transport, "origin", "replica", "ops", policy))
    replica_channel = HypervisorOperationChannel(ReliableChannel(replica_transport, "replica", "replica", "ops", policy, peer="origin"))
    origin_os, replica_os = HeadlessOS(), HeadlessOS()
    origin_os.hypervisor.classifier = LexicalDecisionModel()
    replica_os.hypervisor.classifier = LexicalDecisionModel()
    identity, envelope, ground = _admitted_ground(origin_os)
    assert replica_os.seed_admission.admit(envelope).accepted
    origin_calls, replica_calls = [], []
    origin_registry, replica_registry = OperatorRegistry(), _registry(replica_calls)
    origin_registry.declare(replica_registry.specs()[0])
    replica_registry.declare(OperatorSpec("local.extra", 1, "Unrelated local operator", "any", "any", ("memory",)))
    origin_runtime = VirtualLayerRuntime(origin_registry, "origin-node", frozenset({"cpu"}))
    replica_runtime = VirtualLayerRuntime(replica_registry, "node-a", frozenset({"cpu"}))
    workload = _workload(identity, ground)
    event = origin_runtime.build_event("origin", "ops", 1, workload.logical_time, workload, "core.sum_pair")
    worker_pid = replica_os.environment.kernel.spawn(
        "remote-virtual-layer-worker", capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=replica_os.environment.init_pid,
    )
    try:
        assert origin_channel.send(event) == 1
        origin_transport.service()
        result = replica_runtime.receive_and_execute(replica_channel, replica_os, worker_pid)
        assert result is not None and result.action is HypervisorAction.ALLOW and result.executed is True
        assert result.effect["result"] == 9 and result.effect["node_id"] == "node-a"
        assert origin_calls == [] and len(replica_calls) == 1
        limited_pid = replica_os.environment.kernel.spawn(
            "limited-remote-virtual-layer-worker", capabilities=(Capability("/safe", frozenset({"read"})),),
            parent_pid=replica_os.environment.init_pid,
        )
        denied_event = origin_runtime.build_event("origin", "ops", 2, workload.logical_time, workload, "core.sum_pair")
        assert origin_channel.send(denied_event) == 2
        origin_transport.service()
        denied = replica_runtime.receive_and_execute(replica_channel, replica_os, limited_pid)
        assert denied is not None and denied.action is HypervisorAction.DENY and denied.executed is False
        assert replica_calls == [workload.workload_id]
        assert replica_os.environment.kernel.journal.verify()
    finally:
        for transport in (origin_transport, replica_transport):
            if not transport.closed:
                transport.close()
