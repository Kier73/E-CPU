from __future__ import annotations

import copy

import pytest

from mailcpu import (
    BinaryFrontierPartition,
    BinaryFrontierPartitionPlan,
    ComputationalFabricRouteWitness,
    ComputationalHostAdvertisement,
    ComputationalPeerEndpoint,
    DataflowBinaryLane,
    DataflowMultiplyFrontierRequest,
    FrontierPartitionError,
    OperatorSpec,
    RouteMetric,
    dataflow_multiply_operator_spec,
    split_binary_frontier_request,
)


PLAN = "a" * 64
CONTEXT = "b" * 64
GROUND = "c" * 64
DIRECTORY = "d" * 64
TOPOLOGY = "e" * 64
IMPLEMENTATION_B = "1" * 64
IMPLEMENTATION_C = "2" * 64


def _request() -> DataflowMultiplyFrontierRequest:
    """Mathematics: create one content-bound homogeneous MUL frontier with four independent DAG lane identities."""
    lanes = tuple(
        DataflowBinaryLane(
            node_id=f"pc-{index:06d}",
            node_digest=f"{index + 10:064x}",
            destination=f"r{index}",
            left=index + 2,
            right=index + 3,
        )
        for index in range(1, 5)
    )
    return DataflowMultiplyFrontierRequest(
        plan_digest=PLAN,
        context_digest=CONTEXT,
        frontier_index=3,
        lanes=lanes,
    )


def _route(
    peer_id: str,
    host_id: str,
    address_digest: str,
    *,
    implementation: str,
    operator_spec: OperatorSpec | None = None,
    topology_digest: str = TOPOLOGY,
) -> ComputationalFabricRouteWitness:
    """Mathematics: construct a typed remote route proposal with an exact operation, Ground, endpoint and cost identity."""
    spec = operator_spec or dataflow_multiply_operator_spec()
    metrics = ("latency", "energy", "bytes", "risk")
    network_values = (2, 1, 64, 0)
    host_values = (3, 4, 32, 0)
    network = tuple(
        RouteMetric(name, unit, amount)
        for name, unit, amount in zip(metrics, ("ticks", "units", "bytes", "score"), network_values)
    )
    host = tuple(
        RouteMetric(name, unit, amount)
        for name, unit, amount in zip(metrics, ("ticks", "units", "bytes", "score"), host_values)
    )
    total = tuple(
        RouteMetric(name, unit, first + second)
        for name, unit, first, second in zip(
            metrics, ("ticks", "units", "bytes", "score"), network_values, host_values
        )
    )
    advertisement = ComputationalHostAdvertisement(
        host_id=host_id,
        node_id=f"node-{peer_id}",
        peer_id=peer_id,
        operator_spec=spec,
        substrates=("cpu",),
        computational_ground_fingerprints=(GROUND,),
        program_fingerprints=(),
        supports_ground_program_compilation=False,
        supports_structural_memory=True,
        implementation_fingerprint=implementation,
        costs=host,
        virtual_capacity=128,
        max_energy=100_000,
        max_bytes=1_000_000,
        max_virtual_ticks=100_000,
    )
    return ComputationalFabricRouteWitness(
        address_digest=address_digest,
        directory_digest=DIRECTORY,
        topology_digest=topology_digest,
        origin_peer_id="peer-a",
        peer_path=("peer-a", peer_id),
        link_ids=("f" * 64,),
        peer_endpoints=(
            ComputationalPeerEndpoint("peer-a", "peer-a.fabric.test", "127.0.0.1", 44001),
            ComputationalPeerEndpoint(peer_id, f"{peer_id}.fabric.test", "127.0.0.1", 44002),
        ),
        target_host=advertisement,
        network_costs=network,
        host_costs=host,
        total_costs=total,
    )


def test_binary_frontier_split_preserves_typed_request_identity_and_covers_lanes() -> None:
    """Mathematics: child requests partition the original ordered lane set without changing plan/context/frontier coordinates."""
    request = _request()
    groups = (("pc-000001", "pc-000002"), ("pc-000003", "pc-000004"))

    children = split_binary_frontier_request(request, groups)

    assert len(children) == 2
    assert all(type(item) is DataflowMultiplyFrontierRequest for item in children)
    assert tuple(node for child in children for node in (lane.node_id for lane in child.lanes)) == tuple(
        lane.node_id for lane in request.lanes
    )
    assert all(item.plan_digest == request.plan_digest for item in children)
    assert all(item.context_digest == request.context_digest for item in children)
    assert all(item.frontier_index == request.frontier_index for item in children)
    assert len({item.digest for item in children}) == 2
    assert children[0].lanes[0].node_digest == request.lanes[0].node_digest


def test_binary_frontier_partition_plan_round_trips_full_child_routes_and_lane_evidence() -> None:
    """Mathematics: a multi-host proposal is a digest-bound disjoint cover retaining every typed child request and route."""
    request = _request()
    first, second = split_binary_frontier_request(
        request,
        (("pc-000001", "pc-000002"), ("pc-000003", "pc-000004")),
    )
    first_route = _route(
        "peer-b",
        "logical-host-b",
        "6" * 64,
        implementation=IMPLEMENTATION_B,
    )
    second_route = _route(
        "peer-c",
        "logical-host-c",
        "7" * 64,
        implementation=IMPLEMENTATION_C,
    )
    partitions = (
        BinaryFrontierPartition(first, first_route),
        BinaryFrontierPartition(second, second_route),
    )
    plan = BinaryFrontierPartitionPlan(
        plan_digest=PLAN,
        context_digest=CONTEXT,
        frontier_index=3,
        operation="MUL",
        computational_ground_fingerprint=GROUND,
        origin_peer_id="peer-a",
        directory_digest=DIRECTORY,
        topology_digest=TOPOLOGY,
        frontier_node_ids=tuple(lane.node_id for lane in request.lanes),
        partitions=partitions,
    )

    restored = BinaryFrontierPartitionPlan.from_dict(plan.to_dict())

    assert restored == plan
    assert restored.digest == plan.digest
    assert restored.authoritative is False
    assert tuple(
        node_id for partition in restored.partitions for node_id in partition.node_ids
    ) == plan.frontier_node_ids
    assert restored.partitions[0].route_witness.target_host.host_id == "logical-host-b"
    assert restored.partitions[1].route_witness.target_host.implementation_fingerprint == IMPLEMENTATION_C


def test_binary_frontier_partition_rejects_wrong_operation_host_contract() -> None:
    """Mathematics: a route may serve a partition only when its advertised operator contract matches the child request."""
    request = _request()
    child = split_binary_frontier_request(
        request,
        (("pc-000001", "pc-000002"), ("pc-000003", "pc-000004")),
    )[0]
    wrong = OperatorSpec(
        operator_id="mailcpu.dataflow.add_frontier",
        version=3,
        description="Wrong operation for this partition",
        input_kind="object",
        output_kind="object",
        substrates=("cpu",),
        required_rights=frozenset({"compute"}),
        base_energy=16,
        energy_per_byte=2,
        max_input_bytes=262_144,
        max_output_bytes=262_144,
        replay_safe=True,
    )
    route = _route(
        "peer-b",
        "logical-host-b",
        "8" * 64,
        implementation=IMPLEMENTATION_B,
        operator_spec=wrong,
    )

    with pytest.raises(FrontierPartitionError, match="exact operation contract"):
        BinaryFrontierPartition(child, route)


def test_binary_frontier_partition_plan_rejects_gaps_duplicates_and_one_host() -> None:
    """Mathematics: a partition plan is admissible only when its child-node multiset equals the frontier set and spans distinct hosts."""
    request = _request()
    first, second = split_binary_frontier_request(
        request,
        (("pc-000001", "pc-000002"), ("pc-000003", "pc-000004")),
    )
    route_b = _route(
        "peer-b", "logical-host-b", "9" * 64, implementation=IMPLEMENTATION_B
    )
    route_c = _route(
        "peer-c", "logical-host-c", "1" * 64, implementation=IMPLEMENTATION_C
    )

    with pytest.raises(FrontierPartitionError, match="cover every frontier node exactly once"):
        BinaryFrontierPartitionPlan(
            plan_digest=PLAN,
            context_digest=CONTEXT,
            frontier_index=3,
            operation="MUL",
            computational_ground_fingerprint=GROUND,
            origin_peer_id="peer-a",
            directory_digest=DIRECTORY,
            topology_digest=TOPOLOGY,
            frontier_node_ids=tuple(lane.node_id for lane in request.lanes) + ("pc-000005",),
            partitions=(
                BinaryFrontierPartition(first, route_b),
                BinaryFrontierPartition(second, route_c),
            ),
        )

    same_host_route = _route(
        "peer-b",
        "logical-host-b",
        "2" * 64,
        implementation=IMPLEMENTATION_B,
    )
    second_on_same_host = BinaryFrontierPartition(second, same_host_route)
    with pytest.raises(FrontierPartitionError, match="at least two distinct logical hosts"):
        BinaryFrontierPartitionPlan(
            plan_digest=PLAN,
            context_digest=CONTEXT,
            frontier_index=3,
            operation="MUL",
            computational_ground_fingerprint=GROUND,
            origin_peer_id="peer-a",
            directory_digest=DIRECTORY,
            topology_digest=TOPOLOGY,
            frontier_node_ids=tuple(lane.node_id for lane in request.lanes),
            partitions=(
                BinaryFrontierPartition(first, route_b),
                second_on_same_host,
            ),
        )


def test_binary_frontier_partition_plan_refuses_mixed_directory_or_topology_views() -> None:
    """Mathematics: child route witnesses must originate from one coherent fabric catalogue view."""
    request = _request()
    first, second = split_binary_frontier_request(
        request,
        (("pc-000001", "pc-000002"), ("pc-000003", "pc-000004")),
    )
    first_route = _route("peer-b", "logical-host-b", "3" * 64, implementation=IMPLEMENTATION_B)
    second_route = _route(
        "peer-c", "logical-host-c", "4" * 64,
        implementation=IMPLEMENTATION_C, topology_digest="5" * 64,
    )
    plan_args = {
        "plan_digest": PLAN,
        "context_digest": CONTEXT,
        "frontier_index": 3,
        "operation": "MUL",
        "computational_ground_fingerprint": GROUND,
        "origin_peer_id": "peer-a",
        "directory_digest": DIRECTORY,
        "topology_digest": TOPOLOGY,
        "frontier_node_ids": tuple(lane.node_id for lane in request.lanes),
        "partitions": (
            BinaryFrontierPartition(first, first_route),
            BinaryFrontierPartition(second, second_route),
        ),
    }

    with pytest.raises(FrontierPartitionError, match="origin/directory/topology"):
        BinaryFrontierPartitionPlan(**plan_args)


def test_binary_frontier_partition_plan_deserialization_rejects_tampered_winner_and_child_request() -> None:
    """Mathematics: partition plan digest commits every child request and its complete route proposal."""
    request = _request()
    first, second = split_binary_frontier_request(
        request,
        (("pc-000001", "pc-000002"), ("pc-000003", "pc-000004")),
    )
    plan = BinaryFrontierPartitionPlan(
        plan_digest=PLAN,
        context_digest=CONTEXT,
        frontier_index=3,
        operation="MUL",
        computational_ground_fingerprint=GROUND,
        origin_peer_id="peer-a",
        directory_digest=DIRECTORY,
        topology_digest=TOPOLOGY,
        frontier_node_ids=tuple(lane.node_id for lane in request.lanes),
        partitions=(
            BinaryFrontierPartition(
                first,
                _route("peer-b", "logical-host-b", "a" * 64, implementation=IMPLEMENTATION_B),
            ),
            BinaryFrontierPartition(
                second,
                _route("peer-c", "logical-host-c", "b" * 64, implementation=IMPLEMENTATION_C),
            ),
        ),
    )
    payload = copy.deepcopy(plan.to_dict())
    payload["partitions"][0]["request"]["lanes"][0]["destination"] = "altered"

    with pytest.raises(FrontierPartitionError, match="digest|request"):
        BinaryFrontierPartitionPlan.from_dict(payload)


def test_binary_frontier_split_rejects_duplicate_or_missing_lanes_and_noncanonical_groups() -> None:
    """Mathematics: every original binary lane appears in exactly one stably ordered non-empty child group."""
    request = _request()

    with pytest.raises(FrontierPartitionError, match="cover the exact parent"):
        split_binary_frontier_request(
            request,
            (("pc-000001", "pc-000002"), ("pc-000002", "pc-000003", "pc-000004")),
        )
    with pytest.raises(FrontierPartitionError, match="cover the exact parent"):
        split_binary_frontier_request(
            request,
            (("pc-000001",), ("pc-000002", "pc-000003")),
        )
    with pytest.raises(FrontierPartitionError, match="stable order"):
        split_binary_frontier_request(
            request,
            (("pc-000002", "pc-000001"), ("pc-000003", "pc-000004")),
        )
