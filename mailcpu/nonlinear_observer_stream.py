"""NCR-STREAM-003: exact indexed nonlinear observations with conditional emissions.

Receiver-pinned NCR-007 Boolean source laws admit an independently checked
Koopman observer feature space. Their strictly descending active ranks also
provide a finite stabilization horizon. A conditional stream can therefore be
split into a checked transient and a constant tail: the k-th emitted event is
locatable without replaying k transitions or enumerating 2**width states.

These are mathematical observations; neither this API nor a content digest
constitutes MailCPU SEND delivery, remote permission or Hypervisor execution.
The optional navigable_compute dependency must be installed at the source
revision independently pinned by the receiver.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping

from .substrate_bootstrap import BootstrapRefused

_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_SCHEMA = "mailcpu.ncr-nonlinear-conditional-stream.v1"
_MAX_PACKET = 2_000_000
_MAX_LOGICAL_BITS = 4096


def _hex(value: int) -> str:
    """Mathematics: injectively encode an integer as canonical hexadecimal."""

    return hex(value)


def _unhex(value: Any) -> int:
    """Mathematics: admit only the unique lowercase hexadecimal integer spelling."""

    if type(value) is not str:
        raise BootstrapRefused("stream integer must be canonical hexadecimal text")
    try:
        parsed = int(value, 16)
    except (ValueError, TypeError) as exc:
        raise BootstrapRefused("stream integer is not hexadecimal") from exc
    if _hex(parsed) != value:
        raise BootstrapRefused("stream integer has noncanonical spelling")
    return parsed


def _sha(value: Any, label: str) -> str:
    """Mathematics: check that a claimed SHA256 content identity is lowercase hex."""

    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise BootstrapRefused(f"{label} must be a 64-character lowercase SHA256 digest")
    return value


def _canonical(value: object) -> bytes:
    """Mathematics: domain-separate a JSON-only mathematical observation receipt."""

    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


@dataclass(frozen=True, slots=True)
class AdmittedNCRStreamGround:
    """Receiver-source-pinned and independently audited nonlinear mathematical Ground."""

    source_commit: str
    packet_sha256: str
    family_sha256: str
    ground_sha256: str
    source_width: int
    feature_dimension: int
    drain_horizon: int
    family: Any
    ground: Any


def admit_ncr_stream_ground(
    raw: bytes, *, receiver_expected_sha256: str, source_commit: str
) -> AdmittedNCRStreamGround:
    """Mathematics: verify exact bytes and NCR source/Koopman algebra on receipt.

    The commit identity is an explicit receiver pin. The deployment must also
    verify the installed navigable_compute package against that checkout;
    this method cannot infer its Git provenance from the import path.
    """

    expected = _sha(receiver_expected_sha256, "receiver-pinned packet")
    if type(source_commit) is not str or _COMMIT.fullmatch(source_commit) is None:
        raise BootstrapRefused("NCR source commit must be an exact 40-hex receiver pin")
    if type(raw) is not bytes or not 0 < len(raw) <= _MAX_PACKET:
        raise BootstrapRefused("NCR source packet exceeds the mathematical carrier budget")
    observed = sha256(raw).hexdigest()
    if observed != expected:
        raise BootstrapRefused("NCR packet bytes differ from the receiver-owned digest")
    try:
        from navigable_compute.nonlinear_koopman_wire import decode_nonlinear
    except ImportError as exc:
        raise BootstrapRefused("pinned NCR mathematical verifier is unavailable") from exc
    try:
        family, ground, _ = decode_nonlinear(raw)
    except (TypeError, ValueError, OverflowError, IndexError, AttributeError) as exc:
        raise BootstrapRefused("independent NCR nonlinear mathematical audit refused") from exc
    width = family.description.width
    if not 2 <= width <= 128 or not 1 <= ground.dimension <= 256:
        raise BootstrapRefused("nonlinear source/observer dimensions are outside admission")
    return AdmittedNCRStreamGround(
        source_commit, observed, family.digest, ground.digest,
        width, ground.dimension, family.description.drain_horizon, family, ground
    )


@dataclass(frozen=True, slots=True)
class NonlinearEmittedEvent:
    """One emitted value, indexed by emission ordinal and source-word iteration."""

    index: int
    iteration: int
    mailbox: str
    value: int


@dataclass(frozen=True, slots=True)
class NonlinearStreamReceipt:
    """Portable mathematical observation bound to exact source, observer and query."""

    source_commit: str
    packet_sha256: str
    family_sha256: str
    ground_sha256: str
    initial: int
    word: tuple[int, ...]
    gate_bit: int | None
    value_bit: int
    mailbox: str
    event: NonlinearEmittedEvent

    def _payload(self) -> dict[str, Any]:
        """Mathematics: encode the entire event query in a versioned exact algebra."""

        return {
            "schema": _SCHEMA,
            "source_commit": self.source_commit,
            "packet_sha256": self.packet_sha256,
            "family_sha256": self.family_sha256,
            "ground_sha256": self.ground_sha256,
            "initial": _hex(self.initial),
            "word": list(self.word),
            "gate_bit": self.gate_bit,
            "value_bit": self.value_bit,
            "mailbox": self.mailbox,
            "event": {
                "index": _hex(self.event.index),
                "iteration": _hex(self.event.iteration),
                "mailbox": self.event.mailbox,
                "value": _hex(self.event.value),
            },
        }

    @property
    def digest(self) -> str:
        """Mathematics: content-address the entire claimed nonlinear observation."""

        return sha256(_canonical(self._payload())).hexdigest()

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: produce a portable digest-bound JSON receipt."""

        return {**self._payload(), "digest": self.digest}

    @classmethod
    def from_snapshot(cls, raw: Mapping[str, Any]) -> "NonlinearStreamReceipt":
        """Mathematics: strict exact decoding, including rejection of unknown keys."""

        if not isinstance(raw, Mapping) or set(raw) != {
            "schema", "source_commit", "packet_sha256", "family_sha256",
            "ground_sha256", "initial", "word", "gate_bit", "value_bit",
            "mailbox", "event", "digest",
        } or raw["schema"] != _SCHEMA:
            raise BootstrapRefused("nonlinear observation envelope is malformed")
        if type(raw["source_commit"]) is not str or _COMMIT.fullmatch(raw["source_commit"]) is None:
            raise BootstrapRefused("nonlinear stream source pin is malformed")
        for name in ("packet_sha256", "family_sha256", "ground_sha256", "digest"):
            _sha(raw[name], name)
        if type(raw["mailbox"]) is not str or not 0 < len(raw["mailbox"]) <= 128:
            raise BootstrapRefused("nonlinear observation mailbox is invalid")
        word = raw["word"]
        if type(word) is not list or len(word) > 16 or any(
            type(action) is not int or action < 0 for action in word
        ):
            raise BootstrapRefused("nonlinear observation action word is invalid")
        if type(raw["value_bit"]) is not int or raw["value_bit"] < 0:
            raise BootstrapRefused("nonlinear value bit is invalid")
        gate = raw["gate_bit"]
        if gate is not None and (type(gate) is not int or gate < 0):
            raise BootstrapRefused("nonlinear emission gate bit is invalid")
        event = raw["event"]
        if type(event) is not dict or set(event) != {
            "index", "iteration", "mailbox", "value"
        } or type(event["mailbox"]) is not str:
            raise BootstrapRefused("nonlinear event fields are malformed")
        initial = _unhex(raw["initial"])
        index, iteration, value = (_unhex(event[k]) for k in ("index", "iteration", "value"))
        if (initial < 0 or index < 0 or iteration < 1 or value not in (0, 1)
                or index.bit_length() > _MAX_LOGICAL_BITS
                or iteration.bit_length() > _MAX_LOGICAL_BITS):
            raise BootstrapRefused("nonlinear event is outside the canonical domain")
        result = cls(
            raw["source_commit"], raw["packet_sha256"], raw["family_sha256"],
            raw["ground_sha256"], initial, tuple(word), gate, raw["value_bit"],
            raw["mailbox"],
            NonlinearEmittedEvent(index, iteration, event["mailbox"], value),
        )
        if result.snapshot() != dict(raw):
            raise BootstrapRefused("nonlinear stream receipt digest or canonical form mismatches")
        return result


class NCRConditionalObserverStream:
    """Indexed 0/1 emissions from one verified rank-draining nonlinear source."""

    def __init__(
        self,
        admitted: AdmittedNCRStreamGround,
        *,
        initial: int,
        word: tuple[int, ...] = (0,),
        value_bit: int = 0,
        gate_bit: int | None = None,
        mailbox: str = "nonlinear.observation",
        max_transient_iterations: int = 64,
    ) -> None:
        """Mathematics: construct a finite exact transient and verified stationary tail."""

        if not isinstance(admitted, AdmittedNCRStreamGround):
            raise BootstrapRefused("admitted verified nonlinear source Ground is required")
        family, ground = admitted.family, admitted.ground
        if type(initial) is not int or not 0 <= initial < (1 << admitted.source_width):
            raise BootstrapRefused("initial nonlinear source state exceeds admitted width")
        if type(word) is not tuple or not 1 <= len(word) <= 16 or any(
            type(action) is not int or not 0 <= action < len(family.operators)
            for action in word
        ):
            raise BootstrapRefused("nonlinear action word is invalid")
        number_observers = len(family.description.observers)
        if type(value_bit) is not int or not 0 <= value_bit < number_observers:
            raise BootstrapRefused("nonlinear value readout is not a source observer bit")
        if gate_bit is not None and (
            type(gate_bit) is not int or not 0 <= gate_bit < number_observers
        ):
            raise BootstrapRefused("nonlinear emission gate must be a source observer bit")
        if type(mailbox) is not str or not 0 < len(mailbox) <= 128:
            raise BootstrapRefused("nonlinear output mailbox must be a bounded name")
        if (type(max_transient_iterations) is not int
                or not 0 <= max_transient_iterations <= 4096):
            raise BootstrapRefused("transient observation budget is invalid")
        cycles = (admitted.drain_horizon + len(word) - 1) // len(word)
        if cycles > max_transient_iterations:
            raise BootstrapRefused("certified stabilization exceeds transient budget")
        self.admitted = admitted
        self.initial = initial
        self.word = word
        self.value_bit = value_bit
        self.gate_bit = gate_bit
        self.mailbox = mailbox
        self.stabilization_iteration = cycles
        self._transient: tuple[NonlinearEmittedEvent, ...]
        transient = []
        state = initial
        for iteration in range(1, cycles + 1):
            state = self._advance(state)
            observed = family.project_observer(state)
            if self._enabled(observed):
                transient.append(NonlinearEmittedEvent(
                    len(transient), iteration, mailbox, (observed >> value_bit) & 1
                ))
        if self._advance(state) != state:
            raise BootstrapRefused("NCR certified causal-rank stabilization failed")
        terminal = family.project_observer(state)
        # The actual candidate feature Ground must agree at the fixed point.
        if ground.read(ground.project(state)) != terminal:
            raise BootstrapRefused("foreign nonlinear source/observer fixed point disagrees")
        self._transient = tuple(transient)
        self._tail_value: int | None = (
            (terminal >> value_bit) & 1 if self._enabled(terminal) else None
        )

    def _advance(self, state: int) -> int:
        """Mathematics: compose one declared source action word in order."""

        for action in self.word:
            state = self.admitted.family.operators[action].apply(state)
        return state

    def _enabled(self, observed: int) -> bool:
        """Mathematics: exact event-count predicate on the declared observer bit."""

        return self.gate_bit is None or bool((observed >> self.gate_bit) & 1)

    def length(self) -> int | None:
        """Mathematics: return finite emitted count, or None for a permanent emitting tail."""

        return len(self._transient) if self._tail_value is None else None

    def event(self, index: int) -> NonlinearEmittedEvent:
        """Mathematics: locate output ordinal through the finite transient plus stationary tail.

        The selected logical-time value is also reconstructed using upstream
        GF(2) Koopman powering and its independent original-source verifier.
        """

        if type(index) is not int or index < 0 or index.bit_length() > _MAX_LOGICAL_BITS:
            raise IndexError("nonlinear emission index is not a bounded nonnegative integer")
        if index < len(self._transient):
            found = self._transient[index]
        elif self._tail_value is not None:
            iteration = self.stabilization_iteration + 1 + index - len(self._transient)
            if iteration.bit_length() > _MAX_LOGICAL_BITS:
                raise BootstrapRefused("nonlinear selected logical coordinate exceeds 4096 bits")
            found = NonlinearEmittedEvent(index, iteration, self.mailbox, self._tail_value)
        else:
            raise IndexError("nonlinear stream has no such emitted event")
        try:
            from navigable_compute.nonlinear_koopman import navigate_nonlinear
            from navigable_compute.nonlinear_koopman_verify import verify_nonlinear_result
            result = navigate_nonlinear(
                self.admitted.family, self.admitted.ground,
                self.initial, self.word, found.iteration,
            )
            if not verify_nonlinear_result(
                self.admitted.family, self.admitted.ground, result
            ):
                raise BootstrapRefused("selected nonlinear observer result failed independent audit")
            observed = int(result.observed_decimal)
        except (ValueError, TypeError, OverflowError, ImportError) as exc:
            raise BootstrapRefused("selected nonlinear Koopman navigation refused") from exc
        if not self._enabled(observed) or (observed >> self.value_bit) & 1 != found.value:
            raise BootstrapRefused("selected nonlinear stream disagrees with Koopman source")
        return found

    def issue_receipt(self, index: int) -> NonlinearStreamReceipt:
        """Mathematics: bind a selected emission to source, observer and temporal identity."""

        event = self.event(index)
        return NonlinearStreamReceipt(
            self.admitted.source_commit,
            self.admitted.packet_sha256,
            self.admitted.family_sha256,
            self.admitted.ground_sha256,
            self.initial, self.word, self.gate_bit,
            self.value_bit, self.mailbox, event,
        )


def verify_nonlinear_stream_receipt(
    receipt: NonlinearStreamReceipt,
    *,
    packet: bytes,
    receiver_expected_sha256: str,
    source_commit: str,
) -> bool:
    """Mathematics: independently re-admit the exact source and reconstruct one event.

    No source state enumeration, output-prefix replay to the requested index,
    sender trust, or remote execution permission is involved.
    """

    if not isinstance(receipt, NonlinearStreamReceipt):
        return False
    try:
        if (receipt.packet_sha256 != receiver_expected_sha256
                or receipt.source_commit != source_commit):
            return False
        admitted = admit_ncr_stream_ground(
            packet, receiver_expected_sha256=receiver_expected_sha256,
            source_commit=source_commit,
        )
        observer = NCRConditionalObserverStream(
            admitted, initial=receipt.initial, word=receipt.word,
            value_bit=receipt.value_bit, gate_bit=receipt.gate_bit,
            mailbox=receipt.mailbox,
        )
        return observer.issue_receipt(receipt.event.index) == receipt
    except (BootstrapRefused, IndexError, ValueError, TypeError, OverflowError):
        return False
