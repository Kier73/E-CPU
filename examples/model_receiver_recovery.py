"""USM-005: recover a model-operated Ground after receiver death before ACK.

This reuses E-CPU's real mTLS SocketTransport, ReliableChannel snapshots,
StructuralMemoryRegistry snapshots and quorum-backed RecoveryStateManifest.
The model host remains alive while the receiver is hard-killed and replaced.
Test anchor ledgers are three durable files on one machine: quorum protocol
is exercised, but the anchors are not independent failure domains.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Mapping

from examples.model_authenticated_fabric import (
    CONTEXT, COORDINATE, MODEL_DNS, MODEL_ENDPOINT, RECEIVER_DNS,
    RECEIVER_ENDPOINT, CALL_CHANNEL, DONE_SCHEMA, ModelFabricRefused,
    _ack, _channels, _receive, model_tls_context, receiver_session,
    server_tls_context,
)
from examples.model_ground_os import GroundPolicyModel, _digest, sample_stream
from examples.model_system_calls import GroundSystemCallSession, verify_system_call_trace
from examples.model_system_worker import decide
from examples.run_model_authenticated_experiment import ephemeral_certificates
from mailcpu.mtls_transport import accept_mutual_tls, connect_mutual_tls
from mailcpu.recovery_lineage import (
    RecoveryLineageAuthority, RecoveryLineageCoordinator, RecoveryStateManifest,
)
from mailcpu.reliability import ReliableChannel
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.socket_transport import SocketTransport
from mailcpu.structural_memory import StructuralMemoryRegistry

SCHEMA = "mailcpu.usm005.model-recovery-checkpoint.v1"
PROTOCOL = "mailcpu.model-recovery.v1"
MACHINE = "model-ground-recovery"
GENESIS = hashlib.sha256(b"mailcpu-usm005-lineage-genesis-v1").hexdigest()
EXIT_AFTER_EFFECT_BEFORE_ACK = 86
MODEL_ARTIFACT = "high-request"
STREAM_ID = "model-survived-receiver"
SESSION_ID = "session-model-receiver-restart"


class ModelRecoveryRefused(RuntimeError):
    """A checkpoint or replay is not admissible to the restarted receiver."""


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    """Use one canonical state representation for exact manifest content identity."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _persist(path: Path, data: bytes) -> None:
    """Publish durable all-or-nothing state bytes within one filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".usm005-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
        # Linux runner: the rename is durable after its parent directory is fsynced.
        directory = os.open(str(path.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class ModelRecoveryStore:
    """Fixed-membership durable checkpoint roots with a quorum high-water mark."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.membership = SeedCommitMembership(
            MACHINE, 1, ("A", "B", "C"), "A", 1, GENESIS,
        )
        authorities = {
            member: RecoveryLineageAuthority(
                self.membership, member, str(self.root / f"anchor-{member}.jsonl")
            )
            for member in self.membership.member_ids
        }
        self.lineage = RecoveryLineageCoordinator(self.membership, authorities)

    def save(self, state: Mapping[str, Any], cut: str) -> RecoveryStateManifest:
        """Seal the exact state bytes before the receiver may acknowledge it."""
        _validate_state(state)
        generation, predecessor = self.lineage.high_water()
        generation += 1
        raw = _canonical_bytes(state)
        manifest = RecoveryStateManifest(
            machine_id=self.membership.system_id,
            incarnation=self.membership.incarnation,
            owner_id=self.membership.owner_id,
            owner_term=self.membership.owner_term,
            membership_digest=self.membership.digest,
            generation=generation,
            predecessor_digest=predecessor,
            state_digest=hashlib.sha256(raw).hexdigest(),
            capture_cut=cut,
        )
        _persist(self.root / f"checkpoint-{generation}.json", raw)
        _persist(self.root / f"manifest-{generation}.json",
                 _canonical_bytes(manifest.snapshot()))
        self.lineage.seal(manifest)
        self.lineage.verify_state(manifest)
        return manifest

    def load(self, generation: int | None = None) -> tuple[dict[str, Any], RecoveryStateManifest]:
        """Reject tampered, unsealed, conflicting, or superseded checkpoints."""
        current, _ = self.lineage.high_water()
        if current == 0:
            raise ModelRecoveryRefused("no quorum-anchored recovery state exists")
        selected = current if generation is None else generation
        try:
            manifest = RecoveryStateManifest.from_snapshot(json.loads(
                (self.root / f"manifest-{selected}.json").read_text(encoding="utf-8")
            ))
            raw = (self.root / f"checkpoint-{selected}.json").read_bytes()
            manifest.verify_payload(raw)
            self.lineage.verify_state(manifest)
            state = json.loads(raw)
            _validate_state(state)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ModelRecoveryRefused("quorum recovery state validation failed") from exc
        return state, manifest


def _capture(
    session: GroundSystemCallSession,
    incoming: ReliableChannel,
    outgoing: ReliableChannel,
    reply: Mapping[str, Any],
    result: Mapping[str, Any],
    model: GroundPolicyModel,
) -> dict[str, Any]:
    """Freeze one post-semantic-commit, pre-transport-ACK receiver cut."""
    return {
        "schema": SCHEMA,
        "model": model.snapshot(),
        "session_id": session.session_id,
        "stream_id": session.stream_id,
        "observations": list(session.observations),
        "context": session.context,
        "training_count": session.training_count,
        "coordinate": session.coordinate,
        "allowed_ops": sorted(session.allowed_ops),
        "phase": session.phase,
        "head": session.head,
        "events": session.events,
        "ground_revision": session.ground_revision,
        "ground_digest": session.ground_digest,
        "registry": session.registry.snapshot(),
        "outgoing_channel": outgoing.snapshot(),
        "incoming_channel": incoming.snapshot(),
        "committed_reply": dict(reply),
        "committed_result": dict(result),
    }


def _validate_state(payload: Any) -> None:
    """Check receiver checkpoint identity, exact operation chain and Ground head."""
    expected = {
        "schema", "model", "session_id", "stream_id", "observations", "context",
        "training_count", "coordinate", "allowed_ops", "phase", "head", "events",
        "ground_revision", "ground_digest", "registry", "outgoing_channel",
        "incoming_channel", "committed_reply", "committed_result",
    }
    if not isinstance(payload, dict) or set(payload) != expected or payload["schema"] != SCHEMA:
        raise ModelRecoveryRefused("invalid receiver checkpoint schema")
    model = GroundPolicyModel.from_snapshot(payload["model"])
    if (payload["session_id"] != SESSION_ID
            or payload["stream_id"] != STREAM_ID
            or payload["coordinate"] != COORDINATE
            or payload["training_count"] != 24
            or payload["context"] != CONTEXT
            or payload["observations"] != list(sample_stream("affine", 201))
            or payload["allowed_ops"] != ["observe", "propose", "read"]):
        raise ModelRecoveryRefused("checkpoint changed receiver-owned intention or source")
    if model.digest != payload["committed_reply"].get("model_digest"):
        raise ModelRecoveryRefused("checkpoint model identity is inconsistent")
    events = payload["events"]
    if (payload["phase"] != "complete" or not isinstance(events, list)
            or len(events) != 3 or events[-1]["call"]["op"] != "read"):
        raise ModelRecoveryRefused("checkpoint is not at the claimed effect-commit cut")
    if (events[-1]["call"] != payload["committed_reply"].get("call")
            or events[-1]["output"] != payload["committed_result"]):
        raise ModelRecoveryRefused("checkpoint's accepted result is not the committed event")
    trace = {
        "schema": "mailcpu.model-syscall-trace.v1",
        "session_id": payload["session_id"], "stream_id": payload["stream_id"],
        "observation_digest": _digest(payload["observations"]),
        "training_count": payload["training_count"],
        "requested_coordinate": payload["coordinate"],
        "phase": payload["phase"], "events": events, "head": payload["head"],
    }
    trace["trace_digest"] = _digest(trace)
    if not verify_system_call_trace(trace):
        raise ModelRecoveryRefused("checkpoint operation journal cannot be reconstructed")
    if (events[-1]["output"].get("ground_digest") != payload["ground_digest"]
            or payload["ground_revision"] != 1):
        raise ModelRecoveryRefused("checkpoint Ground revision disagrees with last read")
    if (payload["incoming_channel"].get("channel") != CALL_CHANNEL
            or payload["incoming_channel"].get("next_receive_sequence") not in (3, 4)
            or payload["outgoing_channel"].get("next_sequence") != 4):
        raise ModelRecoveryRefused("checkpoint does not preserve the unacknowledged read cut")


def _restore(state: dict[str, Any]) -> GroundSystemCallSession:
    """Reconstruct registry + session and reject a semantic identity mismatch."""
    registry = StructuralMemoryRegistry.from_snapshot(
        state["registry"],
        admission_policy=lambda proposal: (
            proposal.spec.domain == "model-operated-observed-orbit"
            and proposal.spec.context == CONTEXT
        ),
    )
    session = GroundSystemCallSession(
        registry=registry, session_id=state["session_id"],
        stream_id=state["stream_id"], observations=state["observations"],
        coordinate=state["coordinate"], training_count=state["training_count"],
        context=state["context"], allowed_ops=frozenset(state["allowed_ops"]),
    )
    session.events = state["events"]
    session.phase = state["phase"]
    session.head = state["head"]
    session.ground_revision = state["ground_revision"]
    session.ground_digest = state["ground_digest"]
    version = registry.version_for_revision(STREAM_ID, state["ground_revision"])
    if version.spec.digest != state["ground_digest"]:
        raise ModelRecoveryRefused("restored E-CPU registry disagrees with session Ground")
    if not verify_system_call_trace(session.trace()):
        raise ModelRecoveryRefused("restored session trace is invalid")
    return session


def receiver(root: Path, *, restore: bool) -> int:
    """Serve one process incarnation; first hard-crashes after read commit."""
    keys = _paths(root)
    store = ModelRecoveryStore(root / "checkpoint")
    listener = SocketTransport.listen("127.0.0.1", 0)
    transport = None
    try:
        print(json.dumps({"ready_port": listener.getsockname()[1],
                          "incarnation": 2 if restore else 1}), flush=True)
        transport = accept_mutual_tls(
            listener, RECEIVER_ENDPOINT, MODEL_ENDPOINT,
            server_tls_context(keys["receiver_cert"], keys["receiver_key"], keys["ca"]),
            expected_peer_dns=MODEL_DNS,
        )
        if not restore:
            model = GroundPolicyModel(bias=30.0)

            def commit_cut(
                session: GroundSystemCallSession, incoming: ReliableChannel,
                outgoing: ReliableChannel, reply: Mapping[str, Any],
                result: Mapping[str, Any],
            ) -> None:
                if reply["call"]["op"] != "read":
                    return
                # Durable Ground + model journal + channel cut, quorum sealed,
                # then hard-kill *inside* ReliableChannel.receive(commit).
                state = _capture(session, incoming, outgoing, reply, result, model)
                store.save(state, "after_ground_read_commit_before_transport_ack")
                os._exit(EXIT_AFTER_EFFECT_BEFORE_ACK)

            receiver_session(
                transport, model=model, observations=sample_stream("affine", 201),
                session_id=SESSION_ID, stream_id=STREAM_ID,
                after_commit=commit_cut,
            )
            raise ModelRecoveryRefused("first receiver unexpectedly survived the crash cut")
        state, before = store.load()
        if state["incoming_channel"]["next_receive_sequence"] != 3:
            raise ModelRecoveryRefused("first receiver checkpoint already acknowledged the lost read")
        session = _restore(state)
        outbound = ReliableChannel.from_snapshot(state["outgoing_channel"], transport)
        incoming = ReliableChannel.from_snapshot(state["incoming_channel"], transport)
        # Resend the exact unanswered stage prompt so the model can ACK
        # its old receive sequence on the replacement TLS connection.
        pending_prompts = outbound.pending_sequences()
        if pending_prompts:
            for sequence in pending_prompts:
                outbound.retransmit(sequence)
        semantic_reentries = 0
        replayed = []
        def replay_commit(sequence: int, reply: Any) -> None:
            nonlocal semantic_reentries
            if (sequence != 3
                    or _digest(reply) != _digest(state["committed_reply"])
                    or reply["call"] != session.events[-1]["call"]):
                raise ModelRecoveryRefused("retransmission is not the committed semantic operation")
            # Explicitly no session.apply() and no registry navigation:
            # all the semantic effects are already in the restored Ground.
            replayed.append(session.events[-1]["output"])
        delivered_seq, _ = _receive(incoming, outbound, commit=replay_commit)
        if delivered_seq != 3 or len(replayed) != 1:
            raise ModelRecoveryRefused("committed model operation was not replayed")
        next_state = _capture(
            session, incoming, outbound,
            state["committed_reply"], state["committed_result"],
            GroundPolicyModel.from_snapshot(state["model"]),
        )
        after = store.save(next_state, "after_ack_replay_without_semantic_reentry")
        done = {
            "kind": DONE_SCHEMA, "session_id": session.session_id,
            "trace_digest": session.trace()["trace_digest"], "phase": session.phase,
            "value": replayed[0]["value"],
            "read_receipt_id": replayed[0]["read_receipt_id"],
            "ground_digest": session.ground_digest,
        }
        outbound.send(done)
        _ack(outbound)
        report = {
            "schema": "mailcpu.usm005.receiver-recovery-result.v1",
            "status": session.phase,
            "replayed_request_sequence": delivered_seq,
            "semantic_reentries": semantic_reentries,
            "events": len(session.events),
            "ground_digest": session.ground_digest,
            "ground_revision": session.ground_revision,
            "read_receipt_id": replayed[0]["read_receipt_id"],
            "value": replayed[0]["value"],
            "trace_digest": session.trace()["trace_digest"],
            "first_quorum_generation": before.generation,
            "latest_quorum_generation": after.generation,
            "receiver_process": os.getpid(),
        }
        (root / "recovered-report.json").write_text(
            json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        return 0
    finally:
        if transport is not None and not transport.closed:
            transport.close()
        listener.close()


def _paths(root: Path) -> dict[str, Path]:
    """Resolve only known local testing certificate filenames."""
    return {k: root / name for k, name in (
        ("ca", "ca.pem"), ("receiver_cert", "receiver.pem"),
        ("receiver_key", "receiver.key"), ("model_cert", "model.pem"),
        ("model_key", "model.key"),
    )}


def _spawn(root: Path, restore: bool) -> tuple[subprocess.Popen[str], int]:
    """Launch a fresh receiver process and read its exact bound socket port."""
    child = subprocess.Popen(
        (sys.executable, "-m", "examples.model_receiver_recovery", "receiver",
         "--root", str(root)) + (("--restore",) if restore else ()),
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if child.stdout is None:
        child.kill()
        raise ModelRecoveryRefused("receiver did not expose a ready stream")
    line = child.stdout.readline()
    try:
        record = json.loads(line)
        port = record["ready_port"]
        if type(port) is not int or port <= 0:
            raise ValueError("invalid receiver port")
    except (ValueError, TypeError, KeyError) as exc:
        child.kill()
        child.communicate(timeout=5)
        raise ModelRecoveryRefused("receiver process failed to publish its listener") from exc
    return child, port


def run_demo(root: Path) -> dict[str, Any]:
    """Prove one model host survives a hard receiver kill and resumes by TLS."""
    root.mkdir(parents=True, exist_ok=True)
    # Same-model process throughout this function, never restarted.
    temporary = root / "certificates"
    temporary.mkdir(exist_ok=True)
    keys = ephemeral_certificates(temporary)
    for name, key in keys.items():
        target = _paths(root).get(name)
        if target is not None:
            target.write_bytes(key.read_bytes())
    cert_paths = _paths(root)
    first = replacement = None
    first_transport = second_transport = None
    try:
        first, port = _spawn(root, False)
        first_transport = connect_mutual_tls(
            "127.0.0.1", port, MODEL_ENDPOINT, RECEIVER_ENDPOINT,
            model_tls_context(cert_paths["model_cert"], cert_paths["model_key"], cert_paths["ca"]),
            server_hostname=RECEIVER_DNS,
        )
        outbound, inbound = _channels(first_transport, model_side=True)
        seen = []
        for index in range(3):
            _seq, request = _receive(inbound, outbound)
            reply = decide(request)
            outbound.send(reply)
            seen.append(reply["call"]["op"])
            if index < 2:
                _ack(outbound)
        if seen != ["observe", "propose", "read"]:
            raise ModelRecoveryRefused("model did not choose the required three system calls")
        # No ACK for the read: receiver exits in the E-CPU commit callback.
        model_outbound = outbound.snapshot()
        model_inbound = inbound.snapshot()
        first_exit = first.wait(timeout=25)
        if first_exit != EXIT_AFTER_EFFECT_BEFORE_ACK:
            raise ModelRecoveryRefused(f"receiver exited at wrong crash cut: {first_exit}")
        if 3 not in outbound.pending_sequences():
            raise ModelRecoveryRefused("model did not retain an unacknowledged read")
        first_pid = first.pid
        if first_transport is not None and not first_transport.closed:
            first_transport.close()
        replacement, port = _spawn(root, True)
        second_transport = connect_mutual_tls(
            "127.0.0.1", port, MODEL_ENDPOINT, RECEIVER_ENDPOINT,
            model_tls_context(cert_paths["model_cert"], cert_paths["model_key"], cert_paths["ca"]),
            server_hostname=RECEIVER_DNS,
        )
        resumed_outbound = ReliableChannel.from_snapshot(model_outbound, second_transport)
        resumed_inbound = ReliableChannel.from_snapshot(model_inbound, second_transport)
        if not resumed_outbound.retransmit(3):
            raise ModelRecoveryRefused("the original semantic request was not available")
        _sequence, done = _receive(resumed_inbound, resumed_outbound, timeout=20)
        if not isinstance(done, dict) or done.get("kind") != DONE_SCHEMA:
            raise ModelRecoveryRefused("replacement receiver did not finalize the operation")
        _ack(resumed_outbound)
        out, err = replacement.communicate(timeout=20)
        if replacement.returncode != 0:
            raise ModelRecoveryRefused("replacement receiver refused: " + err[-500:])
        report = json.loads((root / "recovered-report.json").read_text(encoding="utf-8"))
        if (done["trace_digest"] != report["trace_digest"] or done["phase"] != "complete"
                or done["value"] != report["value"]
                or done["read_receipt_id"] != report["read_receipt_id"]
                or done["ground_digest"] != report["ground_digest"]):
            raise ModelRecoveryRefused("model and recovered receiver disagree on final Ground")
        expected = (7 + 201 + 5 * COORDINATE) % 97
        if report["value"] != expected or report["semantic_reentries"] != 0:
            raise ModelRecoveryRefused("recovered Ground diverged or replayed semantic effect")
        core = {
            "schema": "mailcpu.usm005.operational-report.v1",
            "model_process": os.getpid(),
            "first_receiver_process": first_pid,
            "replacement_receiver_process": report["receiver_process"],
            "first_receiver_exit": first_exit,
            "model_unchanged_process": True,
            "read_pending_at_crash": "3" in model_outbound["pending"],
            "authenticated_reconnect": True,
            "model_calls": seen,
            "result": report,
            "source_oracle_match": True,
            "quorum_anchor_failure_domains": 1,
        }
        return {**core, "report_digest": _digest(core)}
    finally:
        for transport in (first_transport, second_transport):
            if transport is not None and not transport.closed:
                transport.close()
        for child in (first, replacement):
            if child is not None and child.poll() is None:
                child.kill()
                child.communicate(timeout=5)


def main() -> int:
    """Run parent-host demo or launch the separate receiver process role."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("demo", "receiver"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--restore", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("usm005-report.json"))
    args = parser.parse_args()
    if args.role == "receiver":
        if args.root is None:
            parser.error("receiver role requires --root")
        return receiver(args.root, restore=args.restore)
    with tempfile.TemporaryDirectory(prefix="usm005-") as temp:
        report = run_demo(Path(temp))
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({"status": report["result"]["status"],
                      "semantic_reentries": report["result"]["semantic_reentries"],
                      "quorum_generation": report["result"]["latest_quorum_generation"],
                      "report_digest": report["report_digest"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
