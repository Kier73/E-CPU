"""Source-resident checkpoint-bound VGI probes over E-CPU's authenticated fabric.

The source host executes the existing receiver-local pure Virtual Layer
operator; only the missing probe coordinates cross the authenticated E-CPU
peer forwarding path. All authority and code stay local to the host.
Content digests are evidence of integrity, not signatures.
"""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Callable, Mapping

from .computational_fabric import ComputationalFabricDirectory
from .computational_fabric_forwarding import (
    ComputationalFabricForwardingClient, ComputationalFabricForwardingEnvelope,
    ComputationalFabricHopReceipt,
)
from .computational_transition import ComputationalTransitionContext
from .vgi_guarded_recovery import (
    CheckpointProbeObservation, CheckpointSourceObservation, GuardedProgram,
    VGIDurableGroundSession, VGIRecoveryError,
)
from .vgi_guarded_runtime import _runtime_modules
from .virtual_layer import OperatorRegistry, OperatorSpec, VirtualLayerWorkload

SOURCE_PROBE_OPERATOR = "vgi.guarded.source_probe"
QUERY_SCHEMA = "mailcpu.vgi.fabric.checkpoint-probe-query.v1"
RESULT_SCHEMA = "mailcpu.vgi.fabric.checkpoint-probe-result.v1"
MAX_PROBE_BYTES = 16_384


def _plain(x: Any) -> Any:
    if isinstance(x, Mapping):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    return x


def _canonical(x: Any) -> bytes:
    try:
        return json.dumps(_plain(x), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise VGIRecoveryError("fabric probe is not finite JSON") from exc


def _sha(x: Any) -> str:
    return sha256(_canonical(x)).hexdigest()


def _digest(x: Any, label: str) -> str:
    if type(x) is not str or len(x) != 64 or any(k not in "0123456789abcdef" for k in x):
        raise VGIRecoveryError(f"invalid {label} digest")
    return x


def _fields(x: Any, fields: set[str], label: str) -> dict[str, Any]:
    record = _plain(x)
    if type(record) is not dict or set(record) != fields:
        raise VGIRecoveryError(f"invalid {label} fields")
    if len(_canonical(record)) > MAX_PROBE_BYTES:
        raise VGIRecoveryError(f"{label} exceeds frame bound")
    return record


_QUERY_FIELDS = {
    "schema", "session_id", "revision", "checkpoint_digest", "lineage_digest",
    "artifact_manifest_digest", "program_fingerprint", "from_stage", "to_stage",
    "old_coordinates", "probe_basis_digest", "requester_peer_id", "operation_id",
    "logical_time", "transition_input_digest",
}
_RESULT_FIELDS = {
    "schema", "query_digest", "session_id", "revision", "checkpoint_digest",
    "lineage_digest", "program_fingerprint", "from_stage", "to_stage",
    "old_coordinates", "probe_basis_digest", "source_peer_id", "source_host_id",
    "probe_values", "result_digest",
}


def make_probe_query(context: ComputationalTransitionContext, program: GuardedProgram,
                     from_stage: int, to_stage: int, old_coordinates: tuple[int, ...],
                     requester_peer_id: str) -> dict[str, Any]:
    """Name the exact committed source and only the needed missing rows."""
    guarded, _, _ = _runtime_modules()
    if (type(from_stage) is not int or type(to_stage) is not int
        or not 0 <= from_stage < len(program.stages) or to_stage != from_stage + 1
        or to_stage >= len(program.stages)):
        raise VGIRecoveryError("probe stage is not the next admitted Ground")
    previous = program.stages[from_stage].admitted
    new = program.stages[to_stage].admitted
    plan = guarded.plan_migration(previous, new)
    if type(old_coordinates) is not tuple or len(old_coordinates) != previous.dimension or any(
        type(x) is not int or not 0 <= x < previous.modulus for x in old_coordinates
    ):
        raise VGIRecoveryError("probe query coordinates are not an admitted quotient state")
    if type(requester_peer_id) is not str or not requester_peer_id or len(requester_peer_id) > 100:
        raise VGIRecoveryError("invalid requesting fabric peer")
    if context.interpretation_fingerprint != program.fingerprint:
        raise VGIRecoveryError("probe query is outside the admitted interpretation")
    return {
        "schema": QUERY_SCHEMA, "session_id": context.session_id,
        "revision": context.revision, "checkpoint_digest": context.checkpoint_digest,
        "lineage_digest": context.lineage_digest,
        "artifact_manifest_digest": context.artifact_manifest_digest,
        "program_fingerprint": program.fingerprint,
        "from_stage": from_stage, "to_stage": to_stage,
        "old_coordinates": list(old_coordinates),
        "probe_basis_digest": _sha([list(row) for row in plan.probe_rows]),
        "requester_peer_id": requester_peer_id, "operation_id": context.operation_id,
        "logical_time": context.logical_time,
        "transition_input_digest": context.input_digest,
    }


class VGISourceProbeOperator:
    """Source host: verify M3 quorum head before observing locally resident state."""

    def __init__(self, session: VGIDurableGroundSession, *, source_peer_id: str,
                 source_host_id: str, allowed_requester_peer_id: str,
                 source_observer: Callable[[str], CheckpointSourceObservation]):
        if not isinstance(session, VGIDurableGroundSession):
            raise TypeError("source requires a real VGI M3 session")
        for value in (source_peer_id, source_host_id, allowed_requester_peer_id):
            if type(value) is not str or not value or len(value) > 100:
                raise VGIRecoveryError("source peer, host and requester identities must be explicit")
        if not callable(source_observer):
            raise TypeError("source observer must be locally installed")
        self.session = session
        self.source_peer_id = source_peer_id
        self.source_host_id = source_host_id
        self.allowed_requester_peer_id = allowed_requester_peer_id
        self.source_observer = source_observer
        self.spec = OperatorSpec(
            operator_id=SOURCE_PROBE_OPERATOR, version=1,
            description="Source-resident M3 verified minimal VGI migration probe",
            input_kind="object", output_kind="object", substrates=("cpu",),
            required_rights=frozenset({"compute"}), base_energy=16, energy_per_byte=1,
            max_input_bytes=MAX_PROBE_BYTES, max_output_bytes=MAX_PROBE_BYTES,
            deterministic=True, effect_mode="pure",
        )

    def register(self, registry: OperatorRegistry) -> OperatorSpec:
        registry.register(self.spec, self.execute)
        return self.spec

    def execute(self, value: Any, workload: VirtualLayerWorkload) -> dict[str, Any]:
        query = _fields(value, _QUERY_FIELDS, "source probe query")
        if (not isinstance(workload, VirtualLayerWorkload)
            or _plain(workload.input_value) != query
            or workload.operator_ref(SOURCE_PROBE_OPERATOR).version != 1):
            raise VGIRecoveryError("source probe must arrive as the original typed workload")
        if query["schema"] != QUERY_SCHEMA or query["requester_peer_id"] != self.allowed_requester_peer_id:
            raise VGIRecoveryError("source probe requester or schema differs")
        for k in ("checkpoint_digest", "lineage_digest", "artifact_manifest_digest",
                  "program_fingerprint", "probe_basis_digest", "transition_input_digest"):
            _digest(query[k], k)
        if (type(query["revision"]) is not int or query["revision"] < 1
            or type(query["logical_time"]) is not int or query["logical_time"] < 1
            or type(query["operation_id"]) is not str or not query["operation_id"]):
            raise VGIRecoveryError("source query revision/operation fields differ")
        snapshot = self.session.load()
        head = snapshot.checkpoint
        state = self.session.backend.inspect(snapshot.state_bytes)
        if (query["session_id"] != head.session_id
            or query["revision"] != snapshot.revision
            or query["checkpoint_digest"] != snapshot.checkpoint_digest
            or query["lineage_digest"] != snapshot.lineage_manifest.digest
            or query["artifact_manifest_digest"] != head.artifact_manifest_digest
            or query["program_fingerprint"] != self.session.program.fingerprint
            or query["from_stage"] != state["stage"]
            or query["to_stage"] != state["stage"] + 1
            or query["old_coordinates"] != state["coordinates"]):
            raise VGIRecoveryError("source M3 checkpoint does not match requested observation")
        program = self.session.program
        if query["to_stage"] >= len(program.stages):
            raise VGIRecoveryError("source probe requests unavailable Ground")
        guarded, _, _ = _runtime_modules()
        old = program.stages[state["stage"]].admitted
        new_stage = program.stages[state["stage"] + 1]
        plan = guarded.plan_migration(old, new_stage.admitted)
        if query["probe_basis_digest"] != _sha([list(row) for row in plan.probe_rows]):
            raise VGIRecoveryError("requested probe basis differs from source's admitted Ground")
        observation = self.source_observer(snapshot.checkpoint_digest)
        if (not isinstance(observation, CheckpointSourceObservation)
            or observation.checkpoint_digest != snapshot.checkpoint_digest):
            raise VGIRecoveryError("local source observation is not pinned to M3 head")
        x = observation.source_state
        if (type(x) is not tuple or len(x) != new_stage.admitted.source_dimension
            or any(type(v) is not int or not 0 <= v < new_stage.admitted.modulus for v in x)
            or old.project(x) != tuple(state["coordinates"])):
            raise VGIRecoveryError("local source observation contradicts the committed quotient")
        probes = guarded.observe_migration_probes(new_stage.source, x, new_stage.admitted, plan)
        result = {
            "schema": RESULT_SCHEMA, "query_digest": _sha(query),
            "session_id": head.session_id, "revision": snapshot.revision,
            "checkpoint_digest": snapshot.checkpoint_digest,
            "lineage_digest": snapshot.lineage_manifest.digest,
            "program_fingerprint": program.fingerprint,
            "from_stage": state["stage"], "to_stage": state["stage"] + 1,
            "old_coordinates": list(state["coordinates"]),
            "probe_basis_digest": query["probe_basis_digest"],
            "source_peer_id": self.source_peer_id, "source_host_id": self.source_host_id,
            "probe_values": list(probes),
        }
        result["result_digest"] = _sha(result)
        if len(_canonical(result)) > MAX_PROBE_BYTES:
            raise VGIRecoveryError("source probe result exceeds bound")
        return result


def verify_probe_result(query: Mapping[str, Any], result: Any, program: GuardedProgram,
                        *, source_peer_id: str, source_host_id: str) -> tuple[int, ...]:
    """Check meaning; the caller MUST also verify the authenticated fabric hop."""
    expected = _fields(query, _QUERY_FIELDS, "probe query")
    response = _fields(result, _RESULT_FIELDS, "probe result")
    if response["schema"] != RESULT_SCHEMA or response["result_digest"] != _sha({
        k: v for k, v in response.items() if k != "result_digest"
    }):
        raise VGIRecoveryError("probe result content digest disagrees")
    if (response["query_digest"] != _sha(expected)
        or response["session_id"] != expected["session_id"]
        or response["revision"] != expected["revision"]
        or response["checkpoint_digest"] != expected["checkpoint_digest"]
        or response["lineage_digest"] != expected["lineage_digest"]
        or response["program_fingerprint"] != program.fingerprint
        or response["from_stage"] != expected["from_stage"]
        or response["to_stage"] != expected["to_stage"]
        or response["old_coordinates"] != expected["old_coordinates"]
        or response["probe_basis_digest"] != expected["probe_basis_digest"]
        or response["source_peer_id"] != source_peer_id
        or response["source_host_id"] != source_host_id):
        raise VGIRecoveryError("source probe result belongs to a different M3 request or host")
    guarded, _, _ = _runtime_modules()
    old = program.stages[expected["from_stage"]].admitted
    new = program.stages[expected["to_stage"]].admitted
    plan = guarded.plan_migration(old, new)
    if expected["probe_basis_digest"] != _sha([list(row) for row in plan.probe_rows]):
        raise VGIRecoveryError("request probe basis is not admitted")
    values = response["probe_values"]
    if (type(values) is not list or len(values) != plan.probe_count
        or any(type(v) is not int or not 0 <= v < old.modulus for v in values)):
        raise VGIRecoveryError("source probe values are outside the exact required coordinates")
    guarded.apply_migration(old, new, tuple(expected["old_coordinates"]), tuple(values), plan)
    return tuple(values)


class VGIFabricForwardedProbeObserver:
    """Destination: issue exact query over a pre-admitted direct E-CPU mTLS hop.

    The trusted envelope builder selects the source operator through the
    normal E-CPU route and optional execution-claim machinery. It is locally
    installed and never supplied through a remote workload.
    """

    def __init__(self, program: GuardedProgram, *,
                 client: ComputationalFabricForwardingClient,
                 directory: ComputationalFabricDirectory,
                 source_peer_id: str, source_host_id: str,
                 envelope_builder: Callable[[dict[str, Any]], ComputationalFabricForwardingEnvelope]):
        if not isinstance(client, ComputationalFabricForwardingClient):
            raise TypeError("observer requires an authenticated E-CPU forwarding client")
        if not isinstance(directory, ComputationalFabricDirectory):
            raise TypeError("observer requires an E-CPU fabric directory")
        if client.local_peer_id != directory.local_peer_id or client.remote_endpoint.peer_id != source_peer_id:
            raise VGIRecoveryError("probe client is not the direct mTLS peer owning the source")
        self.program = program
        self.client = client
        self.directory = directory
        self.source_peer_id = source_peer_id
        self.source_host_id = source_host_id
        self.envelope_builder = envelope_builder

    def __call__(self, context: ComputationalTransitionContext, from_stage: int,
                 to_stage: int, old_coordinates: tuple[int, ...]) -> CheckpointProbeObservation:
        query = make_probe_query(context, self.program, from_stage, to_stage,
                                 old_coordinates, self.client.local_peer_id)
        envelope = self.envelope_builder(query)
        if not isinstance(envelope, ComputationalFabricForwardingEnvelope):
            raise VGIRecoveryError("local route builder did not produce a typed fabric envelope")
        if (envelope.address.operator_id != SOURCE_PROBE_OPERATOR
            or _plain(envelope.address.workload.input_value) != query
            or envelope.address.program_fingerprint != self.program.fingerprint
            or envelope.route.peer_path != (self.client.local_peer_id, self.source_peer_id)
            or envelope.route.target_host.host_id != self.source_host_id
            or envelope.route.target_host.peer_id != self.source_peer_id
            or envelope.origin_peer_id != self.client.local_peer_id
            or envelope.origin_channel != self.client.origin_channel
            or envelope.address.workload.logical_time != context.logical_time):
            raise VGIRecoveryError("source route changed the checkpoint query, host or authenticated peer")
        receipt = self.client.forward(envelope, self.directory)
        if (not isinstance(receipt, ComputationalFabricHopReceipt)
            or not receipt.succeeded or receipt.peer_id != self.source_peer_id
            or receipt.next_peer_id is not None
            or receipt.operation_digest != envelope.operation_digest
            or receipt.envelope_digest != envelope.advance().digest):
            raise VGIRecoveryError("fabric source did not return a correlated successful terminal receipt")
        terminal = receipt.terminal_execution
        if (not isinstance(terminal, Mapping) or terminal.get("accepted") is not True
            or terminal.get("executed") is not True):
            raise VGIRecoveryError("fabric terminal Hypervisor did not execute the source probe")
        try:
            result = terminal["execution"]["effect"]["result"]
        except (TypeError, KeyError) as exc:
            raise VGIRecoveryError("terminal fabric receipt lacks the VGI operator output") from exc
        probes = verify_probe_result(query, result, self.program,
                                     source_peer_id=self.source_peer_id,
                                     source_host_id=self.source_host_id)
        return CheckpointProbeObservation(
            context.checkpoint_digest, context.lineage_digest, self.program.fingerprint,
            from_stage, to_stage, old_coordinates, probes,
            self.source_peer_id, self.source_host_id, receipt.digest,
        )
