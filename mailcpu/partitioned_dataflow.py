"""Receipt-bound multi-host execution for homogeneous binary dataflow frontiers.

The planner assigns every child request an exact ComputationalAddress and a
route witness. Dispatch remains inside ComputationalFabricDataflowBinaryDispatcher,
so every child still traverses authenticated forwarding and terminal Hypervisor
admission. A parent receipt is emitted only after every child receipt validates.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .computational_fabric import (
    ComputationalFabricPlacementSet,
    ComputationalFabricResolver,
    ComputationalFabricRouteWitness,
    ComputationalFabricStatus,
)
from .computational_resolver import ComputationalAddress
from .frontier_partition import (
    BinaryFrontierPartition,
    BinaryFrontierPartitionPlan,
    FrontierPartitionError,
    _request_from_dict,
    split_binary_frontier_request,
)
from .program_dataflow_fabric import (
    DataflowAddFrontierReceipt,
    DataflowAddFrontierRequest,
    DataflowCompareFrontierReceipt,
    DataflowCompareFrontierRequest,
    DataflowMultiplyFrontierReceipt,
    DataflowMultiplyFrontierRequest,
    OperationNativeDataflowError,
)
from .semantic_translation import canonical_value_digest


_MAX_PARTITIONS = 64
_MAX_ROUTE_CANDIDATES = 128
_REQUEST_TYPES = {
    "ADD": DataflowAddFrontierRequest,
    "COMPARE": DataflowCompareFrontierRequest,
    "MUL": DataflowMultiplyFrontierRequest,
}
_RECEIPT_TYPES = {
    "ADD": DataflowAddFrontierReceipt,
    "COMPARE": DataflowCompareFrontierReceipt,
    "MUL": DataflowMultiplyFrontierReceipt,
}


def _operation_for_request(request: Any) -> str:
    for operation, request_type in _REQUEST_TYPES.items():
        if type(request) is request_type:
            return operation
    raise OperationNativeDataflowError("partitioned execution requires an exact typed ADD, COMPARE, or MUL request")


@dataclass(frozen=True)
class BinaryFrontierChildReceipt:
    """One child partition paired with its independently verified typed host receipt."""

    partition: BinaryFrontierPartition
    receipt: Any

    def __post_init__(self) -> None:
        if not isinstance(self.partition, BinaryFrontierPartition):
            raise OperationNativeDataflowError("child receipt requires a typed BinaryFrontierPartition")
        expected_type = _RECEIPT_TYPES[self.partition.operation]
        if type(self.receipt) is not expected_type:
            raise OperationNativeDataflowError("child receipt type does not match its partition operation")
        route = self.partition.route_witness
        receipt = self.receipt
        if receipt.request_digest != self.partition.request.digest:
            raise OperationNativeDataflowError("child receipt belongs to a different child request")
        if tuple(node_id for node_id, _value in receipt.results) != self.partition.node_ids:
            raise OperationNativeDataflowError("child receipt result identities differ from its exact partition lanes")
        if (
            receipt.host_id != route.target_host.host_id
            or receipt.peer_id != route.target_host.peer_id
            or receipt.peer_path != route.peer_path
            or receipt.route_witness_digest != route.digest
            or receipt.implementation_fingerprint != route.target_host.implementation_fingerprint
        ):
            raise OperationNativeDataflowError("child receipt does not bind its assigned host, route, and implementation")
        expected_memory = {
            reference.binding
            for lane in self.partition.request.lanes
            for reference in (lane.left_reference, lane.right_reference)
            if reference is not None
        }
        actual_memory = {binding for binding, _receipt in receipt.structural_memory_receipts}
        if actual_memory != expected_memory:
            raise OperationNativeDataflowError("child receipt Structural Memory bindings differ from the exact child request")

    @property
    def digest(self) -> str:
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "mailcpu.binary-frontier-child-receipt.v1",
            "partition": self.partition.to_dict(),
            "receipt": self.receipt.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BinaryFrontierChildReceipt":
        expected = {"schema", "partition", "receipt"}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise OperationNativeDataflowError("binary frontier child receipt fields are malformed")
        if payload["schema"] != "mailcpu.binary-frontier-child-receipt.v1":
            raise OperationNativeDataflowError("binary frontier child receipt schema is unsupported")
        try:
            partition = BinaryFrontierPartition.from_dict(payload["partition"])
            receipt_type = _RECEIPT_TYPES[partition.operation]
            receipt = receipt_type.from_dict(payload["receipt"])
            return cls(partition, receipt)
        except (KeyError, TypeError, ValueError, FrontierPartitionError) as exc:
            if isinstance(exc, OperationNativeDataflowError):
                raise
            raise OperationNativeDataflowError("binary frontier child receipt contains invalid typed evidence") from exc


def _validate_parent_plan(
    request: DataflowAddFrontierRequest | DataflowCompareFrontierRequest | DataflowMultiplyFrontierRequest,
    plan: BinaryFrontierPartitionPlan,
) -> None:
    operation = _operation_for_request(request)
    if (
        plan.plan_digest != request.plan_digest
        or plan.context_digest != request.context_digest
        or plan.frontier_index != request.frontier_index
        or plan.operation != operation
        or plan.frontier_node_ids != tuple(sorted(lane.node_id for lane in request.lanes))
    ):
        raise OperationNativeDataflowError("partition plan does not bind the exact parent frontier request")
    child_lanes = tuple(sorted(
        (lane for partition in plan.partitions for lane in partition.request.lanes),
        key=lambda lane: lane.node_id,
    ))
    if tuple(lane.to_dict() for lane in child_lanes) != tuple(
        lane.to_dict() for lane in request.lanes
    ):
        raise OperationNativeDataflowError("child partition lanes do not reconstruct the exact parent request")


def _ordered_child_receipts(
    plan: BinaryFrontierPartitionPlan,
    children: Sequence[BinaryFrontierChildReceipt],
    *,
    allow_partial: bool,
) -> tuple[BinaryFrontierChildReceipt, ...]:
    by_partition: dict[str, BinaryFrontierChildReceipt] = {}
    for child in children:
        if not isinstance(child, BinaryFrontierChildReceipt):
            raise OperationNativeDataflowError("parent receipt children must be typed child receipts")
        partition_digest = child.partition.digest
        if partition_digest in by_partition:
            raise OperationNativeDataflowError("one child partition has more than one receipt")
        by_partition[partition_digest] = child
    expected = {partition.digest: partition for partition in plan.partitions}
    if not set(by_partition).issubset(expected):
        raise OperationNativeDataflowError("child receipt refers to a partition outside the parent plan")
    if not allow_partial and set(by_partition) != set(expected):
        raise OperationNativeDataflowError("composite parent receipt is missing one or more child receipts")
    ordered = tuple(
        by_partition[item.digest]
        for item in plan.partitions
        if item.digest in by_partition
    )
    for child in ordered:
        expected_partition = expected[child.partition.digest]
        if child.partition.to_dict() != expected_partition.to_dict():
            raise OperationNativeDataflowError("child receipt partition differs from the assigned parent-plan partition")
    return ordered


@dataclass(frozen=True)
class BinaryFrontierCompositeReceipt:
    """Complete parent frontier evidence assembled from every verified child receipt."""

    request: DataflowAddFrontierRequest | DataflowCompareFrontierRequest | DataflowMultiplyFrontierRequest
    plan: BinaryFrontierPartitionPlan
    children: tuple[BinaryFrontierChildReceipt, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.plan, BinaryFrontierPartitionPlan):
            raise OperationNativeDataflowError("composite receipt requires a typed partition plan")
        _validate_parent_plan(self.request, self.plan)
        ordered = _ordered_child_receipts(self.plan, tuple(self.children), allow_partial=False)
        object.__setattr__(self, "children", ordered)

    @property
    def operation(self) -> str:
        return self.plan.operation

    @property
    def request_digest(self) -> str:
        return self.request.digest

    @property
    def results(self) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(
            (item for child in self.children for item in child.receipt.results),
            key=lambda item: item[0],
        ))

    @property
    def structural_memory_receipts(self) -> tuple[tuple[str, Any], ...]:
        receipts = tuple(sorted(
            (item for child in self.children for item in child.receipt.structural_memory_receipts),
            key=lambda item: item[0],
        ))
        if len({binding for binding, _receipt in receipts}) != len(receipts):
            raise OperationNativeDataflowError("composite receipt contains duplicate Structural Memory bindings")
        return receipts

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": "mailcpu.binary-frontier-composite-receipt.v1",
            "operation": self.operation,
            "request": self.request.to_dict(),
            "plan": self.plan.to_dict(),
            "children": [item.to_dict() for item in self.children],
            "results": [[node_id, value] for node_id, value in self.results],
            "structural_memory_receipt_digests": [
                [binding, receipt.digest]
                for binding, receipt in self.structural_memory_receipts
            ],
        }

    @property
    def digest(self) -> str:
        return canonical_value_digest(self._payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "digest": self.digest}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BinaryFrontierCompositeReceipt":
        expected = {
            "schema", "operation", "request", "plan", "children", "results",
            "structural_memory_receipt_digests", "digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise OperationNativeDataflowError("binary frontier composite receipt fields are malformed")
        if (
            payload["schema"] != "mailcpu.binary-frontier-composite-receipt.v1"
            or not isinstance(payload["children"], list)
            or not isinstance(payload["results"], list)
            or not isinstance(payload["structural_memory_receipt_digests"], list)
        ):
            raise OperationNativeDataflowError("binary frontier composite receipt schema or nested fields are invalid")
        try:
            request = _request_from_dict(payload["request"])
            plan = BinaryFrontierPartitionPlan.from_dict(payload["plan"])
            receipt = cls(
                request=request,
                plan=plan,
                children=tuple(BinaryFrontierChildReceipt.from_dict(item) for item in payload["children"]),
            )
        except (KeyError, TypeError, ValueError, FrontierPartitionError) as exc:
            if isinstance(exc, OperationNativeDataflowError):
                raise
            raise OperationNativeDataflowError("binary frontier composite receipt contains invalid nested evidence") from exc
        if (
            payload["operation"] != receipt.operation
            or payload["results"] != [[node_id, value] for node_id, value in receipt.results]
            or payload["structural_memory_receipt_digests"] != [
                [binding, item.digest] for binding, item in receipt.structural_memory_receipts
            ]
            or payload["digest"] != receipt.digest
        ):
            raise OperationNativeDataflowError("binary frontier composite receipt projection or digest is inconsistent")
        return receipt


@dataclass(frozen=True)
class BinaryFrontierExecutionCheckpoint:
    """Replay-safe progress record containing the fixed route plan and only validated child receipts."""

    request: DataflowAddFrontierRequest | DataflowCompareFrontierRequest | DataflowMultiplyFrontierRequest
    plan: BinaryFrontierPartitionPlan
    successful_children: tuple[BinaryFrontierChildReceipt, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.plan, BinaryFrontierPartitionPlan):
            raise OperationNativeDataflowError("execution checkpoint requires a typed partition plan")
        _validate_parent_plan(self.request, self.plan)
        ordered = _ordered_child_receipts(self.plan, tuple(self.successful_children), allow_partial=True)
        object.__setattr__(self, "successful_children", ordered)

    @property
    def complete(self) -> bool:
        return len(self.successful_children) == len(self.plan.partitions)

    @property
    def remaining_partitions(self) -> tuple[BinaryFrontierPartition, ...]:
        completed = {item.partition.digest for item in self.successful_children}
        return tuple(item for item in self.plan.partitions if item.digest not in completed)

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": "mailcpu.binary-frontier-execution-checkpoint.v1",
            "request": self.request.to_dict(),
            "plan": self.plan.to_dict(),
            "successful_children": [item.to_dict() for item in self.successful_children],
        }

    @property
    def digest(self) -> str:
        return canonical_value_digest(self._payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "digest": self.digest}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BinaryFrontierExecutionCheckpoint":
        expected = {"schema", "request", "plan", "successful_children", "digest"}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise OperationNativeDataflowError("binary frontier execution checkpoint fields are malformed")
        if (
            payload["schema"] != "mailcpu.binary-frontier-execution-checkpoint.v1"
            or not isinstance(payload["successful_children"], list)
        ):
            raise OperationNativeDataflowError("binary frontier execution checkpoint schema or children are invalid")
        try:
            checkpoint = cls(
                request=_request_from_dict(payload["request"]),
                plan=BinaryFrontierPartitionPlan.from_dict(payload["plan"]),
                successful_children=tuple(
                    BinaryFrontierChildReceipt.from_dict(item)
                    for item in payload["successful_children"]
                ),
            )
        except (KeyError, TypeError, ValueError, FrontierPartitionError) as exc:
            if isinstance(exc, OperationNativeDataflowError):
                raise
            raise OperationNativeDataflowError("binary frontier execution checkpoint contains invalid nested evidence") from exc
        if payload["digest"] != checkpoint.digest:
            raise OperationNativeDataflowError("binary frontier execution checkpoint digest mismatch")
        return checkpoint


class PartitionedFrontierIncomplete(OperationNativeDataflowError):
    """A bounded set of child dispatches did not complete; checkpoint contains all validated progress."""

    def __init__(
        self,
        message: str,
        checkpoint: BinaryFrontierExecutionCheckpoint,
        failures: Sequence[str] = (),
    ) -> None:
        super().__init__(message)
        self.checkpoint = checkpoint
        self.failures = tuple(failures)


class PartitionedComputationalFabricDataflowBinaryDispatcher:
    """Dispatch independently addressed children, checkpoint progress, and assemble one parent receipt."""

    def __init__(
        self,
        dispatcher: Any,
        *,
        max_concurrency: int = 4,
        checkpoint_sink: Callable[[BinaryFrontierExecutionCheckpoint], None] | None = None,
    ) -> None:
        if (
            not callable(dispatcher)
            or not callable(getattr(dispatcher, "prepare_routes", None))
            or not isinstance(getattr(dispatcher, "forwarding_clients", None), Mapping)
            or not isinstance(getattr(dispatcher, "operation", None), str)
            or dispatcher.operation not in _REQUEST_TYPES
        ):
            raise OperationNativeDataflowError("partitioned dispatcher requires a configured ComputationalFabricDataflowBinaryDispatcher")
        if type(max_concurrency) is not int or not 1 <= max_concurrency <= _MAX_PARTITIONS:
            raise OperationNativeDataflowError(f"max_concurrency must be in the range 1..{_MAX_PARTITIONS}")
        if checkpoint_sink is not None and not callable(checkpoint_sink):
            raise OperationNativeDataflowError("checkpoint_sink must be callable")
        self.dispatcher = dispatcher
        self.operator_spec = dispatcher.operator_spec
        self.operation = dispatcher.operation
        self.max_concurrency = max_concurrency
        self.checkpoint_sink = checkpoint_sink

    def _new_plan(
        self,
        request: DataflowAddFrontierRequest | DataflowCompareFrontierRequest | DataflowMultiplyFrontierRequest,
        partition_groups: Sequence[Sequence[str]],
    ) -> BinaryFrontierPartitionPlan:
        child_requests = split_binary_frontier_request(request, partition_groups)
        choices: list[tuple[BinaryFrontierPartition, ...]] = []
        directory_digest: str | None = None
        topology_digest: str | None = None

        for child_request in child_requests:
            address, placement = self.dispatcher.prepare_routes(child_request, max_candidates=_MAX_ROUTE_CANDIDATES)
            if not isinstance(address, ComputationalAddress) or not isinstance(placement, ComputationalFabricPlacementSet):
                raise OperationNativeDataflowError("child preparation did not return a typed address and placement set")
            if placement.status is not ComputationalFabricStatus.FOUND:
                details = "; ".join(item.detail for item in placement.blockers[:4])
                raise OperationNativeDataflowError(
                    f"no feasible remote host for child {child_request.digest}: {placement.status.value}: {details}"
                )
            if directory_digest is None:
                directory_digest = placement.directory_digest
                topology_digest = placement.topology_digest
            elif (
                placement.directory_digest != directory_digest
                or placement.topology_digest != topology_digest
            ):
                raise OperationNativeDataflowError("fabric directory/topology changed while preparing child routes")

            candidates = tuple(
                route for route in placement.candidates
                if isinstance(route, ComputationalFabricRouteWitness)
                and route.address_digest == address.digest
                and len(route.peer_path) >= 2
                and route.peer_path[1] in self.dispatcher.forwarding_clients
                and route.target_host.implementation_fingerprint is not None
            )
            if not candidates:
                raise OperationNativeDataflowError(
                    f"child {child_request.digest} has no remote route through a configured authenticated next hop"
                )
            choices.append(tuple(
                BinaryFrontierPartition(child_request, address, route)
                for route in candidates
            ))

        # Stable augmenting-path matching allocates distinct logical hosts
        # without greedily consuming a host needed by a later child.
        owners: dict[tuple[str, str], int] = {}
        selected: dict[int, BinaryFrontierPartition] = {}

        def place(child_index: int, visited_children: set[int], visited_hosts: set[tuple[str, str]]) -> bool:
            if child_index in visited_children:
                return False
            visited_children.add(child_index)
            for candidate in choices[child_index]:
                host_key = (
                    candidate.route_witness.target_host.peer_id,
                    candidate.route_witness.target_host.host_id,
                )
                if host_key in visited_hosts:
                    continue
                visited_hosts.add(host_key)
                previous = owners.get(host_key)
                if previous is None or place(previous, visited_children, visited_hosts):
                    owners[host_key] = child_index
                    selected[child_index] = candidate
                    return True
            return False

        for index in range(len(child_requests)):
            if not place(index, set(), set()):
                raise OperationNativeDataflowError(
                    "the available remote host set cannot assign every child to a distinct logical host"
                )

        partitions = tuple(sorted(
            selected[index] for index in range(len(child_requests)),
            key=lambda item: (
                item.node_ids[0],
                item.route_witness.target_host.peer_id,
                item.route_witness.target_host.host_id,
                item.request.digest,
            ),
        ))
        if directory_digest is None or topology_digest is None:
            raise OperationNativeDataflowError("partition planner did not capture a coherent fabric view")
        return BinaryFrontierPartitionPlan(
            plan_digest=request.plan_digest,
            context_digest=request.context_digest,
            frontier_index=request.frontier_index,
            operation=self.operation,
            computational_ground_fingerprint=self.dispatcher.computational_ground_fingerprint,
            origin_peer_id=self.dispatcher.origin_peer_id,
            directory_digest=directory_digest,
            topology_digest=topology_digest,
            frontier_node_ids=tuple(sorted(lane.node_id for lane in request.lanes)),
            partitions=partitions,
        )

    def dispatch(
        self,
        request: DataflowAddFrontierRequest | DataflowCompareFrontierRequest | DataflowMultiplyFrontierRequest,
        partition_groups: Sequence[Sequence[str]] | None = None,
        *,
        checkpoint: BinaryFrontierExecutionCheckpoint | Mapping[str, Any] | None = None,
    ) -> BinaryFrontierCompositeReceipt:
        operation = _operation_for_request(request)
        if operation != self.operation:
            raise OperationNativeDataflowError("parent request operation differs from the configured binary dispatcher")

        if checkpoint is None:
            if partition_groups is None:
                raise OperationNativeDataflowError("initial partitioned execution requires explicit partition_groups")
            plan = self._new_plan(request, partition_groups)
            state = BinaryFrontierExecutionCheckpoint(request, plan, ())
        else:
            state = (
                checkpoint
                if isinstance(checkpoint, BinaryFrontierExecutionCheckpoint)
                else BinaryFrontierExecutionCheckpoint.from_dict(checkpoint)
            )
            if state.request.digest != request.digest or state.request.to_dict() != request.to_dict():
                raise OperationNativeDataflowError("recovery checkpoint belongs to a different parent frontier request")
            if partition_groups is not None:
                proposed = split_binary_frontier_request(request, partition_groups)
                proposed_groups = {tuple(item.node_ids) for item in proposed}
                recovered_groups = {tuple(item.node_ids) for item in state.plan.partitions}
                if proposed_groups != recovered_groups:
                    raise OperationNativeDataflowError("recovery partition_groups differ from the saved exact partition plan")

        if state.complete:
            return BinaryFrontierCompositeReceipt(request, state.plan, state.successful_children)

        if self.checkpoint_sink is not None:
            try:
                self.checkpoint_sink(state)
            except Exception as exc:
                raise PartitionedFrontierIncomplete(
                    f"could not persist the partition plan before dispatch: {exc}",
                    state,
                    (f"checkpoint_sink: {type(exc).__name__}: {exc}",),
                ) from exc

        completed = {item.partition.digest: item for item in state.successful_children}
        failures: list[str] = []
        pending = state.remaining_partitions
        index_by_digest = {item.digest: index for index, item in enumerate(state.plan.partitions)}

        def dispatch_one(partition: BinaryFrontierPartition) -> BinaryFrontierChildReceipt:
            partition_index = index_by_digest[partition.digest]
            # Each frontier reserves one bounded 64-sequence window on this
            # dispatcher channel; child ordinals are stable across recovery.
            sequence = (
                self.dispatcher.first_sequence
                + request.frontier_index * _MAX_PARTITIONS
                + partition_index
            )
            receipt = self.dispatcher(
                partition.request,
                route_witness=partition.route_witness,
                origin_sequence=sequence,
            )
            return BinaryFrontierChildReceipt(partition, receipt)

        with ThreadPoolExecutor(
            max_workers=min(self.max_concurrency, len(pending)),
            thread_name_prefix="ecpu-frontier",
        ) as executor:
            futures = {executor.submit(dispatch_one, partition): partition for partition in pending}
            for future in as_completed(futures):
                partition = futures[future]
                try:
                    child_receipt = future.result()
                except Exception as exc:
                    failures.append(
                        f"{partition.request.digest}: {type(exc).__name__}: {str(exc)[:512]}"
                    )
                    continue
                completed[partition.digest] = child_receipt
                state = BinaryFrontierExecutionCheckpoint(
                    request,
                    state.plan,
                    tuple(
                        completed[item.digest]
                        for item in state.plan.partitions
                        if item.digest in completed
                    ),
                )
                if self.checkpoint_sink is not None:
                    try:
                        self.checkpoint_sink(state)
                    except Exception as exc:
                        failures.append(f"checkpoint_sink: {type(exc).__name__}: {str(exc)[:512]}")
        
        final_state = BinaryFrontierExecutionCheckpoint(
            request,
            state.plan,
            tuple(
                completed[item.digest]
                for item in state.plan.partitions
                if item.digest in completed
            ),
        )
        if failures or not final_state.complete:
            raise PartitionedFrontierIncomplete(
                f"partitioned {self.operation} frontier is incomplete: "
                f"{len(final_state.successful_children)}/{len(final_state.plan.partitions)} child receipts verified",
                final_state,
                failures,
            )
        return BinaryFrontierCompositeReceipt(request, final_state.plan, final_state.successful_children)

    def __call__(
        self,
        request: DataflowAddFrontierRequest | DataflowCompareFrontierRequest | DataflowMultiplyFrontierRequest,
    ) -> BinaryFrontierCompositeReceipt:
        raise OperationNativeDataflowError(
            "partitioned dispatcher requires explicit partition_groups; call dispatch(request, partition_groups)"
        )
