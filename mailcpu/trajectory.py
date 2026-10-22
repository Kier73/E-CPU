"""Append-only indexed trajectory stream with receipt-chain verification."""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


TRAJECTORY_MAGIC = b"MTRJ"
TRAJECTORY_VERSION = 1
TRAJECTORY_HEADER = struct.Struct("<4sII")
TRAJECTORY_RECORD = struct.Struct("<QQI32s")
TRAJECTORY_INDEX_ENTRY = struct.Struct("<QQQ")


class TrajectoryError(Exception):
    """Trajectory file, index, or receipt-chain failure."""


@dataclass(frozen=True)
class TrajectoryFrame:
    """One logical event and its chain receipt."""

    sequence: int
    logical_time: int
    payload: dict[str, Any]
    receipt: bytes


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    """Mathematics: encode event payload as canonical bytes `c = JSON(sort_keys, compact)(payload)`."""

    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _receipt(previous: bytes, sequence: int, logical_time: int, payload: bytes) -> bytes:
    """Mathematics: compute the chain identity `H_n = SHA256(H_{n-1} || n || t_n || c_n)`."""

    material = previous + struct.pack("<QQI", sequence, logical_time, len(payload)) + payload
    return hashlib.sha256(material).digest()


class TrajectoryWriter:
    """Writer for a binary event stream and sparse logical-time index."""

    def __init__(self, data_path: str | Path, index_path: str | Path, stride: int = 64) -> None:
        """Mathematics: initialize empty stream state `H_0 = 0^256`, sequence `n = 0`, and index stride `K`."""

        if stride <= 0:
            raise ValueError("stride must be positive")
        self.data_path = Path(data_path)
        self.index_path = Path(index_path)
        self.stride = stride
        self._data = self.data_path.open("wb")
        self._index = self.index_path.open("wb")
        self._data.write(TRAJECTORY_HEADER.pack(TRAJECTORY_MAGIC, TRAJECTORY_VERSION, stride))
        self._index.write(TRAJECTORY_HEADER.pack(TRAJECTORY_MAGIC, TRAJECTORY_VERSION, stride))
        self._sequence = 0
        self._last_time = 0
        self._previous_receipt = b"\x00" * 32
        self._closed = False

    @classmethod
    def resume(cls, data_path: str | Path, index_path: str | Path) -> "TrajectoryWriter":
        """Mathematics: recover `(n_last,t_last,H_last,K)` after verification and append the next frame with `H_next=SHA256(H_last||c_next)` without truncation."""

        data = Path(data_path)
        index = Path(index_path)
        last_frame: TrajectoryFrame | None = None
        with TrajectoryReader(data, index) as reader:
            count = reader.verify()

            def capture(frame: TrajectoryFrame) -> None:
                """Mathematics: retain only the terminal frame `f_{n_last}` while the reader proves the complete prefix."""

                nonlocal last_frame
                last_frame = frame

            reader.replay(capture)
            stride = reader.stride
        writer = cls.__new__(cls)
        writer.data_path = data
        writer.index_path = index
        writer.stride = stride
        writer._data = data.open("ab")
        try:
            writer._index = index.open("ab")
        except Exception:
            writer._data.close()
            raise
        writer._sequence = count
        writer._last_time = 0 if last_frame is None else last_frame.logical_time
        writer._previous_receipt = b"\x00" * 32 if last_frame is None else last_frame.receipt
        writer._closed = False
        return writer

    def append(self, logical_time: int, payload: dict[str, Any]) -> TrajectoryFrame:
        """Mathematics: append frame `n` with clamped time `t_n = max(t_{n-1}, raw_t)` and receipt `H_n`."""

        if self._closed:
            raise TrajectoryError("trajectory writer is closed")
        if logical_time < 0:
            raise ValueError("logical_time must be non-negative")
        canonical = _canonical_payload(payload)
        clamped_time = max(self._last_time, logical_time)
        receipt = _receipt(self._previous_receipt, self._sequence, clamped_time, canonical)
        offset = self._data.tell()
        if self._sequence % self.stride == 0:
            self._index.write(TRAJECTORY_INDEX_ENTRY.pack(self._sequence, clamped_time, offset))
        self._data.write(
            TRAJECTORY_RECORD.pack(self._sequence, clamped_time, len(canonical), receipt)
        )
        self._data.write(canonical)
        frame = TrajectoryFrame(self._sequence, clamped_time, dict(payload), receipt)
        self._sequence += 1
        self._last_time = clamped_time
        self._previous_receipt = receipt
        return frame

    def flush(self) -> None:
        """Mathematics: force the prefix of the append-only stream written so far to stable file buffers."""

        self._data.flush()
        self._index.flush()

    def close(self) -> None:
        """Mathematics: close both stream factors after flushing, preserving all appended frames and index entries."""

        if self._closed:
            return
        self.flush()
        self._data.close()
        self._index.close()
        self._closed = True

    def __enter__(self) -> "TrajectoryWriter":
        """Mathematics: return the writer identity for the context-preserving composition `with W as w`."""

        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """Mathematics: close the stream on all context exits, including exceptional exits."""

        self.close()


class TrajectoryReader:
    """Reader, seeker, and verifier for a trajectory stream."""

    def __init__(self, data_path: str | Path, index_path: str | Path) -> None:
        """Mathematics: validate stream/index headers and initialize cursor `(offset, sequence) = (header, 0)`."""

        self.data_path = Path(data_path)
        self.index_path = Path(index_path)
        self._data = self.data_path.open("rb")
        self._index = self.index_path.open("rb")
        data_header = self._data.read(TRAJECTORY_HEADER.size)
        index_header = self._index.read(TRAJECTORY_HEADER.size)
        if data_header != index_header:
            raise TrajectoryError("trajectory data/index headers disagree")
        magic, version, stride = TRAJECTORY_HEADER.unpack(data_header)
        if magic != TRAJECTORY_MAGIC or version != TRAJECTORY_VERSION or stride <= 0:
            raise TrajectoryError("invalid trajectory header")
        self.stride = stride
        self._data_start = TRAJECTORY_HEADER.size
        self._cursor_offset = self._data_start
        self._cursor_sequence = 0

    def read_frame(self) -> TrajectoryFrame | None:
        """Mathematics: decode the next record `R_n = (n,t,len,H) || payload`, or return `⊥` at EOF."""

        self._data.seek(self._cursor_offset)
        header = self._data.read(TRAJECTORY_RECORD.size)
        if not header:
            return None
        if len(header) != TRAJECTORY_RECORD.size:
            raise TrajectoryError("truncated trajectory record header")
        sequence, logical_time, length, receipt = TRAJECTORY_RECORD.unpack(header)
        if sequence != self._cursor_sequence:
            raise TrajectoryError("trajectory sequence discontinuity")
        payload_bytes = self._data.read(length)
        if len(payload_bytes) != length:
            raise TrajectoryError("truncated trajectory payload")
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TrajectoryError("invalid trajectory payload encoding") from exc
        if not isinstance(payload, dict):
            raise TrajectoryError("trajectory payload must be an object")
        self._cursor_offset += TRAJECTORY_RECORD.size + length
        self._cursor_sequence += 1
        return TrajectoryFrame(sequence, logical_time, payload, receipt)

    def seek_time(self, target_time: int) -> TrajectoryFrame | None:
        """Mathematics: binary-search sparse index then linearly scan at most `stride` records for `t ≥ target_time`."""

        if target_time < 0:
            raise ValueError("target_time must be non-negative")
        self._index.seek(TRAJECTORY_HEADER.size)
        entries: list[tuple[int, int, int]] = []
        while True:
            raw = self._index.read(TRAJECTORY_INDEX_ENTRY.size)
            if not raw:
                break
            if len(raw) != TRAJECTORY_INDEX_ENTRY.size:
                raise TrajectoryError("truncated trajectory index entry")
            entries.append(TRAJECTORY_INDEX_ENTRY.unpack(raw))
        if not entries:
            return None
        lo, hi = 0, len(entries)
        best = 0
        while lo < hi:
            mid = (lo + hi) // 2
            if entries[mid][1] <= target_time:
                best = mid
                lo = mid + 1
            else:
                hi = mid
        sequence, _, offset = entries[best]
        self._cursor_offset = offset
        self._cursor_sequence = sequence
        while True:
            frame = self.read_frame()
            if frame is None:
                return None
            if frame.logical_time >= target_time:
                return frame

    def verify(self) -> int:
        """Mathematics: verify monotonic time, contiguous sequence, and every receipt link; return frame count."""

        self._cursor_offset = self._data_start
        self._cursor_sequence = 0
        previous = b"\x00" * 32
        last_time = 0
        count = 0
        while True:
            frame = self.read_frame()
            if frame is None:
                return count
            canonical = _canonical_payload(frame.payload)
            if frame.logical_time < last_time:
                raise TrajectoryError("logical time decreased")
            expected = _receipt(previous, frame.sequence, frame.logical_time, canonical)
            if frame.receipt != expected:
                raise TrajectoryError(f"receipt mismatch at sequence {frame.sequence}")
            previous = frame.receipt
            last_time = frame.logical_time
            count += 1

    def replay(self, handler: Callable[[TrajectoryFrame], None]) -> int:
        """Mathematics: apply handler homomorphically over ordered frames `F = (f_0, ..., f_n)` and return `|F|`."""

        self._cursor_offset = self._data_start
        self._cursor_sequence = 0
        count = 0
        while True:
            frame = self.read_frame()
            if frame is None:
                return count
            handler(frame)
            count += 1

    def close(self) -> None:
        """Mathematics: release reader resources without changing the immutable trajectory stream."""

        self._data.close()
        self._index.close()

    def __enter__(self) -> "TrajectoryReader":
        """Mathematics: return reader identity for context composition."""

        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """Mathematics: close data and index handles on context exit."""

        self.close()
