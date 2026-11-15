"""USM-008: quorum-fenced model-result publication across authenticated claimants.

This is an integration of E-CPU's existing recovery-lineage quorum, remote
authority services, MailCPU mTLS, ReliableChannel, Ground receipts, and
receiver-loss restoration. It introduces no new quorum algorithm.

A *fixed A owner service* mediates requests from two separately certified
replacement claimants. The claimants do not possess authority A credentials.
Only one candidate's exact recovered result can occupy publication generation
3. All other candidates are refused by the latest native quorum state.

The publication is a journaled logical result, not an external effect.
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
import time
from typing import Any, Callable, Mapping

from examples.model_authenticated_fabric import (
    _ack, _receive, model_tls_context, server_tls_context,
)
from examples.model_distributed_lineage import (
    prepare_distributed_authorities,
)
from examples.model_ground_os import _digest, sample_stream
from examples.model_receiver_recovery import (
    COORDINATE, ModelRecoveryRefused, ModelRecoveryStore,
    _canonical_bytes, _persist, run_demo,
)
from examples.model_system_calls import verify_system_call_trace
from examples.run_model_authenticated_experiment import _openssl
from mailcpu.mtls_transport import accept_mutual_tls, connect_mutual_tls
from mailcpu.recovery_lineage import (
    RecoveryLineageError, RecoveryStateManifest,
)
from mailcpu.reliability import ReliableChannel, ReliabilityPolicy
from mailcpu.socket_transport import SocketTransport

CLAIM_SCHEMA = "mailcpu.usm008.model-publication-claim.v1"
REQUEST_SCHEMA = "mailcpu.usm008.model-publication-request.v1"
VERDICT_SCHEMA = "mailcpu.usm008.model-publication-verdict.v1"
REPORT_SCHEMA = "mailcpu.usm008.quorum-publication-report.v1"
BROKER_DNS = "publication-authority.model.local"
CLAIMANT_ROLE_DNS = "candidate.model.local"
CANDIDATES = {
    "replacement-a": "candidate-a.model.local",
    "replacement-b": "candidate-b.model.local",
}
RECEIVER = "authority-gate"
CLAIMANT = "candidate"
REQUEST_CHANNEL = "model.publication.request"
RESPONSE_CHANNEL = "model.publication.verdict"
CLOSE_CUT = "after_quorum_publication_claim"
TIMEOUT = 18.0


class ModelPublicationRefused(RuntimeError):
    """A claimant cannot publish the recovered Ground under the current quorum."""


def _strict_identity(certificate: Mapping[str, Any]) -> str:
    """Determine the candidate solely from CA-verified client certificate SANs."""
    names = {
        entry[1] for entry in certificate.get("subjectAltName", ())
        if isinstance(entry, tuple) and len(entry) == 2 and entry[0] == "DNS"
    }
    if CLAIMANT_ROLE_DNS not in names:
        raise ModelPublicationRefused("peer did not present authorized claimant role")
    matched = [owner for owner, name in CANDIDATES.items() if name in names]
    if len(matched) != 1:
        raise ModelPublicationRefused("claimant certificate does not bind one owner")
    return matched[0]


def issue_claimant_certificates(directory: Path) -> None:
    """Generate local test identities under existing USM-005 ephemeral CA."""
    ca, key = directory / "ca.pem", directory / "ca.key"
    if not ca.is_file() or not key.is_file():
        raise ModelPublicationRefused("ephemeral test CA not present")
    for owner, dns in (("authority", BROKER_DNS), *CANDIDATES.items()):
        cert_key = directory / f"publication-{owner}.key"
        request = directory / f"publication-{owner}.csr"
        certificate = directory / f"publication-{owner}.pem"
        extensions = directory / f"publication-{owner}.ext"
        _openssl(directory, "req", "-newkey", "rsa:2048", "-nodes",
                 "-keyout", str(cert_key), "-out", str(request),
                 "-subj", f"/CN={dns}")
        names = f"DNS:{dns}" if owner == "authority" else (
            f"DNS:{dns},DNS:{CLAIMANT_ROLE_DNS}"
        )
        extensions.write_text(
            f"subjectAltName={names}\n"
            "extendedKeyUsage=clientAuth,serverAuth\n"
            "basicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n",
            encoding="utf-8",
        )
        _openssl(directory, "x509", "-req", "-in", str(request),
                 "-CA", str(ca), "-CAkey", str(key), "-CAcreateserial",
                 "-out", str(certificate), "-days", "1",
                 "-sha256", "-extfile", str(extensions))


def _channels(transport: SocketTransport, *, candidate_side: bool) -> tuple[
    ReliableChannel, ReliableChannel,
]:
    """Use the existing reciprocal E-CPU reliable-channel framing."""
    policy = ReliabilityPolicy(lease_ticks=4, max_attempts=12, window_size=4)
    if candidate_side:
        return (
            ReliableChannel(transport, CLAIMANT, RECEIVER, REQUEST_CHANNEL, policy),
            ReliableChannel(transport, CLAIMANT, CLAIMANT, RESPONSE_CHANNEL, policy,
                            peer=RECEIVER),
        )
    return (
        ReliableChannel(transport, RECEIVER, CLAIMANT, RESPONSE_CHANNEL, policy),
        ReliableChannel(transport, RECEIVER, RECEIVER, REQUEST_CHANNEL, policy,
                        peer=CLAIMANT),
    )


def verified_ground(core: Mapping[str, Any]) -> dict[str, Any]:
    """Require actual E-CPU Ground and model-operation receipt consistency.

    The receiver source fixture is explicit: no status claim is treated as
    proof. The caller must separately verify its latest native recovery root.
    """
    if not isinstance(core, Mapping) or core.get("schema") != (
        "mailcpu.usm005.operational-report.v1"
    ):
        raise ModelPublicationRefused("not a recovered E-CPU model result")
    digest = core.get("report_digest")
    if type(digest) is not str or _digest(
        {k: v for k, v in core.items() if k != "report_digest"}
    ) != digest:
        raise ModelPublicationRefused("source report digest is incorrect")
    result = core.get("result")
    if not isinstance(result, Mapping):
        raise ModelPublicationRefused("missing native E-CPU recovery result")
    trace = result.get("session_trace")
    if not isinstance(trace, Mapping) or not verify_system_call_trace(trace):
        raise ModelPublicationRefused("recovered operation trace is invalid")
    if (
        result.get("status") != "complete"
        or trace.get("phase") != "complete"
        or trace.get("trace_digest") != result.get("trace_digest")
        or result.get("semantic_reentries") != 0
        or result.get("first_quorum_generation") != 1
        or result.get("latest_quorum_generation") != 2
        or core.get("first_receiver_exit") != 86
        or core.get("model_unchanged_process") is not True
        or core.get("read_pending_at_crash") is not True
        or core.get("authenticated_reconnect") is not True
        or core.get("quorum_anchor_failure_domains") != 1
    ):
        raise ModelPublicationRefused("recovered E-CPU result did not meet native cut")
    events = trace.get("events")
    if (not isinstance(events, list) or len(events) != 3
            or [e["call"]["op"] for e in events] != ["observe", "propose", "read"]):
        raise ModelPublicationRefused("not a three-step model-operated Ground")
    receipt = events[-1]["output"]
    if (
        receipt.get("status") != "completed"
        or receipt.get("read_receipt_id") != result.get("read_receipt_id")
        or receipt.get("ground_digest") != result.get("ground_digest")
        or receipt.get("value") != result.get("value")
        or events[-1]["call"]["coordinate"] != COORDINATE
        or result.get("ground_revision") != 1
        or receipt["value"] != (7 + 201 + 5 * COORDINATE) % 97
    ):
        raise ModelPublicationRefused("recovered result contradicts admitted Ground")
    return {
        "source_report_digest": digest,
        "trace_digest": result["trace_digest"],
        "ground_digest": result["ground_digest"],
        "read_receipt_id": result["read_receipt_id"],
        "value": result["value"],
        "coordinate": COORDINATE,
        "model_digest": result["model_digest"],
    }


def _claim(owner_id: str, ground: Mapping[str, Any], predecessor: str) -> dict[str, Any]:
    """Bind the contender, original receipt, and exact predecessor Ground root."""
    return {
        "schema": CLAIM_SCHEMA,
        "owner_id": owner_id,
        "source_report_digest": ground["source_report_digest"],
        "trace_digest": ground["trace_digest"],
        "ground_digest": ground["ground_digest"],
        "read_receipt_id": ground["read_receipt_id"],
        "value": ground["value"],
        "coordinate": ground["coordinate"],
        "model_digest": ground["model_digest"],
        "predecessor_manifest_digest": predecessor,
    }


class QuorumPublicationGate:
    """Fixed-owner E-CPU quorum controls *one* recovered Ground publication."""

    def __init__(self, root: Path, recovered: Mapping[str, Any]) -> None:
        self.root = root
        self.ground = verified_ground(recovered)
        self.store = ModelRecoveryStore(root / "checkpoint")
        latest_state, self.before = self.store.load()
        if self.before.generation != 2:
            raise ModelPublicationRefused("model result must have recovery generation two")
        if latest_state["phase"] != "complete":
            raise ModelPublicationRefused("native quorum state is not a completed Ground")
        if latest_state["events"][-1]["output"]["read_receipt_id"] != self.ground["read_receipt_id"]:
            raise ModelPublicationRefused("native recovery state differs from source report")
        self.expected_previous = self.before.digest
        self.claim_path = root / "publication-claim-3.json"
        self.manifest_path = root / "publication-manifest-3.json"
        self._closed = False

    def close(self) -> None:
        if not self._closed:
            self.store.close()
            self._closed = True

    def _read_committed_claim(self) -> tuple[dict[str, Any], RecoveryStateManifest]:
        """Verify exact latest quorum state, not just the presence of local files."""
        if not self.claim_path.is_file() or not self.manifest_path.is_file():
            raise ModelPublicationRefused("committed publication claim record unavailable")
        claim_bytes = self.claim_path.read_bytes()
        manifest = RecoveryStateManifest.from_snapshot(json.loads(
            self.manifest_path.read_text(encoding="utf-8")
        ))
        manifest.verify_payload(claim_bytes)
        self.store.lineage.verify_state(manifest)
        state = json.loads(claim_bytes)
        if not isinstance(state, dict) or set(state) != {
            "schema", "owner_id", "source_report_digest", "trace_digest",
            "ground_digest", "read_receipt_id", "value", "coordinate",
            "model_digest", "predecessor_manifest_digest",
        } or state != _claim(state.get("owner_id"), self.ground, self.expected_previous):
            raise ModelPublicationRefused("quorum claim payload was not bound to Ground")
        if state["owner_id"] not in CANDIDATES:
            raise ModelPublicationRefused("quorum winner is not an admitted candidate")
        if (manifest.generation != 3
                or manifest.predecessor_digest != self.before.digest
                or manifest.capture_cut != CLOSE_CUT):
            raise ModelPublicationRefused("quorum publication generation is invalid")
        return state, manifest

    def decide(self, owner_id: str, request: Any) -> dict[str, Any]:
        """Commit one winner; reject stale or differently bound claimants."""
        if self._closed:
            raise ModelPublicationRefused("publication authority is no longer active")
        if owner_id not in CANDIDATES:
            raise ModelPublicationRefused("unknown authenticated candidate identity")
        expected_request = {
            "schema": REQUEST_SCHEMA,
            "owner_id": owner_id,
            **self.ground,
        }
        if not isinstance(request, Mapping) or dict(request) != expected_request:
            raise ModelPublicationRefused("claim request differs from TLS-bound Ground")
        generation, previous = self.store.lineage.high_water()
        if generation == 2:
            if previous != self.before.digest:
                raise ModelPublicationRefused("model recovery root changed under publication")
            claim = _claim(owner_id, self.ground, previous)
            payload = _canonical_bytes(claim)
            manifest = RecoveryStateManifest(
                machine_id=self.store.membership.system_id,
                incarnation=self.store.membership.incarnation,
                owner_id=self.store.membership.owner_id,
                owner_term=self.store.membership.owner_term,
                membership_digest=self.store.membership.digest,
                generation=3,
                predecessor_digest=previous,
                state_digest=hashlib.sha256(payload).hexdigest(),
                capture_cut=CLOSE_CUT,
            )
            _persist(self.claim_path, payload)
            _persist(self.manifest_path, _canonical_bytes(manifest.snapshot()))
            # No successful result may escape until the native majority has
            # fsynced its identical prepare/commit decision.
            self.store.lineage.seal(manifest)
        elif generation != 3:
            raise ModelPublicationRefused("publication authority is at an unknown generation")
        committed, manifest = self._read_committed_claim()
        winner = committed["owner_id"]
        admitted = winner == owner_id
        outcome = {
            "schema": VERDICT_SCHEMA,
            "owner_id": owner_id,
            "status": "authorized" if admitted else "superseded",
            "winner_owner_id": winner,
            "generation": manifest.generation,
            "manifest_digest": manifest.digest,
            "source_trace_digest": self.ground["trace_digest"],
            "quorum_root": manifest.digest,
            "publication": ({
                "read_receipt_id": committed["read_receipt_id"],
                "ground_digest": committed["ground_digest"],
                "value": committed["value"],
                "coordinate": committed["coordinate"],
                "owner_id": owner_id,
                "owner_generation": 3,
            } if admitted else None),
        }
        return {**outcome, "verdict_digest": _digest(outcome)}


def _serve(
    transport: SocketTransport, gate: QuorumPublicationGate,
) -> dict[str, Any]:
    """Enforce one TLS client identity and one native reliable-channel RPC."""
    certificate = transport.socket.getpeercert()
    owner_id = _strict_identity(certificate)
    outgoing, incoming = _channels(transport, candidate_side=False)
    accepted = []

    def apply(_seq: int, request: Any) -> None:
        accepted.append(gate.decide(owner_id, request))

    _receive(incoming, outgoing, commit=apply, timeout=TIMEOUT)
    if len(accepted) != 1:
        raise ModelPublicationRefused("claim transport was not committed")
    outgoing.send(accepted[0])
    _ack(outgoing, timeout=TIMEOUT)
    return accepted[0]


def _client(port: int, root: Path, owner_id: str, evidence_file: Path) -> dict[str, Any]:
    """The claimant sends only its own evidence; it cannot open remote journals."""
    if owner_id not in CANDIDATES:
        raise ModelPublicationRefused("unsupported claimant identity")
    certs = root / "certificates"
    transport = connect_mutual_tls(
        "127.0.0.1", port, CLAIMANT, RECEIVER,
        model_tls_context(
            certs / f"publication-{owner_id}.pem",
            certs / f"publication-{owner_id}.key",
            certs / "ca.pem",
        ),
        server_hostname=BROKER_DNS,
    )
    try:
        ground = verified_ground(json.loads(evidence_file.read_text(encoding="utf-8")))
        outbound, inbound = _channels(transport, candidate_side=True)
        outgoing = {"schema": REQUEST_SCHEMA, "owner_id": owner_id, **ground}
        outbound.send(outgoing)
        _seq, answer = _receive(inbound, outbound, timeout=TIMEOUT)
        _ack(outbound, timeout=TIMEOUT)
        if (
            not isinstance(answer, dict)
            or set(answer) != {
                "schema", "owner_id", "status", "winner_owner_id", "generation",
                "manifest_digest", "source_trace_digest", "quorum_root",
                "publication", "verdict_digest",
            }
            or answer["schema"] != VERDICT_SCHEMA
            or answer["owner_id"] != owner_id
            or answer["source_trace_digest"] != ground["trace_digest"]
            or _digest({k:v for k,v in answer.items() if k != "verdict_digest"})
            != answer["verdict_digest"]
        ):
            raise ModelPublicationRefused("peer returned an unauthenticated result claim")
        return {**answer, "candidate_process": os.getpid()}
    finally:
        if not transport.closed:
            transport.close()


def run_quorum_publication(root: Path) -> dict[str, Any]:
    """Use a model-operated real Ground for a two-candidate mTLS quorum claim."""
    status: dict[str, Any] = {}
    original_evidence = None
    claims: list[dict[str, Any]] = []

    def setup(directory: Path, certs: Mapping[str, Path]) -> Callable[[], None]:
        stop, authority_status = prepare_distributed_authorities(directory, certs)
        status["authority_status"] = authority_status
        issue_claimant_certificates(directory / "certificates")
        return stop

    def publication_hook(directory: Path, core: Mapping[str, Any]) -> dict[str, Any]:
        nonlocal original_evidence
        original_evidence = {**core, "report_digest": _digest(core)}
        evidence_file = directory / "recovered-model-for-claim.json"
        _persist(evidence_file, _canonical_bytes(original_evidence))
        gate = QuorumPublicationGate(directory, original_evidence)
        listener = SocketTransport.listen("127.0.0.1", 0)
        port = listener.getsockname()[1]
        candidates: list[subprocess.Popen[str]] = []
        try:
            for owner_id in CANDIDATES:
                child = subprocess.Popen(
                    (
                        sys.executable, "-m", "examples.model_quorum_publication",
                        "claimant", "--root", str(directory),
                        "--owner-id", owner_id, "--port", str(port),
                        "--source", str(evidence_file),
                    ), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True,
                )
                candidates.append(child)
            for _ in CANDIDATES:
                transport = accept_mutual_tls(
                    listener, RECEIVER, CLAIMANT,
                    server_tls_context(
                        directory / "certificates" / "publication-authority.pem",
                        directory / "certificates" / "publication-authority.key",
                        directory / "certificates" / "ca.pem",
                    ),
                    expected_peer_dns=CLAIMANT_ROLE_DNS,
                )
                try:
                    claims.append(_serve(transport, gate))
                finally:
                    if not transport.closed:
                        transport.close()
            all_clients = []
            for p in candidates:
                out, err = p.communicate(timeout=30)
                if p.returncode != 0:
                    raise ModelPublicationRefused("mTLS candidate refused: " + err[-400:])
                all_clients.append(json.loads(out))
            successful = [item for item in all_clients if item["status"] == "authorized"]
            denied = [item for item in all_clients if item["status"] == "superseded"]
            if len(successful) != 1 or len(denied) != 1:
                raise ModelPublicationRefused("quorum did not fence a unique publication")
            claim, manifest = gate._read_committed_claim()
            if successful[0]["owner_id"] != claim["owner_id"]:
                raise ModelPublicationRefused("client winner differs from committed quorum root")
            if any(
                item["candidate_process"] == os.getpid() for item in all_clients
            ) or len(set(item["candidate_process"] for item in all_clients)) != 2:
                raise ModelPublicationRefused("candidates were not separate processes")
            # Note: claim authority is only valid for the current latest
            # generation. Never trust a durable but superseded local file.
            return {
                "candidate_claims": all_clients,
                "publication_manifest": manifest.snapshot(),
                "publication_owner": claim["owner_id"],
                "publication_value": claim["value"],
                "verified_ground": gate.ground,
                "quorum_generation": manifest.generation,
                "native_quorum_verified": True,
                "logical_publication_only": True,
            }
        finally:
            gate.close()
            listener.close()
            for p in candidates:
                if p.poll() is None:
                    p.kill()
                p.communicate(timeout=5)

    # Extension hook is invoked after USM-005 receiver loss and model result
    # validation, while E-CPU native remote authorities are still live.
    from examples.model_receiver_recovery import run_demo
    recovered = run_demo(
        root, configure_lineage=setup, publication_hook=publication_hook,
    )
    if not status["authority_status"]["alive_through_receiver_replacement"]:
        raise ModelPublicationRefused("remote quorum authorities did not survive receiver loss")
    chosen = recovered["quorum_publication"]
    if chosen["quorum_generation"] != 3:
        raise ModelPublicationRefused("publication was not majority-authorized")
    report = {
        "schema": REPORT_SCHEMA,
        "recovered_model": {
            k:v for k,v in recovered.items() if k != "quorum_publication"
        },
        "publication": chosen,
        "authority_os_processes": status["authority_status"]["authority_process_ids"],
        "single_physical_failure_domain": True,
        "physical_independence_verified": False,
    }
    return {**report, "report_digest": _digest(report)}


def main() -> int:
    """Reproduce the full quorum gate, or run one isolated claimant client."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("demo", "claimant"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--owner-id", choices=tuple(CANDIDATES))
    parser.add_argument("--port", type=int)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, default=Path("usm008-publication.json"))
    args = parser.parse_args()
    if args.role == "claimant":
        if (
            args.root is None or args.port is None or args.owner_id is None
            or args.source is None
        ):
            parser.error("claimant requires root, port, owner-id and source")
        print(json.dumps(_client(args.port, args.root, args.owner_id, args.source),
                         sort_keys=True))
        return 0
    with tempfile.TemporaryDirectory(prefix="usm008-") as tmp:
        document = run_quorum_publication(Path(tmp))
    args.output.write_text(
        json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "report_digest": document["report_digest"],
        "quorum_generation": document["publication"]["quorum_generation"],
        "winner": document["publication"]["publication_owner"],
        "value": document["publication"]["publication_value"],
        "denied_count": sum(1 for item in document["publication"]["candidate_claims"]
                            if item["status"] == "superseded"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
