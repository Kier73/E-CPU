"""Agreement-bound migration of reliable mailbox state between transport substrates."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from ._codec import message_from_record as _message_from_snapshot
from ._codec import message_to_record as _message_snapshot
from .model import Message
from .recovery_policy import RecoveryPolicyAgreement, RecoveryPolicyError
from .reliability import ReliableChannel
from .socket_transport import SocketTransport
from .transport import InMemoryTransport


class TransportMigrationError(ValueError):
    """A transport migration checkpoint, agreement, or target substrate is invalid."""


def _transport_kind(transport: Any) -> str:
    """Mathematics: classify substrate `T` into the finite migration domain `{socket,memory}` or refuse it."""

    if isinstance(transport, SocketTransport):
        return "socket"
    if isinstance(transport, InMemoryTransport):
        return "memory"
    raise TransportMigrationError(f"unsupported migration transport: {type(transport).__name__}")


@dataclass(frozen=True)
class TransportMigrationCheckpoint:
    """A versioned protocol-state product independent of source transport storage identities."""

    source_transport_kind: str
    target_transport_kind: str
    channel: dict[str, Any]
    queued_messages: tuple[dict[str, Any], ...]
    agreement: dict[str, Any]

    @classmethod
    def capture(
        cls,
        transport: Any,
        channel: ReliableChannel,
        agreement: RecoveryPolicyAgreement,
        *,
        source_transport_kind: str | None = None,
    ) -> "TransportMigrationCheckpoint":
        """Mathematics: capture `M=(T_kind,R,Q,A)` after binding `R.transport=T` and `A.source_transport=T_kind`."""

        if not isinstance(channel, ReliableChannel) or channel.transport is not transport:
            raise TransportMigrationError("migration channel is not bound to source transport")
        if not isinstance(agreement, RecoveryPolicyAgreement):
            raise TransportMigrationError("migration requires a RecoveryPolicyAgreement")
        detected_kind = _transport_kind(transport)
        source_kind = detected_kind if source_transport_kind is None else source_transport_kind
        if source_kind != detected_kind:
            raise TransportMigrationError("declared source transport kind does not match substrate")
        if agreement.source_transport != source_kind:
            raise TransportMigrationError("agreement source transport does not match source substrate")
        try:
            raw_snapshot = transport.snapshot()
        except (AttributeError, TypeError, ValueError) as exc:
            raise TransportMigrationError("source transport cannot expose a migration snapshot") from exc
        queues = raw_snapshot.get("queues") if isinstance(raw_snapshot, Mapping) else None
        if not isinstance(queues, Mapping):
            raise TransportMigrationError("source transport snapshot has no mailbox queues")
        queued: list[dict[str, Any]] = []
        for raw_address in sorted(queues, key=str):
            address = str(raw_address)
            if not address:
                raise TransportMigrationError("source transport contains an empty mailbox address")
            for message in transport.list(address):
                if not isinstance(message, Message) or message.recipient != address:
                    raise TransportMigrationError("source transport queue contains an invalid message")
                queued.append({"address": address, "message": _message_snapshot(message)})
        return cls(
            source_kind,
            agreement.target_transport,
            deepcopy(channel.snapshot()),
            tuple(queued),
            deepcopy(agreement.to_dict()),
        )

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any]) -> "TransportMigrationCheckpoint":
        """Mathematics: reconstruct `M` only when substrate labels, channel state, queue records, and agreement are complete."""

        if int(payload.get("version", 1)) != 1:
            raise TransportMigrationError("unsupported transport migration checkpoint version")
        source_kind = str(payload.get("source_transport_kind", ""))
        target_kind = str(payload.get("target_transport_kind", ""))
        channel = payload.get("channel")
        queued = payload.get("queued_messages")
        agreement = payload.get("agreement")
        if (
            source_kind not in {"socket", "memory"}
            or target_kind not in {"socket", "memory"}
            or not isinstance(channel, Mapping)
            or not isinstance(queued, (list, tuple))
            or not isinstance(agreement, Mapping)
        ):
            raise TransportMigrationError("transport migration checkpoint is incomplete")
        RecoveryPolicyAgreement.from_dict(agreement)
        normalized_queue: list[dict[str, Any]] = []
        for item in queued:
            if not isinstance(item, Mapping) or not isinstance(item.get("message"), Mapping):
                raise TransportMigrationError("transport migration queue record is invalid")
            address = str(item.get("address", ""))
            if not address:
                raise TransportMigrationError("transport migration queue address is empty")
            message = _message_from_snapshot(dict(item["message"]))
            if message.recipient != address:
                raise TransportMigrationError("transport migration message recipient disagrees with queue address")
            normalized_queue.append({"address": address, "message": _message_snapshot(message)})
        return cls(source_kind, target_kind, deepcopy(dict(channel)), tuple(normalized_queue), deepcopy(dict(agreement)))

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize `M` with deep copies so target migration cannot alias checkpoint state."""

        return {
            "version": 1,
            "source_transport_kind": self.source_transport_kind,
            "target_transport_kind": self.target_transport_kind,
            "channel": deepcopy(self.channel),
            "queued_messages": deepcopy(list(self.queued_messages)),
            "agreement": deepcopy(self.agreement),
        }


class CrossTransportRecoveryCoordinator:
    """Perform one agreement-bound reliable-channel handoff from socket or memory into memory."""

    @staticmethod
    def checkpoint(
        transport: Any,
        channel: ReliableChannel,
        agreement: RecoveryPolicyAgreement,
        *,
        source_transport_kind: str | None = None,
    ) -> TransportMigrationCheckpoint:
        """Mathematics: expose `capture(T,R,A)` as the migration checkpoint boundary."""

        return TransportMigrationCheckpoint.capture(
            transport,
            channel,
            agreement,
            source_transport_kind=source_transport_kind,
        )

    @staticmethod
    def migrate(
        checkpoint: TransportMigrationCheckpoint,
        agreement: RecoveryPolicyAgreement,
        target_transport: Any,
    ) -> ReliableChannel:
        """Mathematics: realize `R_target=restore(M.channel, import(M.Q,target))` only when `fingerprint(A_M)=fingerprint(A)`."""

        if not isinstance(checkpoint, TransportMigrationCheckpoint):
            raise TransportMigrationError("migration requires a TransportMigrationCheckpoint")
        if not isinstance(agreement, RecoveryPolicyAgreement):
            raise TransportMigrationError("migration requires a RecoveryPolicyAgreement")
        try:
            stored_agreement = RecoveryPolicyAgreement.from_dict(checkpoint.agreement)
        except RecoveryPolicyError as exc:
            raise TransportMigrationError("checkpoint contains an invalid recovery agreement") from exc
        if stored_agreement.fingerprint != agreement.fingerprint:
            raise TransportMigrationError("migration agreement does not match checkpoint")
        target_kind = _transport_kind(target_transport)
        if checkpoint.source_transport_kind != agreement.source_transport:
            raise TransportMigrationError("checkpoint source transport does not match agreement")
        if checkpoint.target_transport_kind != agreement.target_transport or target_kind != agreement.target_transport:
            raise TransportMigrationError("migration target transport does not match agreement")
        if target_kind != "memory" or not isinstance(target_transport, InMemoryTransport):
            raise TransportMigrationError("the current migration adapter supports only an in-memory target")
        try:
            shadow = InMemoryTransport.from_snapshot(deepcopy(target_transport.snapshot()))
            _import_messages(shadow, checkpoint.queued_messages)
            ReliableChannel.from_snapshot(deepcopy(checkpoint.channel), shadow)
        except (TransportMigrationError, TypeError, ValueError, KeyError, OverflowError, AttributeError) as exc:
            raise TransportMigrationError("migration preflight rejected the target state") from exc
        _import_messages(target_transport, checkpoint.queued_messages)
        try:
            return ReliableChannel.from_snapshot(deepcopy(checkpoint.channel), target_transport)
        except (TypeError, ValueError, KeyError, OverflowError) as exc:
            raise TransportMigrationError("target transport cannot restore reliable channel state") from exc


def _import_messages(target: InMemoryTransport, records: tuple[dict[str, Any], ...]) -> None:
    """Mathematics: preserve each source mailbox order `Q_a=[m_1,…,m_n]` while replacing only storage identity."""

    for item in records:
        address = str(item.get("address", ""))
        raw_message = item.get("message")
        if not address or not isinstance(raw_message, Mapping):
            raise TransportMigrationError("migration queue record is invalid")
        message = _message_from_snapshot(dict(raw_message))
        if message.recipient != address:
            raise TransportMigrationError("migration queue message recipient mismatch")
        target.send(address, message)
