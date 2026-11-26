"""Quorum-persistent VGI guarded execution through E-CPU's native M1/M3/M4.

The source code remains receiver-installed, source-pinned Python. The session
retains reduced coordinates, a canonical proof receipt and an immutable
program identity. Only M3 commit_state can publish a successor. A remote
packet does not grant rights or supply a trusted migration observation.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Callable, Mapping

from .computational_session import (
    ComputationalSessionSnapshot, ComputationalSessionStore,
)
from .computational_transition import (
    ComputationalSessionTransitionAdapter, ComputationalTransitionContext,
    ComputationalTransitionContract, ComputationalTransitionError,
)
from .vgi_guarded_runtime import _runtime_modules

STATE_SCHEMA = "mailcpu.vgi.guarded.reduced-session.v1"
INPUT_SCHEMA = "mailcpu.vgi.guarded.session-input.v1"
PROGRAM_SCHEMA = "mailcpu.vgi.guarded.admitted-program.v1"
TRANSITION_ID = "vgi.guarded.reduced-session.transition.v1"
MAX_INPUT_BYTES = 65536
MAX_STATE_BYTES = 1_048_576
MAX_QUANTUM_INPUTS = 128
MAX_MACRO_DIGITS = 120


class VGIRecoveryError(ComputationalTransitionError):
    """A reduced-state session, observation, or mathematical witness is invalid."""


def _duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for k, v in pairs:
        if k in result:
            raise VGIRecoveryError("duplicate JSON field")
        result[k] = v
    return result


def _reject_constant(value: str) -> None:
    raise VGIRecoveryError("non-finite JSON number")


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf8")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise VGIRecoveryError("expected finite canonical JSON") from exc


def _decode(value: bytes, maximum: int, label: str) -> dict[str, Any]:
    if type(value) is not bytes or len(value) > maximum:
        raise VGIRecoveryError(f"{label} exceeds bounded UTF-8 input")
    try:
        parsed = json.loads(value.decode("utf8"), object_pairs_hook=_duplicates,
                            parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise VGIRecoveryError(f"invalid {label} JSON") from exc
    if type(parsed) is not dict or _canonical(parsed) != value:
        raise VGIRecoveryError(f"{label} is not canonical JSON object")
    return parsed


def _sha(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


def _require_digest(value: Any, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise VGIRecoveryError(f"{label} must be a SHA-256 digest")
    return value


def _keys(record: Any, fields: set[str], label: str) -> dict[str, Any]:
    if type(record) is not dict or set(record) != fields:
        raise VGIRecoveryError(f"{label} has noncanonical fields")
    return record


def _index(value: Any, upper: int, label: str) -> int:
    if type(value) is not int or not 0 <= value < upper:
        raise VGIRecoveryError(f"invalid {label}")
    return value


def _word(value: Any) -> int:
    if type(value) is not str or not 1 <= len(value) <= MAX_MACRO_DIGITS:
        raise VGIRecoveryError("invalid decimal macro count")
    if not value.isascii() or not value.isdecimal() or (len(value) > 1 and value[0] == "0"):
        raise VGIRecoveryError("macro count must be canonical decimal")
    return int(value)


@dataclass(frozen=True, slots=True)
class GroundStage:
    source: Any
    certificate: Mapping[str, Any]
    admitted: Any

    @classmethod
    def admit(cls, source: Any, certificate: Mapping[str, Any]) -> "GroundStage":
        guarded, _, _ = _runtime_modules()  # revalidate real installed source pins
        if not isinstance(source, guarded.GuardedGround):
            raise VGIRecoveryError("stage source must be a pinned VGI GuardedGround")
        if type(certificate) is not dict:
            raise VGIRecoveryError("stage certificate must be a canonical dictionary")
        admitted = guarded.admit_guarded_reduction(source, certificate)
        return cls(source, json.loads(_canonical(certificate)), admitted)


@dataclass(frozen=True, slots=True)
class GuardedProgram:
    """All allowed Ground stages are admitted before the process starts."""
    stages: tuple[GroundStage, ...]
    fingerprint: str

    @classmethod
    def admit(cls, stages: tuple[tuple[Any, Mapping[str, Any]], ...]) -> "GuardedProgram":
        if type(stages) is not tuple or not 1 <= len(stages) <= 8:
            raise VGIRecoveryError("program must contain 1..8 certified stages")
        qualified = tuple(GroundStage.admit(source, cert) for source, cert in stages)
        guarded, _, _ = _runtime_modules()
        for a, b in zip(qualified, qualified[1:]):
            guarded.plan_migration(a.admitted, b.admitted)
        body = {"schema": PROGRAM_SCHEMA, "stages": [
            {"source": x.source.to_dict(), "certificate": x.certificate}
            for x in qualified
        ]}
        return cls(qualified, _sha(body))


@dataclass(frozen=True, slots=True)
class CheckpointSourceObservation:
    """Source bytes returned by a *receiver-owned*, checkpoint-keyed observer."""
    checkpoint_digest: str
    source_state: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class CheckpointProbeObservation:
    """Receiver-validated probe values from an authenticated E-CPU fabric hop.

    The receipt digest identifies the verified hop receipt; it is not a
    standalone signature or evidence of TLS identity when detached.
    """
    checkpoint_digest: str
    lineage_digest: str
    program_fingerprint: str
    from_stage: int
    to_stage: int
    old_coordinates: tuple[int, ...]
    probes: tuple[int, ...]
    source_peer_id: str
    source_host_id: str
    fabric_receipt_digest: str


# Both callbacks are installed by the receiver, never transported as code.
SourceObserver = Callable[[ComputationalTransitionContext], CheckpointSourceObservation]
ProbeObserver = Callable[[ComputationalTransitionContext, int, int, tuple[int, ...]], CheckpointProbeObservation]


class GuardedTransitionBackend:
    """Local deterministic VGI transition; M4 builds the CAS context."""

    def __init__(self, program: GuardedProgram, backend_fingerprint: str,
                 *, source_observer: SourceObserver | None = None,
                 probe_observer: ProbeObserver | None = None) -> None:
        if source_observer is not None and probe_observer is not None:
            raise VGIRecoveryError("choose exactly one source observation path")
        self.program = program
        self.backend_fingerprint = backend_fingerprint
        self.source_observer = source_observer
        self.probe_observer = probe_observer

    def _state(self, raw: bytes) -> dict[str, Any]:
        record = _decode(raw, MAX_STATE_BYTES, "state")
        _keys(record, {"schema", "program", "stage", "coordinates", "virtual_steps", "last_event"}, "state")
        if record["schema"] != STATE_SCHEMA or record["program"] != self.program.fingerprint:
            raise VGIRecoveryError("persisted state interpretation differs")
        i = _index(record["stage"], len(self.program.stages), "stage")
        q = self.program.stages[i].admitted
        x = record["coordinates"]
        if type(x) is not list or len(x) != q.dimension or any(type(v) is not int or not 0 <= v < q.modulus for v in x):
            raise VGIRecoveryError("invalid persisted reduced coordinates")
        _word(record["virtual_steps"])
        event = record["last_event"]
        if type(event) is not dict or event.get("kind") not in ("initial", "advance", "migrate", "jump"):
            raise VGIRecoveryError("invalid persisted event")
        guarded, _, _ = _runtime_modules()
        if event["kind"] == "advance":
            _keys(event, {"kind", "receipt", "predecessor_checkpoint", "predecessor_lineage"}, "advance event")
            check = guarded.verify_guarded_receipt(q, event["receipt"])
            if list(check["final"]) != x:
                raise VGIRecoveryError("recorded execution receipt differs from committed state")
        elif event["kind"] == "initial":
            _keys(event, {"kind"}, "initial event")
        elif event["kind"] == "migrate":
            if event.get("observer_authority") == "receiver-local-checkpoint-keyed":
                _keys(event, {"kind", "from_stage", "before", "predecessor_checkpoint", "predecessor_lineage",
                              "source_snapshot_sha256", "probes", "observer_authority"}, "migration event")
            authority = event.get("observer_authority")
            if authority not in ("receiver-local-checkpoint-keyed", "m3-fabric-probe-v1"):
                raise VGIRecoveryError("unsupported migration observation provenance")
            if authority == "m3-fabric-probe-v1":
                _keys(event, {"kind", "from_stage", "before", "predecessor_checkpoint",
                             "predecessor_lineage", "source_snapshot_sha256", "probes",
                             "observer_authority", "source_peer_id", "source_host_id",
                             "fabric_receipt_digest"}, "fabric migration event")
                if event["source_snapshot_sha256"] is not None:
                    raise VGIRecoveryError("fabric probe event must not contain source snapshot")
                if (type(event["source_peer_id"]) is not str or not event["source_peer_id"]
                    or type(event["source_host_id"]) is not str or not event["source_host_id"]):
                    raise VGIRecoveryError("fabric source host identity is missing")
                _require_digest(event["fabric_receipt_digest"], "fabric receipt")
            prior = _index(event["from_stage"], len(self.program.stages), "previous stage")
            if prior + 1 != i:
                raise VGIRecoveryError("migration stage changed unexpectedly")
            previous = self.program.stages[prior].admitted
            if type(event["before"]) is not list or type(event["probes"]) is not list:
                raise VGIRecoveryError("migration coordinates are not arrays")
            plan = guarded.plan_migration(previous, q)
            lifted = guarded.apply_migration(previous, q,
                tuple(event["before"]), tuple(event["probes"]), plan)
            if tuple(x) != lifted:
                raise VGIRecoveryError("migration proof does not reconstruct committed state")
            if authority == "receiver-local-checkpoint-keyed":
                _require_digest(event["source_snapshot_sha256"], "source snapshot")
        else:
            _keys(event, {"kind", "before", "symbol", "steps", "predecessor_checkpoint", "predecessor_lineage"}, "jump event")
            before = event["before"]
            if type(before) is not list or q.jump_invariant(tuple(before), event["symbol"], _word(event["steps"])) != tuple(x):
                raise VGIRecoveryError("jump proof does not reconstruct committed state")
        if event["kind"] != "initial":
            _require_digest(event["predecessor_checkpoint"], "checkpoint predecessor")
            _require_digest(event["predecessor_lineage"], "lineage predecessor")
        return record

    def inspect(self, state_bytes: bytes) -> dict[str, Any]:
        return self._state(state_bytes)

    def transition(self, state_bytes: bytes, input_bytes: bytes,
                   context: ComputationalTransitionContext) -> bytes:
        if context.interpretation_fingerprint != self.program.fingerprint:
            raise VGIRecoveryError("M4 context is not bound to the program")
        state = self._state(state_bytes)
        command = _decode(input_bytes, MAX_INPUT_BYTES, "transition")
        if command.get("schema") != INPUT_SCHEMA:
            raise VGIRecoveryError("input schema differs")
        idx = state["stage"]
        q = self.program.stages[idx].admitted
        guarded, _, _ = _runtime_modules()
        initial = tuple(state["coordinates"])
        event: dict[str, Any]
        if command.get("kind") == "advance":
            _keys(command, {"schema", "kind", "inputs"}, "advance request")
            inputs = command["inputs"]
            if type(inputs) is not list or not 1 <= len(inputs) <= MAX_QUANTUM_INPUTS or any(type(x) is not str for x in inputs):
                raise VGIRecoveryError("advance requires 1..128 symbolic inputs")
            receipt = guarded.run_guarded(q, initial, tuple(inputs))
            verified = guarded.verify_guarded_receipt(q, receipt)
            state["coordinates"] = list(verified["final"])
            state["virtual_steps"] = str(_word(state["virtual_steps"]) + len(inputs))
            event = {"kind": "advance", "receipt": receipt,
                     "predecessor_checkpoint": context.checkpoint_digest,
                     "predecessor_lineage": context.lineage_digest}
        elif command.get("kind") == "migrate":
            _keys(command, {"schema", "kind", "target"}, "migration request")
            target = _index(command["target"], len(self.program.stages), "migration target")
            if target != idx + 1:
                raise VGIRecoveryError("migration must advance exactly one admitted stage")
            new_stage = self.program.stages[target]
            new = new_stage.admitted
            plan = guarded.plan_migration(q, new)
            if self.probe_observer is not None:
                remote = self.probe_observer(context, idx, target, initial)
                if not isinstance(remote, CheckpointProbeObservation):
                    raise VGIRecoveryError("fabric observer returned no typed probe observation")
                if (remote.checkpoint_digest != context.checkpoint_digest
                    or remote.lineage_digest != context.lineage_digest
                    or remote.program_fingerprint != self.program.fingerprint
                    or remote.from_stage != idx or remote.to_stage != target
                    or remote.old_coordinates != initial):
                    raise VGIRecoveryError("remote probe belongs to another committed M3 state")
                if not remote.source_peer_id or not remote.source_host_id:
                    raise VGIRecoveryError("remote probe source identity is missing")
                _require_digest(remote.fabric_receipt_digest, "fabric receipt")
                probes = remote.probes
                lifted = guarded.apply_migration(q, new, initial, probes, plan)
                event = {"kind": "migrate", "from_stage": idx, "before": list(initial),
                         "predecessor_checkpoint": context.checkpoint_digest,
                         "predecessor_lineage": context.lineage_digest,
                         "source_snapshot_sha256": None, "probes": list(probes),
                         "observer_authority": "m3-fabric-probe-v1",
                         "source_peer_id": remote.source_peer_id,
                         "source_host_id": remote.source_host_id,
                         "fabric_receipt_digest": remote.fabric_receipt_digest}
            else:
                if self.source_observer is None:
                    raise VGIRecoveryError("receiver has not bound a source observer")
                observation = self.source_observer(context)
                if (not isinstance(observation, CheckpointSourceObservation)
                    or observation.checkpoint_digest != context.checkpoint_digest):
                    raise VGIRecoveryError("source observation does not belong to this M3 checkpoint")
                x = observation.source_state
                if type(x) is not tuple or len(x) != new.source_dimension or any(
                    type(v) is not int or not 0 <= v < new.modulus for v in x
                ):
                    raise VGIRecoveryError("invalid trusted source snapshot")
                if q.project(x) != initial:
                    raise VGIRecoveryError("source snapshot disagrees with committed reduced state")
                probes = guarded.observe_migration_probes(new_stage.source, x, new, plan)
                lifted = guarded.apply_migration(q, new, initial, probes, plan)
                if lifted != new.project(x):
                    raise VGIRecoveryError("migration does not preserve source observation")
                event = {"kind": "migrate", "from_stage": idx, "before": list(initial),
                         "predecessor_checkpoint": context.checkpoint_digest,
                         "predecessor_lineage": context.lineage_digest,
                         "source_snapshot_sha256": _sha(list(x)), "probes": list(probes),
                         "observer_authority": "receiver-local-checkpoint-keyed"}
            state["stage"] = target
            state["coordinates"] = list(lifted)
        elif command.get("kind") == "jump":
            _keys(command, {"schema", "kind", "symbol", "steps"}, "jump request")
            if type(command["symbol"]) is not str:
                raise VGIRecoveryError("jump input must be a symbolic label")
            steps = _word(command["steps"])
            final = q.jump_invariant(initial, command["symbol"], steps)
            state["coordinates"] = list(final)
            state["virtual_steps"] = str(_word(state["virtual_steps"]) + steps)
            event = {"kind": "jump", "before": list(initial), "symbol": command["symbol"], "steps": command["steps"],
                     "predecessor_checkpoint": context.checkpoint_digest,
                     "predecessor_lineage": context.lineage_digest}
        else:
            raise VGIRecoveryError("operation is not in the admitted command set")
        state["last_event"] = event
        result = _canonical(state)
        if len(result) > MAX_STATE_BYTES:
            raise VGIRecoveryError("candidate state exceeds M1 bound")
        return result


class VGIDurableGroundSession:
    """High-level wrapper around E-CPU's existing quorum-anchored M4 transition API."""

    def __init__(self, session_store: ComputationalSessionStore,
                 program: GuardedProgram, *,
                 source_observer: SourceObserver | None = None,
                 probe_observer: ProbeObserver | None = None) -> None:
        if not isinstance(session_store, ComputationalSessionStore):
            raise TypeError("expected ComputationalSessionStore")
        if session_store.state_schema_id != STATE_SCHEMA:
            raise VGIRecoveryError("M3 session schema differs from guarded reduced state")
        self.store = session_store
        self.program = program
        self.backend = GuardedTransitionBackend(program, session_store.backend_fingerprint,
                                                source_observer=source_observer,
                                                probe_observer=probe_observer)
        self.contract = ComputationalTransitionContract(
            transition_id=TRANSITION_ID, state_schema_id=STATE_SCHEMA,
            input_schema_id=INPUT_SCHEMA,
            interpretation_fingerprint=program.fingerprint,
            backend_fingerprint=session_store.backend_fingerprint,
            max_input_bytes=MAX_INPUT_BYTES, max_state_bytes=MAX_STATE_BYTES,
            deterministic=True, effect_mode="pure",
        )
        self.adapter = ComputationalSessionTransitionAdapter(self.store, self.contract, self.backend)

    def initialize(self, initial_source_state: tuple[int, ...]) -> ComputationalSessionSnapshot:
        q = self.program.stages[0].admitted
        coordinates = q.project(initial_source_state)
        state = {"schema": STATE_SCHEMA, "program": self.program.fingerprint,
                 "stage": 0, "coordinates": list(coordinates), "virtual_steps": "0",
                 "last_event": {"kind": "initial"}}
        return self.store.create_session(_canonical(state))

    def _check_snapshot(self, snapshot: ComputationalSessionSnapshot) -> None:
        """Cross-bind the saved mathematical receipt to the actual M3 predecessor."""
        state = self.backend.inspect(snapshot.state_bytes)
        event = state["last_event"]
        if event["kind"] != "initial" and (
            event["predecessor_checkpoint"] != snapshot.checkpoint.predecessor_checkpoint_digest
            or event["predecessor_lineage"] != snapshot.checkpoint.predecessor_lineage_digest
        ):
            raise VGIRecoveryError("Ground event does not match committed M3 predecessor")

    def load(self) -> ComputationalSessionSnapshot:
        snapshot = self.store.load_latest()
        self._check_snapshot(snapshot)
        return snapshot

    def inspect(self) -> dict[str, Any]:
        return self.backend.inspect(self.load().state_bytes)

    def advance(self, inputs: tuple[str, ...], *, operation_id: str,
                expected_revision: int, expected_checkpoint_digest: str) -> ComputationalSessionSnapshot:
        return self._apply({"schema": INPUT_SCHEMA, "kind": "advance", "inputs": list(inputs)},
                           operation_id, expected_revision, expected_checkpoint_digest)

    def migrate(self, *, operation_id: str, target: int,
                expected_revision: int, expected_checkpoint_digest: str) -> ComputationalSessionSnapshot:
        return self._apply({"schema": INPUT_SCHEMA, "kind": "migrate", "target": target},
                           operation_id, expected_revision, expected_checkpoint_digest)

    def jump(self, *, operation_id: str, symbol: str, steps: int,
             expected_revision: int, expected_checkpoint_digest: str) -> ComputationalSessionSnapshot:
        if type(steps) is not int or steps < 0:
            raise VGIRecoveryError("macro steps must be nonnegative integer")
        return self._apply({"schema": INPUT_SCHEMA, "kind": "jump", "symbol": symbol, "steps": str(steps)},
                           operation_id, expected_revision, expected_checkpoint_digest)

    def _apply(self, command: dict[str, Any], operation_id: str,
               expected_revision: int, expected_checkpoint_digest: str) -> ComputationalSessionSnapshot:
        return self.adapter.apply(_canonical(command), operation_id=operation_id,
                                  expected_revision=expected_revision,
                                  expected_checkpoint_digest=expected_checkpoint_digest)

    def export_latest(self) -> dict[str, Any]:
        self.load()
        return self.store.export_latest()

    def restore_export(self, record: Mapping[str, Any]) -> ComputationalSessionSnapshot:
        restored = self.store.restore_export(record)
        self._check_snapshot(restored)
        return restored
