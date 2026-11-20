"""IPS-007: the resource checks the fence in the same durable effect transaction."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest

from mailcpu.fenced_effect_receiver import (
    EffectFencingRefused, FencedGroundEffectReceiver, PublishedGroundEffect,
    published_effect,
)
from mailcpu.fenced_generated_ground import FencedGroundHead, FencedGroundError
from mailcpu.recovery_lineage import RecoveryLineageError
from mailcpu.semantic_translation import canonical_value_digest

from test_fenced_generated_ground import _bootstrap, _host, _restart, _lineage

RESOURCE = "/virtual-layer/effects/ips007-register"


def _published_two_stage(root: Path):
    """Create two independently verified IPS-004 stages and distinct quorum heads."""
    lineage, original, os, envelope, pid = _bootstrap(root)
    host0 = _host(root, "ips007-stage-zero")
    first_assignment = lineage.assign(original, host0)
    first_candidate = lineage.compute(first_assignment, host0, os, pid)
    first = lineage.publish(first_assignment, first_candidate)
    host1 = _host(root, "ips007-stage-one")
    second_assignment = lineage.assign(first, host1)
    next_os, next_pid = _restart(envelope)
    second_candidate = lineage.compute(second_assignment, host1, next_os, next_pid)
    final = lineage.publish(second_assignment, second_candidate)
    assert lineage._session(final.checkpoint).complete
    assert lineage._session(final.checkpoint).value == 16
    return lineage, original, first_assignment, first, second_assignment, final


def test_quorum_published_stage_writes_exact_receiver_register_once(
    tmp_path: Path,
) -> None:
    """Only a checked IPS-005 published Ground can mutate the selected resource."""
    lineage, _, _, first, _, final = _published_two_stage(tmp_path)
    receiver = FencedGroundEffectReceiver(tmp_path/"receiver.db", resource=RESOURCE, plan_digest=lineage.plan.digest)
    assert receiver.snapshot()["register_value"] is None

    # A stage-0 publication was valid historically but is no longer
    # the current majority head once stage 1 has been published.
    with pytest.raises(RecoveryLineageError, match="stale"):
        receiver.install(lineage, first)
    authorized = receiver.install(lineage, final)
    assert authorized["event"] == "publish"
    claim = published_effect(final, RESOURCE)
    assert claim.stage_index == 1
    assert claim.value == 16
    result = receiver.apply(claim)
    assert result["committed"] is True
    assert result["value"] == 16
    assert result["root"] == final.manifest.digest
    assert result["physical_host_attested"] is False
    assert result["quorum_snapshot_is_bearer_authority"] is False
    assert receiver.apply(claim) == result
    assert receiver.snapshot()["register_value"] == 16
    assert receiver.snapshot()["accepted_effects"] == 1

    reopened = FencedGroundEffectReceiver(tmp_path/"receiver.db", resource=RESOURCE, plan_digest=lineage.plan.digest)
    assert reopened.apply(claim) == result
    assert reopened.snapshot()["accepted_effects"] == 1
    with pytest.raises(EffectFencingRefused, match="resource"):
        reopened.apply(replace(claim, resource="/virtual-layer/effects/other"))
    with pytest.raises(EffectFencingRefused, match="different Ground plan"):
        FencedGroundEffectReceiver(
            tmp_path/"receiver.db", resource=RESOURCE, plan_digest="0"*64,
        )



def test_unpublished_candidate_never_grants_external_side_effect(
    tmp_path: Path,
) -> None:
    """A mathematically correct computation without publication has no effect."""
    lineage, original, os, _, pid = _bootstrap(tmp_path)
    receiver = FencedGroundEffectReceiver(tmp_path/"effects.db", resource=RESOURCE, plan_digest=lineage.plan.digest)
    h_old = _host(tmp_path,"old-unpublished")
    h_new = _host(tmp_path,"new-authorized")
    assigned = lineage.assign(original, h_old)
    old_candidate = lineage.compute(assigned, h_old, os, pid)
    newer = lineage.assign(assigned, h_new)
    # Only the *assignment* has been sealed. No stage result was published.
    receiver.install(lineage, newer)
    state = receiver.snapshot()
    assert state["installed_event"] == "reassign"
    assert state["accepted_effects"] == 0

    # Forge an inert request using real old mathematical output. The receiver
    # must reject it because its installed root is an assignment, not publish.
    old_receipt = old_candidate.next_checkpoint["payload"]["stages"][0]["stage_receipt"]
    bad = PublishedGroundEffect(
        RESOURCE, assigned.manifest.generation, assigned.manifest.digest,
        lineage.plan.digest, old_candidate.next_checkpoint["digest"], 1, 0,
        h_old.locus, old_receipt["receipt_digest"],
        old_receipt["output"]["value"],
    )
    with pytest.raises(EffectFencingRefused, match="stale, unpublished"):
        receiver.apply(bad)
    assert receiver.snapshot()["register_value"] is None


def test_atomic_effect_rollback_if_receiver_write_fails(
    tmp_path: Path,
) -> None:
    """A failed register update cannot leave an accepted effect receipt behind."""
    lineage, _, _, _, _, final = _published_two_stage(tmp_path)
    path = tmp_path/"atomic.db"
    receiver = FencedGroundEffectReceiver(path, resource=RESOURCE, plan_digest=lineage.plan.digest)
    receiver.install(lineage, final)
    claim = published_effect(final, RESOURCE)
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TRIGGER ips007_abort_write BEFORE INSERT ON registers
            BEGIN
                SELECT RAISE(ABORT, 'forced register failure');
            END;
        """)
    with pytest.raises(sqlite3.IntegrityError, match="forced register failure"):
        receiver.apply(claim)
    assert receiver.snapshot()["register_value"] is None
    assert receiver.snapshot()["accepted_effects"] == 0

    with sqlite3.connect(path) as db:
        db.execute("DROP TRIGGER ips007_abort_write")
    accepted = receiver.apply(claim)
    assert accepted["committed"]
    assert receiver.snapshot()["accepted_effects"] == 1
    assert receiver.snapshot()["register_value"] == 16


def test_multiple_threads_same_published_effect_commit_once(
    tmp_path: Path,
) -> None:
    """Separate DB connections serialize the exact effect and its dedupe record."""
    lineage, _, _, _, _, final = _published_two_stage(tmp_path)
    receiver = FencedGroundEffectReceiver(tmp_path/"threads.db", resource=RESOURCE, plan_digest=lineage.plan.digest)
    receiver.install(lineage, final)
    request = published_effect(final, RESOURCE)
    with ThreadPoolExecutor(max_workers=6) as pool:
        receipts = list(pool.map(receiver.apply, (request,)*12))
    assert len({r["digest"] for r in receipts}) == 1
    assert receiver.snapshot()["accepted_effects"] == 1
    assert receiver.snapshot()["register_value"] == 16


def test_separate_process_paused_old_effect_is_rejected_after_new_root(
    tmp_path: Path,
) -> None:
    """Old process sees a correct claim, then newer authority installs before its write."""
    lineage, original, os, envelope, pid = _bootstrap(tmp_path)
    host0 = _host(tmp_path, "first-host")
    first_assigned = lineage.assign(original, host0)
    first = lineage.publish(
        first_assigned, lineage.compute(first_assigned, host0, os, pid)
    )
    claim0 = published_effect(first, RESOURCE)
    receiver = FencedGroundEffectReceiver(tmp_path/"interprocess.db", resource=RESOURCE, plan_digest=lineage.plan.digest)
    receiver.install(lineage, first)
    assert receiver.apply(claim0)["committed"] is True
    assert receiver.snapshot()["accepted_effects"] == 1

    claim_file = tmp_path/"old-request.json"
    claim_file.write_text(json.dumps(claim0.to_dict()), encoding="utf-8")
    ready, go = tmp_path/"old-ready", tmp_path/"release-old"
    worker = Path(__file__).parent/"helpers"/"ips007_effect_worker.py"
    process = subprocess.Popen(
        (sys.executable,str(worker),str(tmp_path/"interprocess.db"),
         RESOURCE,lineage.plan.digest,str(claim_file),str(ready),str(go)),
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        limit = time.monotonic()+10
        while not ready.is_file() and time.monotonic() < limit:
            if process.poll() is not None:
                raise AssertionError("effect worker exited before barrier")
            time.sleep(.02)
        assert ready.is_file()

        # New stage assignment is a quorum-sealed revocation of the prior
        # published root at this receiver, even though it has no new effect.
        next_host = _host(tmp_path,"next-host")
        later_assignment = lineage.assign(first,next_host)
        receiver.install(lineage,later_assignment)
        assert receiver.snapshot()["installed_event"] == "assign"
        go.write_text("go",encoding="utf-8")
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr
        result = json.loads(stdout)
        assert result["accepted"] is False
        assert "stale" in result["reason"]
        assert receiver.snapshot()["register_value"] == claim0.value
        assert receiver.snapshot()["accepted_effects"] == 1

        # Restore receiver DB from a different Python object and perform
        # the next stage only with the newly published, verified quorum head.
        next_os,next_pid = _restart(envelope)
        final = lineage.publish(
            later_assignment,
            lineage.compute(later_assignment,next_host,next_os,next_pid),
        )
        reopened = FencedGroundEffectReceiver(
            tmp_path/"interprocess.db", resource=RESOURCE, plan_digest=lineage.plan.digest,
        )
        reopened.install(lineage,final)
        claim1 = published_effect(final,RESOURCE)
        assert reopened.apply(claim1)["value"] == 16
        assert reopened.snapshot()["accepted_effects"] == 2
        assert reopened.snapshot()["register_value"] == 16
        with pytest.raises(EffectFencingRefused,match="stale"):
            reopened.apply(claim0)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


def test_bad_claims_cannot_change_current_register(
    tmp_path: Path,
) -> None:
    """Changing root, host, coordinate, receipt or output cannot bypass the fence."""
    lineage, _, _, _, _, head = _published_two_stage(tmp_path)
    receiver = FencedGroundEffectReceiver(tmp_path/"negative.db", resource=RESOURCE, plan_digest=lineage.plan.digest)
    receiver.install(lineage,head)
    proper = published_effect(head,RESOURCE)
    bad = [
        replace(proper, manifest_digest="0"*64),
        replace(proper, checkpoint_digest="0"*64),
        replace(proper, plan_digest="0"*64),
        replace(proper, host_id="former-host"),
        replace(proper, receipt_digest="0"*64),
        replace(proper, epoch=proper.epoch+1),
        replace(proper, stage_index=0),
        replace(proper, value=proper.value+1),
    ]
    for item in bad:
        with pytest.raises(EffectFencingRefused,match="stale"):
            receiver.apply(item)
    with pytest.raises(EffectFencingRefused,match="schema"):
        PublishedGroundEffect.from_dict(proper.to_dict()|{"unexpected":True})
    assert receiver.snapshot()["accepted_effects"] == 0
    assert receiver.apply(proper)["committed"] is True


def test_install_requires_quorum_current_and_native_checkpoint_integrity(
    tmp_path: Path,
) -> None:
    """A valid archived hash alone cannot install an unauthorized effect root."""
    lineage, _, _, first, _, final = _published_two_stage(tmp_path)
    receiver = FencedGroundEffectReceiver(tmp_path/"quorum.db", resource=RESOURCE, plan_digest=lineage.plan.digest)
    with pytest.raises(RecoveryLineageError,match="stale"):
        receiver.install(lineage,first)

    minority = _lineage(tmp_path,members=("authority-a",))
    with pytest.raises(RecoveryLineageError,match="read quorum"):
        receiver.install(minority,final)
    assert receiver.snapshot()["installed_generation"] is None

    altered = deepcopy(final.state)
    altered["checkpoint"]["payload"]["stages"][-1]["stage_receipt"]["output"]["value"] += 1
    fake = FencedGroundHead(final.manifest,json.dumps(altered,sort_keys=True))
    with pytest.raises((FencedGroundError, RecoveryLineageError, ValueError)):
        receiver.install(lineage,fake)
    receiver.install(lineage,final)
    with pytest.raises(RecoveryLineageError,match="stale"):
        receiver.install(lineage,first)


def test_rebooted_receiver_keeps_monotonic_fence_and_rejects_rollback(
    tmp_path: Path,
) -> None:
    """Committed installed authority cannot be reset by reopening the DB."""
    lineage, _, _, _, _, final = _published_two_stage(tmp_path)
    path = tmp_path/"restart.db"
    receiver = FencedGroundEffectReceiver(path, resource=RESOURCE, plan_digest=lineage.plan.digest)
    receiver.install(lineage,final)
    claim = published_effect(final,RESOURCE)
    assert receiver.apply(claim)["committed"]
    original = receiver.snapshot()
    del receiver
    again = FencedGroundEffectReceiver(path, resource=RESOURCE, plan_digest=lineage.plan.digest)
    assert again.snapshot() == original
    assert again.apply(claim)["committed"]
    assert again.snapshot()["accepted_effects"] == 1
