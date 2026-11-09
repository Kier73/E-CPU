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
    RecoveryLineageAuthority,
    RecoveryLineageCoordinator,
    SeedCommitMembership,
    TransferableExecutionClaimStore,
    ComputationalFabricForwardingEnvelope,
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
    "peer-d": hashlib.sha256(b"partition-peer-d").hexdigest(),
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
        eligible_nodes=("node-peer-b", "node-peer-c", "node-peer-d"),
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
    if peer_id == "peer-d":
        # Route the alternate Host through the same first hop used by the
        # failed peer-c assignment. Rehome must therefore allocate a fresh
        # transport sequence for the new claim epoch.
        peer_path = ("peer-a", "peer-c", "peer-d")
        endpoints = (
            ComputationalPeerEndpoint("peer-a", "peer-a.fabric.test", "127.0.0.1", 44001),
            ComputationalPeerEndpoint("peer-c", "peer-c.fabric.test", "127.0.0.1", 44002),
            ComputationalPeerEndpoint("peer-d", "peer-d.fabric.test", "127.0.0.1", 44003),
        )
        link_ids = (
            hashlib.sha256(b"link-peer-c-relay").hexdigest(),
            hashlib.sha256(b"link-peer-d-terminal").hexdigest(),
        )
    else:
        peer_path = ("peer-a", peer_id)
        endpoints = (
            ComputationalPeerEndpoint("peer-a", "peer-a.fabric.test", "127.0.0.1", 44001),
            ComputationalPeerEndpoint(peer_id, f"{peer_id}.fabric.test", "127.0.0.1", 44002),
        )
        link_ids = (hashlib.sha256(f"link-{peer_id}".encode()).hexdigest(),)
    return ComputationalFabricRouteWitness(
        address_digest=address.digest,
        directory_digest=DIRECTORY,
        topology_digest=TOPOLOGY,
        origin_peer_id="peer-a",
        peer_path=peer_path,
        link_ids=link_ids,
        peer_endpoints=endpoints,
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
    forwarding_clients = {"peer-b": object(), "peer-c": object(), "peer-d": object()}

    def __init__(
        self,
        *,
        ambiguous_node: str | None = None,
        execution_claim_store: TransferableExecutionClaimStore | None = None,
    ) -> None:
        self.ambiguous_node = ambiguous_node
        self.execution_claim_store = execution_claim_store
        self.calls: dict[str, int] = {}
        self.semantic_effects: dict[str, int] = {}
        self.completed: dict[tuple[str, str, int], DataflowAddFrontierReceipt] = {}
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.sequences: list[tuple[str, str, int]] = []

    def prepare_routes(self, request: DataflowAddFrontierRequest, *, max_candidates: int = 128):
        address = _address(request)
        routes = tuple(sorted(
            (_route("peer-b", address), _route("peer-c", address), _route("peer-d", address)),
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
            advertised_host_count=3,
            eligible_host_count=3,
            expanded_states=1,
            candidates=routes[:max_candidates],
            truncated=False,
        )
        return address, placement

    def prepare_execution_claims(self, parent_request, partitions):
        """Mathematics: batch-bind every fake child to one real quorum generation just like the production dispatcher."""
        if self.execution_claim_store is None:
            return {}
        specifications = []
        for partition in partitions:
            route = partition.route_witness
            specifications.append({
                "parent_request_digest": parent_request.digest,
                "child_request_digest": partition.request.digest,
                "address_digest": partition.address.digest,
                "operator_spec": self.operator_spec,
                "computational_ground_fingerprint": GROUND,
                "owner_peer_id": route.target_host.peer_id,
                "owner_host_id": route.target_host.host_id,
                "implementation_fingerprint": route.target_host.implementation_fingerprint,
            })
        bundles = self.execution_claim_store.create_many(tuple(specifications))
        return {
            partition.digest: bundle
            for partition, bundle in zip(partitions, bundles)
        }

    def __call__(
        self,
        request: DataflowAddFrontierRequest,
        *,
        route_witness: ComputationalFabricRouteWitness | None = None,
        origin_sequence: int | None = None,
        parent_request_digest: str | None = None,
        claim_bundle=None,
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
            claim_epoch = 0 if claim_bundle is None else claim_bundle.claim.current_assignment.epoch
            receipt_key = (key, route_witness.target_host.peer_id, claim_epoch)
            receipt = self.completed.get(receipt_key)
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
                    execution_claim=None if claim_bundle is None else {
                        "schema": "mailcpu.execution-claim-attestation.v1",
                        "claim_id": claim_bundle.claim.claim_id,
                        "assignment_epoch": claim_bundle.claim.current_assignment.epoch,
                        "ticket_digest": claim_bundle.digest,
                        "state_generation": claim_bundle.manifest.generation,
                        "state_manifest_digest": claim_bundle.manifest.digest,
                    },
                )
                self.completed[receipt_key] = receipt
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
    assert base.frontier_sequence_stride == 256
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


def _claim_store(tmp_path):
    """Mathematics: create one three-peer fixed-membership claim authority for fake authenticated child hosts."""
    membership = SeedCommitMembership(
        "partitioned-dataflow-claims",
        1,
        ("peer-a", "peer-b", "peer-c"),
        "peer-a",
        1,
        "0" * 64,
    )
    authorities = {
        member: RecoveryLineageAuthority(
            membership,
            member,
            tmp_path / f"{member}.claims.jsonl",
        )
        for member in membership.member_ids
    }
    coordinator = RecoveryLineageCoordinator(membership, authorities)
    return TransferableExecutionClaimStore(tmp_path / "claims", coordinator)


def test_claim_bound_partitioned_dispatch_batches_tickets_and_preserves_receipt_provenance(tmp_path) -> None:
    """Mathematics: every child ticket and terminal receipt in one parent frontier shares one exact quorum root."""
    request = _request()
    store = _claim_store(tmp_path)
    base = _FakeAuthenticatedBinaryDispatcher(execution_claim_store=store)
    dispatcher = PartitionedComputationalFabricDataflowBinaryDispatcher(
        base,
        partition_count=2,
        max_concurrency=2,
    )

    composite = dispatcher(request)

    assert isinstance(composite, BinaryFrontierCompositeReceipt)
    assert len(composite.children) == 2
    assert all(child.claim_bundle is not None for child in composite.children)
    assert all(child.receipt.execution_claim is not None for child in composite.children)
    assert all(child.completion_bundle is not None for child in composite.children)
    assert all(child.completion_bundle.claim.status.value == "completed" for child in composite.children)
    assert len({child.claim_bundle.manifest.generation for child in composite.children}) == 1
    assert len({child.claim_bundle.manifest.digest for child in composite.children}) == 1
    assert len({child.completion_bundle.manifest.generation for child in composite.children}) == 1
    assert len({child.completion_bundle.manifest.digest for child in composite.children}) == 1
    assert all(
        child.completion_bundle.claim.child_receipt_digest == child.receipt.digest
        for child in composite.children
    )
    assert all(
        child.claim_bundle.claim.parent_request_digest == request.digest
        and child.claim_bundle.claim.child_request_digest == child.partition.request.digest
        and child.claim_bundle.claim.address_digest == child.partition.address.digest
        for child in composite.children
    )

    restored = BinaryFrontierCompositeReceipt.from_dict(composite.to_dict())
    assert restored.digest == composite.digest
    assert all(child.claim_bundle is not None for child in restored.children)

    child_payload = composite.children[0].to_dict()
    child_payload["receipt"]["execution_claim"]["assignment_epoch"] += 1
    from mailcpu.partitioned_dataflow import BinaryFrontierChildReceipt
    with pytest.raises(ValueError, match="execution claim|claim"):
        BinaryFrontierChildReceipt.from_dict(child_payload)

    # A terminal claim from another parent cannot be paired with this child.
    other_parent = store.create(
        parent_request_digest=hashlib.sha256(b"another-parent").hexdigest(),
        child_request_digest=composite.children[0].partition.request.digest,
        address_digest=composite.children[0].partition.address.digest,
        operator_spec=dataflow_add_operator_spec(),
        computational_ground_fingerprint=GROUND,
        owner_peer_id=composite.children[0].partition.route_witness.target_host.peer_id,
        owner_host_id=composite.children[0].partition.route_witness.target_host.host_id,
        implementation_fingerprint=composite.children[0].partition.route_witness.target_host.implementation_fingerprint,
    )
    with pytest.raises(ValueError, match="quorum-bound claim"):
        BinaryFrontierChildReceipt(
            composite.children[0].partition,
            composite.children[0].receipt,
            other_parent,
        )


def test_claim_bound_envelope_round_trip_and_relay_preserve_exact_ticket(tmp_path) -> None:
    """Mathematics: envelope v2 transports the claim and exact parent across each route cursor without changing its ticket."""
    from mailcpu.frontier_partition import split_binary_frontier_request

    request = _request()
    base = _FakeAuthenticatedBinaryDispatcher()
    partition = split_binary_frontier_request(
        request,
        (
            (request.lanes[0].node_id,),
            tuple(lane.node_id for lane in request.lanes[1:]),
        ),
    )[0]
    # Use the exact one-lane child address from the real partition plan.
    store = _claim_store(tmp_path)
    spec = {
        "parent_request_digest": request.digest,
        "child_request_digest": partition.request.digest,
        "address_digest": partition.address.digest,
        "operator_spec": base.operator_spec,
        "computational_ground_fingerprint": GROUND,
        "owner_peer_id": "peer-b",
        "owner_host_id": "logical-peer-b",
        "implementation_fingerprint": _IMPLEMENTATIONS["peer-b"],
    }
    ticket = store.create(**spec)
    route = _route("peer-b", partition.address)
    envelope = ComputationalFabricForwardingEnvelope.begin(
        partition.address,
        route,
        origin_channel="claim-bound-envelope-test",
        origin_sequence=17,
        parent_request_digest=request.digest,
        claim_bundle=ticket,
    )
    encoded = envelope.to_dict()
    assert encoded["schema"] == "mailcpu.computational-fabric-forward-envelope.v2"
    restored = ComputationalFabricForwardingEnvelope.from_dict(encoded)
    assert restored.digest == envelope.digest
    advanced = restored.advance()
    assert advanced.claim_bundle.digest == ticket.digest
    assert advanced.parent_request_digest == request.digest
    assert advanced.to_dict()["claim_bundle"] == encoded["claim_bundle"]


def test_claim_bound_partition_recovery_completes_all_children_together_after_ambiguous_reply(tmp_path) -> None:
    """Mathematics: checkpoint resume reuses an ambiguous child receipt and commits all child claims in one completion generation."""
    request = _request()
    store = _claim_store(tmp_path)
    base = _FakeAuthenticatedBinaryDispatcher(
        ambiguous_node="pc-000003",
        execution_claim_store=store,
    )
    checkpoints = []
    dispatcher = PartitionedComputationalFabricDataflowBinaryDispatcher(
        base,
        partition_count=2,
        max_concurrency=2,
        checkpoint_sink=checkpoints.append,
        max_rehome_rounds=0,
    )

    with pytest.raises(PartitionedFrontierIncomplete) as caught:
        dispatcher.dispatch(request)
    checkpoint = caught.value.checkpoint
    assert len(checkpoint.successful_children) == 1
    assert all(child.claim_bundle is not None for child in checkpoint.successful_children)
    assert all(child.completion_bundle is None for child in checkpoint.successful_children)
    assert store.high_water[0] == 1

    composite = dispatcher.dispatch(
        request,
        checkpoint=type(checkpoint).from_dict(checkpoint.to_dict()),
    )
    assert len(composite.children) == 2
    assert all(child.completion_bundle is not None for child in composite.children)
    assert len({child.completion_bundle.manifest.digest for child in composite.children}) == 1
    assert sorted(base.semantic_effects.values()) == [1, 1]
    assert store.high_water[0] == 2
    assert checkpoints[-1].complete
    assert all(child.completion_bundle is not None for child in checkpoints[-1].successful_children)

    # Process restart after quorum completion but before the caller consumes
    # the composite is an exact idempotent completion retry, not a new epoch.
    committed_high_water = store.high_water
    completed_checkpoint = type(checkpoint)(request, composite.plan, composite.children)
    replayed = dispatcher.dispatch(
        request,
        checkpoint=type(checkpoint).from_dict(completed_checkpoint.to_dict()),
    )
    assert replayed.digest == composite.digest
    assert store.high_water == committed_high_water


def test_claim_bound_frontier_automatically_rehomes_ambiguous_child_with_one_new_epoch(tmp_path) -> None:
    """Mathematics: a pure child with a lost response is recomputed on a distinct Host and only the quorum-current epoch completes."""
    request = _request()
    store = _claim_store(tmp_path)
    base = _FakeAuthenticatedBinaryDispatcher(
        ambiguous_node="pc-000001",
        execution_claim_store=store,
    )
    checkpoints = []
    dispatcher = PartitionedComputationalFabricDataflowBinaryDispatcher(
        base,
        partition_count=2,
        max_concurrency=2,
        checkpoint_sink=checkpoints.append,
        max_rehome_rounds=1,
    )

    composite = dispatcher.dispatch(request)

    assert isinstance(composite, BinaryFrontierCompositeReceipt)
    assert len(composite.children) == 2
    rehomed = [
        child for child in composite.children
        if len(child.claim_bundle.claim.assignments) == 2
    ]
    assert len(rehomed) == 1
    child = rehomed[0]
    history = child.claim_bundle.claim.assignments
    assert (history[0].owner_peer_id, history[0].owner_host_id) != (
        history[1].owner_peer_id, history[1].owner_host_id
    )
    assert history[1].owner_peer_id == "peer-d"
    assert history[1].epoch == 2
    assert history[1].failure_evidence_digest is not None
    assert child.partition.route_witness.target_host.peer_id == "peer-d"
    assert child.receipt.peer_id == "peer-d"
    assert child.receipt.execution_claim["assignment_epoch"] == 2
    assert child.completion_bundle.claim.current_assignment.epoch == 2
    attempt_sequences = {
        sequence
        for request_digest, _peer_id, sequence in base.sequences
        if request_digest == child.partition.request.digest
    }
    assert len(attempt_sequences) == 2
    assert max(attempt_sequences) - min(attempt_sequences) == 64
    assert child.completion_bundle.claim.status.value == "completed"
    assert child.completion_bundle.claim.child_receipt_digest == child.receipt.digest

    # The old Host may have completed the pure operation before its response
    # was lost. That physical computation is visible, but its epoch was not
    # selected as the semantic result accepted by the parent frontier.
    effects = sorted(base.semantic_effects.values())
    assert effects == [1, 2]
    assert len({item.completion_bundle.manifest.digest for item in composite.children}) == 1
    assert store.high_water[0] == 3  # assignment batch, one rehome batch, one completion batch

    intent_checkpoints = [item for item in checkpoints if item.reassignment_intents]
    confirmed_checkpoints = [item for item in checkpoints if item.reassignments]
    assert intent_checkpoints and confirmed_checkpoints
    restored_intent = type(intent_checkpoints[0]).from_dict(intent_checkpoints[0].to_dict())
    assert len(restored_intent.reassignment_intents) == 1
    restored_confirmed = type(confirmed_checkpoints[0]).from_dict(confirmed_checkpoints[-1].to_dict())
    assert restored_confirmed.reassignments
    restored_route = next(
        item for item in restored_confirmed.current_partitions
        if item.request.digest == child.partition.request.digest
    )
    assert restored_route.digest == child.partition.digest
    assert restored_route.route_witness.target_host.peer_id == "peer-d"

    restored_composite = BinaryFrontierCompositeReceipt.from_dict(composite.to_dict())
    assert restored_composite.digest == composite.digest


def test_claim_bound_frontier_resumes_quorum_committed_rehome_from_persisted_intent(tmp_path) -> None:
    """Mathematics: a crash after quorum reassignment but before confirmed checkpoint publication replays the exact intent idempotently."""
    request = _request()
    store = _claim_store(tmp_path)
    base = _FakeAuthenticatedBinaryDispatcher(
        ambiguous_node="pc-000003",
        execution_claim_store=store,
    )
    persisted = []
    fail_confirmed_once = {"value": True}

    def checkpoint_sink(checkpoint):
        persisted.append(checkpoint)
        if checkpoint.reassignments and not checkpoint.reassignment_intents and fail_confirmed_once["value"]:
            fail_confirmed_once["value"] = False
            raise RuntimeError("simulated process cut after quorum assignment commit")

    dispatcher = PartitionedComputationalFabricDataflowBinaryDispatcher(
        base,
        partition_count=2,
        max_concurrency=2,
        checkpoint_sink=checkpoint_sink,
        max_rehome_rounds=1,
    )
    with pytest.raises(PartitionedFrontierIncomplete) as caught:
        dispatcher.dispatch(request)

    saved_intent = next(item for item in reversed(persisted) if item.reassignment_intents)
    committed = store.high_water
    assert saved_intent.reassignment_intents
    assert committed[0] == 2  # create_many + reassign_many; completion has not run

    resumed_dispatcher = PartitionedComputationalFabricDataflowBinaryDispatcher(
        base,
        partition_count=2,
        max_concurrency=2,
        checkpoint_sink=persisted.append,
        max_rehome_rounds=0,
    )
    composite = resumed_dispatcher.dispatch(
        request,
        checkpoint=type(saved_intent).from_dict(saved_intent.to_dict()),
    )
    assert len(composite.children) == 2
    assert store.high_water[0] == 3
    assert len({child.completion_bundle.manifest.digest for child in composite.children}) == 1
    rehomed = [child for child in composite.children if len(child.claim_bundle.claim.assignments) == 2]
    assert len(rehomed) == 1 and rehomed[0].receipt.peer_id == "peer-d"
    attempts = {
        sequence
        for request_digest, _peer_id, sequence in base.sequences
        if request_digest == rehomed[0].partition.request.digest
    }
    assert len(attempts) == 2 and max(attempts) - min(attempts) == 64
