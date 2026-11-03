"""Capability-gated bounded transfers between private MailCPU process memory images."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from .classifier import HypervisorArbitrationEvent
from .headless import HeadlessOS
from .memory import VirtualMemory, VirtualMemoryError


_OPERATION = "execute CPU instruction memory transfer"
_RESOURCE = "/memory/transfer"
_EXECUTE_RIGHT = frozenset({"execute"})


class TransitMemoryTransferError(ValueError):
    """Mathematics: reject a transfer unless endpoint ownership, local capabilities, bounds, and private-page mappings all hold."""


class TransitMemoryTransferHost:
    """Copy a bounded byte interval between receiver-owned private process memory images."""

    def __init__(
        self,
        operating_system: HeadlessOS,
        authority_pid: int,
        *,
        max_transfer_bytes: int = 1 << 20,
    ) -> None:
        """Mathematics: bind transfer host H to receiver OS S and authority a under byte budget B."""

        if not isinstance(operating_system, HeadlessOS):
            raise TypeError("memory transfer host requires a HeadlessOS receiver")
        if not isinstance(authority_pid, int) or isinstance(authority_pid, bool) or authority_pid <= 0:
            raise TypeError("memory transfer authority pid must be a positive integer")
        if not isinstance(max_transfer_bytes, int) or isinstance(max_transfer_bytes, bool) or max_transfer_bytes <= 0:
            raise ValueError("memory transfer byte bound must be a positive integer")
        operating_system.environment.kernel._process(authority_pid)
        self.operating_system = operating_system
        self.authority_pid = authority_pid
        self.max_transfer_bytes = max_transfer_bytes

    def _require_capability(self, pid: int, right: str) -> None:
        """Mathematics: admit endpoint e=(pid,right) iff an authority capability c satisfies c.allows('/memory/pid',right)."""

        authority = self.operating_system.environment.kernel._process(self.authority_pid)
        resource = f"/memory/{pid}"
        if not any(capability.allows(resource, right) for capability in authority.capabilities):
            raise TransitMemoryTransferError(
                f"receiver authority lacks {right!r} permission for {resource}"
            )

    @staticmethod
    def _private_range(
        memory: VirtualMemory,
        address: int,
        length: int,
        access: str,
    ) -> None:
        """Mathematics: require every page in P(address,length) to be resident, private, mapped, and writable for destination access."""

        try:
            memory.validate_access(address, length, access)
        except VirtualMemoryError as exc:
            raise TransitMemoryTransferError(f"{access} range is not mapped: {exc}") from exc

        first_page = address // memory.page_size
        last_page = (address + length - 1) // memory.page_size
        mappings = {mapping.page_number: mapping for mapping in memory.mapped_pages()}
        for page_number in range(first_page, last_page + 1):
            mapping = mappings.get(page_number)
            if mapping is None:
                raise TransitMemoryTransferError(
                    f"{access} range requires resident page {page_number}"
                )
            if mapping.shared_id is not None:
                raise TransitMemoryTransferError(
                    "initial memory transfer host admits private process pages only"
                )
            if access == "write" and not mapping.writable:
                raise TransitMemoryTransferError(
                    f"destination page {page_number} is read-only"
                )

    def handle(self, event: HypervisorArbitrationEvent) -> dict[str, Any]:
        """Mathematics: copy bytes B=S[src,offset:length] to a private destination candidate and commit its mapping relation atomically."""

        if not isinstance(event, HypervisorArbitrationEvent):
            raise TransitMemoryTransferError("memory transfer requires a typed arbitration event")
        request = event.request
        if request.operation != _OPERATION or request.resource != _RESOURCE:
            raise TransitMemoryTransferError("operation identity is not a MailCPU memory transfer request")
        if request.required_rights != _EXECUTE_RIGHT or request.granted_rights != _EXECUTE_RIGHT:
            raise TransitMemoryTransferError("exact receiver-local execute authority is required")
        if request.destructive:
            raise TransitMemoryTransferError("bounded memory transfers cannot be marked destructive")

        payload = request.payload
        expected_fields = {
            "source_pid",
            "source_address",
            "destination_pid",
            "destination_address",
            "length",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected_fields:
            raise TransitMemoryTransferError("memory transfer payload fields are invalid")

        source_pid = payload.get("source_pid")
        destination_pid = payload.get("destination_pid")
        source_address = payload.get("source_address")
        destination_address = payload.get("destination_address")
        length = payload.get("length")
        for name, value in (
            ("source_pid", source_pid),
            ("destination_pid", destination_pid),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise TransitMemoryTransferError(f"{name} must be a positive integer")
        for name, value in (
            ("source_address", source_address),
            ("destination_address", destination_address),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise TransitMemoryTransferError(f"{name} must be a non-negative integer")
        if not isinstance(length, int) or isinstance(length, bool) or length <= 0:
            raise TransitMemoryTransferError("transfer length must be a positive integer")
        if length > self.max_transfer_bytes:
            raise TransitMemoryTransferError("transfer length exceeds configured byte bound")

        self._require_capability(source_pid, "read")
        self._require_capability(destination_pid, "write")
        kernel = self.operating_system.environment.kernel
        kernel._process(source_pid)
        kernel._process(destination_pid)

        try:
            source_memory = self.operating_system.vm.memories[source_pid]
            destination_memory = self.operating_system.vm.memories[destination_pid]
        except KeyError as exc:
            raise TransitMemoryTransferError("transfer endpoint has no virtual memory image") from exc

        self._private_range(source_memory, source_address, length, "read")
        self._private_range(destination_memory, destination_address, length, "write")
        try:
            data = source_memory.read(source_address, length)
            if len(data) != length:
                raise TransitMemoryTransferError("source memory returned a truncated interval")

            # Writes happen against a private COW candidate. The live destination
            # mapping changes only after the complete interval has been written.
            candidate = destination_memory.clone()
            written = candidate.write(destination_address, data)
            if written != length:
                raise TransitMemoryTransferError("destination memory accepted a truncated interval")
            destination_memory.commit_from(candidate)
            observed = destination_memory.read(destination_address, length)
        except VirtualMemoryError as exc:
            raise TransitMemoryTransferError(f"memory transfer could not commit: {exc}") from exc

        data_digest = hashlib.sha256(data).hexdigest()
        if observed != data:
            raise TransitMemoryTransferError("destination verification did not match the transferred source bytes")

        receipt_payload = {
            "operation": "memory.transfer",
            "source": event.source,
            "channel": event.channel,
            "sequence": event.sequence,
            "logical_time": event.logical_time,
            "source_pid": source_pid,
            "source_address": source_address,
            "destination_pid": destination_pid,
            "destination_address": destination_address,
            "length": length,
            "data_digest": data_digest,
        }
        receipt = kernel.journal.append(
            "memory.transfer.committed",
            receipt_payload,
        )
        return {
            "source_pid": source_pid,
            "source_address": source_address,
            "destination_pid": destination_pid,
            "destination_address": destination_address,
            "bytes_transferred": length,
            "data_digest": data_digest,
            "completion_receipt": receipt.digest,
        }
