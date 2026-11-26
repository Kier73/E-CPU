"""Actual subprocess destruction at native M3 publication cuts.

Local file pages and three durable journals share a physical failure domain.
The cut is before the second COMMIT or after commit_state returns, not an
arbitrary instruction-level or power-loss test.
"""
import hashlib
import multiprocessing
import os
from pathlib import Path

import pytest

from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.computational_session import ComputationalSessionStore
from mailcpu.recovery_lineage import RecoveryLineageAuthority, RecoveryLineageCoordinator
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.rrns import affine_orbit_jump


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class DiskPages:
    page_size = 32

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put_page(self, data):
        assert len(data) == self.page_size
        key = sha(data)
        path = self.root / key
        if not path.exists():
            temporary = self.root / (key + ".tmp")
            with temporary.open("wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        assert path.read_bytes() == data
        return key

    def get_page(self, key):
        value = (self.root / key).read_bytes()
        assert sha(value) == key and len(value) == self.page_size
        return value


class PauseBeforeCommit(RecoveryLineageAuthority):
    def __init__(self, membership, member_id, journal, ready, hold):
        super().__init__(membership, member_id, journal)
        self.ready = ready
        self.hold = hold

    def commit(self, proposal, certificate):
        if proposal.slot > 1:
            self.ready.set()
            self.hold.wait(120)
            raise RuntimeError("parent failed to terminate interrupted coordinator")
        return super().commit(proposal, certificate)


def store(root, cut=None, ready=None, hold=None):
    root = Path(root)
    membership = SeedCommitMembership("ec-stress-003", 1, ("A", "B", "C"), "A", 1, sha(b"genesis"))
    authorities = {}
    for member in membership.member_ids:
        journal = root / "authorities" / (member + ".jsonl")
        if cut == "minority" and member == "B":
            authorities[member] = PauseBeforeCommit(membership, member, journal, ready, hold)
        else:
            authorities[member] = RecoveryLineageAuthority(membership, member, journal)
    return ComputationalSessionStore(
        root / "state", ComputationalObjectStore(DiskPages(root / "pages"), chunk_size=32),
        RecoveryLineageCoordinator(membership, authorities),
        artifact_manifest_digest=sha(b"affine-64"), backend_fingerprint=sha(b"rrns"),
        state_schema_id="affine.u64.v1",
    )


def candidate(initial, coordinate):
    a, b = 5, 7
    A, B = affine_orbit_jump(a, b, 1 << 64, coordinate)
    return ((A * int.from_bytes(initial, "little") + B) % (1 << 64)).to_bytes(8, "little")


def advance(s, old, coordinate):
    return s.commit_state(
        candidate(old.state_bytes, coordinate),
        expected_revision=old.revision,
        expected_checkpoint_digest=old.checkpoint_digest,
        transition_id=f"jump-{coordinate}",
        operation_id="affine.jump",
        input_digest=sha(str(coordinate).encode()),
        logical_time=coordinate,
    )


def child(root, cut, coordinate, ready, hold):
    s = store(root, cut, ready, hold)
    old = s.load_latest()
    advance(s, old, coordinate)
    if cut == "minority":
        raise AssertionError("minority cut was not reached")
    ready.set()
    hold.wait(120)


@pytest.mark.parametrize("cut", ["minority", "ack-lost"])
def test_native_m3_actual_coordinator_death(tmp_path, cut):
    ctx = multiprocessing.get_context("spawn")
    initial = store(tmp_path).create_session((123).to_bytes(8, "little"))
    coordinate = (1 << 60) + 12345
    ready, hold = ctx.Event(), ctx.Event()
    proc = ctx.Process(target=child, args=(tmp_path, cut, coordinate, ready, hold))
    proc.start()
    try:
        assert ready.wait(30), "child never reached declared crash cut"
        assert proc.is_alive()
        proc.kill()
        proc.join(10)
        assert not proc.is_alive() and proc.exitcode != 0
    finally:
        if proc.is_alive():
            proc.kill()
            proc.join(10)

    recovered = store(tmp_path)
    if cut == "minority":
        assert recovered.load_latest().revision == 1
        result = recovered.resume_pending()
    else:
        result = recovered.load_latest()
        assert advance(recovered, initial, coordinate).replayed
    assert result.revision == 2
    # Independent geometric sum (divide exactly before modular reduction).
    m = 1 << 64
    geom = (pow(5, coordinate, 4*m) - 1) // 4
    expected = (pow(5, coordinate, m)*123 + 7*geom) % m
    assert int.from_bytes(result.state_bytes, "little") == expected
    assert store(tmp_path).load_latest().checkpoint_digest == result.checkpoint_digest
