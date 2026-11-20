"""IPS-005: quorum-anchored assignment, rehoming, and late-result fencing."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path
import sys

import pytest

from mailcpu import (
    Capability, HeadlessOS, HypervisorPolicy, LexicalDecisionModel,
    SystemIdentity, SystemSeed, SystemSeedEnvelope, VirtualGroundRef,
)
from mailcpu.evidence_path_resolver import RouteMetric
from mailcpu.fenced_generated_ground import (
    FencedGroundCandidate, FencedGroundError, FencedGroundLineage,
)
from mailcpu.generative_ground_construction import (
    AffineBehaviorIntention, AffinePrimitive, synthesize_ground,
)
from mailcpu.ground_native_realization import RealizationPolicy
from mailcpu.inverse_architecture_synthesis import ProposedRelation
from mailcpu.qualified_generated_ground import QualifiedGroundExecution, QualifiedStageHost
from mailcpu.recovery_lineage import (
    RecoveryLineageAuthority, RecoveryLineageCoordinator, RecoveryLineageError,
)
from mailcpu.runtime_qualification import (
    QualificationPolicy, SubprocessQualificationEndpoint, qualify,
)
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.semantic_translation import RepresentationRef, canonical_value_digest

GENESIS = hashlib.sha256(b"ips005-native-generated-ground-genesis").hexdigest()


def _goal() -> AffineBehaviorIntention:
    """Describe the desired system without specifying its executable word."""
    relation = ProposedRelation(
        "e"*64,
        RepresentationRef.from_payload("ips005", 1, {"end":"in"}),
        RepresentationRef.from_payload("ips005", 1, {"end":"out"}),
        "b"*64, "c"*64, "d"*64, (RouteMetric("latency_us", "us", 1),),
    )
    return AffineBehaviorIntention(relation, 17, 4, 11, 9)


def _palette() -> tuple[AffinePrimitive, ...]:
    """Offer native mathematical operators that can be composed by IPS-003."""
    return (
        AffinePrimitive("first",17,3,2),
        AffinePrimitive("second",17,8,5),
        AffinePrimitive("distractor",17,1,1),
    )


def _receiver():
    """Admit one E-CPU virtual Ground and create a locally permitted Hypervisor."""
    os = HeadlessOS()
    os.hypervisor.classifier = LexicalDecisionModel()
    os.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    identity = SystemIdentity("ips005-generated-machine", 1)
    envelope = SystemSeedEnvelope(identity, "executor", "ips005", SystemSeed.from_system(os))
    assert os.seed_admission.admit(envelope).accepted
    ground = VirtualGroundRef.from_envelope(envelope)
    pid = os.environment.kernel.spawn(
        "ips005-executor",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=os.environment.init_pid,
    )
    return os, identity, envelope, ground, pid


def _restart(envelope: SystemSeedEnvelope):
    """Restore the same admitted virtual Ground on a different receiver OS."""
    os = HeadlessOS()
    os.hypervisor.classifier = LexicalDecisionModel()
    os.hypervisor.policy = HypervisorPolicy(embedding_review_confidence=1.0)
    assert os.seed_admission.admit(envelope).accepted
    pid = os.environment.kernel.spawn(
        "ips005-replacement",
        capabilities=(Capability("/virtual-layer/operators", frozenset({"compute"})),),
        parent_pid=os.environment.init_pid,
    )
    return os, pid


def _host(tmp_path: Path, name: str) -> QualifiedStageHost:
    """Qualify distinct fixed-vocabulary native subprocess worker identities."""
    directory = tmp_path / name
    directory.mkdir(parents=True)
    endpoint = SubprocessQualificationEndpoint(
        name, (sys.executable, "-m", "mailcpu.runtime_qualification_worker",
               "--host", name, "--directory", str(directory)),
        timeout=8,
    )
    policy = QualificationPolicy(
        frozenset({name}), "ips005-observer", 10,
        frozenset({"observer", "computational_fragment"}), max_calls=4,
    )
    report = qualify(endpoint, policy, coordinate=1, seed="ips005-qualification-seed")
    return QualifiedStageHost(
        name, endpoint, report.payload, policy,
        RealizationPolicy(frozenset({(name, "interpreter")}), 10),
    )


def _membership() -> SeedCommitMembership:
    """Configure a native fixed owner and three durable independent journals."""
    return SeedCommitMembership(
        "ips005-generated-machine", 1, ("authority-a", "authority-b", "authority-c"),
        "authority-a", 1, GENESIS,
    )


def _authorities(root: Path, membership: SeedCommitMembership):
    """Open each durable authority journal in its own distinct storage file."""
    return {
        member: RecoveryLineageAuthority(
            membership, member, root / f"{member}.jsonl"
        )
        for member in membership.member_ids
    }


def _lineage(root: Path, *, members=None):
    """Create an IPS-005 wrapper on existing independent recovery-lineage quorum."""
    membership = _membership()
    authority = _authorities(root, membership)
    if members is not None:
        authority = {k: v for k, v in authority.items() if k in members}
    goal, palette = _goal(), _palette()
    plan = synthesize_ground(goal, palette)
    assert plan.primitive_names == ("first", "second")
    native = RecoveryLineageCoordinator(membership, authority)
    return FencedGroundLineage(native, root/"artifacts", plan, goal, palette)


def _bootstrap(root: Path):
    """Seal one initial unassigned generated machine checkpoint in a majority."""
    os, identity, envelope, ground, pid = _receiver()
    lineage = _lineage(root)
    session = QualifiedGroundExecution(
        lineage.plan, lineage.intention, lineage.primitives,
        identity, ground,
    )
    head = lineage.bootstrap(session)
    assert lineage.lineage.high_water() == (1, head.manifest.digest)
    assert len(head.state["checkpoint"]["payload"]["stages"]) == 0
    return lineage, head, os, envelope, pid


def test_delayed_old_worker_is_fenced_after_quorum_rehome(tmp_path: Path) -> None:
    """An old genuine result can be correct yet no longer publishable."""
    lineage, head, os, envelope, pid = _bootstrap(tmp_path)
    old_host = _host(tmp_path, "old-host")
    replacement = _host(tmp_path, "replacement-host")

    old_assignment = lineage.assign(head, old_host)
    assert old_assignment.assignment["epoch"] == 1
    old_candidate = lineage.compute(old_assignment, old_host, os, pid)
    assert old_candidate.authoritative is False
    assert old_candidate.next_checkpoint["payload"]["stages"][0]["host"] == "old-host"

    # This is the late-response race: old pure work finished but the
    # publisher has not committed it. A majority reassigns the *same*
    # uncommitted stage to another independent host.
    current = lineage.assign(old_assignment, replacement)
    assert current.assignment["epoch"] == 2
    assert current.assignment["host_id"] == "replacement-host"
    assert current.checkpoint == old_assignment.checkpoint
    assert lineage.lineage.high_water() == (3, current.manifest.digest)

    with pytest.raises(RecoveryLineageError, match="stale"):
        lineage.publish(old_assignment, old_candidate)
    with pytest.raises(RecoveryLineageError, match="stale"):
        lineage.compute(old_assignment, old_host, os, pid)

    replacement_os, replacement_pid = _restart(envelope)
    fresh = lineage.compute(current, replacement, replacement_os, replacement_pid)
    anchored = lineage.publish(current, fresh)
    assert anchored.state["event"] == "publish"
    assert anchored.assignment is None
    assert anchored.state["epoch"] == 2
    assert anchored.checkpoint["payload"]["stages"][0]["host"] == "replacement-host"
    assert lineage.lineage.high_water() == (4, anchored.manifest.digest)
    with pytest.raises(RecoveryLineageError, match="stale"):
        lineage.publish(current, fresh)

    # Reopen every durable participant and an entirely new coordinator.
    reopened = _lineage(tmp_path)
    recovered = reopened.restore_latest()
    assert recovered.manifest.digest == anchored.manifest.digest
    assert recovered.checkpoint == anchored.checkpoint
    assert reopened._session(recovered.checkpoint).value is None
    # The prior host is neither available nor needed by the recovery path.
    final_host = _host(tmp_path, "third-host")
    next_assignment = reopened.assign(recovered, final_host)
    final_os, final_pid = _restart(envelope)
    final_candidate = reopened.compute(next_assignment, final_host, final_os, final_pid)
    finished = reopened.publish(next_assignment, final_candidate)
    assert reopened._session(finished.checkpoint).value == 16
    assert reopened._session(finished.checkpoint).complete
    assert [s["host"] for s in finished.checkpoint["payload"]["stages"]] == [
        "replacement-host", "third-host",
    ]
    assert reopened.lineage.high_water() == (6, finished.manifest.digest)
    with pytest.raises(FencedGroundError, match="already completed"):
        reopened.assign(finished, old_host)


def test_conflicting_assignments_cannot_both_commit_same_quorum_slot(tmp_path: Path) -> None:
    """Two independent coordinators racing on the same head get one slot."""
    lineage, head, _, _, _ = _bootstrap(tmp_path)
    competing = _lineage(tmp_path)
    first = _host(tmp_path, "first")
    second = _host(tmp_path, "second")
    accepted = lineage.assign(head, first)
    assert accepted.assignment["host_id"] == "first"
    # B's identical previous checkpoint is not an authority to
    # overwrite A's already committed assignment, even with different
    # content-addressed artifact bytes and an exact predecessor digest.
    with pytest.raises(RecoveryLineageError, match="stale"):
        competing.assign(head, second)
    assert competing.restore_latest().manifest.digest == accepted.manifest.digest


def test_rehome_interleaved_after_preflight_cannot_publish_under_new_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exact quorum-head check cannot be followed by a stale later-slot seal."""
    lineage, initial, os, _, pid = _bootstrap(tmp_path)
    old_host = _host(tmp_path, "slow-owner")
    next_host = _host(tmp_path, "winning-owner")
    assigned = lineage.assign(initial, old_host)
    old_candidate = lineage.compute(assigned, old_host, os, pid)
    competing = _lineage(tmp_path)

    original_seal = lineage._seal

    def seal_after_rival_reassign(state, *, capture_cut, expected_parent):
        """Place a real durable majority rehome after publish checked its head."""
        newer = competing.assign(assigned, next_host)
        assert newer.assignment["host_id"] == next_host.locus
        return original_seal(
            state, capture_cut=capture_cut, expected_parent=expected_parent,
        )

    monkeypatch.setattr(lineage, "_seal", seal_after_rival_reassign)
    with pytest.raises(FencedGroundError, match="expected parent"):
        lineage.publish(assigned, old_candidate)
    restored = competing.restore_latest()
    assert restored.assignment["host_id"] == next_host.locus
    assert restored.assignment["epoch"] == assigned.assignment["epoch"] + 1


def test_missing_read_quorum_prevents_assignment_and_compute(tmp_path: Path) -> None:
    """Local checkpoint presence cannot substitute for independent majority state."""
    full, head, os, _, pid = _bootstrap(tmp_path)
    host = _host(tmp_path, "quorum-test-host")
    assigned = full.assign(head, host)
    minority = _lineage(tmp_path, members=("authority-a",))
    with pytest.raises(RecoveryLineageError, match="read quorum"):
        minority.restore_latest()
    with pytest.raises(RecoveryLineageError, match="read quorum"):
        minority.compute(assigned, host, os, pid)
    assert len(assigned.checkpoint["payload"]["stages"]) == 0


def test_quorum_reads_require_latest_not_hash_valid_older_bytes(tmp_path: Path) -> None:
    """Older fully valid state artifacts cannot be restored after reassignment."""
    lineage, head, _, _, _ = _bootstrap(tmp_path)
    host = _host(tmp_path, "previous")
    old = lineage.assign(head, host)
    next_host = _host(tmp_path, "current")
    new = lineage.assign(old, next_host)
    with pytest.raises(RecoveryLineageError, match="stale"):
        lineage.restore(old)
    assert lineage.restore(new).assignment["host_id"] == "current"


def test_tampered_and_rehashed_stage_candidate_rejected_before_seal(tmp_path: Path) -> None:
    """Rehashing a false DAG or claiming another host cannot bypass Ground checks."""
    lineage, head, os, _, pid = _bootstrap(tmp_path)
    host = _host(tmp_path, "permitted-host")
    current = lineage.assign(head, host)
    candidate = lineage.compute(current, host, os, pid)
    with pytest.raises(FencedGroundError, match="candidate is fenced"):
        lineage.publish(current, replace(candidate, host_id="unqualified-host"))
    with pytest.raises(FencedGroundError, match="candidate is fenced"):
        lineage.publish(current, replace(candidate, assignment_epoch=1_000))
    with pytest.raises(FencedGroundError, match="candidate is fenced"):
        lineage.publish(current, replace(candidate, assignment_manifest_digest="0"*64))

    # Rehash the outer IPS-004 snapshot after corrupting the native DAG.
    corrupt = deepcopy(candidate.next_checkpoint)
    corrupt["payload"]["dag_snapshot"]["state"]["commits"][0]["result"]["value"] = 999
    corrupt["digest"] = canonical_value_digest(corrupt["payload"])
    with pytest.raises(FencedGroundError, match="checkpoint failed replay"):
        lineage.publish(current, replace(candidate, next_checkpoint=corrupt))
    assert lineage.lineage.high_water() == (2, current.manifest.digest)


def test_missing_compute_rights_do_not_publish_any_state(tmp_path: Path) -> None:
    """A valid assignment is not a substitute for origin Hypervisor capability."""
    lineage, head, os, _, _ = _bootstrap(tmp_path)
    host = _host(tmp_path, "qualified")
    assigned = lineage.assign(head, host)
    denied = os.environment.kernel.spawn(
        "denied-publisher",
        capabilities=(Capability("/unrelated", frozenset({"read"})),),
        parent_pid=os.environment.init_pid,
    )
    with pytest.raises(Exception):
        lineage.compute(assigned, host, os, denied)
    assert lineage.lineage.high_water() == (2, assigned.manifest.digest)
    assert len(lineage.restore_latest().checkpoint["payload"]["stages"]) == 0


def test_missing_artifact_refuses_restart_even_if_quorum_is_intact(tmp_path: Path) -> None:
    """The quorum root is not a backup of the checkpoint's full data bytes."""
    lineage, head, _, _, _ = _bootstrap(tmp_path)
    artifact = lineage._material(
        head.manifest.generation, head.manifest.state_digest, "state",
    )
    artifact.unlink()
    with pytest.raises(FileNotFoundError):
        _lineage(tmp_path).restore_latest()


def test_stale_primitive_or_wrong_machine_identity_is_not_recoverable(tmp_path: Path) -> None:
    """A content-valid certificate cannot migrate to another source definition."""
    lineage, head, _, _, _ = _bootstrap(tmp_path)
    revised = (replace(lineage.primitives[0], offset=3),) + lineage.primitives[1:]
    wrong = FencedGroundLineage(
        lineage.lineage, lineage.root,
        lineage.plan, lineage.intention, revised,
    )
    with pytest.raises(FencedGroundError, match="checkpoint failed replay"):
        wrong.restore_latest()
    altered = deepcopy(head.state)
    altered["checkpoint"]["payload"]["system"]["system_id"] = "different-machine"
    with pytest.raises(Exception):
        lineage._validate_state(altered)
