"""SAB-012: receiver-owned active formation behind an authenticated TLS boundary.

No wire request installs code, chooses an executable, or grants a capability.
A receiver configures a fixed Ground and an interpreter before accepting clients.
The E-CPU Virtual Layer/Hypervisor admits the operation *before* the installed
Ground seed is formed and activated by the receiver-owned handler.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from typing import Any, Mapping, Sequence

from .active_host_formation import FormationPolicy, LocalInterpreterSurface, SeedManifest
from .capability_construction import (
    STAGE, ACTIVATE, CapabilityConstructionCompiler, ConstructionInventory,
    ConstructionPolicy, bind_receiving_surface,
)
from .federated_placement import (
    PinnedTLSServer, FederationRefused, MAX_FRAME,
    MutualTLSQualificationEndpoint,
)
from .ground_native_realization import (
    AffineGround, GroundIntention, independent_observation,
)
from .runtime_qualification import (
    REQUEST_KIND, RESPONSE_KIND, canonical, digest, _check_response,
)
from .runtime_qualification_worker import _write_atomic

PROOF_OPERATION = "formation_proof"
SCHEMA = "mailcpu.sab012.receiver-formed-native.v1"
GROUND_KEYS = ("a", "c", "mod", "x0", "coordinate")


class ReceiverFormationRefused(FederationRefused):
    """Fail closed on unauthenticated, unauthorized or semantically invalid formation."""


def _check_affine_request(message: Mapping[str, Any], host_id: str,
                          fixed: AffineGround) -> tuple[GroundIntention, str]:
    """Reject a changed mathematical Ground and all dynamic dispatch fields."""
    if (not isinstance(message, Mapping)
            or set(message) != {"kind", "host", "nonce", "operation", "payload"}
            or message.get("kind") != REQUEST_KIND
            or message.get("host") != host_id
            or message.get("operation") != "affine_mod"
            or type(message.get("nonce")) is not str
            or not 8 <= len(message["nonce"]) <= 64
            or not isinstance(message.get("payload"), dict)):
        raise ReceiverFormationRefused("invalid receiver-owned operation request")
    p = message["payload"]
    if (set(p) != set(GROUND_KEYS)
            or any(type(p[x]) is not int for x in GROUND_KEYS)
            or (p["a"], p["c"], p["mod"], p["x0"]) !=
                    (fixed.a, fixed.c, fixed.modulus, fixed.seed)
            or not 0 <= p["coordinate"] <= 10**18):
        raise ReceiverFormationRefused("request differs from receiver's installed Ground")
    intention = GroundIntention(
        "sab012-" + digest({"request": dict(message)})[:32],
        fixed, p["coordinate"],
    )
    return intention, digest(dict(message))


def _native_formed_affine(
    message: Mapping[str, Any], *, host_id: str, ground: AffineGround,
    directory: Path, engine: str, native_authority: bool,
    formation_authority: bool,
) -> tuple[dict[str, int], dict[str, Any]]:
    """Admit a receiver-local Virtual Layer handler before forming its seed.

    The only runtime implementation installed into the receiver is the trusted
    SAB-009 generator selected by the locally configured engine. No remote
    source or authority parameters are interpreted by this function.
    """
    intention, request_digest = _check_affine_request(message, host_id, ground)
    from . import (
        Capability, HeadlessOS, HypervisorAction, HypervisorPolicy,
        LexicalDecisionModel, OperatorRegistry, OperatorSpec, SystemIdentity,
        SystemSeed, SystemSeedEnvelope, VirtualBudget, VirtualGroundRef,
        VirtualLayerRuntime, VirtualLayerWorkload, VirtualOperatorRef,
    )
    from .law_certifier import lcg_navigate

    if engine not in {"python", "javascript"}:
        raise ReceiverFormationRefused("receiver did not configure a supported engine")
    surface_id = host_id + ".formed"
    surface_dir = directory / "installed-ground"
    executable = sys.executable if engine == "python" else shutil.which("node")
    if not executable:
        raise ReceiverFormationRefused("configured interpreter is unavailable")
    evidence: list[dict[str, Any]] = []
    operating_system = HeadlessOS()
    operating_system.hypervisor.classifier = LexicalDecisionModel()
    operating_system.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    identity = SystemIdentity("sab012-receiver", 1)
    envelope = SystemSeedEnvelope(
        identity, "sab012", "receiver-local", SystemSeed.from_system(operating_system)
    )
    if not operating_system.seed_admission.admit(envelope).accepted:
        raise ReceiverFormationRefused("receiver System Ground was not admitted")
    spec = OperatorSpec(
        operator_id="sab012.form_and_observe", version=1,
        description="Receiver-owned formation and observation of the fixed affine Ground",
        input_kind="object", output_kind="object", substrates=("cpu",),
        required_rights=frozenset({"compute"}), base_energy=8, energy_per_byte=1,
        max_input_bytes=4096, max_output_bytes=256,
        deterministic=True, effect_mode="pure",
    )
    registry = OperatorRegistry()

    def form_under_native_admission(value: Any, _workload: Any) -> dict[str, int]:
        """Called by the Virtual Layer only following the receiver Hypervisor gate."""
        if not formation_authority:
            raise ReceiverFormationRefused("receiver's formation permission is revoked")
        if value != message["payload"]:
            raise ReceiverFormationRefused("native handler input changed")
        surface_dir.mkdir(parents=True, exist_ok=True)
        surface = LocalInterpreterSurface(surface_id, engine, surface_dir, executable)
        stage = bind_receiving_surface(surface, locus=host_id + ".stage",
                operation=STAGE, coordinate=0, lease_until=10**18)
        activate = bind_receiving_surface(surface, locus=host_id + ".activate",
                operation=ACTIVATE, coordinate=0, lease_until=10**18)
        authority = ConstructionPolicy(frozenset({
            (stage.locus, stage.operation), (activate.locus, activate.operation),
        }), 10**18)
        formation = FormationPolicy(frozenset({(surface_id, engine)}), 10**18)
        compiler = CapabilityConstructionCompiler(
            ConstructionInventory((stage, activate)), authority,
        )
        plan = compiler.compile(intention)
        formed, receipt = compiler.form(intention, plan, formation_policy=formation)
        expected = independent_observation(intention)
        if (receipt.payload["output"] != {"value": expected}
                or formed.manifest.ground != ground.fingerprint):
            raise ReceiverFormationRefused("formed computation differs from admitted Ground")
        evidence.append({
            "construction_plan": plan.fingerprint,
            "seed_manifest": formed.manifest.fingerprint,
            "seed_source_sha256": formed.manifest.source_sha256,
            "formation_policy": formation.fingerprint,
            "construction_policy": authority.fingerprint,
            "observation_receipt": receipt.fingerprint,
            "engine": engine,
        })
        return {"value": expected}

    registry.register(spec, form_under_native_admission)
    runtime = VirtualLayerRuntime(registry, "sab012-node", frozenset({"cpu"}))
    caps = ((Capability("/virtual-layer/operators", frozenset({"compute"})),)
            if native_authority else ())
    pid = operating_system.environment.kernel.spawn(
        "sab012-formed-receiver", capabilities=caps,
        parent_pid=operating_system.environment.init_pid,
    )
    workload = VirtualLayerWorkload(
        workload_id="sab012-" + message["nonce"], system=identity,
        ground=VirtualGroundRef.from_envelope(envelope),
        intention={"goal": "receiver-formed-bounded-affine-observation"},
        operators=(VirtualOperatorRef("sab012.form_and_observe", 1, "cpu"),),
        input_value=dict(message["payload"]),
        budget=VirtualBudget(10_000, 10_000, 1000), logical_time=17,
        eligible_nodes=("sab012-node",), max_hops=1,
    )
    outcome = runtime.execute_operator(
        operating_system, pid, "sab012.remote", "sab012.operation", 1, 17,
        workload, "sab012.form_and_observe",
    )
    expected = {"value": lcg_navigate(ground.a, ground.c, ground.modulus,
                                      ground.seed, intention.coordinate)}
    if (outcome.action is not HypervisorAction.ALLOW
            or not outcome.executed
            or outcome.effect.get("kind") != "virtual_layer.operator_result"
            or outcome.effect.get("operator_contract_digest") != spec.digest
            or outcome.effect.get("result") != expected
            or len(evidence) != 1):
        raise ReceiverFormationRefused("native admission or formed observation refused")
    return expected, {
        "schema": SCHEMA + ".evidence",
        "host": host_id, "request_digest": request_digest,
        "ground": ground.fingerprint, "coordinate": intention.coordinate,
        "value": expected["value"], "formed": evidence[0],
        "native_operator": spec.digest,
        "hypervisor_action": outcome.action.value,
        "hypervisor_executed": outcome.executed,
        "hypervisor_receipt_digest": digest(outcome.to_dict()),
        "physical_host_attested": False,
    }


def _audit_path(directory: Path, host_id: str, nonce: str) -> Path:
    return directory / "formed-native-receipts" / (
        digest({"host": host_id, "nonce": nonce}) + ".json"
    )


def serve_worker(
    message: Mapping[str, Any], *, host_id: str, ground: AffineGround,
    directory: Path, engine: str = "python", native_authority: bool = True,
    formation_authority: bool = True,
) -> dict[str, Any]:
    """Fresh locally installed worker with immutably retained formation proof."""
    intention, request_digest = _check_affine_request(message, host_id, ground)
    if not native_authority or not formation_authority:
        raise ReceiverFormationRefused("current local receiver authority has been revoked")
    path = _audit_path(directory, host_id, message["nonce"])
    if path.exists():
        # Pure idempotent replay, but only under *current* locally configured grants.
        try:
            old = json.loads(path.read_bytes())
        except (OSError, ValueError) as exc:
            raise ReceiverFormationRefused("stored native formation evidence is invalid") from exc
        if (not isinstance(old, dict)
                or set(old) != {"schema", "host", "request_digest", "ground", "result", "evidence", "digest"}
                or old.get("schema") != SCHEMA + ".audit"
                or old.get("host") != host_id
                or old.get("request_digest") != request_digest
                or old.get("ground") != ground.fingerprint
                or old.get("result") != {"value": independent_observation(intention)}
                or old.get("digest") != digest({k:v for k,v in old.items() if k != "digest"})):
            raise ReceiverFormationRefused("conflicting or corrupt native formation replay")
        # A saved receipt cannot mask deletion or mutation of the installed seed.
        try:
            installed = directory / "installed-ground"
            manifest = SeedManifest.from_dict(json.loads(
                (installed / "ecpu-seed-manifest.json").read_bytes()))
            source = (installed / ("ecpu-seed.py" if engine == "python" else "ecpu-seed.js")).read_bytes()
            recorded = old["evidence"]["formed"]
            if (manifest.fingerprint != recorded["seed_manifest"]
                    or manifest.engine != engine
                    or manifest.surface_id != host_id + ".formed"
                    or manifest.ground != ground.fingerprint
                    or manifest.source_sha256 != hashlib.sha256(source).hexdigest()
                    or manifest.source_bytes != len(source)
                    or manifest.source_sha256 != recorded["seed_source_sha256"]):
                raise ReceiverFormationRefused("installed seed no longer matches the native replay")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ReceiverFormationRefused("formed seed verification failed on replay") from exc
        return _ok(message, old["result"])
    result, evidence = _native_formed_affine(
        message, host_id=host_id, ground=ground, directory=directory,
        engine=engine, native_authority=native_authority,
        formation_authority=formation_authority,
    )
    audit = {"schema": SCHEMA + ".audit", "host": host_id,
             "request_digest": request_digest, "ground": ground.fingerprint,
             "result": result, "evidence": evidence}
    audit["digest"] = digest(audit)
    _write_atomic(path, audit)
    return _ok(message, result)


def _ok(message: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    reply = {"kind": RESPONSE_KIND, "host": message["host"],
             "nonce": message["nonce"], "boot": secrets.token_hex(16),
             "ok": True, "result": dict(result), "error": None}
    _check_response(message, reply)
    return reply


class ReceiverFormingTLSServer(PinnedTLSServer):
    """Pin TLS, receiver Ground, interpreter, and grants outside the wire protocol."""

    def __init__(self, *, ground: AffineGround, engine: str = "python",
                 formation_authority: bool = True, allow_proofs: bool = False,
                 **kwargs: Any) -> None:
        if not isinstance(ground, AffineGround) or engine not in {"python", "javascript"}:
            raise ReceiverFormationRefused("receiver Ground or engine is invalid")
        super().__init__(**kwargs)
        self.ground, self.engine = ground, engine
        self.formation_authority = bool(formation_authority)
        self.allow_proofs = bool(allow_proofs)

    def _execute(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if request.get("operation") == PROOF_OPERATION:
            if not self.allow_proofs:
                raise ReceiverFormationRefused("receiver has not granted proof retrieval")
            if (set(request) != {"kind", "host", "nonce", "operation", "payload"}
                    or request.get("kind") != REQUEST_KIND
                    or request.get("host") != self.host_id
                    or not isinstance(request.get("payload"), dict)
                    or set(request["payload"]) != {"request_nonce", "request_digest"}
                    or type(request.get("nonce")) is not str
                    or not 8 <= len(request["nonce"]) <= 64):
                raise ReceiverFormationRefused("malformed formation evidence query")
            nonce = request["payload"]["request_nonce"]
            if type(nonce) is not str or not 8 <= len(nonce) <= 64:
                raise ReceiverFormationRefused("malformed formed operation nonce")
            if not self.native_authority or not self.formation_authority:
                raise ReceiverFormationRefused("formation attestation grant revoked")
            path = _audit_path(self.storage_directory, self.host_id, nonce)
            if not path.is_file():
                raise ReceiverFormationRefused("no native formed operation evidence")
            try:
                audit = json.loads(path.read_bytes())
            except (OSError, ValueError) as exc:
                raise ReceiverFormationRefused("unreadable receiver formation evidence") from exc
            if (not isinstance(audit, dict)
                    or set(audit) != {"schema", "host", "request_digest", "ground", "result", "evidence", "digest"}
                    or audit["schema"] != SCHEMA + ".audit"
                    or audit["host"] != self.host_id
                    or audit["request_digest"] != request["payload"]["request_digest"]
                    or audit["digest"] != digest({k:v for k,v in audit.items() if k!="digest"})):
                raise ReceiverFormationRefused("receiver evidence integrity or binding failed")
            return _ok(request, {"audit": audit})
        if request.get("operation") != "affine_mod":
            return super()._execute(request)
        if "affine_mod" not in self.allowed_operations:
            return super()._execute(request)
        _check_affine_request(request, self.host_id, self.ground)
        args = [sys.executable, "-m", "mailcpu.receiver_formed_native", "worker",
                "--host-id", self.host_id, "--storage-directory", str(self.storage_directory),
                "--engine", self.engine,
                "--a", str(self.ground.a), "--c", str(self.ground.c),
                "--mod", str(self.ground.modulus), "--x0", str(self.ground.seed)]
        if not self.native_authority:
            args.append("--revoke-native")
        if not self.formation_authority:
            args.append("--revoke-formation")
        try:
            execution = subprocess.run(args, input=canonical(dict(request)) + b"\n",
                    capture_output=True, timeout=self.worker_timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ReceiverFormationRefused("receiver formed worker unavailable") from exc
        if (execution.returncode != 0 or execution.stderr
                or len(execution.stdout) > MAX_FRAME
                or execution.stdout.count(b"\n") != 1
                or not execution.stdout.endswith(b"\n")):
            raise ReceiverFormationRefused("receiver native formation worker refused")
        try:
            reply = json.loads(execution.stdout)
            if (not isinstance(reply, dict)
                    or canonical(reply) + b"\n" != execution.stdout):
                raise ReceiverFormationRefused("receiver formed worker returned noncanonical response")
            _check_response(request, reply)
        except (TypeError, ValueError) as exc:
            raise ReceiverFormationRefused("invalid receiver formed worker response") from exc
        return reply


class AttestedFormedEndpoint:
    """Validate a receiver's TLS-bound formation evidence after each compute reply."""

    separate_process_per_exchange = True

    def __init__(self, endpoint: MutualTLSQualificationEndpoint) -> None:
        if not isinstance(endpoint, MutualTLSQualificationEndpoint):
            raise ReceiverFormationRefused("formed endpoint requires native mTLS client")
        self.endpoint, self.host_id = endpoint, endpoint.host_id
        self.last_attestation: dict[str, Any] | None = None
        self.last_request_digest: str | None = None

    def exchange(self, request: Mapping[str, Any], *, max_bytes: int) -> Mapping[str, Any]:
        if request.get("operation") == "affine_mod":
            self.last_attestation = None
            self.last_request_digest = None
        reply = self.endpoint.exchange(request, max_bytes=max_bytes)
        if request.get("operation") != "affine_mod" or reply.get("ok") is not True:
            return reply
        correlation = digest(dict(request))
        challenge = {"kind": REQUEST_KIND, "host": self.host_id,
            "nonce": digest({"proof":correlation})[:32],
            "operation": PROOF_OPERATION,
            "payload": {"request_nonce": request["nonce"], "request_digest":correlation}}
        proof_reply = self.endpoint.exchange(challenge, max_bytes=max_bytes)
        if proof_reply.get("ok") is not True:
            raise ReceiverFormationRefused("receiver did not furnish its formed execution evidence")
        body = proof_reply["result"]
        audit = body.get("audit") if isinstance(body, Mapping) else None
        if (not isinstance(audit, dict)
                or set(audit) != {"schema", "host", "request_digest", "ground", "result", "evidence", "digest"}
                or audit.get("schema") != SCHEMA + ".audit"
                or audit.get("host") != self.host_id
                or audit.get("request_digest") != correlation
                or audit.get("result") != reply["result"]
                or audit.get("digest") != digest({k:v for k,v in audit.items() if k != "digest"})):
            raise ReceiverFormationRefused("native formation proof contradicts exact TLS execution")
        e = audit["evidence"]
        p = request.get("payload")
        if (not isinstance(p, Mapping) or set(p) != set(GROUND_KEYS)
                or any(type(p[x]) is not int for x in GROUND_KEYS)):
            raise ReceiverFormationRefused("formed request payload was not exact")
        if audit["ground"] != AffineGround(p["a"], p["c"], p["mod"], p["x0"]).fingerprint:
            raise ReceiverFormationRefused("formed evidence Ground differs from actual request")
        if (not isinstance(e, Mapping)
                or not isinstance(p, Mapping)
                or e.get("schema") != SCHEMA + ".evidence"
                or e.get("ground") != audit["ground"]
                or e.get("request_digest") != correlation
                or e.get("coordinate") != p.get("coordinate")
                or e.get("value") != reply["result"].get("value")
                or e.get("hypervisor_action") != "allow"
                or e.get("hypervisor_executed") is not True
                or not isinstance(e.get("formed"), Mapping)
                or type(e["formed"].get("seed_manifest")) is not str
                or any(type(e.get(k)) is not str or len(e[k]) != 64 or
                       any(c not in "0123456789abcdef" for c in e[k])
                       for k in ("native_operator", "hypervisor_receipt_digest"))
                or e.get("physical_host_attested") is not False):
            raise ReceiverFormationRefused("receiver formation or native authority evidence is incomplete")
        self.last_attestation = audit
        self.last_request_digest = correlation
        return reply


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("serve", "worker"))
    p.add_argument("--host-id", required=True)
    p.add_argument("--storage-directory", required=True)
    p.add_argument("--engine", choices=("python", "javascript"), default="python")
    for field in ("a", "c", "mod", "x0"):
        p.add_argument("--"+field, type=int, required=True)
    p.add_argument("--revoke-native", action="store_true")
    p.add_argument("--revoke-formation", action="store_true")
    p.add_argument("--allow-formation-proof", action="store_true")
    p.add_argument("--listen-address", default="127.0.0.1")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--certificate")
    p.add_argument("--key")
    p.add_argument("--ca-file")
    p.add_argument("--client-dns")
    p.add_argument("--allow", action="append", default=[])
    p.add_argument("--ready-file")
    p.add_argument("--max-connections", type=int, default=0)
    p.add_argument("--worker-timeout", type=float, default=20.0)
    args = p.parse_args(argv)
    ground = AffineGround(args.a, args.c, args.mod, args.x0)
    root = Path(args.storage_directory)
    if args.mode == "worker":
        try:
            raw = sys.stdin.buffer.readline(MAX_FRAME + 2)
            if len(raw) > MAX_FRAME or not raw.endswith(b"\n"):
                return 2
            request = json.loads(raw)
            if not isinstance(request, dict) or canonical(request) + b"\n" != raw:
                return 2
            reply = serve_worker(request, host_id=args.host_id, ground=ground,
                directory=root, engine=args.engine,
                native_authority=not args.revoke_native,
                formation_authority=not args.revoke_formation)
            sys.stdout.buffer.write(canonical(reply) + b"\n")
            return 0
        except (ReceiverFormationRefused, ValueError, OSError, TypeError, KeyError):
            return 2
    if any(not x for x in (args.certificate, args.key, args.ca_file, args.client_dns)):
        return 2
    server = ReceiverFormingTLSServer(
        host_id=args.host_id, host=args.listen_address, port=args.port,
        certificate=args.certificate, key=args.key, ca_file=args.ca_file,
        client_dns=args.client_dns, storage_directory=str(root),
        allowed_operations=frozenset(args.allow),
        native_authority=not args.revoke_native,
        formation_authority=not args.revoke_formation,
        allow_proofs=args.allow_formation_proof,
        worker_timeout=args.worker_timeout, ground=ground, engine=args.engine,
    )
    server.serve(ready_file=args.ready_file, max_connections=args.max_connections)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())