from __future__ import annotations

import hashlib
import threading
import time

import pytest

from mailcpu import (
    BinaryFrontierCompositeReceipt,
    ComputationalFabricPlacementSet,
    ComputationalFabricRouteWitness,
    ComputationalHostAdvertisement,
    ComputationalPeerEndpoint,
    DataflowAddFrontierReceipt,
    DataflowAddFrontierRequest,
    DataflowBinaryLane,
    PartitionedComputationalFabricDataflowBinaryDispatcher,
    PartitionedFrontierIncomplete,
    RouteMetric,
    RouteMetricKey,
    SystemIdentity,
    VirtualBudget,
    VirtualGroundRef,
    VirtualLayerWorkload,
    VirtualOperatorRef,
    dataflow_add_operator_spec,
)
from mailcpu.computational_resolver import ComputationalAddress
from mailcpu.computational_fabric import ComputationalFabricStatus

PLAN = "a" * 64
CONTEXT = "b" * 64
GROUND = "c" * 64
DIRECTORY = "d" * 64
TOPOLOGY = "e" * 64
_IMPLEMENTATIONS = {
    "peer-b": hashlib.sha256(b"partition-peer-b").hexdigest(),
    "peer-c": hashlib.sha256(b"partition-peer-c").hexdigest(),
}
_METRICS = (
    RouteMetricKey("latency", "ticks"),
    RouteMetricKey("energy", "units"),
    RouteMetricKey("bytes", "bytes"),
    RouteMetricKey("risk", "score"),
)


def _request() -> DataflowAddFrontierRequest:
    return DataflowAddFrontierRequest(
        PLAN,
        CONTEXT,
        2,
        tuple(
            DataflowBinaryLane(
                node_id=f"pc-{index:06d}",
                node_digest=f"{index + 10:064x}",
                destination=f"r{index}",
                left=index + 2,
                right=index + 3,
            )
            for index in range(1, 5)
        ),
    )


def _address(request: DataflowAddFrontierRequest) -> ComputationalAddress:
    spec = dataflow_add_operator_spec()
    workload = VirtualLayerWorkload(
        workload_id=f"dataflow-add-{request.plan_digest[:12]}-{request.frontier_index:04d}",
        system=SystemIdentity("partitioned-dataflow-test", 1),
        ground=VirtualGroundRef("3" * 64, "4" * 64, 1, "5" * 64),
        intention={"goal": {
            "kind": spec.operator_id,
            "plan_digest": request.plan_digest,
            "context_digest": request.context_digest,
            "request_digest": request.digest,
            "frontier_index": request.frontier_index,
            "lanes": [item.to_dict() for item in request.lanes],
        }},
        operators=(VirtualOperatorRef(spec.operator_id, spec.version),),
        input_value={
            "lanes": [
                {
                    "node_id": lane.node_id,
                    "left": {"kind": "inline", "value": lane.left},
                    "right": {"kind": "inline", "value": lane.right},
                }
                for lane in request.lanes
            ],
            "max_steps": 64,
        },
        budget=VirtualBudget(100_000, 1_000_000, 100_000),
        logical_time=request.frontier_index,
        eligible_nodes=("node-peer-b", "node-peer-c"),
        max_hops=8,
    )
    return ComputationalAddress.from_workload(
        workload,
        spec.operator_id,
        spec,
        GROUND,
        metric_order=_METRICS,
    )


def _route(peer_id: str, address: ComputationalAddress) -> ComputationalFabricRouteWitness:
    spec = dataflow_add_operator_spec()
    network_values = (1 if peer_id == "peer-b" else 2, 1, 64, 0)
    host_values = (3, 4, 32, 0)
    metrics = ("latency", "energy", "bytes", "risk")
    units = ("ticks", "units", "bytes", "score")
    network = tuple(RouteMetric(k, u, n) for k, u, n in zip(metrics, units, network_values))
    host = tuple(RouteMetric(k, u, n) for k, u, n in zip(metrics, units, host_values))
    total = tuple(
        RouteMetric(k, u, n + h)
        for k, u, n, h in zip(metrics, units, network_values, host_values)
    )
    advertisement = ComputationalHostAdvertisement(
        host_id=f"logical-{peer_id}",
        node_id=f"node-{peer_id}",
        peer_id=peer_id,
        operator_spec=spec,
        substrates=("cpu",),
        computational_ground_fingerprints=(GROUND,),
        program_fingerprints=(),
        supports_ground_program_compilation=True,
        supports_structural_memory=False,
        implementation_fingerprint=_IMPLEMENTATIONS[peer_id],
        costs=host,
        virtual_capacity=128,
        max_energy=100_000,
        max_bytes=1_000_000,
        max_virtual_ticks=100_000,
    )
    return ComputationalFabricRouteWitness(
        address_digest=address.digest,
        directory_digest=DIRECTORY,
        topology_digest=TOPOLOGY,
        origin_peer_id="peer-a",
        peer_path=("peer-a", peer_id),
        link_ids=(hashlib.sha256(f"link-{peer_id}".encode()).hexdigest(),),
        peer_endpoints=(
            ComputationalPeerEndpoint("peer-a", "peer-a.fabric.test", "127.0.0.1", 44001),
            ComputationalPeerEndpoint(peer_id, f"{peer_id}.fabric.test", "127.0.0.1", 44002),
        ),
        target_host=advertisement,
        network_costs=network,
        host_costs=host,
        total_costs=total,
    )


class _FakeAuthenticatedBinaryDispatcher:
    """A narrow test double around the already-built route plan/receipt boundary."""

    operation = "ADD"
    operator_spec = dataflow_add_operator_spec()
    computational_ground_fingerprint = GROUND
    origin_peer_id = "peer-a"
    first_sequence = 100
    frontier_sequence_stride = 1
    forwarding_clients = {"peer-b": object(), "peer-c": object()}

    def __init__(self, *, ambiguous_node: str | None = None) -> None:
        self.ambiguous_node = ambiguous_node
        self.calls: dict[str, int] = {}
        self.semantic_effects: dict[str, int] = {}
        self.completed: dict[str, DataflowAddFrontierReceipt] = {}
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.sequences: list[tuple[str, str, int]] = []

    def prepare_routes(self, request: DataflowAddFrontierRequest, *, max_candidates: int = 128):
        address = _address(request)
        routes = tuple(sorted(
            (_route("peer-b", address), _route("peer-c", address)),
            key=lambda item: (
                tuple(metric.amount for metric in item.total_costs),
                len(item.link_ids),
                item.peer_path,
                item.link_ids,
                item.target_host.host_id,
                item.target_host.node_id,
            ),
        ))
        placement = ComputationalFabricPlacementSet(
            status=ComputationalFabricStatus.FOUND,
            address_digest=address.digest,
            directory_digest=DIRECTORY,
            topology_digest=TOPOLOGY,
            advertised_host_count=2,
            eligible_host_count=2,
            expanded_states=1,
            candidates=routes[:max_candidates],
            truncated=False,
        )
        return address, placement

    def __call__(
        self,
        request: DataflowAddFrontierRequest,
        *,
        route_witness: ComputationalFabricRouteWitness | None = None,
        origin_sequence: int | None = None,
    ) -> DataflowAddFrontierReceipt:
        assert route_witness is not None
        assert origin_sequence is not None
        key = request.digest
        with self._lock:
            self.calls[key] = self.calls.get(key, 0) + 1
            self.sequences.append((key, route_witness.target_host.peer_id, origin_sequence))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.02)
            receipt = self.completed.get(key)
            if receipt is None:
                results = tuple(
                    (lane.node_id, lane.left + lane.right)
                    for lane in request.lanes
                )
                receipt = DataflowAddFrontierReceipt(
                    request_digest=request.digest,
                    results=results,
                    host_id=route_witness.target_host.host_id,
                    peer_id=route_witness.target_host.peer_id,
                    peer_path=route_witness.peer_path,
                    route_witness_digest=route_witness.digest,
                    forwarding_receipt_digest=hashlib.sha256(b"forward").hexdigest(),
                    operator_effect_digest=hashlib.sha256(b"effect").hexdigest(),
                    implementation_fingerprint=route_witness.target_host.implementation_fingerprint,
                    backend_receipt_digest=hashlib.sha256(b"backend").hexdigest(),
                )
                self.completed[key] = receipt
                self.semantic_effects[key] = self.semantic_effects.get(key, 0) + 1
                if self.ambiguous_node in {lane.node_id for lane in request.lanes}:
                    self.ambiguous_node = None
                    raise TimeoutError("simulated lost response after receiver-side semantic effect")
            return receipt
        finally:
            with self._lock:
                self.active -= 1


def test_partitioned_dispatch_builds_composite_receipt_and_executes_independent_hosts_concurrently() -> None:
    request = _request()
    base = _FakeAuthenticatedBinaryDispatcher()
    checkpoints = []
    dispatcher = PartitionedComputationalFabricDataflowBinaryDispatcher(
        base,
        partition_count=2,
        max_concurrency=2,
        checkpoint_sink=checkpoints.append,
    )

    composite = dispatcher(request)

    assert isinstance(composite, BinaryFrontierCompositeReceipt)
    assert composite.request_digest == request.digest
    assert composite.results == tuple(
        (lane.node_id, lane.left + lane.right) for lane in request.lanes
    )
    assert {child.receipt.peer_id for child in composite.children} == {"peer-b", "peer-c"}
    assert len({child.partition.address.digest for child in composite.children}) == 2
    assert base.max_active == 2
    assert base.frontier_sequence_stride == 64
    assert checkpoints and checkpoints[0].successful_children == ()
    assert checkpoints[-1].complete

    restored = BinaryFrontierCompositeReceipt.from_dict(composite.to_dict())
    assert restored.digest == composite.digest
    assert restored.results == composite.results

    tampered = composite.to_dict()
    tampered["children"][0]["receipt"]["results"][0][1] += 1
    with pytest.raises(ValueError, match="digest|oracle|result"):
        BinaryFrontierCompositeReceipt.from_dict(tampered)


def test_partitioned_dispatch_recovery_reuses_verified_children_and_replays_ambiguous_child_effect_once() -> None:
    request = _request()
    base = _FakeAuthenticatedBinaryDispatcher(ambiguous_node="pc-000003")
    dispatcher = PartitionedComputationalFabricDataflowBinaryDispatcher(
        base,
        partition_count=2,
        max_concurrency=2,
    )

    with pytest.raises(PartitionedFrontierIncomplete) as caught:
        dispatcher.dispatch(request)

    checkpoint = caught.value.checkpoint
    assert not checkpoint.complete
    assert len(checkpoint.successful_children) == 1
    assert len(checkpoint.remaining_partitions) == 1
    restored_checkpoint = type(checkpoint).from_dict(checkpoint.to_dict())

    composite = dispatcher.dispatch(request, checkpoint=restored_checkpoint)

    assert isinstance(composite, BinaryFrontierCompositeReceipt)
    assert len(composite.children) == 2
    assert sorted(base.semantic_effects.values()) == [1, 1]
    assert sorted(base.calls.values()) == [1, 2]
    assert len(base.sequences) == 3
    identities = {(request_digest, peer_id, sequence) for request_digest, peer_id, sequence in base.sequences}
    assert len(identities) == 2
    assert len({sequence for _request, _peer, sequence in base.sequences}) == 2
    replay_identity: dict[str, set[tuple[str, int]]] = {}
    for request_digest, peer_id, sequence in base.sequences:
        replay_identity.setdefault(request_digest, set()).add((peer_id, sequence))
    assert all(len(values) == 1 for values in replay_identity.values())


def test_partitioned_dispatch_refuses_parent_request_drift_during_recovery() -> None:
    request = _request()
    base = _FakeAuthenticatedBinaryDispatcher(ambiguous_node="pc-000003")
    dispatcher = PartitionedComputationalFabricDataflowBinaryDispatcher(base, max_concurrency=2)

    with pytest.raises(PartitionedFrontierIncomplete) as caught:
        dispatcher.dispatch(request)

    checkpoint = caught.value.checkpoint
    changed = DataflowAddFrontierRequest(
        request.plan_digest,
        request.context_digest,
        request.frontier_index,
        tuple(
            DataflowBinaryLane(
                lane.node_id,
                lane.node_digest,
                lane.destination,
                lane.left + 1,
                lane.right,
            )
            for lane in request.lanes
        ),
    )
    with pytest.raises(ValueError, match="different parent frontier"):
        dispatcher.dispatch(changed, checkpoint=checkpoint)



def test_operation_native_executor_commits_one_composite_receipt_for_the_original_dag_frontier() -> None:
    from mailcpu import (
        MailCPUDataflowCompiler,
        assemble,
        compare_dataflow_with_reference,
    )
    from mailcpu.program_dataflow_fabric import execute_dataflow_operation_native

    program = assemble(
        "set a 2\n"
        "set b 3\n"
        "set c 4\n"
        "set d 5\n"
        "add x a b\n"
        "add y c d\n"
        "halt"
    )
    plan = MailCPUDataflowCompiler().compile_program(program)
    base = _FakeAuthenticatedBinaryDispatcher()
    dispatcher = PartitionedComputationalFabricDataflowBinaryDispatcher(
        base,
        partition_count=2,
        max_concurrency=2,
    )

    report = execute_dataflow_operation_native(plan, dispatcher)
    comparison = compare_dataflow_with_reference(plan, report.execution, program)

    assert comparison.equivalent
    assert report.execution.observation["registers"]["x"] == 5
    assert report.execution.observation["registers"]["y"] == 9
    composite_receipts = [
        item for item in report.frontier_receipts
        if isinstance(item, BinaryFrontierCompositeReceipt)
    ]
    assert len(composite_receipts) == 1
    assert len(composite_receipts[0].children) == 2
    assert set(dict(composite_receipts[0].results)) == {
        lane.node_id
        for lane in composite_receipts[0].request.lanes
    }
