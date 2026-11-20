"""IPS-008: real mTLS effect service, prepared handoff and crash recovery."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import time

import pytest

from mailcpu.effect_receiver_service import (
    AuthenticatedGroundEffectClient, EffectReceiverServiceError,
)
from mailcpu.fenced_effect_receiver import (
    EffectFencingRefused, FencedGroundEffectReceiver, published_effect,
)
from mailcpu.recovery_lineage import RecoveryLineageError

from test_fenced_generated_ground import _bootstrap, _host, _restart, _lineage
from test_recovery_lineage_service import (
    _make_certificates, _owner_context,
)

RESOURCE = "/virtual-layer/effects/ips008-register"


def _published_first(root: Path):
    """Quorum-publish one original IPS-004 stage as a valid source for a handoff."""
    lineage, initial, system, envelope, pid = _bootstrap(root)
    original = _host(root, "ips008-first")
    assigned = lineage.assign(initial, original)
    first = lineage.publish(
        assigned, lineage.compute(assigned, original, system, pid),
    )
    return lineage, first, envelope


def _start(root: Path, certificates: dict[str, Path]):
    """Hard-crashable service owns its own real SQLite state and TLS listener."""
    marker = root / "receiver-ready.json"
    if marker.exists():
        marker.unlink()
    worker = Path(__file__).parent/"helpers"/"ips008_effect_service_worker.py"
    p = subprocess.Popen([
        sys.executable, str(worker), str(root),
        str(certificates["B_cert"]), str(certificates["B_key"]),
        str(certificates["ca"]), str(marker), "owner-a.mailcpu.test",
    ], cwd=Path(__file__).resolve().parents[1],
       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not marker.is_file():
        if p.poll() is not None:
            out, err = p.communicate(timeout=5)
            raise AssertionError("effect service failed: " + err[-2000:] + out[-1000:])
        time.sleep(.03)
    assert marker.is_file(), "effect service did not advertise its listener"
    info = json.loads(marker.read_text(encoding="utf-8"))
    return p, info


def _client(info: dict, certificates: dict, *, dns="member-b.mailcpu.test",
            certificate="A"):
    """Create one pinned mTLS client with owner-specific certificate."""
    if certificate == "A":
        context = _owner_context(certificates)
    else:
        context = ssl.create_default_context(
            ssl.Purpose.SERVER_AUTH, cafile=str(certificates["ca"]),
        )
        context.load_cert_chain(
            str(certificates[f"{certificate}_cert"]),
            str(certificates[f"{certificate}_key"]),
        )
    return AuthenticatedGroundEffectClient(
        info["host"], int(info["port"]), context,
        server_hostname=dns, timeout=2.0,
    )


def _kill(p: subprocess.Popen) -> None:
    """Forcefully stop the resource process without a graceful transaction exit."""
    if p.poll() is None:
        p.kill()
    p.communicate(timeout=5)


def test_barrier_survives_owner_rollback_and_rejects_old_effect_before_quorum_rehome(
    tmp_path: Path,
) -> None:
    """A durable freeze precedes rehome, and restart cannot make it disappear."""
    lineage, first, envelope = _published_first(tmp_path)
    receiver = FencedGroundEffectReceiver(
        tmp_path/"receiver.sqlite", resource=RESOURCE,
        plan_digest=lineage.plan.digest,
    )
    receiver.install(lineage, first)
    old = published_effect(first,RESOURCE)
    assert receiver.apply(old)["committed"]

    host = _host(tmp_path,"ips008-next")
    barrier = receiver.prepare_handoff(lineage,first,next_host=host.locus)
    assert barrier["source_root"] == first.manifest.digest
    assert receiver.snapshot()["pending_handoff_digest"] == barrier["barrier_digest"]
    with pytest.raises(EffectFencingRefused,match="handoff barrier"):
        receiver.apply(old)

    # Simulate loss of the owner/coordinator without any new quorum root:
    # reopening the exact original journals sees the old valid root, but
    # the independent effect resource retains the fail-closed barrier.
    fresh_lineage = _lineage(tmp_path)
    assert fresh_lineage.restore_latest().manifest.digest == first.manifest.digest
    fresh_receiver = FencedGroundEffectReceiver(
        tmp_path/"receiver.sqlite", resource=RESOURCE,
        plan_digest=fresh_lineage.plan.digest,
    )
    with pytest.raises(EffectFencingRefused,match="handoff barrier"):
        fresh_receiver.apply(old)
    assert fresh_receiver.prepare_handoff(
        fresh_lineage, fresh_lineage.restore_latest(), next_host=host.locus,
    ) == barrier
    with pytest.raises(EffectFencingRefused,match="another durable"):
        fresh_receiver.prepare_handoff(
            fresh_lineage,first,next_host="different-host",
        )

    # The owner recovers and seals only the exact requested successor;
    # the matching installed assignment atomically releases the barrier.
    assigned = fresh_lineage.assign(first,host)
    assert assigned.assignment["epoch"] == barrier["target_epoch"]
    with pytest.raises(EffectFencingRefused,match="handoff barrier"):
        fresh_receiver.apply(old)
    fresh_receiver.install(fresh_lineage, assigned, require_handoff=True)
    assert fresh_receiver.snapshot()["pending_handoff_digest"] is None
    with pytest.raises(EffectFencingRefused,match="stale"):
        fresh_receiver.apply(old)

    operating_system, pid = _restart(envelope)
    final = fresh_lineage.publish(
        assigned, fresh_lineage.compute(assigned,host,operating_system,pid),
    )
    fresh_receiver.install(fresh_lineage,final,require_handoff=True)
    assert fresh_receiver.apply(published_effect(final,RESOURCE))["value"] == 16
    assert fresh_receiver.snapshot()["accepted_effects"] == 2


def test_wrong_quorum_successor_cannot_release_prepared_barrier(tmp_path: Path) -> None:
    """Exactly one next epoch+host+parent relation may discharge a freeze."""
    lineage, first, _ = _published_first(tmp_path)
    receiver = FencedGroundEffectReceiver(
        tmp_path/"receiver.sqlite",resource=RESOURCE,
        plan_digest=lineage.plan.digest,
    )
    receiver.install(lineage,first)
    target = _host(tmp_path,"ips008-authorized-next")
    receiver.prepare_handoff(lineage,first,next_host=target.locus)
    rival = _host(tmp_path,"ips008-rival")
    # A coordinator that bypasses the optional barrier protocol can seal a
    # mathematically and quorum-valid assignment. Resource nevertheless
    # refuses to install it and remains frozen, rather than accepting an
    # arbitrary later assignment that was not previously acknowledged.
    wrong_assignment = lineage.assign(first,rival)
    with pytest.raises(EffectFencingRefused,match="does not satisfy"):
        receiver.install(lineage,wrong_assignment,require_handoff=True)
    assert receiver.snapshot()["pending_handoff_digest"] is not None


def test_remote_assignment_requires_barrier_before_activation(tmp_path: Path) -> None:
    """No candidate created by an unaffiliated coordinator unlocks the service."""
    lineage, first, _ = _published_first(tmp_path)
    receiver = FencedGroundEffectReceiver(
        tmp_path/"receiver.sqlite",resource=RESOURCE,
        plan_digest=lineage.plan.digest,
    )
    receiver.install(lineage,first)
    new = lineage.assign(first,_host(tmp_path,"ips008-unprepared"))
    with pytest.raises(EffectFencingRefused,match="requires prepared handoff"):
        receiver.install(lineage,new,require_handoff=True)
    assert receiver.snapshot()["installed_root"] == first.manifest.digest


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL CLI needed for real mTLS identities")
def test_real_mtls_receiver_crash_after_prepared_barrier_and_recovered_activation(
    tmp_path: Path,
) -> None:
    """Hard-kill receiver after durable freeze; old worker can never slip through."""
    lineage, first, envelope = _published_first(tmp_path)
    certificates = _make_certificates(tmp_path)
    process, info = _start(tmp_path,certificates)
    after_restart = None
    try:
        client = _client(info,certificates)
        activation = client.activate(first.manifest.digest)
        assert activation["event"] == "publish"
        old = published_effect(first,RESOURCE)
        assert client.apply(old)["committed"]
        target = _host(tmp_path,"ips008-mtls-next")
        barrier = client.prepare(first.manifest.digest,target.locus)
        assert barrier["target_epoch"] == first.state["epoch"] + 1
        assert client.snapshot()["pending_handoff_digest"] == barrier["barrier_digest"]
        with pytest.raises(EffectFencingRefused,match="handoff barrier"):
            client.apply(old)

        _kill(process)
        after_restart, info2 = _start(tmp_path,certificates)
        client2 = _client(info2,certificates)
        assert client2.snapshot()["pending_handoff_digest"] == barrier["barrier_digest"]
        with pytest.raises(EffectFencingRefused,match="handoff barrier"):
            client2.apply(old)

        # Quorum hasn't changed despite service death; only the exact
        # previously acknowledged target can now be committed and activated.
        new_lineage = _lineage(tmp_path)
        assert new_lineage.restore_latest().manifest.digest == first.manifest.digest
        assigned = new_lineage.assign(first,target)
        with pytest.raises(EffectFencingRefused,match="handoff barrier"):
            client2.apply(old)
        activated = client2.activate(assigned.manifest.digest)
        assert activated["event"] == "assign"
        assert client2.snapshot()["pending_handoff_digest"] is None
        with pytest.raises(EffectFencingRefused,match="stale"):
            client2.apply(old)

        next_os,next_pid = _restart(envelope)
        final = new_lineage.publish(
            assigned,new_lineage.compute(assigned,target,next_os,next_pid),
        )
        client2.activate(final.manifest.digest)
        accepted = client2.apply(published_effect(final,RESOURCE))
        assert accepted["value"] == 16
        assert client2.snapshot()["accepted_effects"] == 2
        assert client2.snapshot()["register_value"] == 16

        # A live CA-signed wrong subject is not a valid owner identity.
        wrong_client = _client(info2,certificates,certificate="C")
        with pytest.raises((EffectReceiverServiceError,EffectFencingRefused)):
            wrong_client.snapshot()
        wrong_dns = _client(info2,certificates,dns="member-c.mailcpu.test")
        with pytest.raises(EffectReceiverServiceError,match="TLS"):
            wrong_dns.snapshot()
        assert client2.snapshot()["accepted_effects"] == 2
    finally:
        _kill(process)
        if after_restart is not None:
            _kill(after_restart)


@pytest.mark.skipif(shutil.which("openssl") is None, reason="OpenSSL CLI needed for real mTLS identities")
def test_real_tls_barrier_preparation_and_activation_are_current_quorum_only(tmp_path: Path) -> None:
    """Old quorum roots and unprepared successor states cannot be remotely promoted."""
    lineage,first,_ = _published_first(tmp_path)
    certificates = _make_certificates(tmp_path)
    process,info = _start(tmp_path,certificates)
    try:
        client = _client(info,certificates)
        client.activate(first.manifest.digest)
        wrong = "0"*64
        with pytest.raises(EffectFencingRefused,match="current quorum"):
            client.prepare(wrong,"future-host")
        target = _host(tmp_path,"unprepared-tls")
        new = lineage.assign(first,target)
        with pytest.raises(EffectFencingRefused,match="requires prepared handoff"):
            client.activate(new.manifest.digest)
        with pytest.raises(EffectFencingRefused,match="current quorum"):
            client.prepare(first.manifest.digest,target.locus)
        assert client.snapshot()["installed_root"] == first.manifest.digest
    finally:
        _kill(process)
