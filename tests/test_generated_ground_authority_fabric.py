"""IPS-006: authenticated authority rejoin for generated Ground publication.

Uses the existing E-CPU TLS service subprocess fixtures and genuine
IPS-003/004/005 Ground execution, not a mock majority or synthetic vote.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import shutil
import ssl
from pathlib import Path

import pytest

from mailcpu import (
    RecoveryLineageAuthority, RecoveryLineageError, SeedCommitMembership,
)
from mailcpu.generated_ground_authority_fabric import (
    GeneratedGroundAuthorityError, PinnedRecoveryAuthority,
    connect_generated_ground_quorum,
)
from mailcpu.qualified_generated_ground import QualifiedGroundExecution
from mailcpu.recovery_lineage_transport import (
    DistributedRecoveryLineageCoordinator, RecoveryLineageTransportError,
)

from test_fenced_generated_ground import (
    _goal, _palette, _receiver, _restart, _host,
)
from test_recovery_lineage_service import (
    _make_certificates, _owner_context, _start_member, _stop,
)

GENESIS = hashlib.sha256(b"ips006-independent-authority-genesis-v1").hexdigest()


def _membership() -> SeedCommitMembership:
    """Pin the IPS-005 virtual system to a real three-member recovery quorum."""
    return SeedCommitMembership(
        "ips005-generated-machine", 1, ("A", "B", "C"), "A", 1, GENESIS,
    )


def _peer_ids(ready_b: dict, ready_c: dict) -> tuple[PinnedRecoveryAuthority, ...]:
    """Carry explicit member-specific TLS SAN and address pins to the adapter."""
    return (
        PinnedRecoveryAuthority("B", ready_b["host"], ready_b["port"],
                                "member-b.mailcpu.test"),
        PinnedRecoveryAuthority("C", ready_c["host"], ready_c["port"],
                                "member-c.mailcpu.test"),
    )


def _open(
    root: Path,
    certificates: dict,
    pins: tuple[PinnedRecoveryAuthority, ...],
    *,
    degraded: bool = False,
):
    """Reopen the independent owner journal and only authenticated peer streams."""
    from mailcpu.generative_ground_construction import synthesize_ground
    goal, palette = _goal(), _palette()
    return connect_generated_ground_quorum(
        _membership(), root / "authorities" / "A.jsonl",
        pins, _owner_context(certificates), root / "ground-artifacts",
        synthesize_ground(goal, palette), goal, palette,
        degraded=degraded, timeout=.45, handshake_timeout=.45,
    )


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL required for mTLS authorities")
def test_independent_tls_quorum_rehomes_late_ground_and_recovers_with_survivor(
    tmp_path: Path,
) -> None:
    """Quorum A+B survives C outage; C's lag is repaired before B's outage."""
    certificates = _make_certificates(tmp_path)
    membership = _membership()
    process_b, ready_b = _start_member(tmp_path, membership, certificates, "B")
    process_c, ready_c = _start_member(tmp_path, membership, certificates, "C")
    pins = _peer_ids(ready_b, ready_c)
    processes = [process_b, process_c]
    os, identity, envelope, ground, pid = _receiver()
    old_host = _host(tmp_path, "ips006-old-host")
    replacement_host = _host(tmp_path, "ips006-replacement-host")
    final_host = _host(tmp_path, "ips006-final-host")

    try:
        # Every authority is an actual process/journal; the owner is local.
        with _open(tmp_path, certificates, pins) as initial:
            assert isinstance(initial.coordinator, DistributedRecoveryLineageCoordinator)
            assert initial.connected_members == ("A", "B", "C")
            session = QualifiedGroundExecution(
                initial.publisher.plan, initial.publisher.intention,
                initial.publisher.primitives, identity, ground,
            )
            head = initial.publisher.bootstrap(session)
            slow_assignment = initial.publisher.assign(head, old_host)
            old_candidate = initial.publisher.compute(
                slow_assignment, old_host, os, pid,
            )
            assert old_candidate.next_checkpoint["payload"]["stages"][0]["host"] == old_host.locus
            assert old_candidate.authoritative is False
            assert initial.coordinator.high_water() == (
                2, slow_assignment.manifest.digest,
            )

        # Kill a remote authority and *recreate* the owner-side coordinator.
        # Its connected subset A+B forms the SAME fixed membership quorum q=2.
        _stop(process_c)
        assert process_c.poll() is not None
        with _open(tmp_path, certificates, pins, degraded=True) as degraded:
            assert degraded.unavailable_members == ("C",)
            assert degraded.connected_members == ("A", "B")
            recovered = degraded.restore_latest()
            assert recovered.manifest.digest == slow_assignment.manifest.digest

            rehomed = degraded.publisher.assign(recovered, replacement_host)
            assert rehomed.assignment["epoch"] == 2
            with pytest.raises(RecoveryLineageError, match="stale"):
                degraded.publisher.publish(slow_assignment, old_candidate)

            replacement_os, replacement_pid = _restart(envelope)
            winner = degraded.publisher.compute(
                rehomed, replacement_host, replacement_os, replacement_pid,
            )
            published = degraded.publisher.publish(rehomed, winner)
            assert published.assignment is None
            assert published.checkpoint["payload"]["stages"][0]["host"] == replacement_host.locus
            assert degraded.coordinator.high_water() == (
                4, published.manifest.digest,
            )

        # No independent read majority => even locally intact artifact files
        # cannot justify any new stage or a recovered "latest" snapshot.
        _stop(process_b)
        assert process_b.poll() is not None
        with _open(tmp_path, certificates, pins, degraded=True) as missing:
            assert missing.unavailable_members == ("B", "C")
            assert missing.connected_members == ("A",)
            with pytest.raises(RecoveryLineageError, match="read quorum"):
                missing.restore_latest()

        # Restart B/C against their original independently durable journals.
        # B knows generation 4; C lagged at generation 2. The high-water is
        # still readable through A+B, but C must catch up before replacing B.
        process_b, ready_b = _start_member(tmp_path, membership, certificates, "B")
        process_c, ready_c = _start_member(tmp_path, membership, certificates, "C")
        processes.extend((process_b, process_c))
        healed_pins = _peer_ids(ready_b, ready_c)
        with _open(tmp_path, certificates, healed_pins) as healed:
            assert healed.restore_latest().manifest.digest == published.manifest.digest
            assert healed.coordinator.authorities["C"].committed_state() == (
                2, slow_assignment.manifest.digest,
            )
            proof_three = healed.coordinator.seal(rehomed.manifest)
            proof_four = healed.coordinator.seal(published.manifest)
            assert proof_three.proposal.slot == 3
            assert proof_four.proposal.slot == 4
            assert healed.coordinator.authorities["C"].committed_state() == (
                4, published.manifest.digest,
            )

        # Reopen under a *different* surviving majority A+C while B is dead.
        _stop(process_b)
        with _open(tmp_path, certificates, healed_pins, degraded=True) as alternate:
            assert alternate.unavailable_members == ("B",)
            assert alternate.connected_members == ("A", "C")
            latest = alternate.restore_latest()
            assert latest.manifest.digest == published.manifest.digest
            assigned = alternate.publisher.assign(latest, final_host)
            os_final, pid_final = _restart(envelope)
            candidate = alternate.publisher.compute(assigned, final_host, os_final, pid_final)
            completed = alternate.publisher.publish(assigned, candidate)
            assert alternate.publisher._session(completed.checkpoint).value == 16
            assert alternate.publisher._session(completed.checkpoint).complete
            assert [s["host"] for s in completed.checkpoint["payload"]["stages"]] == [
                "ips006-replacement-host", "ips006-final-host",
            ]
            assert alternate.coordinator.high_water() == (
                6, completed.manifest.digest,
            )
            with pytest.raises(RecoveryLineageError, match="stale"):
                alternate.publisher.publish(slow_assignment, old_candidate)
    finally:
        for process in processes:
            _stop(process)


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL required for TLS identity tests")
def test_degraded_start_never_bypasses_dns_pins_or_missing_majority(
    tmp_path: Path,
) -> None:
    """A trusted wrong certificate is never counted as configured member B."""
    certificates = _make_certificates(tmp_path)
    membership = _membership()
    proc_b, ready_b = _start_member(tmp_path, membership, certificates, "B")
    proc_c, ready_c = _start_member(tmp_path, membership, certificates, "C")
    try:
        pins = _peer_ids(ready_b, ready_c)
        bad = (
            replace(pins[0], server_dns="member-c.mailcpu.test"),
            pins[1],
        )
        with pytest.raises(GeneratedGroundAuthorityError, match="configured network"):
            _open(tmp_path, certificates, bad, degraded=True)
        wrong_dns = (
            replace(pins[0], server_dns="wrong-member.mailcpu.test"),
            pins[1],
        )
        with _open(tmp_path, certificates, wrong_dns, degraded=True) as safe:
            assert safe.connected_members == ("A", "C")
            assert safe.unavailable_members == ("B",)
        with pytest.raises(RecoveryLineageTransportError):
            _open(tmp_path, certificates, wrong_dns, degraded=False)

        unverified = ssl._create_unverified_context()
        from mailcpu.generative_ground_construction import synthesize_ground
        goal, primitives = _goal(), _palette()
        with pytest.raises(GeneratedGroundAuthorityError, match="authenticated TLS"):
            connect_generated_ground_quorum(
                membership, tmp_path/"authorities"/"A.jsonl", pins,
                unverified, tmp_path/"ground-artifacts",
                synthesize_ground(goal, primitives), goal, primitives,
            )
    finally:
        _stop(proc_b)
        _stop(proc_c)


def test_distributed_coordinator_degraded_flag_never_changes_membership(
    tmp_path: Path,
) -> None:
    """Without owner, or without read majority, omitting peer clients is not authority."""
    membership = _membership()
    owner = RecoveryLineageAuthority(
        membership, "A", tmp_path/"authority-a.jsonl",
    )
    with pytest.raises(RecoveryLineageTransportError, match="set must equal fixed membership"):
        DistributedRecoveryLineageCoordinator(membership, {"A": owner})
    with pytest.raises(RecoveryLineageTransportError, match="local fixed owner"):
        DistributedRecoveryLineageCoordinator.with_available_peers(membership, {})
    with pytest.raises(RecoveryLineageTransportError, match="unknown authority"):
        DistributedRecoveryLineageCoordinator.with_available_peers(
            membership, {"A": owner, "X": owner},
        )
    reduced = DistributedRecoveryLineageCoordinator.with_available_peers(
        membership, {"A": owner},
    )
    assert reduced.membership.digest == membership.digest
    assert reduced.membership.quorum == 2
    with pytest.raises(RecoveryLineageError, match="read quorum"):
        reduced.high_water()
    with pytest.raises(RecoveryLineageError, match="strict-majority"):
        from mailcpu.recovery_lineage import RecoveryStateManifest
        manifest = RecoveryStateManifest(
            membership.system_id, 1, membership.owner_id, 1,
            membership.digest, 1, membership.genesis_state_digest,
            hashlib.sha256(b"state").hexdigest(), "ips006.no-quorum",
        )
        reduced.seal(manifest)
