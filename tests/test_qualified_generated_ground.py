"""IPS-004: native Hypervisor admission, typed handoff, and host-independent replay."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from mailcpu import (
    Capability, HeadlessOS, HypervisorPolicy, LexicalDecisionModel,
    SystemIdentity, SystemSeed, SystemSeedEnvelope, VirtualGroundRef,
)
from mailcpu.generative_ground_construction import (
    AffineBehaviorIntention, AffinePrimitive, compile_ground_dag, synthesize_ground,
)
from mailcpu.ground_native_realization import RealizationPolicy
from mailcpu.inverse_architecture_synthesis import ProposedRelation
from mailcpu.evidence_path_resolver import RouteMetric
from mailcpu.qualified_generated_ground import (
    QualifiedGroundExecution, QualifiedGroundExecutionError, QualifiedStageHost,
)
from mailcpu.runtime_qualification import (
    QualificationPolicy, QualificationRefused, SubprocessQualificationEndpoint, qualify,
)
from mailcpu.semantic_translation import RepresentationRef, canonical_value_digest
from mailcpu.federated_placement import MutualTLSQualificationEndpoint


def _goal() -> AffineBehaviorIntention:
    """Impose exact intended behavior independently of executable primitives."""
    relation = ProposedRelation(
        "e"*64,
        RepresentationRef.from_payload("ips004.test", 1, {"node":"input"}),
        RepresentationRef.from_payload("ips004.test", 1, {"node":"output"}),
        "b"*64, "c"*64, "d"*64, (RouteMetric("latency_us","us", 5),),
    )
    return AffineBehaviorIntention(relation, 17, 4, 11, 9)


def _palette() -> tuple[AffinePrimitive, ...]:
    """Provide the exact primitive capabilities, never the target composition."""
    return (
        AffinePrimitive("first",17,3,2),
        AffinePrimitive("second",17,8,5),
        AffinePrimitive("distractor",17,1,1),
    )


def _setup():
    """Prepare the admitted native virtual Ground and a qualified computation plan."""
    goal, primitives = _goal(), _palette()
    plan = synthesize_ground(goal, primitives)
    assert plan.status == "constructed_exact_affine_ground"
    assert plan.primitive_names == ("first","second")
    os = HeadlessOS()
    os.hypervisor.classifier = LexicalDecisionModel()
    os.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    identity = SystemIdentity("ips004-generated-ground", 1)
    envelope = SystemSeedEnvelope(identity, "executor", "ips004", SystemSeed.from_system(os))
    assert os.seed_admission.admit(envelope).accepted
    ground = VirtualGroundRef.from_envelope(envelope)
    pid = os.environment.kernel.spawn(
        "ips004-authorized",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=os.environment.init_pid,
    )
    return goal, primitives, plan, os, identity, envelope, ground, pid


def _subprocess_host(name: str, root: Path, *, wrong=False) -> QualifiedStageHost:
    """Qualify fresh per-message independent workers of the fixed SAB-003 vocabulary."""
    directory = root / name
    directory.mkdir()
    command = (sys.executable, "-m", "mailcpu.runtime_qualification_worker",
               "--host", name, "--directory", str(directory))
    if wrong:
        command += ("--wrong-compute",)
    endpoint = SubprocessQualificationEndpoint(name, command, timeout=6)
    policy = QualificationPolicy(
        frozenset({name}), "ips004-source-observer", 10,
        frozenset({"observer", "computational_fragment"}), max_calls=4,
    )
    report = qualify(endpoint, policy, coordinate=1, seed="ips004-probe-seed-011")
    return QualifiedStageHost(
        name, endpoint, report.payload, policy,
        RealizationPolicy(frozenset({(name, "interpreter")}), 10),
    )


def _restore_os(envelope: SystemSeedEnvelope) -> tuple[HeadlessOS, int]:
    """Restore the same Ground identity in a new receiver OS/Hypervisor instance."""
    replacement = HeadlessOS()
    replacement.hypervisor.classifier = LexicalDecisionModel()
    replacement.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    assert replacement.seed_admission.admit(envelope).accepted
    pid = replacement.environment.kernel.spawn(
        "ips004-replacement",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=replacement.environment.init_pid,
    )
    return replacement, pid


def test_two_disjoint_subprocess_hosts_hypervisor_dag_recovery_and_replay() -> None:
    """Second receiver resumes only uncommitted work after a distinct first host vanishes."""
    goal, primitives, plan, os, identity, envelope, ground, pid = _setup()
    with tempfile.TemporaryDirectory(prefix="ips004-subprocess-") as tmp:
        home = Path(tmp)
        host_one = _subprocess_host("first-host", home)
        session = QualifiedGroundExecution(plan, goal, primitives, identity, ground)
        first = session.advance(os, pid, host_one)
        assert len(first["payload"]["stages"]) == 1
        assert session.value is None
        first_output = session.dag.result("ips003.stage.000")
        assert first_output["value"] == (3 * goal.query_input + 2) % goal.modulus
        assert first["payload"]["stages"][0]["hypervisor_effect"]["kind"] == "virtual_layer.operator_result"
        assert first["payload"]["stages"][0]["stage_receipt"]["evidence"]["fresh_process"] is True
        # Reconstruct without referencing the first endpoint, Hypervisor, or worker.
        restored = QualifiedGroundExecution.from_checkpoint(plan, goal, primitives, first)
        assert restored.checkpoint() == first
        new_os, new_pid = _restore_os(envelope)
        second_host = _subprocess_host("replacement-host", home)
        second = restored.advance(new_os, new_pid, second_host)
        assert restored.complete
        assert restored.value == (7 * goal.query_input + 4) % goal.modulus == 16
        assert {r["host"] for r in second["payload"]["stages"]} == {
            "first-host", "replacement-host",
        }
        assert restored.dag.result("ips003.stage.001")["input"] == first_output["value"]
        assert restored.dag.is_complete
        assert len(second["payload"]["stages"]) == 2
        independent = QualifiedGroundExecution.from_checkpoint(
            plan, goal, primitives, second,
        )
        assert independent.complete
        assert independent.value == 16
        assert independent.checkpoint() == second
        with pytest.raises(QualifiedGroundExecutionError):
            independent.advance(new_os, new_pid, second_host)


def test_hypervisor_denial_prevents_external_host_execution() -> None:
    """Missing compute right refuses before running an already qualified worker."""
    goal, primitives, plan, os, identity, _, ground, _ = _setup()
    with tempfile.TemporaryDirectory(prefix="ips004-denial-") as tmp:
        host = _subprocess_host("qualified-host", Path(tmp))
        counted = []

        class CountingEndpoint:
            """Count only execution requests after the prior host qualification."""
            host_id = host.locus
            separate_process_per_exchange = True
            def exchange(self, request, *, max_bytes):
                """Delegate using the qualified native endpoint under count."""
                counted.append(request["operation"])
                return host.endpoint.exchange(request, max_bytes=max_bytes)

        counted_host = replace(host, endpoint=CountingEndpoint())
        denied_pid = os.environment.kernel.spawn(
            "ips004-unprivileged",
            capabilities=(Capability("/safe", frozenset({"read"})),),
            parent_pid=os.environment.init_pid,
        )
        session = QualifiedGroundExecution(plan, goal, primitives, identity, ground)
        with pytest.raises(QualifiedGroundExecutionError, match="Hypervisor denied"):
            session.advance(os, denied_pid, counted_host)
        assert counted == []
        assert not session.dag.committed_nodes
        assert not session.stages


def test_rehashed_incorrect_dag_checkpoint_refuses_after_restore() -> None:
    """Self-consistent DAG checksums cannot overwrite the requested computation."""
    goal, primitives, plan, os, identity, _, ground, pid = _setup()
    with tempfile.TemporaryDirectory(prefix="ips004-forgery-") as tmp:
        host = _subprocess_host("host-one", Path(tmp))
        session = QualifiedGroundExecution(plan, goal, primitives, identity, ground)
        saved = session.advance(os, pid, host)
        bad = deepcopy(saved)
        forged = compile_ground_dag(plan, goal, primitives)
        legitimate = session.dag.result("ips003.stage.000")
        forged.commit("ips003.stage.000", legitimate | {"value": (legitimate["value"]+1)%17})
        bad["payload"]["dag_snapshot"] = forged.snapshot()
        bad["digest"] = canonical_value_digest(bad["payload"])
        with pytest.raises(QualifiedGroundExecutionError, match="checkpoint DAG disagrees"):
            QualifiedGroundExecution.from_checkpoint(plan, goal, primitives, bad)
        altered = deepcopy(saved)
        altered["payload"]["stages"][0]["stage_receipt"]["output"]["value"] += 1
        altered["digest"] = canonical_value_digest(altered["payload"])
        with pytest.raises(Exception):
            QualifiedGroundExecution.from_checkpoint(plan, goal, primitives, altered)
        with pytest.raises(QualifiedGroundExecutionError):
            QualifiedGroundExecution.from_checkpoint(plan, goal, primitives, {
                "payload": saved["payload"], "digest": "0"*64,
            })


def test_recovery_rejects_changed_intention_operator_and_virtual_ground() -> None:
    """Construction changes cannot borrow an old trusted computational prefix."""
    goal, primitives, plan, os, identity, _, ground, pid = _setup()
    with tempfile.TemporaryDirectory(prefix="ips004-stale-") as tmp:
        host = _subprocess_host("host-one", Path(tmp))
        session = QualifiedGroundExecution(plan, goal, primitives, identity, ground)
        saved = session.advance(os, pid, host)
        revised = (replace(primitives[0], offset=3),) + primitives[1:]
        with pytest.raises(QualifiedGroundExecutionError):
            QualifiedGroundExecution.from_checkpoint(plan, goal, revised, saved)
        altered = deepcopy(saved)
        altered["payload"]["ground"]["state_digest"] = "0"*64
        altered["digest"] = canonical_value_digest(altered["payload"])
        with pytest.raises(QualifiedGroundExecutionError, match="checkpoint DAG disagrees|Hypervisor effect mismatch"):
            QualifiedGroundExecution.from_checkpoint(plan, goal, primitives, altered)
        stale_session = QualifiedGroundExecution(
            plan, goal, primitives, identity,
            replace(ground, state_digest="0"*64),
        )
        with pytest.raises(Exception):
            stale_session.advance(os, pid, host)
        assert not stale_session.dag.committed_nodes


def test_invalid_qualified_worker_refused_before_accepting_computation() -> None:
    """An independently probed worker with wrong arithmetic is never admitted."""
    with tempfile.TemporaryDirectory(prefix="ips004-wrong-") as tmp:
        with pytest.raises(QualificationRefused):
            _subprocess_host("wrong-host", Path(tmp), wrong=True)


def test_identity_ground_recovery_does_not_invent_remote_work() -> None:
    """The virtual identity Ground is complete without creating fabricated effects."""
    goal, primitives, _, _, identity, _, ground, _ = _setup()
    identity_goal = replace(goal, output_at_zero=0, output_at_one=1)
    identity_plan = synthesize_ground(identity_goal, ())
    session = QualifiedGroundExecution(identity_plan, identity_goal, (), identity, ground)
    assert session.value is None
    checkpoint = session.finish_identity()
    assert session.complete
    assert session.value == goal.query_input
    assert checkpoint["payload"]["stages"] == []
    restored = QualifiedGroundExecution.from_checkpoint(identity_plan, identity_goal, (), checkpoint)
    assert restored.complete
    assert restored.value == goal.query_input


def _openssl(*args: str) -> None:
    """Create short-lived fixture certificates with no committed signing material."""
    subprocess.run(("openssl", *args), check=True, capture_output=True, timeout=12)


def _cert(root: Path, ca: Path, name: str, *, client: bool) -> tuple[Path, Path]:
    """Issue a certificate with a specific TLS identity and role."""
    key, csr, crt = (root / (name + ext) for ext in (".key", ".csr", ".crt"))
    _openssl("req", "-new", "-newkey", "rsa:2048", "-nodes",
             "-keyout", str(key), "-out", str(csr),
             "-subj", f"/CN={name}.ips004.test")
    ext = root / (name + ".ext")
    ext.write_text(f"subjectAltName=DNS:{name}.ips004.test\n"
                   "keyUsage=critical,digitalSignature,keyEncipherment\n"
                   f"extendedKeyUsage={'clientAuth' if client else 'serverAuth'}\n")
    _openssl("x509", "-req", "-in", str(csr),
             "-CA", str(ca), "-CAkey", str(root/"ca.key"),
             "-CAcreateserial", "-days", "1",
             "-extfile", str(ext), "-out", str(crt))
    return crt, key


def _start_peer(root: Path, name: str, cert: Path, key: Path, ca: Path):
    """Launch an actual E-CPU mTLS peer with receiver-native fixed-op authorization."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    ready = root / (name + ".ready")
    process = subprocess.Popen(
        (sys.executable, "-m", "mailcpu.federated_placement", "serve",
         "--host-id", name, "--listen-address", "127.0.0.1", "--port", str(port),
         "--certificate", str(cert), "--key", str(key),
         "--ca-file", str(ca), "--client-dns", "origin.ips004.test",
         "--storage-directory", str(root / (name + ".store")),
         "--ready-file", str(ready),
         "--allow", "observe", "--allow", "affine_mod"),
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    until = time.monotonic() + 15
    while not ready.exists() and time.monotonic() < until:
        if process.poll() is not None:
            raise AssertionError("peer failed: " + process.stderr.read().decode()[:1000])
        time.sleep(.03)
    assert ready.exists(), "mTLS listener startup timed out"
    return process, port


def _stop_peer(process) -> None:
    """Release a locally created receiver process and its diagnostic streams."""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=4)
    if process.stderr:
        process.stderr.close()


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL required")
def test_two_mtls_peer_hosts_and_recovery_after_first_peer_death() -> None:
    """Authenticated inter-process execution survives first peer's real process death."""
    goal, primitives, plan, os, identity, envelope, ground, pid = _setup()
    with tempfile.TemporaryDirectory(prefix="ips004-mtls-") as tmp:
        root = Path(tmp)
        ca = root / "ca.crt"
        _openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                 "-subj", "/CN=IPS004-CA", "-addext",
                 "basicConstraints=critical,CA:TRUE", "-addext",
                 "keyUsage=critical,keyCertSign,cRLSign",
                 "-keyout", str(root/"ca.key"), "-out", str(ca))
        client_cert, client_key = _cert(root, ca, "origin", client=True)
        a_cert, a_key = _cert(root, ca, "peer-a", client=False)
        b_cert, b_key = _cert(root, ca, "peer-b", client=False)
        processes = []
        try:
            def peer_host(name: str, cert: Path, key: Path) -> QualifiedStageHost:
                """Qualify independently authenticated and permitted remote receiver."""
                proc, port = _start_peer(root, name, cert, key, ca)
                processes.append(proc)
                endpoint = MutualTLSQualificationEndpoint(
                    name, ("127.0.0.1", port), server_dns=f"{name}.ips004.test",
                    client_certificate=str(client_cert), client_key=str(client_key),
                    ca_file=str(ca),
                )
                qpolicy = QualificationPolicy(
                    frozenset({name}), "ips004-mtls-observer", 10,
                    frozenset({"observer", "computational_fragment"}),
                    max_calls=4,
                )
                report = qualify(
                    endpoint, qpolicy, coordinate=1, seed="ips004-mtls-probe-seed",
                )
                return QualifiedStageHost(
                    name, endpoint, report.payload, qpolicy,
                    RealizationPolicy(frozenset({(name, "interpreter")}), 10),
                )

            first_host = peer_host("peer-a", a_cert, a_key)
            session = QualifiedGroundExecution(plan, goal, primitives, identity, ground)
            first = session.advance(os, pid, first_host)
            assert first["payload"]["stages"][0]["host"] == "peer-a"
            assert first["payload"]["stages"][0]["stage_receipt"]["evidence"]["fresh_process"] is False
            # Destroy the actual first service process before rebuilding the
            # native DAG and completing it on another authenticated peer.
            _stop_peer(processes[0])
            assert processes[0].poll() is not None
            recovered = QualifiedGroundExecution.from_checkpoint(
                plan, goal, primitives, first
            )
            replacement_os, replacement_pid = _restore_os(envelope)
            second_host = peer_host("peer-b", b_cert, b_key)
            finished = recovered.advance(replacement_os, replacement_pid, second_host)
            assert recovered.complete and recovered.value == 16
            assert [item["host"] for item in finished["payload"]["stages"]] == [
                "peer-a", "peer-b",
            ]
            assert QualifiedGroundExecution.from_checkpoint(
                plan, goal, primitives, finished
            ).value == 16
            # A false certificate DNS cannot silently replace its qualified peer.
            wrong_dns = MutualTLSQualificationEndpoint(
                "peer-b", second_host.endpoint.address,
                server_dns="different.ips004.test",
                client_certificate=str(client_cert), client_key=str(client_key),
                ca_file=str(ca),
            )
            with pytest.raises(Exception):
                wrong_dns.exchange(
                    {"kind":"mailcpu.sab003.request.v1","host":"peer-b",
                     "nonce":"a"*32,"operation":"observe",
                     "payload":{"word":"wrong SAN"}},
                    max_bytes=4096,
                )
        finally:
            for process in processes:
                _stop_peer(process)
