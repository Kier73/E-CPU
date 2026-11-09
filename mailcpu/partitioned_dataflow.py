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
from .transferable_execution_claim import (
    ExecutionClaimStatus,
    PortableExecutionClaimBundle,
    TransferableExecutionClaimError,
)


_MAX_PARTITIONS = 64
_MAX_ROUTE_CANDIDATES = 128
_ASSIGNMENT_EPOCH_SLOTS = 4
_SEQUENCE_WINDOW_SIZE = _MAX_PARTITIONS * _ASSIGNMENT_EPOCH_SLOTS
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
    """Mathematics: select the exact binary operator family by typed request class; structurally similar payloads are not interchangeable."""
    for operation, request_type in _REQUEST_TYPES.items():
        if type(request) is request_type:
            return operation
    raise OperationNativeDataflowError("partitioned execution requires an exact typed ADD, COMPARE, or MUL request")


@dataclass(frozen=True)
class BinaryFrontierChildReceipt:
    """One child partition paired with its independently verified typed host receipt."""

    partition: BinaryFrontierPartition
    receipt: Any
    claim_bundle: PortableExecutionClaimBundle | None = None
    completion_bundle: PortableExecutionClaimBundle | None = None

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
        if self.claim_bundle is not None:
            if not isinstance(self.claim_bundle, PortableExecutionClaimBundle):
                raise OperationNativeDataflowError("child receipt claim evidence must be a typed PortableExecutionClaimBundle")
            claim = self.claim_bundle.claim
            assignment = claim.current_assignment
            expected_attestation = {
                "schema": "mailcpu.execution-claim-attestation.v1",
                "claim_id": claim.claim_id,
                "assignment_epoch": assignment.epoch,
                "ticket_digest": self.claim_bundle.digest,
                "state_generation": self.claim_bundle.manifest.generation,
                "state_manifest_digest": self.claim_bundle.manifest.digest,
            }
            if (
                claim.child_request_digest != self.partition.request.digest
                or claim.address_digest != self.partition.address.digest
                or claim.operator_spec.digest != self.partition.address.operator_contract_digest
                or claim.computational_ground_fingerprint != self.partition.address.computational_ground_fingerprint
                or assignment.owner_peer_id != route.target_host.peer_id
                or assignment.owner_host_id != route.target_host.host_id
                or assignment.implementation_fingerprint != route.target_host.implementation_fingerprint
                or dict(receipt.execution_claim or {}) != expected_attestation
            ):
                raise OperationNativeDataflowError(
                    "child receipt does not preserve the exact quorum-bound claim, assignment epoch and target"
                )
        elif receipt.execution_claim is not None:
            raise OperationNativeDataflowError("unclaimed child receipt cannot inject execution-claim evidence")
        if self.completion_bundle is not None:
            if self.claim_bundle is None or not isinstance(self.completion_bundle, PortableExecutionClaimBundle):
                raise OperationNativeDataflowError("claim completion evidence requires its original assignment ticket")
            admitted = self.claim_bundle.claim
            completed = self.completion_bundle.claim
            expected_result_digest = canonical_value_digest({
                "schema": "mailcpu.binary-frontier-child-result.v1",
                "request_digest": self.partition.request.digest,
                "results": [[node_id, value] for node_id, value in receipt.results],
                "operator_effect_digest": receipt.operator_effect_digest,
            })
            if (
                admitted.status is not ExecutionClaimStatus.ASSIGNED
                or completed.status is not ExecutionClaimStatus.COMPLETED
                or completed.claim_id != admitted.claim_id
                or completed.assignments != admitted.assignments
                or completed.result_digest != expected_result_digest
                or completed.child_receipt_digest != receipt.digest
            ):
                raise OperationNativeDataflowError(
                    "child completion ticket does not bind the exact admitted claim, result and typed receipt"
                )
        elif self.claim_bundle is None and self.completion_bundle is not None:
            raise OperationNativeDataflowError("unclaimed child receipt cannot carry completion evidence")

    @property
    def digest(self) -> str:
        """Mathematics: identify the complete child evidence or checkpoint projection with a canonical content digest."""
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the complete typed evidence while retaining the fields required to recompute its digest."""
        payload = {
            "schema": "mailcpu.binary-frontier-child-receipt.v1",
            "partition": self.partition.to_dict(),
            "receipt": self.receipt.to_dict(),
        }
        if self.claim_bundle is not None:
            payload["schema"] = (
                "mailcpu.binary-frontier-child-receipt.v3"
                if self.completion_bundle is not None
                else "mailcpu.binary-frontier-child-receipt.v2"
            )
            payload["claim_bundle"] = self.claim_bundle.to_dict()
            if self.completion_bundle is not None:
                payload["completion_bundle"] = self.completion_bundle.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BinaryFrontierChildReceipt":
        """Mathematics: restore typed evidence only after validating the schema, nested values and canonical digest."""
        base_fields = {"schema", "partition", "receipt"}
        if not isinstance(payload, Mapping):
            raise OperationNativeDataflowError("binary frontier child receipt fields are malformed")
        schema = payload.get("schema")
        completion_bundle = None
        if schema == "mailcpu.binary-frontier-child-receipt.v1" and set(payload) == base_fields:
            claim_bundle = None
        elif schema == "mailcpu.binary-frontier-child-receipt.v2" and set(payload) == base_fields | {"claim_bundle"}:
            if not isinstance(payload.get("claim_bundle"), Mapping):
                raise OperationNativeDataflowError("claim-bound child receipt requires a typed claim bundle")
            claim_bundle = PortableExecutionClaimBundle.from_dict(payload["claim_bundle"])
        elif schema == "mailcpu.binary-frontier-child-receipt.v3" and set(payload) == base_fields | {"claim_bundle", "completion_bundle"}:
            if not isinstance(payload.get("claim_bundle"), Mapping) or not isinstance(payload.get("completion_bundle"), Mapping):
                raise OperationNativeDataflowError("completed child receipt requires typed assignment and completion bundles")
            claim_bundle = PortableExecutionClaimBundle.from_dict(payload["claim_bundle"])
            completion_bundle = PortableExecutionClaimBundle.from_dict(payload["completion_bundle"])
        else:
            raise OperationNativeDataflowError("binary frontier child receipt fields or schema are unsupported")
        try:
            partition = BinaryFrontierPartition.from_dict(payload["partition"])
            receipt_type = _RECEIPT_TYPES[partition.operation]
            receipt = receipt_type.from_dict(payload["receipt"])
            return cls(partition, receipt, claim_bundle, completion_bundle)
        except (KeyError, TypeError, ValueError, FrontierPartitionError) as exc:
            if isinstance(exc, OperationNativeDataflowError):
                raise
            raise OperationNativeDataflowError("binary frontier child receipt contains invalid typed evidence") from exc




@dataclass(frozen=True)
class BinaryFrontierReassignmentIntent:
    """Durable pre-quorum intent that makes a rehome retryable across the claim/checkpoint crash cut."""

    previous_partition: BinaryFrontierPartition
    replacement_partition: BinaryFrontierPartition
    claim_id: str
    expected_epoch: int
    failure_evidence_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.previous_partition, BinaryFrontierPartition) or not isinstance(
            self.replacement_partition, BinaryFrontierPartition
        ):
            raise OperationNativeDataflowError("reassignment intent requires typed previous and replacement partitions")
        if (
            self.previous_partition.request.to_dict() != self.replacement_partition.request.to_dict()
            or self.previous_partition.address.to_dict() != self.replacement_partition.address.to_dict()
        ):
            raise OperationNativeDataflowError("reassignment intent changed the semantic child request or address")
        if (
            self.previous_partition.route_witness.target_host.peer_id,
            self.previous_partition.route_witness.target_host.host_id,
        ) == (
            self.replacement_partition.route_witness.target_host.peer_id,
            self.replacement_partition.route_witness.target_host.host_id,
        ):
            raise OperationNativeDataflowError("reassignment intent must select a different logical Host")
        if not isinstance(self.claim_id, str) or len(self.claim_id) != 64 or any(
            ch not in "0123456789abcdef" for ch in self.claim_id
        ):
            raise OperationNativeDataflowError("reassignment intent claim id must be lowercase SHA-256 hex")
        if type(self.expected_epoch) is not int or self.expected_epoch < 1:
            raise OperationNativeDataflowError("reassignment intent epoch must be a positive strict integer")
        if not isinstance(self.failure_evidence_digest, str) or len(self.failure_evidence_digest) != 64 or any(
            ch not in "0123456789abcdef" for ch in self.failure_evidence_digest
        ):
            raise OperationNativeDataflowError("reassignment intent evidence must be lowercase SHA-256 hex")

    @property
    def child_request_digest(self) -> str:
        return self.replacement_partition.request.digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "mailcpu.binary-frontier-reassignment-intent.v1",
            "previous_partition": self.previous_partition.to_dict(),
            "replacement_partition": self.replacement_partition.to_dict(),
            "claim_id": self.claim_id,
            "expected_epoch": self.expected_epoch,
            "failure_evidence_digest": self.failure_evidence_digest,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BinaryFrontierReassignmentIntent":
        expected = {
            "schema", "previous_partition", "replacement_partition",
            "claim_id", "expected_epoch", "failure_evidence_digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise OperationNativeDataflowError("reassignment intent fields are malformed")
        if (
            payload["schema"] != "mailcpu.binary-frontier-reassignment-intent.v1"
            or not isinstance(payload["previous_partition"], Mapping)
            or not isinstance(payload["replacement_partition"], Mapping)
        ):
            raise OperationNativeDataflowError("reassignment intent schema or nested partitions are invalid")
        try:
            return cls(
                BinaryFrontierPartition.from_dict(payload["previous_partition"]),
                BinaryFrontierPartition.from_dict(payload["replacement_partition"]),
                payload["claim_id"],
                payload["expected_epoch"],
                payload["failure_evidence_digest"],
            )
        except (KeyError, TypeError, ValueError, FrontierPartitionError) as exc:
            if isinstance(exc, OperationNativeDataflowError):
                raise
            raise OperationNativeDataflowError("reassignment intent contains invalid typed evidence") from exc


@dataclass(frozen=True)
class BinaryFrontierPartitionReassignment:
    """One quorum-fenced route replacement for an exact semantic child partition."""

    previous_partition: BinaryFrontierPartition
    replacement_partition: BinaryFrontierPartition
    claim_bundle: PortableExecutionClaimBundle
    failure_evidence_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.previous_partition, BinaryFrontierPartition) or not isinstance(
            self.replacement_partition, BinaryFrontierPartition
        ):
            raise OperationNativeDataflowError("partition reassignment requires typed previous and replacement partitions")
        if not isinstance(self.claim_bundle, PortableExecutionClaimBundle):
            raise OperationNativeDataflowError("partition reassignment requires a portable quorum claim ticket")
        if not isinstance(self.failure_evidence_digest, str) or len(self.failure_evidence_digest) != 64:
            raise OperationNativeDataflowError("partition reassignment failure evidence must be a SHA-256 digest")
        if any(ch not in "0123456789abcdef" for ch in self.failure_evidence_digest):
            raise OperationNativeDataflowError("partition reassignment failure evidence must be lowercase SHA-256 hex")
        previous = self.previous_partition
        replacement = self.replacement_partition
        if (
            previous.request.to_dict() != replacement.request.to_dict()
            or previous.address.to_dict() != replacement.address.to_dict()
            or previous.node_ids != replacement.node_ids
            or previous.operation != replacement.operation
        ):
            raise OperationNativeDataflowError("partition reassignment changed the semantic child request or ComputationalAddress")
        old_route = previous.route_witness
        new_route = replacement.route_witness
        if (
            old_route.target_host.peer_id,
            old_route.target_host.host_id,
        ) == (
            new_route.target_host.peer_id,
            new_route.target_host.host_id,
        ):
            raise OperationNativeDataflowError("partition reassignment must select a different logical Host")
        claim = self.claim_bundle.claim
        if (
            claim.child_request_digest != replacement.request.digest
            or claim.address_digest != replacement.address.digest
            or claim.operator_id != replacement.address.operator_id
            or claim.operator_contract_digest != replacement.address.operator_contract_digest
            or claim.computational_ground_fingerprint != replacement.address.computational_ground_fingerprint
            or claim.status is not ExecutionClaimStatus.ASSIGNED
            or len(claim.assignments) < 2
        ):
            raise OperationNativeDataflowError("reassignment claim does not bind this assigned semantic child")
        prior, current = claim.assignments[-2], claim.current_assignment
        if (
            prior.owner_peer_id != old_route.target_host.peer_id
            or prior.owner_host_id != old_route.target_host.host_id
            or prior.implementation_fingerprint != old_route.target_host.implementation_fingerprint
            or current.owner_peer_id != new_route.target_host.peer_id
            or current.owner_host_id != new_route.target_host.host_id
            or current.implementation_fingerprint != new_route.target_host.implementation_fingerprint
            or current.failure_evidence_digest != self.failure_evidence_digest
            or current.epoch != prior.epoch + 1
        ):
            raise OperationNativeDataflowError("reassignment route does not match the quorum-committed adjacent assignment epochs")

    @property
    def child_request_digest(self) -> str:
        return self.replacement_partition.request.digest

    @property
    def digest(self) -> str:
        return canonical_value_digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "mailcpu.binary-frontier-partition-reassignment.v1",
            "previous_partition": self.previous_partition.to_dict(),
            "replacement_partition": self.replacement_partition.to_dict(),
            "claim_bundle": self.claim_bundle.to_dict(),
            "failure_evidence_digest": self.failure_evidence_digest,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BinaryFrontierPartitionReassignment":
        expected = {
            "schema", "previous_partition", "replacement_partition",
            "claim_bundle", "failure_evidence_digest",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise OperationNativeDataflowError("partition reassignment fields are malformed")
        if (
            payload["schema"] != "mailcpu.binary-frontier-partition-reassignment.v1"
            or not all(isinstance(payload[key], Mapping) for key in (
                "previous_partition", "replacement_partition", "claim_bundle"
            ))
        ):
            raise OperationNativeDataflowError("partition reassignment schema or nested evidence is invalid")
        try:
            return cls(
                BinaryFrontierPartition.from_dict(payload["previous_partition"]),
                BinaryFrontierPartition.from_dict(payload["replacement_partition"]),
                PortableExecutionClaimBundle.from_dict(payload["claim_bundle"]),
                payload["failure_evidence_digest"],
            )
        except (KeyError, TypeError, ValueError, FrontierPartitionError) as exc:
            if isinstance(exc, OperationNativeDataflowError):
                raise
            raise OperationNativeDataflowError("partition reassignment contains invalid typed evidence") from exc


def _validate_parent_plan(
    request: DataflowAddFrontierRequest | DataflowCompareFrontierRequest | DataflowMultiplyFrontierRequest,
    plan: BinaryFrontierPartitionPlan,
) -> None:
    """Mathematics: prove that child partitions preserve the parent plan, context, frontier, operation and exact ordered lane set."""
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
    current_partitions: Sequence[BinaryFrontierPartition] | None = None,
    parent_request_digest: str | None = None,
) -> tuple[BinaryFrontierChildReceipt, ...]:
    """Mathematics: require one receipt per exact semantic child while permitting only claim-proven route epochs."""
    strict_current_routes = current_partitions is not None
    expected = {item.request.digest: item for item in plan.partitions}
    active = {
        item.request.digest: item
        for item in (plan.partitions if current_partitions is None else current_partitions)
    }
    if set(active) != set(expected):
        raise OperationNativeDataflowError("active route assignments do not cover the exact parent child partition set")
    by_child: dict[str, BinaryFrontierChildReceipt] = {}
    for child in children:
        if not isinstance(child, BinaryFrontierChildReceipt):
            raise OperationNativeDataflowError("parent receipt children must be typed child receipts")
        child_key = child.partition.request.digest
        if child_key not in expected:
            raise OperationNativeDataflowError("child receipt refers to a semantic partition outside the parent plan")
        if child_key in by_child:
            raise OperationNativeDataflowError("one semantic child partition has more than one receipt")
        original = expected[child_key]
        current = active[child_key]
        if (
            child.partition.request.to_dict() != original.request.to_dict()
            or child.partition.address.to_dict() != original.address.to_dict()
            or child.partition.node_ids != original.node_ids
            or child.partition.operation != original.operation
        ):
            raise OperationNativeDataflowError("child receipt changed its exact semantic request, address or lane set")
        if strict_current_routes and child.partition.to_dict() != current.to_dict():
            raise OperationNativeDataflowError("child receipt route differs from the checkpoint's latest quorum assignment")
        if child.partition.digest != original.digest:
            ticket = child.claim_bundle
            if ticket is None:
                raise OperationNativeDataflowError("a changed child route requires quorum-bound reassignment history")
            claim = ticket.claim
            assignment = claim.current_assignment
            original_assignment = claim.assignments[0]
            route = child.partition.route_witness
            if (
                len(claim.assignments) < 2
                or claim.child_request_digest != child.partition.request.digest
                or claim.address_digest != child.partition.address.digest
                or not isinstance(claim.parent_request_digest, str)
                or not claim.parent_request_digest
                or (
                    parent_request_digest is not None
                    and claim.parent_request_digest != parent_request_digest
                )
                or original_assignment.owner_peer_id != original.route_witness.target_host.peer_id
                or original_assignment.owner_host_id != original.route_witness.target_host.host_id
                or assignment.owner_peer_id != route.target_host.peer_id
                or assignment.owner_host_id != route.target_host.host_id
                or assignment.implementation_fingerprint != route.target_host.implementation_fingerprint
            ):
                raise OperationNativeDataflowError("changed child route lacks a matching quorum assignment history")
        by_child[child_key] = child
    if not allow_partial and set(by_child) != set(expected):
        raise OperationNativeDataflowError("composite parent receipt is missing one or more child receipts")
    return tuple(
        by_child[item.request.digest]
        for item in plan.partitions
        if item.request.digest in by_child
    )

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
        ordered = _ordered_child_receipts(
            self.plan,
            tuple(self.children),
            allow_partial=False,
            parent_request_digest=self.request.digest,
        )
        claim_children = tuple(child for child in ordered if child.claim_bundle is not None)
        if claim_children and len(claim_children) != len(ordered):
            raise OperationNativeDataflowError("composite receipt cannot mix claimed and unclaimed child operations")
        if claim_children and any(child.completion_bundle is None for child in claim_children):
            raise OperationNativeDataflowError("claim-bound composite receipt requires quorum-completed evidence for every child")
        completion_roots = {
            (child.completion_bundle.manifest.generation, child.completion_bundle.manifest.digest)
            for child in claim_children
        }
        if len(completion_roots) > 1:
            raise OperationNativeDataflowError(
                "parent child completion tickets must share one atomic quorum generation"
            )
        if any(
            child.claim_bundle.claim.parent_request_digest != self.request.digest
            for child in claim_children
        ):
            raise OperationNativeDataflowError("composite child claim does not bind the exact original parent request")
        object.__setattr__(self, "children", ordered)

    @property
    def operation(self) -> str:
        """Mathematics: project the homogeneous binary operator identity committed by the parent partition plan."""
        return self.plan.operation

    @property
    def request_digest(self) -> str:
        """Mathematics: expose the exact parent request identity without deriving a surrogate from child partitions."""
        return self.request.digest

    @property
    def results(self) -> tuple[tuple[str, int], ...]:
        """Mathematics: reconstruct the original parent result vector by concatenating and sorting all verified child lane results."""
        return tuple(sorted(
            (item for child in self.children for item in child.receipt.results),
            key=lambda item: item[0],
        ))

    @property
    def structural_memory_receipts(self) -> tuple[tuple[str, Any], ...]:
        """Mathematics: aggregate child memory receipts by binding and refuse duplicate bindings across partitions."""
        receipts = tuple(sorted(
            (item for child in self.children for item in child.receipt.structural_memory_receipts),
            key=lambda item: item[0],
        ))
        if len({binding for binding, _receipt in receipts}) != len(receipts):
            raise OperationNativeDataflowError("composite receipt contains duplicate Structural Memory bindings")
        return receipts

    def _payload(self) -> dict[str, Any]:
        """Mathematics: project the complete receipt or checkpoint contents that participate in its canonical digest."""
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
        """Mathematics: identify the complete child evidence or checkpoint projection with a canonical content digest."""
        return canonical_value_digest(self._payload())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the complete typed evidence while retaining the fields required to recompute its digest."""
        return {**self._payload(), "digest": self.digest}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BinaryFrontierCompositeReceipt":
        """Mathematics: restore typed evidence only after validating the schema, nested values and canonical digest."""
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
    """Replay-safe parent progress plus quorum-proven route replacement history."""

    request: DataflowAddFrontierRequest | DataflowCompareFrontierRequest | DataflowMultiplyFrontierRequest
    plan: BinaryFrontierPartitionPlan
    successful_children: tuple[BinaryFrontierChildReceipt, ...]
    reassignments: tuple[BinaryFrontierPartitionReassignment, ...] = ()
    reassignment_intents: tuple[BinaryFrontierReassignmentIntent, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.plan, BinaryFrontierPartitionPlan):
            raise OperationNativeDataflowError("execution checkpoint requires a typed partition plan")
        _validate_parent_plan(self.request, self.plan)
        history = tuple(self.reassignments)
        intents = tuple(self.reassignment_intents)
        if any(not isinstance(item, BinaryFrontierPartitionReassignment) for item in history):
            raise OperationNativeDataflowError("checkpoint reassignment history must contain typed reassignment records")
        current = {item.request.digest: item for item in self.plan.partitions}
        latest_epochs: dict[str, int] = {}
        for item in history:
            key = item.child_request_digest
            if key not in current:
                raise OperationNativeDataflowError("reassignment history references a child outside the parent plan")
            if item.previous_partition.to_dict() != current[key].to_dict():
                raise OperationNativeDataflowError("reassignment history does not continue the exact previous route assignment")
            claim = item.claim_bundle.claim
            if claim.parent_request_digest != self.request.digest:
                raise OperationNativeDataflowError("reassignment claim does not bind the exact parent request")
            epoch = claim.current_assignment.epoch
            expected_epoch = latest_epochs.get(key, 1) + 1
            if epoch != expected_epoch:
                raise OperationNativeDataflowError("checkpoint reassignment epochs are not strictly consecutive")
            latest_epochs[key] = epoch
            current[key] = item.replacement_partition
        history_order = tuple(
            (item.child_request_digest, item.claim_bundle.claim.current_assignment.epoch)
            for item in history
        )
        if history_order != tuple(sorted(history_order)):
            raise OperationNativeDataflowError("checkpoint reassignment history must use canonical child/epoch order")
        if any(not isinstance(item, BinaryFrontierReassignmentIntent) for item in intents):
            raise OperationNativeDataflowError("checkpoint reassignment intents must be typed")
        intent_keys = tuple(item.child_request_digest for item in intents)
        if len(intent_keys) != len(set(intent_keys)):
            raise OperationNativeDataflowError("checkpoint cannot contain multiple pending intents for one child")
        if intent_keys != tuple(sorted(intent_keys)):
            raise OperationNativeDataflowError("checkpoint reassignment intents must use canonical child order")
        completed_keys = {item.partition.request.digest for item in self.successful_children}
        for intent in intents:
            key = intent.child_request_digest
            if key not in current or intent.previous_partition.to_dict() != current[key].to_dict():
                raise OperationNativeDataflowError("pending reassignment intent does not continue the latest confirmed route")
            if key in completed_keys:
                raise OperationNativeDataflowError("completed child cannot also have a pending reassignment intent")
            latest_epoch = latest_epochs.get(key, 1)
            if intent.expected_epoch != latest_epoch:
                raise OperationNativeDataflowError("pending reassignment intent does not bind the latest assignment epoch")
        ordered = _ordered_child_receipts(
            self.plan,
            tuple(self.successful_children),
            allow_partial=True,
            current_partitions=tuple(current[item.request.digest] for item in self.plan.partitions),
            parent_request_digest=self.request.digest,
        )
        if any(
            child.claim_bundle is not None
            and child.claim_bundle.claim.parent_request_digest != self.request.digest
            for child in ordered
        ):
            raise OperationNativeDataflowError("checkpoint child assignment ticket does not bind the exact parent request")
        object.__setattr__(self, "successful_children", ordered)
        object.__setattr__(self, "reassignments", history)
        object.__setattr__(self, "reassignment_intents", intents)

    @property
    def current_partitions(self) -> tuple[BinaryFrontierPartition, ...]:
        """Mathematics: project the latest route for each semantic child without rewriting its original parent partition plan."""
        current = {item.request.digest: item for item in self.plan.partitions}
        for item in self.reassignments:
            current[item.child_request_digest] = item.replacement_partition
        return tuple(current[item.request.digest] for item in self.plan.partitions)

    @property
    def complete(self) -> bool:
        """Mathematics: determine completeness by equality between validated child receipt count and fixed partition count."""
        return len(self.successful_children) == len(self.plan.partitions)

    @property
    def remaining_partitions(self) -> tuple[BinaryFrontierPartition, ...]:
        """Mathematics: subtract verified semantic child receipts from the latest quorum-assigned route view."""
        completed = {item.partition.request.digest for item in self.successful_children}
        return tuple(item for item in self.current_partitions if item.request.digest not in completed)

    def _payload(self) -> dict[str, Any]:
        """Mathematics: project complete parent progress and every route-reassignment transition into one canonical checkpoint."""
        schema = (
            "mailcpu.binary-frontier-execution-checkpoint.v3"
            if self.reassignment_intents
            else "mailcpu.binary-frontier-execution-checkpoint.v2"
            if self.reassignments else "mailcpu.binary-frontier-execution-checkpoint.v1"
        )
        payload = {
            "schema": schema,
            "request": self.request.to_dict(),
            "plan": self.plan.to_dict(),
            "successful_children": [item.to_dict() for item in self.successful_children],
        }
        if self.reassignments or self.reassignment_intents:
            payload["reassignments"] = [item.to_dict() for item in self.reassignments]
        if self.reassignment_intents:
            payload["reassignment_intents"] = [item.to_dict() for item in self.reassignment_intents]
        return payload

    @property
    def digest(self) -> str:
        """Mathematics: identify the complete child evidence, route history and checkpoint projection."""
        return canonical_value_digest(self._payload())

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the exact typed checkpoint state with its canonical content digest."""
        return {**self._payload(), "digest": self.digest}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BinaryFrontierExecutionCheckpoint":
        """Mathematics: restore typed parent progress only after validating every original and reassigned route proof."""
        if not isinstance(payload, Mapping):
            raise OperationNativeDataflowError("binary frontier execution checkpoint fields are malformed")
        schema = payload.get("schema")
        base_fields = {"schema", "request", "plan", "successful_children", "digest"}
        if schema == "mailcpu.binary-frontier-execution-checkpoint.v1" and set(payload) == base_fields:
            reassignments = ()
            intents = ()
        elif schema == "mailcpu.binary-frontier-execution-checkpoint.v2" and set(payload) == base_fields | {"reassignments"}:
            if not isinstance(payload.get("reassignments"), list):
                raise OperationNativeDataflowError("checkpoint reassignment history must be a list")
            reassignments = tuple(
                BinaryFrontierPartitionReassignment.from_dict(item)
                for item in payload["reassignments"]
            )
            intents = ()
        elif schema == "mailcpu.binary-frontier-execution-checkpoint.v3" and set(payload) == base_fields | {"reassignments", "reassignment_intents"}:
            if not isinstance(payload.get("reassignments"), list) or not isinstance(
                payload.get("reassignment_intents"), list
            ):
                raise OperationNativeDataflowError("checkpoint route history and pending intents must be lists")
            reassignments = tuple(
                BinaryFrontierPartitionReassignment.from_dict(item)
                for item in payload["reassignments"]
            )
            intents = tuple(
                BinaryFrontierReassignmentIntent.from_dict(item)
                for item in payload["reassignment_intents"]
            )
        else:
            raise OperationNativeDataflowError("binary frontier execution checkpoint schema or fields are unsupported")
        if not isinstance(payload.get("successful_children"), list):
            raise OperationNativeDataflowError("binary frontier execution checkpoint children are invalid")
        try:
            checkpoint = cls(
                request=_request_from_dict(payload["request"]),
                plan=BinaryFrontierPartitionPlan.from_dict(payload["plan"]),
                successful_children=tuple(
                    BinaryFrontierChildReceipt.from_dict(item)
                    for item in payload["successful_children"]
                ),
                reassignments=reassignments,
                reassignment_intents=intents,
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
        partition_count: int = 2,
        partition_groups_by_frontier: Mapping[int, Sequence[Sequence[str]]] | Callable[[Any], Sequence[Sequence[str]]] | None = None,
        max_rehome_rounds: int = 1,
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
        if type(partition_count) is not int or not 2 <= partition_count <= _MAX_PARTITIONS:
            raise OperationNativeDataflowError(f"partition_count must be in the range 2..{_MAX_PARTITIONS}")
        if partition_groups_by_frontier is not None and not (
            callable(partition_groups_by_frontier) or isinstance(partition_groups_by_frontier, Mapping)
        ):
            raise OperationNativeDataflowError("partition_groups_by_frontier must be a mapping or callable")
        if type(max_rehome_rounds) is not int or not 0 <= max_rehome_rounds <= 3:
            raise OperationNativeDataflowError("max_rehome_rounds must be a strict integer in the range 0..3")
        self.dispatcher = dispatcher
        # Reserve 64 sequence slots for each of four possible assignment
        # epochs (initial + three rehomes). A rehome therefore never reuses a
        # relay's previous source/channel/sequence deduplication coordinate.
        current_stride = getattr(dispatcher, "frontier_sequence_stride", 1)
        if type(current_stride) is not int or current_stride < _SEQUENCE_WINDOW_SIZE:
            dispatcher.frontier_sequence_stride = _SEQUENCE_WINDOW_SIZE
        self.operator_spec = dispatcher.operator_spec
        self.operation = dispatcher.operation
        self.max_concurrency = max_concurrency
        self.checkpoint_sink = checkpoint_sink
        self.partition_count = partition_count
        self.partition_groups_by_frontier = partition_groups_by_frontier
        self.max_rehome_rounds = max_rehome_rounds

    def _groups_for_request(self, request: Any) -> tuple[tuple[str, ...], ...] | None:
        """Mathematics: split a sorted lane sequence into deterministic, bounded, non-empty child groups or use the caller's explicit grouping."""
        configured = self.partition_groups_by_frontier
        if callable(configured):
            selected = configured(request)
            return tuple(tuple(group) for group in selected)
        if isinstance(configured, Mapping):
            selected = configured.get(request.frontier_index)
            if selected is not None:
                return tuple(tuple(group) for group in selected)
        lane_ids = tuple(lane.node_id for lane in request.lanes)
        count = min(self.partition_count, len(lane_ids))
        if count < 2:
            return None
        groups: list[tuple[str, ...]] = []
        offset = 0
        quotient, remainder = divmod(len(lane_ids), count)
        for index in range(count):
            width = quotient + (1 if index < remainder else 0)
            groups.append(lane_ids[offset:offset + width])
            offset += width
        return tuple(groups)

    def _new_plan(
        self,
        request: DataflowAddFrontierRequest | DataflowCompareFrontierRequest | DataflowMultiplyFrontierRequest,
        partition_groups: Sequence[Sequence[str]],
    ) -> BinaryFrontierPartitionPlan:
        """Mathematics: bind each exact child request to a live route candidate and solve a stable distinct-host assignment over the candidate sets."""
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
            """Mathematics: find a distinct-host assignment with augmenting-path reassignment while visiting each child and host at most once per search."""
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
            (selected[index] for index in range(len(child_requests))),
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

    def _complete_claimed_children(
        self,
        request: DataflowAddFrontierRequest | DataflowCompareFrontierRequest | DataflowMultiplyFrontierRequest,
        children: Sequence[BinaryFrontierChildReceipt],
    ) -> tuple[BinaryFrontierChildReceipt, ...]:
        """Mathematics: Atomically record one parent frontier's validated child results under one quorum completion generation."""
        store = getattr(self.dispatcher, "execution_claim_store", None)
        selected = tuple(children)
        if store is None:
            if any(item.claim_bundle is not None or item.completion_bundle is not None for item in selected):
                raise OperationNativeDataflowError(
                    "claim-bound frontier checkpoint cannot be accepted without the origin execution-claim store"
                )
            return selected
        if any(item.claim_bundle is None for item in selected):
            raise OperationNativeDataflowError(
                "claim-bound parent frontier cannot mix child receipts without assignment tickets"
            )
        completions = []
        for child in selected:
            claim = child.claim_bundle.claim
            assignment = claim.current_assignment
            if (
                claim.parent_request_digest != request.digest
                or claim.child_request_digest != child.partition.request.digest
                or claim.address_digest != child.partition.address.digest
                or claim.status is not ExecutionClaimStatus.ASSIGNED
            ):
                raise OperationNativeDataflowError(
                    "child assignment ticket does not bind the exact still-assigned parent frontier child"
                )
            result_digest = canonical_value_digest({
                "schema": "mailcpu.binary-frontier-child-result.v1",
                "request_digest": child.partition.request.digest,
                "results": [[node_id, value] for node_id, value in child.receipt.results],
                "operator_effect_digest": child.receipt.operator_effect_digest,
            })
            completions.append({
                "claim_id": claim.claim_id,
                "expected_epoch": assignment.epoch,
                "owner_peer_id": assignment.owner_peer_id,
                "owner_host_id": assignment.owner_host_id,
                "implementation_fingerprint": assignment.implementation_fingerprint,
                "result_digest": result_digest,
                "child_receipt_digest": child.receipt.digest,
            })
        try:
            completed_bundles = store.complete_many(tuple(completions))
        except TransferableExecutionClaimError as exc:
            raise OperationNativeDataflowError(
                f"parent frontier could not atomically commit its current child assignment results: {exc}"
            ) from exc
        if len(completed_bundles) != len(selected):
            raise OperationNativeDataflowError("claim authority returned the wrong number of completion tickets")
        by_claim_id = {bundle.claim.claim_id: bundle for bundle in completed_bundles}
        return tuple(
            BinaryFrontierChildReceipt(
                child.partition,
                child.receipt,
                child.claim_bundle,
                by_claim_id[child.claim_bundle.claim.claim_id],
            )
            for child in selected
        )


    @staticmethod
    def _is_rehomeable_failure(error: BaseException) -> bool:
        """Mathematics: classify only transport/path-loss evidence as permission to attempt pure-operation reassignment."""
        current: BaseException | None = error
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, (TimeoutError, ConnectionError, OSError)):
                return True
            current = current.__cause__ or current.__context__
        detail = str(error).lower()
        return any(token in detail for token in (
            "did not return a result before the rpc deadline",
            "forwarding peer stream failed",
            "request exhausted reliable retry attempts",
            "acknowledgement exhausted its retry budget",
            "without acknowledging the corresponding request frame",
            "could not enqueue forwarding operation",
            "preplanned child route is no longer an exact candidate",
        ))

    def _apply_reassignment_intents(
        self,
        request: DataflowAddFrontierRequest | DataflowCompareFrontierRequest | DataflowMultiplyFrontierRequest,
        state: BinaryFrontierExecutionCheckpoint,
    ) -> BinaryFrontierExecutionCheckpoint:
        """Mathematics: replay a persisted reassignment intent against the quorum ledger and materialize its exact committed route epoch."""
        if not state.reassignment_intents:
            return state
        store = getattr(self.dispatcher, "execution_claim_store", None)
        if store is None:
            raise OperationNativeDataflowError("pending route reassignment requires the original execution-claim authority")
        try:
            bundles = store.reassign_many(tuple({
                "claim_id": item.claim_id,
                "expected_epoch": item.expected_epoch,
                "owner_peer_id": item.replacement_partition.route_witness.target_host.peer_id,
                "owner_host_id": item.replacement_partition.route_witness.target_host.host_id,
                "implementation_fingerprint": item.replacement_partition.route_witness.target_host.implementation_fingerprint,
                "failure_evidence_digest": item.failure_evidence_digest,
            } for item in state.reassignment_intents))
        except TransferableExecutionClaimError as exc:
            raise OperationNativeDataflowError(f"cannot resume the quorum-bound route reassignment batch: {exc}") from exc
        if len(bundles) != len(state.reassignment_intents):
            raise OperationNativeDataflowError("claim authority returned the wrong number of reassignment tickets")
        confirmed = tuple(
            BinaryFrontierPartitionReassignment(
                intent.previous_partition,
                intent.replacement_partition,
                bundle,
                intent.failure_evidence_digest,
            )
            for intent, bundle in zip(state.reassignment_intents, bundles)
        )
        updated = BinaryFrontierExecutionCheckpoint(
            request,
            state.plan,
            state.successful_children,
            tuple(sorted(
                state.reassignments + confirmed,
                key=lambda item: (
                    item.child_request_digest,
                    item.claim_bundle.claim.current_assignment.epoch,
                ),
            )),
            (),
        )
        return updated

    def _rehome_failed_partitions(
        self,
        request: DataflowAddFrontierRequest | DataflowCompareFrontierRequest | DataflowMultiplyFrontierRequest,
        state: BinaryFrontierExecutionCheckpoint,
        failures: Mapping[str, tuple[BinaryFrontierPartition, BaseException]],
        claim_tickets: Mapping[str, PortableExecutionClaimBundle],
    ) -> BinaryFrontierExecutionCheckpoint:
        """Mathematics: choose distinct compatible alternate hosts, persist a rehome intent, then atomically advance all failed child epochs."""
        store = getattr(self.dispatcher, "execution_claim_store", None)
        if store is None:
            raise OperationNativeDataflowError("automatic child rehome requires a configured quorum execution-claim store")
        failed = tuple(
            failures[key]
            for key in sorted(failures)
        )
        if not failed:
            return state
        failed_keys = {partition.request.digest for partition, _error in failed}
        failed_hosts = {
            (partition.route_witness.target_host.peer_id, partition.route_witness.target_host.host_id)
            for partition, _error in failed
        }
        occupied_hosts = failed_hosts | {
            (partition.route_witness.target_host.peer_id, partition.route_witness.target_host.host_id)
            for partition in state.current_partitions
            if partition.request.digest not in failed_keys
        }
        candidate_sets: list[tuple[BinaryFrontierPartition, ...]] = []
        directory_digest: str | None = None
        topology_digest: str | None = None
        for partition, error in failed:
            address, placement = self.dispatcher.prepare_routes(
                partition.request,
                max_candidates=_MAX_ROUTE_CANDIDATES,
            )
            if not isinstance(address, ComputationalAddress) or address.digest != partition.address.digest:
                raise OperationNativeDataflowError("rehome route resolution changed the exact child ComputationalAddress")
            if not isinstance(placement, ComputationalFabricPlacementSet):
                raise OperationNativeDataflowError("rehome route resolution did not return a typed placement set")
            if placement.status is not ComputationalFabricStatus.FOUND:
                details = "; ".join(item.detail for item in placement.blockers[:4])
                raise OperationNativeDataflowError(
                    f"no replacement route is currently feasible for child {partition.request.digest}: "
                    f"{placement.status.value}: {details}"
                )
            if directory_digest is None:
                directory_digest = placement.directory_digest
                topology_digest = placement.topology_digest
            elif (
                placement.directory_digest != directory_digest
                or placement.topology_digest != topology_digest
            ):
                raise OperationNativeDataflowError("fabric directory/topology changed while preparing a rehome batch")

            previous_host = (
                partition.route_witness.target_host.peer_id,
                partition.route_witness.target_host.host_id,
            )
            candidates = tuple(
                BinaryFrontierPartition(partition.request, address, route)
                for route in placement.candidates
                if isinstance(route, ComputationalFabricRouteWitness)
                and route.address_digest == address.digest
                and len(route.peer_path) >= 2
                and route.peer_path[1] in self.dispatcher.forwarding_clients
                and route.target_host.implementation_fingerprint is not None
                and (route.target_host.peer_id, route.target_host.host_id) != previous_host
                and (route.target_host.peer_id, route.target_host.host_id) not in occupied_hosts
            )
            if not candidates:
                raise OperationNativeDataflowError(
                    f"no alternate authenticated logical Host is available for child {partition.request.digest}"
                )
            candidate_sets.append(candidates)

        # Distinct-host matching is performed across the whole failed set so
        # two children are never rebound to one logical execution locus.
        owners: dict[tuple[str, str], int] = {}
        selected: dict[int, BinaryFrontierPartition] = {}

        def place(index: int, visited_children: set[int], visited_hosts: set[tuple[str, str]]) -> bool:
            if index in visited_children:
                return False
            visited_children.add(index)
            for candidate in candidate_sets[index]:
                host_key = (
                    candidate.route_witness.target_host.peer_id,
                    candidate.route_witness.target_host.host_id,
                )
                if host_key in visited_hosts:
                    continue
                visited_hosts.add(host_key)
                previous = owners.get(host_key)
                if previous is None or place(previous, visited_children, visited_hosts):
                    owners[host_key] = index
                    selected[index] = candidate
                    return True
            return False

        for index in range(len(candidate_sets)):
            if not place(index, set(), set()):
                raise OperationNativeDataflowError(
                    "available alternate hosts cannot assign every failed child to a distinct logical Host"
                )

        intents: list[BinaryFrontierReassignmentIntent] = []
        for index, (previous_partition, error) in enumerate(failed):
            ticket = claim_tickets.get(previous_partition.digest)
            if not isinstance(ticket, PortableExecutionClaimBundle):
                raise OperationNativeDataflowError("failed child has no current assignment ticket for quorum reassignment")
            assignment = ticket.claim.current_assignment
            if (
                ticket.claim.status is not ExecutionClaimStatus.ASSIGNED
                or assignment.owner_peer_id != previous_partition.route_witness.target_host.peer_id
                or assignment.owner_host_id != previous_partition.route_witness.target_host.host_id
                or assignment.implementation_fingerprint != previous_partition.route_witness.target_host.implementation_fingerprint
            ):
                raise OperationNativeDataflowError("failed child ticket no longer matches its current route assignment")
            replacement = selected[index]
            evidence = canonical_value_digest({
                "schema": "mailcpu.partitioned-frontier-rehome-evidence.v1",
                "parent_request_digest": request.digest,
                "checkpoint_digest": state.digest,
                "child_request_digest": previous_partition.request.digest,
                "previous_partition_digest": previous_partition.digest,
                "previous_route_digest": previous_partition.route_witness.digest,
                "failure_type": type(error).__name__,
                "failure_detail": str(error)[:1024],
            })
            intents.append(BinaryFrontierReassignmentIntent(
                previous_partition,
                replacement,
                ticket.claim.claim_id,
                assignment.epoch,
                evidence,
            ))

        intent_state = BinaryFrontierExecutionCheckpoint(
            request,
            state.plan,
            state.successful_children,
            state.reassignments,
            tuple(sorted(intents, key=lambda item: item.child_request_digest)),
        )
        if self.checkpoint_sink is not None:
            try:
                self.checkpoint_sink(intent_state)
            except Exception as exc:
                raise PartitionedFrontierIncomplete(
                    f"could not durably persist the child-rehome intent before quorum reassignment: {exc}",
                    intent_state,
                    (f"reassignment_intent_checkpoint: {type(exc).__name__}: {str(exc)[:512]}",),
                ) from exc
        try:
            confirmed_state = self._apply_reassignment_intents(request, intent_state)
        except Exception as exc:
            raise PartitionedFrontierIncomplete(
                f"child-rehome quorum transition is incomplete; the persisted intent is safe to replay: {exc}",
                intent_state,
                (f"reassignment_quorum: {type(exc).__name__}: {str(exc)[:512]}",),
            ) from exc
        if self.checkpoint_sink is not None:
            try:
                self.checkpoint_sink(confirmed_state)
            except Exception as exc:
                raise PartitionedFrontierIncomplete(
                    f"quorum reassignment committed but route-confirmation checkpoint was not published: {exc}",
                    intent_state,
                    (f"reassignment_confirmed_checkpoint: {type(exc).__name__}: {str(exc)[:512]}",),
                ) from exc
        return confirmed_state


    def dispatch(
        self,
        request: DataflowAddFrontierRequest | DataflowCompareFrontierRequest | DataflowMultiplyFrontierRequest,
        partition_groups: Sequence[Sequence[str]] | None = None,
        *,
        checkpoint: BinaryFrontierExecutionCheckpoint | Mapping[str, Any] | None = None,
    ) -> BinaryFrontierCompositeReceipt:
        """Mathematics: dispatch bounded pure children, quorum-rehome transport failures and publish one completed parent receipt."""
        operation = _operation_for_request(request)
        if operation != self.operation:
            raise OperationNativeDataflowError("parent request operation differs from the configured binary dispatcher")

        if checkpoint is None:
            if partition_groups is None:
                partition_groups = self._groups_for_request(request)
            if partition_groups is None:
                raise OperationNativeDataflowError("partitioned execution requires at least two lanes and a valid child grouping")
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

        claim_store = getattr(self.dispatcher, "execution_claim_store", None)
        if claim_store is not None and any(item.claim_bundle is None for item in state.successful_children):
            raise PartitionedFrontierIncomplete(
                "recovered child receipts do not carry assignment tickets for the configured claim authority",
                state,
                ("execution_claim: checkpoint predates or omitted claim-bound dispatch",),
            )
        if claim_store is None and (
            state.reassignments
            or state.reassignment_intents
            or any(item.claim_bundle is not None for item in state.successful_children)
        ):
            raise PartitionedFrontierIncomplete(
                "claim-bound child checkpoint requires the original origin claim authority",
                state,
                ("execution_claim: claim authority is not configured",),
            )

        try:
            state = self._apply_reassignment_intents(request, state)
        except Exception as exc:
            raise PartitionedFrontierIncomplete(
                f"could not recover the pending quorum reassignment cut: {exc}",
                state,
                (f"reassignment_recovery: {type(exc).__name__}: {str(exc)[:512]}",),
            ) from exc

        if self.checkpoint_sink is not None:
            try:
                self.checkpoint_sink(state)
            except Exception as exc:
                raise PartitionedFrontierIncomplete(
                    f"could not persist the parent frontier checkpoint before dispatch: {exc}",
                    state,
                    (f"checkpoint_sink: {type(exc).__name__}: {str(exc)[:512]}",),
                ) from exc

        if state.complete:
            try:
                finalized_children = self._complete_claimed_children(request, state.successful_children)
                finalized_state = BinaryFrontierExecutionCheckpoint(
                    request,
                    state.plan,
                    finalized_children,
                    state.reassignments,
                    state.reassignment_intents,
                )
                if self.checkpoint_sink is not None:
                    self.checkpoint_sink(finalized_state)
            except Exception as exc:
                raise PartitionedFrontierIncomplete(
                    f"could not finalize the complete frontier's quorum-bound child results: {exc}",
                    state,
                    (f"claim_completion: {type(exc).__name__}: {str(exc)[:512]}",),
                ) from exc
            return BinaryFrontierCompositeReceipt(request, state.plan, finalized_state.successful_children)

        completed = {item.partition.request.digest: item for item in state.successful_children}
        last_failures: list[str] = []
        rehome_round = 0
        total_rounds = self.max_rehome_rounds + 1

        for _round in range(total_rounds):
            pending = state.remaining_partitions
            if not pending:
                break

            claim_tickets: dict[str, PortableExecutionClaimBundle] = {}
            if claim_store is not None:
                try:
                    claim_tickets = self.dispatcher.prepare_execution_claims(request, pending)
                except Exception as exc:
                    last_failures = [f"execution_claim: {type(exc).__name__}: {str(exc)[:512]}"]
                    break

            index_by_child = {
                item.request.digest: index
                for index, item in enumerate(state.plan.partitions)
            }

            def dispatch_one(partition: BinaryFrontierPartition) -> BinaryFrontierChildReceipt:
                """Mathematics: send one child through its fixed route with the stable sequence slot and one current quorum ticket."""
                partition_index = index_by_child[partition.request.digest]
                claim_bundle = claim_tickets.get(partition.digest)
                assignment_epoch = (
                    1 if claim_bundle is None
                    else claim_bundle.claim.current_assignment.epoch
                )
                if not 1 <= assignment_epoch <= _ASSIGNMENT_EPOCH_SLOTS:
                    raise OperationNativeDataflowError(
                        "child assignment epoch exceeds the reserved origin-sequence attempt window"
                    )
                sequence = (
                    self.dispatcher.first_sequence
                    + request.frontier_index * self.dispatcher.frontier_sequence_stride
                    + (assignment_epoch - 1) * _MAX_PARTITIONS
                    + partition_index
                )
                if claim_bundle is None:
                    receipt = self.dispatcher(
                        partition.request,
                        route_witness=partition.route_witness,
                        origin_sequence=sequence,
                    )
                else:
                    receipt = self.dispatcher(
                        partition.request,
                        route_witness=partition.route_witness,
                        origin_sequence=sequence,
                        parent_request_digest=request.digest,
                        claim_bundle=claim_bundle,
                    )
                return BinaryFrontierChildReceipt(partition, receipt, claim_bundle)

            by_first_hop: dict[str, list[BinaryFrontierPartition]] = {}
            for partition in pending:
                by_first_hop.setdefault(partition.route_witness.peer_path[1], []).append(partition)
            for group in by_first_hop.values():
                group.sort(key=lambda item: index_by_child[item.request.digest])

            def dispatch_group(
                group: Sequence[BinaryFrontierPartition],
            ) -> tuple[tuple[BinaryFrontierChildReceipt, ...], tuple[tuple[BinaryFrontierPartition, BaseException], ...]]:
                """Mathematics: serialize one authenticated stream and stop at its first ambiguous failure."""
                group_successes: list[BinaryFrontierChildReceipt] = []
                group_failures: list[tuple[BinaryFrontierPartition, BaseException]] = []
                for partition in group:
                    try:
                        group_successes.append(dispatch_one(partition))
                    except Exception as exc:
                        group_failures.append((partition, exc))
                        break
                return tuple(group_successes), tuple(group_failures)

            failures_by_child: dict[str, tuple[BinaryFrontierPartition, BaseException]] = {}
            group_failures: list[str] = []
            with ThreadPoolExecutor(
                max_workers=min(self.max_concurrency, len(by_first_hop)),
                thread_name_prefix="ecpu-frontier",
            ) as executor:
                futures = {
                    executor.submit(dispatch_group, tuple(group)): first_hop
                    for first_hop, group in by_first_hop.items()
                }
                for future in as_completed(futures):
                    first_hop = futures[future]
                    try:
                        group_successes, child_failures = future.result()
                    except Exception as exc:
                        group_failures.append(f"first-hop {first_hop}: {type(exc).__name__}: {str(exc)[:512]}")
                        continue
                    for partition, error in child_failures:
                        failures_by_child[partition.request.digest] = (partition, error)
                        group_failures.append(
                            f"{partition.request.digest}: {type(error).__name__}: {str(error)[:512]}"
                        )
                    for child_receipt in group_successes:
                        completed[child_receipt.partition.request.digest] = child_receipt
                        state = BinaryFrontierExecutionCheckpoint(
                            request,
                            state.plan,
                            tuple(
                                completed[item.request.digest]
                                for item in state.current_partitions
                                if item.request.digest in completed
                            ),
                            state.reassignments,
                            state.reassignment_intents,
                        )
                        if self.checkpoint_sink is not None:
                            try:
                                self.checkpoint_sink(state)
                            except Exception as exc:
                                group_failures.append(f"checkpoint_sink: {type(exc).__name__}: {str(exc)[:512]}")
                                break

            if state.complete:
                break
            last_failures = group_failures
            if (
                claim_store is None
                or rehome_round >= self.max_rehome_rounds
                or not failures_by_child
            ):
                break
            rehomeable = {
                key: value
                for key, value in failures_by_child.items()
                if self._is_rehomeable_failure(value[1])
            }
            if not rehomeable:
                break
            try:
                state = self._rehome_failed_partitions(
                    request,
                    state,
                    rehomeable,
                    claim_tickets,
                )
            except PartitionedFrontierIncomplete as exc:
                state = exc.checkpoint
                last_failures.append(f"rehome: {type(exc).__name__}: {str(exc)[:512]}")
                break
            except Exception as exc:
                last_failures.append(f"rehome: {type(exc).__name__}: {str(exc)[:512]}")
                break
            rehome_round += 1
            # A reassign batch advanced the shared claim root. Every still
            # pending sibling therefore receives a fresh ticket next round.

        if not state.complete:
            raise PartitionedFrontierIncomplete(
                f"partitioned {self.operation} frontier is incomplete: "
                f"{len(state.successful_children)}/{len(state.plan.partitions)} child receipts verified",
                state,
                last_failures,
            )

        try:
            finalized_children = self._complete_claimed_children(request, state.successful_children)
            final_state = BinaryFrontierExecutionCheckpoint(
                request,
                state.plan,
                finalized_children,
                state.reassignments,
                state.reassignment_intents,
            )
            if self.checkpoint_sink is not None:
                self.checkpoint_sink(final_state)
        except Exception as exc:
            raise PartitionedFrontierIncomplete(
                f"could not commit and checkpoint the complete parent frontier result set: {exc}",
                state,
                (f"claim_completion: {type(exc).__name__}: {str(exc)[:512]}",),
            ) from exc
        return BinaryFrontierCompositeReceipt(request, final_state.plan, final_state.successful_children)


    def __call__(
        self,
        request: DataflowAddFrontierRequest | DataflowCompareFrontierRequest | DataflowMultiplyFrontierRequest,
    ) -> BinaryFrontierCompositeReceipt | DataflowAddFrontierReceipt | DataflowCompareFrontierReceipt | DataflowMultiplyFrontierReceipt:
        _operation_for_request(request)
        if len(request.lanes) < 2:
            # A one-lane frontier has no partitioning opportunity; retain the
            # established single-host dispatch and typed receipt contract.
            return self.dispatcher(request)
        return self.dispatch(request, self._groups_for_request(request))
