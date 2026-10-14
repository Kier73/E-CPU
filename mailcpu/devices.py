"""Virtual device bus and simple character-device drivers."""

from __future__ import annotations

from collections import deque
from typing import Any, Callable, Protocol


class Device(Protocol):
    """Driver boundary for a device backed by communication or local state."""

    def read(self, size: int = -1) -> bytes:
        """Mathematics: return a prefix `D[:size]` of the device stream and advance its read cursor."""

        ...

    def write(self, data: bytes) -> int:
        """Mathematics: append `data` to the device stream and return `|data|` on complete acceptance."""

        ...


class NullDevice:
    """POSIX-like sink/source with no readable data."""

    def read(self, size: int = -1) -> bytes:
        """Mathematics: `/dev/null` has empty stream `D = []`, hence `read(D) = b''`."""

        return b""

    def write(self, data: bytes) -> int:
        """Mathematics: discard data while preserving the write-count identity `n = |data|`."""

        return len(data)


class BufferDevice:
    """A deterministic character device whose state is an input/output byte queue."""

    def __init__(self, initial: bytes = b"") -> None:
        """Mathematics: initialize stream state `D := initial` and output history `W := []`."""

        self._buffer = deque(initial)
        self.writes: list[bytes] = []

    def read(self, size: int = -1) -> bytes:
        """Mathematics: consume `min(size, |D|)` bytes from the FIFO stream, or all bytes when `size < 0`."""

        count = len(self._buffer) if size < 0 else min(size, len(self._buffer))
        return bytes(self._buffer.popleft() for _ in range(count))

    def write(self, data: bytes) -> int:
        """Mathematics: append one complete write event `W := W || [data]` and return `|data|`."""

        self.writes.append(bytes(data))
        return len(data)


class TerminalDevice(BufferDevice):
    """A checkpointable terminal driver with foreground-group ownership and canonical input mode."""

    def __init__(
        self,
        initial: bytes = b"",
        controlling_session_id: int | None = None,
        foreground_group_id: int | None = None,
        canonical: bool = True,
        echo: bool = False,
        isig: bool = True,
        pending_signals: list[tuple[int, str]] | None = None,
        eof_pending: bool = False,
        verase: int = 0x7F,
        vkill: int = 0x15,
        veof: int = 0x04,
        peer_hungup: bool = False,
    ) -> None:
        """Mathematics: initialize terminal state `T=(Q,W,s,g,c,e,i,S,E,C,h)` with line-edit controls `C`, EOF state `E`, and peer liveness `h`."""

        super().__init__(initial)
        self.controlling_session_id = controlling_session_id
        self.foreground_group_id = foreground_group_id
        self.canonical = bool(canonical)
        self.echo = bool(echo)
        self.isig = bool(isig)
        self.pending_signals = list(pending_signals or [])
        self.eof_pending = bool(eof_pending)
        self.verase = int(verase)
        self.vkill = int(vkill)
        self.veof = int(veof)
        self.peer_hungup = bool(peer_hungup)
        if any(control < 0 or control > 255 for control in (self.verase, self.vkill, self.veof)):
            raise ValueError("terminal control characters must be bytes")

    def read(self, size: int = -1) -> bytes:
        """Mathematics: return the longest available prefix bounded by `size`, with canonical mode restricting reads to `Q[:newline]` until peer HUP makes residual bytes the final prefix."""

        if not self.canonical:
            return super().read(size)
        values = bytes(self._buffer)
        newline = values.find(b"\n")
        if newline < 0:
            if self.peer_hungup and self._buffer:
                count = len(self._buffer) if size < 0 else min(size, len(self._buffer))
                return bytes(self._buffer.popleft() for _ in range(count))
            if self.eof_pending and self._buffer:
                count = len(self._buffer) if size < 0 else min(size, len(self._buffer))
                return bytes(self._buffer.popleft() for _ in range(count))
            if self.eof_pending:
                self.eof_pending = False
            return b""
        available = newline + 1
        count = available if size < 0 else min(size, available)
        return bytes(self._buffer.popleft() for _ in range(count))

    def feed_input(self, data: bytes) -> int:
        """Mathematics: apply line discipline `L(B)`, consuming control bytes into pending signals and echoing accepted bytes when `e=1`."""

        payload = bytes(data)
        echoed = self._ingest_input(payload)
        if self.echo and echoed:
            self.writes.append(echoed)
        return len(payload)

    def _ingest_input(self, data: bytes, echo_sink: Callable[[bytes], None] | None = None) -> bytes:
        """Mathematics: map each `b` in `B` to `(fg(T),C[b])` when `b∈dom(C)` and ISIG is enabled, else append `b` to `Q`; return echo bytes."""

        payload = bytes(data)
        echoed = bytearray()
        control_signals = {3: "INT", 26: "STOP", 28: "QUIT"}
        for byte in payload:
            signal = control_signals.get(byte) if self.isig and self.foreground_group_id is not None else None
            if signal is not None:
                self.pending_signals.append((int(self.foreground_group_id), signal))
            elif self.canonical and byte == self.verase:
                if self._erase_current_line() and self.echo:
                    echoed.extend(b"\b \b")
            elif self.canonical and byte == self.vkill:
                erased = self._kill_current_line()
                if self.echo and erased:
                    echoed.extend(b"\b \b" * erased)
            elif self.canonical and byte == self.veof:
                self.eof_pending = True
            else:
                self._buffer.append(byte)
                if self.echo:
                    echoed.append(byte)
            if self.echo and signal is not None:
                echoed.append(byte)
        if echo_sink is not None and echoed:
            echo_sink(bytes(echoed))
        return bytes(echoed)

    def _erase_current_line(self) -> bool:
        r"""Mathematics: delete one byte iff `|Q\tail_after_last_newline|>0`, implementing `Q:=Q\{last_byte}`."""

        values = bytes(self._buffer)
        if not values or values.rfind(b"\n") == len(values) - 1:
            return False
        self._buffer.pop()
        return True

    def _kill_current_line(self) -> int:
        r"""Mathematics: remove `k=|Q\tail_after_last_newline|` bytes from the current canonical line and return `k`."""

        values = bytes(self._buffer)
        last_newline = values.rfind(b"\n")
        removable = max(0, len(values) - (last_newline + 1))
        for _ in range(removable):
            self._buffer.pop()
        return removable

    def input_ready(self) -> bool:
        """Mathematics: canonical readiness is `∃ newline∈Q ∨ E=1 ∨ h=1`; raw readiness is `|Q|>0 ∨ h=1`."""

        if not self.canonical:
            return bool(self._buffer) or self.peer_hungup
        return b"\n" in bytes(self._buffer) or self.eof_pending or self.peer_hungup

    def set_foreground(self, session_id: int, group_id: int) -> None:
        """Mathematics: apply terminal ownership transition `(s,g) := (session_id,group_id)` over positive process identities."""

        if session_id <= 0 or group_id <= 0:
            raise ValueError("terminal session and group ids must be positive")
        self.controlling_session_id = int(session_id)
        self.foreground_group_id = int(group_id)

    def set_mode(self, canonical: bool, echo: bool, isig: bool | None = None) -> None:
        """Mathematics: replace terminal mode vector `(c,e,i)` without changing queued bytes or pending events."""

        self.canonical = bool(canonical)
        self.echo = bool(echo)
        if isig is not None:
            self.isig = bool(isig)


class PtyMasterDevice(BufferDevice):
    """The communication-facing endpoint of a virtual pseudo-terminal pair."""

    def __init__(self, pair_id: str, initial: bytes = b"", peer_hungup: bool = False) -> None:
        """Mathematics: initialize master state `M=(Q_m,W_m,pair,h)` with peer identity `pair` and peer-liveness bit `h`."""

        super().__init__(initial)
        self.pair_id = pair_id
        self.peer_hungup = bool(peer_hungup)
        self.peer: PtySlaveDevice | None = None

    def attach(self, peer: "PtySlaveDevice") -> None:
        """Mathematics: complete the bijection `peer(M)=S` exactly once for one PTY pair."""

        if peer.pair_id != self.pair_id:
            raise ValueError("pty peer pair identity mismatch")
        self.peer = peer

    def write(self, data: bytes) -> int:
        """Mathematics: route master write `B` into slave input `Q_s:=Q_s||B`, returning `|B|` after complete acceptance."""

        if self.peer is None or self.peer_hungup:
            raise RuntimeError("pty master has no slave")
        payload = bytes(data)
        self.writes.append(payload)
        self.peer.feed_from_master(payload)
        return len(payload)

    def read(self, size: int = -1) -> bytes:
        """Mathematics: consume `Q_m[:n]`, exposing `b''` exactly when `Q_m=∅ ∧ h=1` after peer closure."""

        return super().read(size)


class PtySlaveDevice(TerminalDevice):
    """The terminal-facing endpoint of a virtual pseudo-terminal pair."""

    def __init__(
        self,
        pair_id: str,
        initial: bytes = b"",
        controlling_session_id: int | None = None,
        foreground_group_id: int | None = None,
        canonical: bool = True,
        echo: bool = False,
        isig: bool = True,
        pending_signals: list[tuple[int, str]] | None = None,
        eof_pending: bool = False,
        verase: int = 0x7F,
        vkill: int = 0x15,
        veof: int = 0x04,
        peer_hungup: bool = False,
    ) -> None:
        """Mathematics: initialize slave terminal state `S=(Q_s,W_s,s,g,c,e,pair)` with a PTY identity."""

        super().__init__(
            initial,
            controlling_session_id,
            foreground_group_id,
            canonical,
            echo,
            isig,
            pending_signals,
            eof_pending,
            verase,
            vkill,
            veof,
            peer_hungup,
        )
        self.pair_id = pair_id
        self.peer: PtyMasterDevice | None = None

    def attach(self, peer: PtyMasterDevice) -> None:
        """Mathematics: complete the bijection `peer(S)=M` exactly once for one PTY pair."""

        if peer.pair_id != self.pair_id:
            raise ValueError("pty peer pair identity mismatch")
        self.peer = peer

    def feed_from_master(self, data: bytes) -> int:
        """Mathematics: apply slave line discipline `L(B)` and route its echo projection into master queue `Q_m`."""

        payload = bytes(data)
        if self.peer is None or self.peer_hungup:
            raise RuntimeError("pty slave has no master")
        self._ingest_input(payload, self.peer._buffer.extend)
        return len(payload)

    def feed_input(self, data: bytes) -> int:
        """Mathematics: treat injected slave input as master-originated bytes, preserving PTY echo and control-signal routing."""

        return self.feed_from_master(data)

    def write(self, data: bytes) -> int:
        """Mathematics: route slave output `B` into master queue `Q_m:=Q_m||B`, recording the accepted write."""

        if self.peer is None or self.peer_hungup:
            raise RuntimeError("pty slave has no master")
        payload = bytes(data)
        self.writes.append(payload)
        self.peer._buffer.extend(payload)
        return len(payload)


class DeviceBus:
    """Addressed driver registry for `/dev`-style I/O."""

    def __init__(self) -> None:
        """Mathematics: initialize the partial device map `D : name ⇀ driver` as empty."""

        self._devices: dict[str, Device] = {}

    def register(self, name: str, device: Device) -> None:
        """Mathematics: extend the device map by function override `D := D[name ↦ device]`."""

        if not name or "/" in name:
            raise ValueError("device names must be non-empty path components")
        if name in self._devices:
            raise ValueError(f"device already registered: {name}")
        self._devices[name] = device

    def create_pty_pair(self) -> tuple[str, str]:
        """Mathematics: choose least unused `i` and extend `D` with connected endpoints `(ptym_i,ptys_i)`."""

        index = 1
        while f"ptym{index:04d}" in self._devices or f"ptys{index:04d}" in self._devices:
            index += 1
        pair_id = f"pty{index:04d}"
        master_name = f"ptym{index:04d}"
        slave_name = f"ptys{index:04d}"
        master = PtyMasterDevice(pair_id)
        slave = PtySlaveDevice(pair_id)
        master.attach(slave)
        slave.attach(master)
        self.register(master_name, master)
        self.register(slave_name, slave)
        return master_name, slave_name

    def remove_pty_pair(self, pair_id: str) -> None:
        r"""Mathematics: remove both endpoint names `D\{m,s}` iff they form the requested pair identity."""

        names = tuple(
            name
            for name, device in self._devices.items()
            if isinstance(device, (PtyMasterDevice, PtySlaveDevice)) and device.pair_id == pair_id
        )
        for name in names:
            del self._devices[name]

    def reconcile_pty_liveness(
        self,
        referenced_paths: set[str],
    ) -> tuple[tuple[str, int | None, int | None], ...]:
        r"""Mathematics: set endpoint liveness `h_e := ¬live(e)` and emit one event for `master↓ ∧ slave↑ ∧ ¬h_slave`.

        The result is `(pair_id, session_id, foreground_group_id)` for each
        master-side closure that still has a live slave.  Removing both names
        is deferred until `live(master)=live(slave)=0`, so the surviving side
        can observe EOF/HUP and the terminal session can receive `SIGHUP`.
        """

        events: list[tuple[str, int | None, int | None]] = []
        for pair_id in self.pty_pairs():
            suffix = pair_id.removeprefix("pty")
            master_name = f"ptym{suffix}"
            slave_name = f"ptys{suffix}"
            master = self._get(master_name)
            slave = self._get(slave_name)
            master_live = f"/dev/{master_name}" in referenced_paths
            slave_live = f"/dev/{slave_name}" in referenced_paths
            if not master_live and slave_live and not slave.peer_hungup:
                slave.peer_hungup = True
                if isinstance(slave, PtySlaveDevice):
                    events.append(
                        (
                            pair_id,
                            slave.controlling_session_id,
                            slave.foreground_group_id,
                        )
                    )
            if not slave_live and not master.peer_hungup:
                master.peer_hungup = True
            if not master_live and not slave_live:
                self.remove_pty_pair(pair_id)
        return tuple(events)

    def pty_pairs(self) -> tuple[str, ...]:
        """Mathematics: project distinct live PTY identities `Π={pair(d):d∈D_pty}` in sorted order."""

        return tuple(
            sorted(
                {
                    device.pair_id
                    for device in self._devices.values()
                    if isinstance(device, (PtyMasterDevice, PtySlaveDevice))
                }
            )
        )

    def read(self, name: str, size: int = -1) -> bytes:
        """Mathematics: dispatch read to `D[name]`, requiring `name ∈ dom(D)`."""

        return self._get(name).read(size)

    def write(self, name: str, data: bytes) -> int:
        """Mathematics: dispatch write to `D[name]`, preserving the driver byte-count contract."""

        return self._get(name).write(data)

    def feed(self, name: str, data: bytes) -> int:
        """Mathematics: append input `B` to a buffered driver state `Q_name := Q_name || B`, refusing non-buffered injection."""

        device = self._get(name)
        if not isinstance(device, BufferDevice):
            raise TypeError(f"device does not accept injected input: {name}")
        if isinstance(device, TerminalDevice):
            return device.feed_input(data)
        device._buffer.extend(data)
        return len(data)

    def readiness(self, name: str, readable: bool) -> bool:
        """Mathematics: project driver readiness `ready(D,read)=|Q_D|>0 ∨ h_D`, EOF-ready for null, and always-ready writes."""

        device = self._get(name)
        if not readable:
            return True
        if isinstance(device, NullDevice):
            return True
        if isinstance(device, TerminalDevice):
            return device.input_ready()
        if isinstance(device, BufferDevice):
            return bool(device._buffer) or bool(getattr(device, "peer_hungup", False))
        return False

    def terminal(self, name: str) -> TerminalDevice | None:
        """Mathematics: project the partial driver map `D[name]` into a terminal state only when `D[name]∈TerminalDevice`."""

        device = self._get(name)
        return device if isinstance(device, TerminalDevice) else None

    def peer_hungup(self, name: str) -> bool:
        """Mathematics: project `h(name)=1` exactly for a PTY endpoint whose opposite endpoint is no longer live."""

        return bool(getattr(self._get(name), "peer_hungup", False))

    def set_terminal_foreground(self, name: str, session_id: int, group_id: int) -> None:
        """Mathematics: delegate foreground ownership transition `G_terminal := (session_id,group_id)` to a terminal driver."""

        terminal = self.terminal(name)
        if terminal is None:
            raise TypeError(f"device is not a terminal: {name}")
        terminal.set_foreground(session_id, group_id)

    def set_terminal_mode(self, name: str, canonical: bool, echo: bool) -> None:
        """Mathematics: delegate mode transition `M_terminal := (canonical,echo)` to a terminal driver, preserving ISIG."""

        terminal = self.terminal(name)
        if terminal is None:
            raise TypeError(f"device is not a terminal: {name}")
        terminal.set_mode(canonical, echo)

    def set_terminal_mode_with_isig(
        self,
        name: str,
        canonical: bool,
        echo: bool,
        isig: bool | None,
    ) -> None:
        """Mathematics: apply optional control bit `i' := isig`, leaving `i` unchanged when `isig=⊥`."""

        terminal = self.terminal(name)
        if terminal is None:
            raise TypeError(f"device is not a terminal: {name}")
        terminal.set_mode(canonical, echo, isig)

    def pop_terminal_signals(self) -> tuple[tuple[str, int, str], ...]:
        """Mathematics: atomically project and clear `E={(d,g,σ)}` from all terminal pending-event lists."""

        events: list[tuple[str, int, str]] = []
        for name, device in sorted(self._devices.items()):
            if not isinstance(device, TerminalDevice):
                continue
            events.extend((name, int(group_id), str(signal)) for group_id, signal in device.pending_signals)
            device.pending_signals.clear()
        return tuple(events)

    def names(self) -> tuple[str, ...]:
        """Mathematics: return the sorted finite domain `dom(D)` as the visible device inventory."""

        return tuple(sorted(self._devices))

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Mathematics: serialize driver state `D[name]` while preserving buffered input and write history."""

        result: dict[str, dict[str, Any]] = {}
        for name, device in sorted(self._devices.items()):
            if isinstance(device, NullDevice):
                result[name] = {"kind": "null"}
            elif isinstance(device, PtyMasterDevice):
                result[name] = {
                    "kind": "pty_master",
                    "pair_id": device.pair_id,
                    "buffer_hex": bytes(device._buffer).hex(),
                    "writes_hex": [item.hex() for item in device.writes],
                    "peer_name": f"ptys{device.pair_id.removeprefix('pty')}",
                    "peer_hungup": device.peer_hungup,
                }
            elif isinstance(device, PtySlaveDevice):
                result[name] = {
                    "kind": "pty_slave",
                    "pair_id": device.pair_id,
                    "buffer_hex": bytes(device._buffer).hex(),
                    "writes_hex": [item.hex() for item in device.writes],
                    "controlling_session_id": device.controlling_session_id,
                    "foreground_group_id": device.foreground_group_id,
                    "canonical": device.canonical,
                    "echo": device.echo,
                    "isig": device.isig,
                    "pending_signals": [list(item) for item in device.pending_signals],
                    "eof_pending": device.eof_pending,
                    "verase": device.verase,
                    "vkill": device.vkill,
                    "veof": device.veof,
                    "peer_hungup": device.peer_hungup,
                    "peer_name": f"ptym{device.pair_id.removeprefix('pty')}",
                }
            elif isinstance(device, TerminalDevice):
                result[name] = {
                    "kind": "terminal",
                    "buffer_hex": bytes(device._buffer).hex(),
                    "writes_hex": [item.hex() for item in device.writes],
                    "controlling_session_id": device.controlling_session_id,
                    "foreground_group_id": device.foreground_group_id,
                    "canonical": device.canonical,
                    "echo": device.echo,
                    "isig": device.isig,
                    "pending_signals": [list(item) for item in device.pending_signals],
                    "eof_pending": device.eof_pending,
                    "verase": device.verase,
                    "vkill": device.vkill,
                    "veof": device.veof,
                    "peer_hungup": device.peer_hungup,
                }
            elif isinstance(device, BufferDevice):
                result[name] = {
                    "kind": "buffer",
                    "buffer_hex": bytes(device._buffer).hex(),
                    "writes_hex": [item.hex() for item in device.writes],
                }
            else:
                raise TypeError(f"device is not checkpointable: {name}")
        return result

    @classmethod
    def from_snapshot(cls, payload: dict[str, dict[str, Any]]) -> "DeviceBus":
        """Mathematics: reconstruct finite driver map `D` from typed state records, refusing unknown driver kinds."""

        bus = cls()
        peer_names: dict[str, str] = {}
        for name, raw in sorted(payload.items()):
            kind = raw.get("kind")
            if kind == "null":
                device: Device = NullDevice()
            elif kind == "pty_master":
                device = PtyMasterDevice(
                    str(raw["pair_id"]),
                    bytes.fromhex(str(raw.get("buffer_hex", ""))),
                    bool(raw.get("peer_hungup", False)),
                )
                device.writes.extend(bytes.fromhex(item) for item in raw.get("writes_hex", []))
                peer_names[name] = str(raw["peer_name"])
            elif kind == "pty_slave":
                device = PtySlaveDevice(
                    str(raw["pair_id"]),
                    bytes.fromhex(str(raw.get("buffer_hex", ""))),
                    None if raw.get("controlling_session_id") is None else int(raw["controlling_session_id"]),
                    None if raw.get("foreground_group_id") is None else int(raw["foreground_group_id"]),
                    bool(raw.get("canonical", True)),
                    bool(raw.get("echo", False)),
                    bool(raw.get("isig", True)),
                    [(int(item[0]), str(item[1])) for item in raw.get("pending_signals", [])],
                    bool(raw.get("eof_pending", False)),
                    int(raw.get("verase", 0x7F)),
                    int(raw.get("vkill", 0x15)),
                    int(raw.get("veof", 0x04)),
                    bool(raw.get("peer_hungup", False)),
                )
                device.writes.extend(bytes.fromhex(item) for item in raw.get("writes_hex", []))
                peer_names[name] = str(raw["peer_name"])
            elif kind == "terminal":
                device = TerminalDevice(
                    bytes.fromhex(str(raw.get("buffer_hex", ""))),
                    None if raw.get("controlling_session_id") is None else int(raw["controlling_session_id"]),
                    None if raw.get("foreground_group_id") is None else int(raw["foreground_group_id"]),
                    bool(raw.get("canonical", True)),
                    bool(raw.get("echo", False)),
                    bool(raw.get("isig", True)),
                    [(int(item[0]), str(item[1])) for item in raw.get("pending_signals", [])],
                    bool(raw.get("eof_pending", False)),
                    int(raw.get("verase", 0x7F)),
                    int(raw.get("vkill", 0x15)),
                    int(raw.get("veof", 0x04)),
                    bool(raw.get("peer_hungup", False)),
                )
                device.writes.extend(bytes.fromhex(item) for item in raw.get("writes_hex", []))
            elif kind == "buffer":
                device = BufferDevice(bytes.fromhex(str(raw.get("buffer_hex", ""))))
                device.writes.extend(bytes.fromhex(item) for item in raw.get("writes_hex", []))
            else:
                raise ValueError(f"unknown device kind: {kind}")
            bus.register(name, device)
        for name, peer_name in peer_names.items():
            device = bus._get(name)
            peer = bus._get(peer_name)
            if isinstance(device, PtyMasterDevice) and isinstance(peer, PtySlaveDevice):
                device.attach(peer)
            elif isinstance(device, PtySlaveDevice) and isinstance(peer, PtyMasterDevice):
                device.attach(peer)
            else:
                raise ValueError(f"invalid pty peer pair: {name}, {peer_name}")
        return bus

    def _get(self, name: str) -> Device:
        """Mathematics: perform the partial-map lookup `D[name]`, failing instead of fabricating a device."""

        try:
            return self._devices[name]
        except KeyError as exc:
            raise KeyError(f"unknown device: {name}") from exc
