"""Receiver-side, capability-gated reads of admitted structural-memory revisions."""

from __future__ import annotations

from typing import Any, Mapping

from .classifier import HypervisorArbitrationEvent
from .headless import HeadlessOS
from .structural_memory import StructuralMemoryError, StructuralMemoryReadReceipt


TRANSIT_STRUCTURAL_MEMORY_OPERATION = (
    "read admitted structural-memory revision coordinate"
)
TRANSIT_STRUCTURAL_MEMORY_RESOURCE = "/structural-memory/read"
_TRANSIT_STRUCTURAL_MEMORY_RIGHTS = frozenset({"read"})
_PAYLOAD_FIELDS = frozenset({"memory_id", "revision", "context", "coordinate"})


class TransitStructuralMemoryError(ValueError):
    """Mathematics: refuse a request unless operation identity, local read authority, exact revision, context, and coordinate are valid."""


class TransitStructuralMemoryHost:
    """Resolve one explicitly pinned structural-memory coordinate at the receiving boundary.

    The host contains no second memory registry and no generator implementation.
    It delegates to the receiver's checkpointed StructuralMemoryRegistry, which
    owns immutable versions, context validation, guarded generator navigation,
    read caching, and evidence receipts.
    """

    operation_name = TRANSIT_STRUCTURAL_MEMORY_OPERATION
    resource_name = TRANSIT_STRUCTURAL_MEMORY_RESOURCE

    def __init__(self, operating_system: HeadlessOS, authority_pid: int) -> None:
        """Mathematics: bind read host H to receiver state S and local authority a; all reads resolve through S.structural_memory."""

        if not isinstance(operating_system, HeadlessOS):
            raise TypeError("transit structural-memory host requires a HeadlessOS receiver")
        if not isinstance(authority_pid, int) or isinstance(authority_pid, bool) or authority_pid <= 0:
            raise TypeError("transit structural-memory authority pid must be a positive integer")
        operating_system.environment.kernel._process(authority_pid)
        self.operating_system = operating_system
        self.authority_pid = authority_pid

    def _require_local_read_capability(self) -> None:
        """Mathematics: admit only when receiver process a holds read on resource r, independent of peer-supplied grants."""

        process = self.operating_system.environment.kernel._process(self.authority_pid)
        if not any(
            capability.allows(self.resource_name, "read")
            for capability in process.capabilities
        ):
            raise TransitStructuralMemoryError(
                f"receiver authority lacks 'read' permission for {self.resource_name}"
            )

    def handle(self, event: HypervisorArbitrationEvent) -> dict[str, Any]:
        """Mathematics: map request (m,r,c,t) to the registry's guarded receipt for immutable version (m,r) at context c and coordinate t."""

        if not isinstance(event, HypervisorArbitrationEvent):
            raise TransitStructuralMemoryError(
                "structural-memory operation requires a typed arbitration event"
            )
        request = event.request
        if request.operation != self.operation_name or request.resource != self.resource_name:
            raise TransitStructuralMemoryError(
                "operation identity is not a structural-memory coordinate read"
            )
        if (
            request.required_rights != _TRANSIT_STRUCTURAL_MEMORY_RIGHTS
            or request.granted_rights != _TRANSIT_STRUCTURAL_MEMORY_RIGHTS
        ):
            raise TransitStructuralMemoryError(
                "exact receiver-local read authority is required"
            )
        if request.destructive:
            raise TransitStructuralMemoryError(
                "structural-memory reads cannot be marked destructive"
            )

        payload = request.payload
        if not isinstance(payload, Mapping) or set(payload) != _PAYLOAD_FIELDS:
            raise TransitStructuralMemoryError(
                "structural-memory read payload fields are invalid"
            )

        memory_id = payload.get("memory_id")
        revision = payload.get("revision")
        context = payload.get("context")
        coordinate = payload.get("coordinate")
        if (
            not isinstance(memory_id, str)
            or not memory_id.strip()
            or len(memory_id) > 256
        ):
            raise TransitStructuralMemoryError(
                "memory_id must be non-empty text of at most 256 characters"
            )
        if not isinstance(revision, int) or isinstance(revision, bool) or revision <= 0:
            raise TransitStructuralMemoryError("revision must be a positive integer")
        if not isinstance(coordinate, int) or isinstance(coordinate, bool) or coordinate < 0:
            raise TransitStructuralMemoryError("coordinate must be a non-negative integer")
        if not isinstance(context, Mapping):
            raise TransitStructuralMemoryError("context must be a mapping")

        # Re-check the actual receiver process even though the worker normally
        # reconstructs granted_rights first. Direct host invocation must not
        # turn an event's asserted grant into authority.
        self._require_local_read_capability()

        try:
            receipt = self.operating_system.structural_memory.read_revision(
                memory_id,
                revision,
                coordinate,
                context=context,
            )
        except StructuralMemoryError as exc:
            raise TransitStructuralMemoryError(
                f"structural-memory read refused: {exc}"
            ) from exc
        except Exception as exc:
            raise TransitStructuralMemoryError(
                f"structural-memory read failed: {type(exc).__name__}: {exc}"
            ) from exc

        if not isinstance(receipt, StructuralMemoryReadReceipt):
            raise TransitStructuralMemoryError(
                "structural-memory registry returned an invalid read receipt"
            )
        return receipt.to_dict()
