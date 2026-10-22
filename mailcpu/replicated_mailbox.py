r"""Durable multi-node mailbox state above the external socket transport.

This module gives active communication a durable memory on each participating
node.  Each mailbox operation is written to a local hash chain, applied to the
local FIFO state, sent through a reliable channel, and applied by the replica
before its acknowledgement is emitted.

Mathematics:
\[
 S_0=(Q=\varnothing,O=\varnothing,H=0),\qquad
 S_{i+1}=apply(S_i,e_i),\qquad
 H_{i+1}=SHA256(H_i\Vert JSON_{canonical}(e_i)).
\]
For operation $o$, the quorum receipt is committed exactly when
\[
 1+|A(o)|\ge q,
\]
where the local durable commit contributes one and $A(o)$ is the set of
replicas whose durable application has been acknowledged.
"""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from ._codec import decode_canonical_value, encode_canonical_value
from .evidence import EvidenceTier, with_evidence_tier
from .model import Message
from .reliability import ReliableChannel


class ReplicatedMailboxError(RuntimeError):
    """A durable operation, recovery record, quorum, or replica identity violates the mailbox contract."""


def _message_to_record(message: Message) -> dict[str, Any]:
    """Mathematics: encode `Message` through the injective canonical algebra so `decode(record(m))=m`."""

    return {
        "sender": message.sender,
        "recipient": message.recipient,
        "op": message.op,
        "addr": message.addr,
        "value": message.value,
        "seq": message.seq,
        "body": encode_canonical_value(message.body),
        "message_id": message.message_id,
    }


def _message_from_record(record: Mapping[str, Any]) -> Message:
    """Mathematics: reconstruct a typed `Message` and preserve tuple-valued body identity."""

    body = decode_canonical_value(record.get("body", {"tuple": []}))
    if not isinstance(body, tuple):
        raise ReplicatedMailboxError("replicated message body must be a tuple")
    message = Message(
        sender=str(record.get("sender", "")),
        recipient=str(record.get("recipient", "")),
        op=str(record.get("op", "")),
        addr=str(record.get("addr", "")),
        value=None if record.get("value") is None else int(record["value"]),
        seq=int(record.get("seq", 0)),
        body=body,
        message_id=str(record.get("message_id", "")),
    )
    if not message.sender or not message.recipient or not message.message_id:
        raise ReplicatedMailboxError("replicated message identity is incomplete")
    return message


def _operation_fingerprint(event: str, payload: Mapping[str, Any]) -> str:
    """Mathematics: derive single-valued operation identity `I(o)=SHA256(JSON_canonical(event,payload))`."""

    encoded = {"event": str(event), "payload": encode_canonical_value(dict(payload))}
    canonical = json.dumps(encoded, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _record_bytes(record: Mapping[str, Any]) -> bytes:
    """Mathematics: serialize one unsigned journal record as `JSON_canonical(record)` for hash chaining."""

    return json.dumps(dict(record), sort_keys=True, separators=(",", ":")).encode("utf-8")


class ReplicatedMailboxStore:
    """Crash-recoverable FIFO mailbox store with operation-idempotent journal application."""

    _VERSION = 1
    _GENESIS = b"\x00" * 32

    def __init__(self, path: str | Path, node_id: str) -> None:
        """Mathematics: initialize `S_0` and replay every complete journal prefix at `path` for node `node_id`."""

        if not node_id:
            raise ReplicatedMailboxError("node_id must be non-empty")
        self.path = Path(path)
        self.node_id = node_id
        self._lock_path = self.path.with_name(f"{self.path.name}.lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._queues: dict[str, deque[Message]] = {}
        self._locations: dict[str, str] = {}
        self._operations: dict[str, str] = {}
        self._next_message = 1
        self._next_operation = 1
        self._sequence = 0
        self._head = self._GENESIS
        self._replay()

    def new_operation_id(self) -> str:
        """Mathematics: allocate fresh operation identity `o_n=(node_id,n)` and advance `n:=n+1`."""

        operation_id = f"{self.node_id}:op:{self._next_operation}"
        self._next_operation += 1
        return operation_id

    def send(self, addr: str, message: Message, operation_id: str | None = None) -> Message:
        """Mathematics: append `ENQUEUE(o,m)` durably, then apply `Q_addr:=Q_addr||[m]` and return `m`."""

        if not addr or not isinstance(message, Message) or message.sender != self.node_id:
            raise ReplicatedMailboxError("local enqueue identity is invalid")
        operation = operation_id or self.new_operation_id()
        stored = replace(message, recipient=addr, message_id=f"{self.node_id}:msg:{self._next_message}")
        self._next_message += 1
        self._commit(
            operation,
            "enqueue",
            {"addr": addr, "message": _message_to_record(stored)},
        )
        return stored

    def apply_replica(self, operation_id: str, event: str, payload: Mapping[str, Any]) -> bool:
        """Mathematics: apply remote event `e(o)` exactly once; equal replays return `False`, conflicts refuse."""

        return self._commit(str(operation_id), str(event), dict(payload))

    def poll(self, addr: str, operation_id: str | None = None) -> Message | None:
        """Mathematics: durably commit `DEQUEUE(o,head(Q_addr))` before removing and returning the FIFO head."""

        queue = self._queues.get(addr)
        if not queue:
            return None
        message = queue[0]
        operation = operation_id or self.new_operation_id()
        self._commit(operation, "dequeue", {"addr": addr, "message_id": message.message_id})
        return message

    def consume(self, message: Message, operation_id: str | None = None) -> bool:
        """Mathematics: durably commit `CONSUME(o,m)` and remove exactly `m∈Q`, otherwise return `False` without mutation."""

        addr = self._locations.get(message.message_id)
        if addr is None:
            return False
        operation = operation_id or self.new_operation_id()
        self._commit(operation, "consume", {"addr": addr, "message_id": message.message_id})
        return True

    def list(self, addr: str) -> tuple[Message, ...]:
        """Mathematics: project immutable FIFO state `Q_addr` without changing the durable state."""

        return tuple(self._queues.get(addr, ()))

    def pending(self, addr: str | None = None) -> int:
        """Mathematics: calculate `|Q|=Σ_a|Q_a|`, or the restricted cardinality `|Q_addr|`."""

        if addr is not None:
            return len(self._queues.get(addr, ()))
        return sum(len(queue) for queue in self._queues.values())

    def location(self, message_id: str) -> str | None:
        """Mathematics: project the partial inverse `L(m)=addr` for a live message, or `∅` when `m∉dom(L)`."""

        return self._locations.get(message_id)

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize durable continuation metadata `(path,node,n,H,next_message,next_operation)`."""

        return {
            "version": self._VERSION,
            "path": str(self.path),
            "node_id": self.node_id,
            "sequence": self._sequence,
            "head_hex": self._head.hex(),
            "next_message": self._next_message,
            "next_operation": self._next_operation,
            "pending": self.pending(),
        }

    def verify(self) -> bool:
        """Mathematics: require a fresh replay to equal `(Q,L,O,n,H)` without changing this store."""

        try:
            candidate = type(self)(self.path, self.node_id)
        except ReplicatedMailboxError:
            return False
        return (
            candidate._queues == self._queues
            and candidate._locations == self._locations
            and candidate._operations == self._operations
            and candidate._sequence == self._sequence
            and candidate._head == self._head
            and candidate._next_message == self._next_message
            and candidate._next_operation == self._next_operation
        )

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, Any], path: str | Path | None = None) -> "ReplicatedMailboxStore":
        """Mathematics: restore the journal-backed store at `path` and require snapshot identity metadata to agree."""

        selected_path = path if path is not None else str(payload["path"])
        store = cls(selected_path, str(payload["node_id"]))
        if int(payload.get("sequence", -1)) != store._sequence or str(payload.get("head_hex", "")) != store._head.hex():
            raise ReplicatedMailboxError("replicated store snapshot does not match journal")
        return store

    def _commit(self, operation_id: str, event: str, payload: Mapping[str, Any]) -> bool:
        """Mathematics: append `R_{i+1}` before applying `e`, with idempotent equal replay and conflict refusal."""

        if not operation_id or not event:
            raise ReplicatedMailboxError("operation identity and event are required")
        payload_map = dict(payload)
        fingerprint = _operation_fingerprint(event, payload_map)
        existing = self._operations.get(operation_id)
        if existing is not None:
            if existing != fingerprint:
                raise ReplicatedMailboxError(f"operation identity conflict: {operation_id}")
            return False
        self._validate_event(event, payload_map)
        sequence = self._sequence + 1
        unsigned = {
            "version": self._VERSION,
            "sequence": sequence,
            "previous": self._head.hex(),
            "operation_id": operation_id,
            "event": event,
            "payload": encode_canonical_value(payload_map),
        }
        receipt = hashlib.sha256(self._head + _record_bytes(unsigned)).hexdigest()
        record = dict(unsigned)
        record["receipt"] = receipt
        line = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        with self._locked_append() as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
        self._sequence = sequence
        self._head = bytes.fromhex(receipt)
        self._apply_event(event, payload_map)
        self._operations[operation_id] = fingerprint
        return True

    def _validate_event(self, event: str, payload: Mapping[str, Any]) -> None:
        """Mathematics: require event precondition `Pre(e,S)` before the durable append mutates the journal."""

        if event == "enqueue":
            addr = str(payload.get("addr", ""))
            message_payload = payload.get("message")
            if not addr or not isinstance(message_payload, Mapping):
                raise ReplicatedMailboxError("enqueue event is malformed")
            message = _message_from_record(message_payload)
            if message.recipient != addr or message.message_id in self._locations:
                raise ReplicatedMailboxError("enqueue message identity or route conflicts")
            return
        addr = str(payload.get("addr", ""))
        message_id = str(payload.get("message_id", ""))
        if not addr or not message_id or self._locations.get(message_id) != addr:
            raise ReplicatedMailboxError("mailbox removal references an unknown message")
        queue = self._queues[addr]
        if event == "dequeue":
            if not queue or queue[0].message_id != message_id:
                raise ReplicatedMailboxError("dequeue is not the FIFO head")
            return
        if event == "consume":
            return
        raise ReplicatedMailboxError(f"unknown replicated mailbox event: {event}")

    def _apply_event(self, event: str, payload: Mapping[str, Any]) -> None:
        """Mathematics: apply a validated event to `(Q,L)` without writing a second journal record."""

        addr = str(payload["addr"])
        if event == "enqueue":
            message = _message_from_record(dict(payload["message"]))
            self._queues.setdefault(addr, deque()).append(message)
            self._locations[message.message_id] = addr
            prefix = f"{self.node_id}:msg:"
            if message.message_id.startswith(prefix):
                self._next_message = max(self._next_message, int(message.message_id[len(prefix) :]) + 1)
            return
        message_id = str(payload["message_id"])
        queue = self._queues[addr]
        for index, message in enumerate(queue):
            if message.message_id == message_id:
                del queue[index]
                break
        del self._locations[message_id]

    def _replay(self) -> None:
        """Mathematics: fold complete records `S_{i+1}=apply(S_i,R_i)` and repair only an incomplete final suffix."""

        raw_data = self.path.read_bytes()
        complete_length = len(raw_data)
        if raw_data and not raw_data.endswith(b"\n"):
            complete_length = raw_data.rfind(b"\n") + 1
            with self.path.open("r+b") as stream:
                stream.truncate(complete_length)
                stream.flush()
                os.fsync(stream.fileno())
            raw_data = raw_data[:complete_length]
        for line in raw_data.splitlines():
            if not line:
                continue
            try:
                record = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ReplicatedMailboxError("replicated journal contains invalid complete JSON") from error
            self._verify_record(record)
            payload = decode_canonical_value(record["payload"])
            if not isinstance(payload, Mapping):
                raise ReplicatedMailboxError("replicated journal payload must be a mapping")
            self._commit_replayed(str(record["operation_id"]), str(record["event"]), dict(payload))

    def _commit_replayed(self, operation_id: str, event: str, payload: Mapping[str, Any]) -> None:
        """Mathematics: apply a verified journal event at its recorded sequence without appending it again."""

        fingerprint = _operation_fingerprint(event, payload)
        existing = self._operations.get(operation_id)
        if existing is not None:
            if existing != fingerprint:
                raise ReplicatedMailboxError("replayed operation identity conflict")
            return
        self._validate_event(event, payload)
        self._apply_event(event, payload)
        self._operations[operation_id] = fingerprint
        prefix = f"{self.node_id}:op:"
        if operation_id.startswith(prefix):
            self._next_operation = max(self._next_operation, int(operation_id[len(prefix) :]) + 1)

    def _verify_record(self, record: Any) -> None:
        """Mathematics: require version, sequence, predecessor, and `receipt=SHA256(H_prev||R)` for one complete record."""

        if not isinstance(record, dict) or int(record.get("version", -1)) != self._VERSION:
            raise ReplicatedMailboxError("unsupported replicated journal record")
        sequence = int(record.get("sequence", -1))
        previous = bytes.fromhex(str(record.get("previous", "")))
        if sequence != self._sequence + 1 or previous != self._head:
            raise ReplicatedMailboxError("replicated journal sequence or predecessor mismatch")
        unsigned = {
            "version": self._VERSION,
            "sequence": sequence,
            "previous": previous.hex(),
            "operation_id": str(record.get("operation_id", "")),
            "event": str(record.get("event", "")),
            "payload": record.get("payload"),
        }
        expected = hashlib.sha256(previous + _record_bytes(unsigned)).hexdigest()
        if str(record.get("receipt", "")) != expected:
            raise ReplicatedMailboxError("replicated journal receipt mismatch")
        self._sequence = sequence
        self._head = bytes.fromhex(expected)

    @contextmanager
    def _locked_append(self) -> Any:
        """Mathematics: serialize local append critical section `A=(lock,write,flush,fsync)` for one complete record."""

        self._lock_path.touch(exist_ok=True)
        with self._lock_path.open("a+b") as lock:
            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            locking_module: Any = None
            try:
                import msvcrt as locking_module
            except ImportError:
                try:
                    import fcntl as locking_module
                except ImportError:
                    locking_module = None
            if locking_module is not None and hasattr(locking_module, "locking"):
                locking_module.locking(lock.fileno(), locking_module.LK_LOCK, 1)
            elif locking_module is not None:
                locking_module.flock(lock.fileno(), locking_module.LOCK_EX)
            try:
                with self.path.open("ab") as stream:
                    yield stream
            finally:
                if locking_module is not None and hasattr(locking_module, "locking"):
                    lock.seek(0)
                    locking_module.locking(lock.fileno(), locking_module.LK_UNLCK, 1)
                elif locking_module is not None:
                    locking_module.flock(lock.fileno(), locking_module.LOCK_UN)


@dataclass(frozen=True)
class ReplicationReceipt:
    """Quorum state for one locally durable operation."""

    operation_id: str
    acknowledged_peers: tuple[str, ...]
    quorum: int

    @property
    def committed(self) -> bool:
        """Mathematics: evaluate global commit predicate `1+|A(o)|≥q`."""

        return 1 + len(self.acknowledged_peers) >= self.quorum

    def to_dict(self) -> dict[str, object]:
        """Mathematics: project quorum receipt `r=(o,A,q,committed)` with controlled-path provenance."""

        return with_evidence_tier(
            {
                "operation_id": self.operation_id,
                "acknowledged_peers": list(self.acknowledged_peers),
                "quorum": self.quorum,
                "committed": self.committed,
            },
            EvidenceTier.E1,
        )


@dataclass
class _PendingOperation:
    """Coordinator state linking one durable event to peer sequence identities."""

    operation_id: str
    event: str
    payload: dict[str, Any]
    sequences: dict[str, int]
    acknowledged: set[str]


class ReplicatedMailboxNode:
    """A mailbox Transport coordinator that replicates durable operations over reliable peer channels."""

    def __init__(
        self,
        store: ReplicatedMailboxStore,
        outbound: Mapping[str, ReliableChannel] | None = None,
        inbound: Mapping[str, ReliableChannel] | None = None,
        quorum: int | None = None,
    ) -> None:
        """Mathematics: bind node `N=(store,outbound,inbound,q)` with `1≤q≤1+|outbound|`."""

        self.store = store
        self.outbound = dict(outbound or {})
        self.inbound = dict(inbound or {})
        total_nodes = 1 + len(self.outbound)
        selected_quorum = total_nodes // 2 + 1 if quorum is None else int(quorum)
        if selected_quorum < 1 or selected_quorum > total_nodes:
            raise ReplicatedMailboxError("replication quorum is outside node set")
        if set(self.outbound) & set(self.inbound):
            raise ReplicatedMailboxError("one peer cannot be both inbound and outbound under one identity")
        self.quorum = selected_quorum
        self._pending: dict[str, _PendingOperation] = {}

    def send(self, addr: str, message: Message) -> Message:
        """Mathematics: locally commit `ENQUEUE(o,m)`, broadcast `e(o)`, and return `m` while quorum progresses."""

        self.service()
        operation_id = self.store.new_operation_id()
        stored = self.store.send(addr, message, operation_id)
        self._publish(operation_id, "enqueue", {"addr": addr, "message": _message_to_record(stored)})
        return stored

    def poll(self, addr: str) -> Message | None:
        """Mathematics: locally commit FIFO `DEQUEUE(o,head(Q_addr))`, then replicate that exact removal."""

        self.service()
        if not self.store.list(addr):
            return None
        operation_id = self.store.new_operation_id()
        message = self.store.poll(addr, operation_id)
        if message is None:
            return None
        self._publish(operation_id, "dequeue", {"addr": addr, "message_id": message.message_id})
        return message

    def consume(self, message: Message) -> bool:
        """Mathematics: commit and broadcast exact removal `CONSUME(o,m)` only when `m∈Q`."""

        self.service()
        addr = self.store.location(message.message_id)
        if addr is None:
            return False
        operation_id = self.store.new_operation_id()
        if not self.store.consume(message, operation_id):
            return False
        self._publish(operation_id, "consume", {"addr": addr, "message_id": message.message_id})
        return True

    def list(self, addr: str) -> tuple[Message, ...]:
        """Mathematics: service peer traffic and project local FIFO `Q_addr` without mutation."""

        self.service()
        return self.store.list(addr)

    def pending(self, addr: str | None = None) -> int:
        """Mathematics: service peer traffic and calculate local mailbox cardinality `|Q_addr|` or `|Q|`."""

        self.service()
        return self.store.pending(addr)

    def service(self) -> int:
        """Mathematics: fold inbound reliable frames into durable state, emit post-commit ACKs, and collect outbound ACKs."""

        applied = 0
        for peer, channel in sorted(self.inbound.items()):
            while channel.peek() is not None:
                def commit(sequence: int, payload: Any, source: str = peer) -> None:
                    """Mathematics: durable replica transition `apply(source,sequence,payload)` precedes channel ACK."""

                    del sequence
                    self._apply_replication(source, payload)

                result = channel.receive(commit=commit)
                if result is not None:
                    applied += 1
        for peer, channel in sorted(self.outbound.items()):
            for sequence in channel.process_ack():
                for state in self._pending.values():
                    if state.sequences.get(peer) == sequence:
                        state.acknowledged.add(peer)
                        break
        return applied

    def tick(self) -> tuple[int, ...]:
        """Mathematics: advance each outbound reliability clock and return failed sequence numbers without changing durable operations."""

        failed: list[int] = []
        for channel in self.outbound.values():
            failed.extend(channel.tick())
        return tuple(failed)

    def receipt(self, operation_id: str) -> ReplicationReceipt:
        """Mathematics: evaluate current quorum receipt `r(o)` after servicing all available acknowledgements."""

        self.service()
        state = self._pending.get(operation_id)
        if state is None:
            raise ReplicatedMailboxError(f"unknown replicated operation: {operation_id}")
        return ReplicationReceipt(operation_id, tuple(sorted(state.acknowledged)), self.quorum)

    def operation_ids(self) -> tuple[str, ...]:
        """Mathematics: expose sorted coordinator domain `dom(P)` without mutating pending replication state."""

        return tuple(sorted(self._pending))

    def snapshot(self) -> dict[str, object]:
        """Mathematics: serialize store identity, quorum, and sequence-to-operation recovery map `P`."""

        return {
            "version": 1,
            "node_id": self.store.node_id,
            "quorum": self.quorum,
            "store": self.store.snapshot(),
            "pending": {
                operation_id: {
                    "event": state.event,
                    "payload": encode_canonical_value(state.payload),
                    "sequences": dict(sorted(state.sequences.items())),
                    "acknowledged": sorted(state.acknowledged),
                }
                for operation_id, state in sorted(self._pending.items())
            },
        }

    @classmethod
    def from_snapshot(
        cls,
        payload: Mapping[str, Any],
        store: ReplicatedMailboxStore,
        outbound: Mapping[str, ReliableChannel] | None = None,
        inbound: Mapping[str, ReliableChannel] | None = None,
    ) -> "ReplicatedMailboxNode":
        """Mathematics: reconstruct coordinator `P` over restored store and channel snapshots."""

        if int(payload.get("version", -1)) != 1 or str(payload.get("node_id")) != store.node_id:
            raise ReplicatedMailboxError("replicated coordinator snapshot identity mismatch")
        node = cls(store, outbound, inbound, int(payload["quorum"]))
        for operation_id, raw in dict(payload.get("pending", {})).items():
            item = dict(raw)
            decoded = decode_canonical_value(item.get("payload", {"dict": []}))
            if not isinstance(decoded, Mapping):
                raise ReplicatedMailboxError("replicated pending payload must be a mapping")
            node._pending[str(operation_id)] = _PendingOperation(
                str(operation_id),
                str(item["event"]),
                dict(decoded),
                {str(peer): int(sequence) for peer, sequence in dict(item.get("sequences", {})).items()},
                {str(peer) for peer in item.get("acknowledged", ())},
            )
        return node

    def _publish(self, operation_id: str, event: str, payload: Mapping[str, Any]) -> None:
        """Mathematics: emit one reliable replication frame per peer and register sequence map `s_peer↦operation` before ACKs arrive."""

        state = _PendingOperation(operation_id, event, dict(payload), {}, set())
        self._pending[operation_id] = state
        frame_payload = {"operation_id": operation_id, "event": event, "payload": dict(payload)}
        for peer, channel in sorted(self.outbound.items()):
            state.sequences[peer] = channel.send(frame_payload)

    def _apply_replication(self, peer: str, payload: Any) -> None:
        """Mathematics: accept only `peer`-bound `(operation_id,event,payload)` and persist it before the caller ACKs."""

        if not isinstance(payload, Mapping):
            raise ReplicatedMailboxError("replication frame payload must be a mapping")
        operation_id = str(payload.get("operation_id", ""))
        event = str(payload.get("event", ""))
        event_payload = payload.get("payload")
        if not operation_id or not event or not isinstance(event_payload, Mapping):
            raise ReplicatedMailboxError("replication frame is malformed")
        if not operation_id.startswith(f"{peer}:op:"):
            raise ReplicatedMailboxError("replication operation identity does not match peer")
        self.store.apply_replica(operation_id, event, dict(event_payload))

