"""Mutual-TLS authority service, partition, reconnect, and owner-restart tests."""

from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from mailcpu import (
    DistributedRecoveryLineageCoordinator,
    RecoveryLineageAuthority,
    RecoveryLineageCoordinator,
    RecoveryLineageError,
    RecoveryLineagePeerClient,
    RecoveryLineageTransportError,
    SeedCommitMembership,
    SeedPrepareVote,
)
from mailcpu.recovery_lineage import RecoveryCheckpointManifest

GENESIS = __import__("hashlib").sha256(
    b"mailcpu-recovery-lineage-mtls-service-genesis-v1"
).hexdigest()
OWNER_DNS = "owner-a.mailcpu.test"


def _membership() -> SeedCommitMembership:
    """Construct the immutable three-member membership used by the failure experiments."""

    return SeedCommitMembership(
        "mtls-recovery-machine",
        1,
        ("A", "B", "C"),
        "A",
        1,
        GENESIS,
    )


def _manifest(membership: SeedCommitMembership) -> RecoveryCheckpointManifest:
    """Bind deterministic endpoint checkpoint and backend digests to generation one."""

    import hashlib

    return RecoveryCheckpointManifest(
        membership.system_id,
        membership.incarnation,
        membership.owner_id,
        membership.owner_term,
        membership.digest,
        1,
        GENESIS,
        hashlib.sha256(b"requester-checkpoint").hexdigest(),
        hashlib.sha256(b"receiver-checkpoint").hexdigest(),
        hashlib.sha256(b'[[\"cpu.execute\",\"/cpu/compute\"]]').hexdigest(),
        "after_response_publish",
    )


def _openssl(directory: Path, *arguments: str) -> None:
    """Run one bounded OpenSSL command and require a successful certificate-generation result."""

    result = subprocess.run(
        ["openssl", *arguments],
        cwd=directory,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"openssl failed: {result.stderr}")


def _make_certificates(directory: Path) -> dict[str, Path]:
    """Create one test CA and distinct DNS identities for the owner and both authority members."""

    ca_key = directory / "ca.key"
    ca_certificate = directory / "ca.pem"
    _openssl(
        directory,
        "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(ca_key), "-out", str(ca_certificate),
        "-days", "3", "-sha256", "-subj", "/CN=MailCPU Recovery Test CA",
        "-addext", "basicConstraints=critical,CA:TRUE",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
    )
    files: dict[str, Path] = {"ca": ca_certificate}
    for member_id, dns_name in (
        ("A", OWNER_DNS),
        ("B", "member-b.mailcpu.test"),
        ("C", "member-c.mailcpu.test"),
    ):
        key = directory / f"{member_id}.key"
        request = directory / f"{member_id}.csr"
        certificate = directory / f"{member_id}.pem"
        extensions = directory / f"{member_id}.ext"
        _openssl(
            directory,
            "req", "-new", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(request),
            "-subj", f"/CN={dns_name}",
        )
        extensions.write_text(
            "\n".join(
                (
                    f"subjectAltName=DNS:{dns_name}",
                    "extendedKeyUsage=clientAuth,serverAuth",
                    "basicConstraints=critical,CA:FALSE",
                    "keyUsage=critical,digitalSignature,keyEncipherment",
                )
            ) + "\n",
            encoding="utf-8",
        )
        _openssl(
            directory,
            "x509", "-req", "-in", str(request),
            "-CA", str(ca_certificate), "-CAkey", str(ca_key),
            "-CAcreateserial", "-out", str(certificate), "-days", "3",
            "-sha256", "-extfile", str(extensions),
        )
        files[f"{member_id}_key"] = key
        files[f"{member_id}_cert"] = certificate
    return files


def _server_context(certificates: dict[str, Path], member_id: str) -> ssl.SSLContext:
    """Build a member-specific TLS server context that requires an owner certificate from the test CA."""

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(
        str(certificates[f"{member_id}_cert"]),
        str(certificates[f"{member_id}_key"]),
    )
    context.load_verify_locations(cafile=str(certificates["ca"]))
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _owner_context(certificates: dict[str, Path]) -> ssl.SSLContext:
    """Build the owner TLS client context with CA validation, DNS checking, and its own client certificate."""

    context = ssl.create_default_context(
        ssl.Purpose.SERVER_AUTH,
        cafile=str(certificates["ca"]),
    )
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(
        str(certificates["A_cert"]),
        str(certificates["A_key"]),
    )
    return context


def _write_membership(path: Path, membership: SeedCommitMembership) -> None:
    """Persist the fixed membership snapshot consumed by independent authority interpreters."""

    path.write_text(
        json.dumps(membership.snapshot(), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _start_member(
    directory: Path,
    membership: SeedCommitMembership,
    certificates: dict[str, Path],
    member_id: str,
) -> tuple[subprocess.Popen[str], dict[str, Any]]:
    """Launch one independently journaled TLS authority process and return its advertised address."""

    worker = Path(__file__).resolve().parent / "helpers" / "recovery_lineage_tls_service_worker.py"
    membership_path = directory / "membership.json"
    _write_membership(membership_path, membership)
    journal = directory / "authorities" / f"{member_id}.jsonl"
    process = subprocess.Popen(
        [
            sys.executable,
            str(worker),
            member_id,
            str(membership_path),
            str(journal),
            str(certificates[f"{member_id}_cert"]),
            str(certificates[f"{member_id}_key"]),
            str(certificates["ca"]),
            OWNER_DNS,
        ],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    line = process.stdout.readline()
    assert line, f"authority {member_id} failed before readiness: rc={process.poll()}"
    ready = json.loads(line)
    assert ready["member_id"] == member_id
    return process, ready


def _connect_peer(
    membership: SeedCommitMembership,
    certificates: dict[str, Path],
    member_id: str,
    ready: dict[str, Any],
    *,
    server_hostname: str | None = None,
) -> RecoveryLineagePeerClient:
    """Open a mutual-TLS peer client bound to the configured member and certificate DNS identity."""

    return RecoveryLineagePeerClient.connect_mutual_tls(
        membership,
        member_id,
        ready["host"],
        int(ready["port"]),
        _owner_context(certificates),
        server_hostname=server_hostname or f"member-{member_id.lower()}.mailcpu.test",
        timeout=0.8,
        handshake_timeout=0.8,
    )


def _reconnect_peer(
    membership: SeedCommitMembership,
    certificates: dict[str, Path],
    member_id: str,
    ready: dict[str, Any],
) -> RecoveryLineagePeerClient:
    """Retry fresh authenticated connections until the still-running service accepts a replacement stream."""

    deadline = time.monotonic() + 5.0
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            return _connect_peer(membership, certificates, member_id, ready)
        except RecoveryLineageTransportError as exc:
            last_error = exc
            time.sleep(0.04)
    raise AssertionError(f"authority {member_id} did not accept a replacement stream: {last_error}")


def _coordinator(
    membership: SeedCommitMembership,
    owner: RecoveryLineageAuthority,
    peers: dict[str, RecoveryLineagePeerClient],
) -> DistributedRecoveryLineageCoordinator:
    """Compose the owner journal with the two configured TLS-authenticated remote processes."""

    return DistributedRecoveryLineageCoordinator(
        membership,
        {membership.owner_id: owner, **peers},
    )


def _stop(process: subprocess.Popen[str]) -> None:
    """Hard-terminate one child service and drain its captured streams."""

    if process.poll() is None:
        process.kill()
    process.communicate(timeout=5)


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL CLI is required to create ephemeral test certificates")
def test_tls_authorities_fail_closed_below_quorum_then_rejoin_and_rebind(tmp_path: Path) -> None:
    """Mathematics: streams and then a service process can fail without losing the exact quorum-sealed generation from its member journal."""

    certificates = _make_certificates(tmp_path)
    membership = _membership()
    manifest = _manifest(membership)
    owner = RecoveryLineageAuthority(
        membership, "A", tmp_path / "authorities" / "A.jsonl"
    )
    process_b, ready_b = _start_member(tmp_path, membership, certificates, "B")
    process_c, ready_c = _start_member(tmp_path, membership, certificates, "C")
    peer_b = _connect_peer(membership, certificates, "B", ready_b)
    peer_c = _connect_peer(membership, certificates, "C", ready_c)
    replacement_b: RecoveryLineagePeerClient | None = None
    replacement_c: RecoveryLineagePeerClient | None = None
    rebound_b: RecoveryLineagePeerClient | None = None
    try:
        isolated = _coordinator(membership, owner, {"B": peer_b, "C": peer_c})
        peer_b.close()
        peer_c.close()
        with pytest.raises(RecoveryLineageError, match="strict-majority prepare quorum"):
            isolated.seal(manifest)

        assert process_b.poll() is None
        assert process_c.poll() is None
        replacement_b = _reconnect_peer(membership, certificates, "B", ready_b)
        replacement_c = _reconnect_peer(membership, certificates, "C", ready_c)
        recovered = _coordinator(
            membership,
            owner,
            {"B": replacement_b, "C": replacement_c},
        )
        proof = recovered.seal(manifest)
        assert tuple(sorted(vote.member_id for vote in proof.certificate.votes)) == (
            "A", "B", "C"
        )
        assert recovered.high_water() == (1, manifest.digest)

        replacement_b.close()

        # Exercise the external supervisor path: terminate B's service process,
        # start a fresh interpreter under the same member identity and journal,
        # then require it to report the already-committed high-water.
        _stop(process_b)
        process_b, ready_b = _start_member(tmp_path, membership, certificates, "B")
        rebound_b = _reconnect_peer(membership, certificates, "B", ready_b)
        assert rebound_b.committed_state() == (1, manifest.digest)
        assert process_b.poll() is None
        assert process_c.poll() is None
    finally:
        for peer in (peer_b, peer_c, replacement_b, replacement_c, rebound_b):
            if peer is not None:
                peer.close()
        _stop(process_b)
        _stop(process_c)


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL CLI is required to create ephemeral test certificates")
def test_tls_rejects_wrong_member_dns_identity_without_killing_authority_service(
    tmp_path: Path,
) -> None:
    """Mathematics: an owner that expects member C's SAN cannot bind member B's certificate, while B remains serviceable."""

    certificates = _make_certificates(tmp_path)
    membership = _membership()
    process_b, ready_b = _start_member(tmp_path, membership, certificates, "B")
    good_peer: RecoveryLineagePeerClient | None = None
    try:
        with pytest.raises(RecoveryLineageTransportError):
            _connect_peer(
                membership,
                certificates,
                "B",
                ready_b,
                server_hostname="member-c.mailcpu.test",
            )
        assert process_b.poll() is None
        good_peer = _reconnect_peer(membership, certificates, "B", ready_b)
        assert good_peer.committed_state() is None
        assert process_b.poll() is None
    finally:
        if good_peer is not None:
            good_peer.close()
        _stop(process_b)


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL CLI is required to create ephemeral test certificates")
def test_owner_process_restart_reopens_exact_vote_and_recovers_with_remote_quorum(
    tmp_path: Path,
) -> None:
    """Mathematics: hard owner-process loss after PREPARE fsync preserves the fixed owner's exact vote for same-term recovery."""

    certificates = _make_certificates(tmp_path)
    membership = _membership()
    manifest = _manifest(membership)
    membership_path = tmp_path / "membership.json"
    manifest_path = tmp_path / "manifest.json"
    _write_membership(membership_path, membership)
    manifest_path.write_text(
        json.dumps(manifest.snapshot(), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    owner_journal = tmp_path / "authorities" / "A.jsonl"
    marker_path = tmp_path / "owner-prepared.json"
    worker = Path(__file__).resolve().parent / "helpers" / "recovery_lineage_owner_crash_worker.py"
    crashed_owner = subprocess.Popen(
        [
            sys.executable,
            str(worker),
            str(membership_path),
            str(owner_journal),
            str(manifest_path),
            str(marker_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not marker_path.is_file() and crashed_owner.poll() is None:
        time.sleep(0.005)
    assert marker_path.is_file(), f"owner did not publish its durable vote: rc={crashed_owner.poll()}"
    crashed_owner.wait(timeout=5)
    assert crashed_owner.returncode == 91
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    original_vote = SeedPrepareVote.from_snapshot(marker["vote"])

    process_b, ready_b = _start_member(tmp_path, membership, certificates, "B")
    process_c, ready_c = _start_member(tmp_path, membership, certificates, "C")
    peer_b = _connect_peer(membership, certificates, "B", ready_b)
    peer_c = _connect_peer(membership, certificates, "C", ready_c)
    try:
        reopened_owner = RecoveryLineageAuthority(membership, "A", owner_journal)
        local = RecoveryLineageCoordinator(membership, {"A": reopened_owner})
        proposal = local.proposal_for(manifest)
        assert reopened_owner.prepare(proposal) == original_vote
        coordinator = _coordinator(membership, reopened_owner, {"B": peer_b, "C": peer_c})
        proof = coordinator.seal(manifest)
        owner_vote = next(
            vote for vote in proof.certificate.votes if vote.member_id == "A"
        )
        assert owner_vote == original_vote
        assert coordinator.high_water() == (1, manifest.digest)
    finally:
        peer_b.close()
        peer_c.close()
        _stop(process_b)
        _stop(process_c)


def test_fixed_membership_refuses_remote_only_quorum_without_owner_vote(
    tmp_path: Path,
) -> None:
    """Mathematics: two remote member votes cannot form an admissible lineage certificate when the fixed owner A is absent."""

    membership = _membership()
    manifest = _manifest(membership)
    member_b = RecoveryLineageAuthority(
        membership, "B", tmp_path / "B.jsonl"
    )
    member_c = RecoveryLineageAuthority(
        membership, "C", tmp_path / "C.jsonl"
    )
    coordinator = RecoveryLineageCoordinator(
        membership,
        {"B": member_b, "C": member_c},
    )
    with pytest.raises(RecoveryLineageError, match="strict-majority prepare quorum"):
        coordinator.seal(manifest)
