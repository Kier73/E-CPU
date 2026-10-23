"""Append-only durable result and host-state journal for remote seed commits."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterator, Mapping

from ._codec import decode_canonical_value, encode_canonical_value
from .headless import HeadlessOS
from .seed_commit_transport import SeedCommitResult, SeedCommitTransportError


class SeedCommitJournalError(RuntimeError):
    """A durable seed result journal is corrupt, conflicting, or inconsistent with host state."""


def _record_bytes(record: Mapping[str, Any]) -> bytes:
    """Mathematics: serialize one unsigned chain record as `J_i=JSON_canonical(record_i)`."""

    return json.dumps(dict(record), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class DurableSeedCommitJournal:
    """Persist remote commit results and host snapshots in one fsynced hash-chain event."""

    _VERSION = 1
    _GENESIS = b"\x00" * 32

    def __init__(self, path: str | Path, executor_id: str) -> None:
        """Mathematics: initialize empty state and replay complete records `S_{i+1}=apply(S_i,R_i)` for executor `N`."""

        if not isinstance(executor_id, str) or not executor_id:
            raise SeedCommitJournalError("executor id must be a non-empty string")
        self.path = Path(path)
        self.executor_id = executor_id
        self._lock_path = self.path.with_name(f"{self.path.name}.lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._entries: dict[tuple[str, str, int], tuple[str, SeedCommitResult]] = {}
        self._latest_state: dict[str, Any] | None = None
        self._sequence = 0
        self._head = self._GENESIS
        self._file_signature: tuple[int, int] | None = None
        with self._locked():
            self._replay(repair_torn_suffix=True)

    def lookup(
        self,
        identity: tuple[str, str, int],
        request_fingerprint: str,
    ) -> SeedCommitResult | None:
        """Mathematics: project `L[I]` after journal refresh; require equal fingerprint or reject identity reuse."""

        self._validate_identity(identity)
        self._validate_fingerprint(request_fingerprint)
        with self._locked():
            self._refresh_if_changed()
            previous = self._entries.get(identity)
            if previous is None:
                return None
            fingerprint, result = previous
            if fingerprint != request_fingerprint:
                raise SeedCommitJournalError("durable seed commit identity conflicts with request fingerprint")
            return deepcopy(result)

    def _refresh_if_changed(self) -> None:
        """Mathematics: replay iff durable file signature `(size,mtime_ns)` differs from the cached prefix signature."""

        stat = self.path.stat()
        signature = (stat.st_size, stat.st_mtime_ns)
        if signature != self._file_signature:
            self._replay(repair_torn_suffix=True)

    def record(
        self,
        identity: tuple[str, str, int],
        request_fingerprint: str,
        result: SeedCommitResult,
        operating_system: HeadlessOS,
    ) -> bool:
        """Mathematics: append `R=(I,f,result,OS)` and fsync before applying durable ledger state; equal replay is idempotent."""

        self._validate_identity(identity)
        self._validate_fingerprint(request_fingerprint)
        if not isinstance(result, SeedCommitResult):
            raise SeedCommitJournalError("durable seed journal requires a SeedCommitResult")
        if not isinstance(operating_system, HeadlessOS):
            raise SeedCommitJournalError("durable seed journal requires a HeadlessOS")
        if (result.request_source, result.request_channel, result.request_sequence) != identity:
            raise SeedCommitJournalError("durable result identity does not match journal operation")
        if result.request_fingerprint != request_fingerprint:
            raise SeedCommitJournalError("durable result fingerprint does not match request")
        result_payload = result.to_dict()
        result_payload["replayed"] = False
        state_snapshot = deepcopy(operating_system.snapshot())
        stored_result = SeedCommitResult.from_dict(result_payload)
        self._validate_state_result(state_snapshot, stored_result)
        with self._locked():
            self._refresh_if_changed()
            previous = self._entries.get(identity)
            if previous is not None:
                previous_fingerprint, previous_result = previous
                if previous_fingerprint != request_fingerprint or previous_result.to_dict() != result_payload:
                    raise SeedCommitJournalError("durable seed commit operation conflicts with prior record")
                return False
            unsigned = {
                "version": self._VERSION,
                "sequence": self._sequence + 1,
                "previous": self._head.hex(),
                "executor_id": self.executor_id,
                "identity": [identity[0], identity[1], identity[2]],
                "request_fingerprint": request_fingerprint,
                "result": encode_canonical_value(result_payload),
                "operating_system": encode_canonical_value(state_snapshot),
            }
            receipt = hashlib.sha256(self._head + _record_bytes(unsigned)).hexdigest()
            record = dict(unsigned)
            record["receipt"] = receipt
            line = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
            with self.path.open("ab") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
            self._entries[identity] = (request_fingerprint, stored_result)
            self._latest_state = state_snapshot
            self._sequence = unsigned["sequence"]
            self._head = bytes.fromhex(receipt)
            stat = self.path.stat()
            self._file_signature = (stat.st_size, stat.st_mtime_ns)
            return True

    def latest_state_snapshot(self) -> dict[str, Any] | None:
        """Mathematics: project the state factor from the maximal durable prefix `R_1…R_n` without aliasing it."""

        with self._locked():
            self._refresh_if_changed()
            return None if self._latest_state is None else deepcopy(self._latest_state)

    def restore_host(self) -> HeadlessOS | None:
        """Mathematics: reconstruct host `OS_n=decode(S_n)` from the latest fsynced result record, or return `∅`."""

        state = self.latest_state_snapshot()
        return None if state is None else HeadlessOS.from_snapshot(state)

    def snapshot(self) -> dict[str, object]:
        """Mathematics: expose journal identity `(path,executor,n,H)` and semantic ledger size without host aliasing."""

        with self._locked():
            self._refresh_if_changed()
            return {
                "version": self._VERSION,
                "path": str(self.path),
                "executor_id": self.executor_id,
                "sequence": self._sequence,
                "head_hex": self._head.hex(),
                "operations": len(self._entries),
            }

    def verify(self) -> bool:
        """Mathematics: verify the complete chain and state/result relation by independent replay `replay(log)=current`."""

        try:
            candidate = type(self).__new__(type(self))
            candidate.path = self.path
            candidate.executor_id = self.executor_id
            candidate._lock_path = self._lock_path
            candidate._entries = {}
            candidate._latest_state = None
            candidate._sequence = 0
            candidate._head = self._GENESIS
            candidate._file_signature = None
            with candidate._locked():
                candidate._replay(repair_torn_suffix=False)
        except (OSError, SeedCommitJournalError, ValueError):
            return False
        return (
            candidate._entries == self._entries
            and candidate._latest_state == self._latest_state
            and candidate._sequence == self._sequence
            and candidate._head == self._head
        )

    def _validate_identity(self, identity: tuple[str, str, int]) -> None:
        """Mathematics: restrict operation key to `I=(source,channel,sequence)∈String²×N⁺`."""

        if (
            not isinstance(identity, tuple)
            or len(identity) != 3
            or any(not isinstance(item, str) or not item for item in identity[:2])
            or not isinstance(identity[2], int)
            or isinstance(identity[2], bool)
            or identity[2] <= 0
        ):
            raise SeedCommitJournalError("durable seed commit identity is invalid")

    def _validate_fingerprint(self, fingerprint: str) -> None:
        """Mathematics: restrict request identity to lowercase SHA-256 hex `D={0,…,f}^{64}`."""

        if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
            raise SeedCommitJournalError("durable seed commit fingerprint is invalid")

    def _validate_state_result(self, state: Mapping[str, Any], result: SeedCommitResult) -> None:
        """Mathematics: require `restore(OS)` succeeds and, for accepted `r`, `registry(OS)[system]=r.envelope`."""

        try:
            restored = HeadlessOS.from_snapshot(deepcopy(dict(state)))
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise SeedCommitJournalError("durable host snapshot cannot be restored") from exc
        if result.accepted:
            current = restored.seed_admission.current(result.system_id)
            if current is None or current.snapshot() != result.envelope.snapshot():
                raise SeedCommitJournalError("durable accepted result does not match restored host registry")

    def _replay(self, *, repair_torn_suffix: bool) -> None:
        """Mathematics: fold records by `H_i=SHA256(H_{i-1}||J_i)` and optionally truncate only an incomplete final line."""

        raw_data = self.path.read_bytes()
        complete_length = len(raw_data)
        if raw_data and not raw_data.endswith(b"\n"):
            complete_length = raw_data.rfind(b"\n") + 1
            if not repair_torn_suffix:
                raise SeedCommitJournalError("durable journal append is incomplete after write")
            with self.path.open("r+b") as stream:
                stream.truncate(complete_length)
                stream.flush()
                os.fsync(stream.fileno())
            raw_data = raw_data[:complete_length]
        entries: dict[tuple[str, str, int], tuple[str, SeedCommitResult]] = {}
        sequence = 0
        head = self._GENESIS
        latest_state: dict[str, Any] | None = None
        for line in raw_data.splitlines():
            if not line:
                continue
            try:
                record = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SeedCommitJournalError("durable seed journal contains invalid complete JSON") from exc
            if not isinstance(record, Mapping):
                raise SeedCommitJournalError("unsupported durable seed journal record")
            raw_version = record.get("version")
            if not isinstance(raw_version, int) or isinstance(raw_version, bool) or raw_version != self._VERSION:
                raise SeedCommitJournalError("unsupported durable seed journal record")
            raw_sequence = record.get("sequence")
            if not isinstance(raw_sequence, int) or isinstance(raw_sequence, bool) or raw_sequence <= 0:
                raise SeedCommitJournalError("durable seed journal sequence is malformed")
            record_sequence = raw_sequence
            try:
                previous_text = record.get("previous")
                if not isinstance(previous_text, str) or len(previous_text) != 64:
                    raise ValueError("predecessor must be 64 lowercase hexadecimal characters")
                if any(character not in "0123456789abcdef" for character in previous_text):
                    raise ValueError("predecessor must be lowercase hexadecimal")
                previous = bytes.fromhex(previous_text)
            except ValueError as exc:
                raise SeedCommitJournalError("durable seed journal predecessor is malformed") from exc
            if record_sequence != sequence + 1 or previous != head or record.get("executor_id") != self.executor_id:
                raise SeedCommitJournalError("durable seed journal chain or executor identity mismatch")
            unsigned = {
                "version": self._VERSION,
                "sequence": record_sequence,
                "previous": previous.hex(),
                "executor_id": self.executor_id,
                "identity": record.get("identity"),
                "request_fingerprint": record.get("request_fingerprint"),
                "result": record.get("result"),
                "operating_system": record.get("operating_system"),
            }
            expected = hashlib.sha256(previous + _record_bytes(unsigned)).hexdigest()
            if record.get("receipt") != expected:
                raise SeedCommitJournalError("durable seed journal receipt mismatch")
            raw_identity = record.get("identity")
            if (
                not isinstance(raw_identity, list)
                or len(raw_identity) != 3
                or not isinstance(raw_identity[0], str)
                or not isinstance(raw_identity[1], str)
                or not isinstance(raw_identity[2], int)
                or isinstance(raw_identity[2], bool)
            ):
                raise SeedCommitJournalError("durable seed journal operation identity is malformed")
            identity = (raw_identity[0], raw_identity[1], raw_identity[2])
            self._validate_identity(identity)
            fingerprint = record.get("request_fingerprint")
            self._validate_fingerprint(fingerprint)
            try:
                result_payload = decode_canonical_value(record.get("result"))
                state_snapshot = decode_canonical_value(record.get("operating_system"))
            except (KeyError, TypeError, ValueError, IndexError) as exc:
                raise SeedCommitJournalError("durable seed journal canonical payload is malformed") from exc
            if not isinstance(result_payload, Mapping) or not isinstance(state_snapshot, Mapping):
                raise SeedCommitJournalError("durable seed journal result or host state is malformed")
            if encode_canonical_value(dict(result_payload)) != record.get("result"):
                raise SeedCommitJournalError("durable seed journal result is not canonically normalized")
            if encode_canonical_value(dict(state_snapshot)) != record.get("operating_system"):
                raise SeedCommitJournalError("durable seed journal host state is not canonically normalized")
            try:
                result = SeedCommitResult.from_dict(result_payload)
            except (TypeError, ValueError) as exc:
                raise SeedCommitJournalError("durable seed journal result fields are invalid") from exc
            result_data = result.to_dict()
            if result_data != dict(result_payload):
                raise SeedCommitJournalError("durable seed journal result is not normalized")
            if (result.request_source, result.request_channel, result.request_sequence) != identity:
                raise SeedCommitJournalError("durable seed journal result identity mismatch")
            if result.request_fingerprint != fingerprint:
                raise SeedCommitJournalError("durable seed journal result fingerprint mismatch")
            if identity in entries:
                raise SeedCommitJournalError("durable seed journal repeats an operation identity")
            copied_state = deepcopy(dict(state_snapshot))
            self._validate_state_result(copied_state, result)
            entries[identity] = (fingerprint, result)
            latest_state = copied_state
            sequence = record_sequence
            head = bytes.fromhex(expected)
        self._entries = entries
        self._latest_state = latest_state
        self._sequence = sequence
        self._head = head
        stat = self.path.stat()
        self._file_signature = (stat.st_size, stat.st_mtime_ns)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Mathematics: serialize journal refresh and append under one cross-process exclusive lock `L`."""

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
                yield
            finally:
                if locking_module is not None and hasattr(locking_module, "locking"):
                    lock.seek(0)
                    locking_module.locking(lock.fileno(), locking_module.LK_UNLCK, 1)
                elif locking_module is not None:
                    locking_module.flock(lock.fileno(), locking_module.LOCK_UN)
