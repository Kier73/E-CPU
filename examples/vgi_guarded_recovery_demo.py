"""Two real Python processes demonstrate native E-CPU M1/M3/M4 VGI continuity.

Run from the checked-out E-CPU root after installing the pinned VGI interpreter:
    python examples/vgi_guarded_recovery_demo.py bootstrap /tmp/vgi-proof
    python examples/vgi_guarded_recovery_demo.py resume /tmp/vgi-proof

The second invocation reopens independent quorum journals and re-admits the
exact M1 page bytes. The checkpoint-keyed *local test observer* is not a remote
host attestation or proof of any live external data source.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path

from vgi.guarded_reduction import GuardedAction, GuardedGround, discover_guarded_reduction
from vgi.symbolic_reduction import AffineAction
from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.computational_session import ComputationalSessionStore, ComputationalSessionCheckpoint
from mailcpu.recovery_lineage import RecoveryLineageAuthority, RecoveryLineageCoordinator
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.vgi_guarded_runtime import admit_vgi_guarded_runtime, vgi_guarded_backend_profile
from mailcpu.vgi_guarded_recovery import (
    STATE_SCHEMA, CheckpointSourceObservation, GuardedProgram, VGIDurableGroundSession,
)

GENESIS = sha256(b"ecpu-vgi-guarded-recovery-two-process-genesis").hexdigest()
SESSION = "guarded-two-process-session"
PAGE_SIZE = 256


class FilesystemPages:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.page_size = PAGE_SIZE

    def put_page(self, data: bytes) -> str:
        if type(data) is not bytes or len(data) != PAGE_SIZE:
            raise ValueError("incorrect page geometry")
        digest = sha256(data).hexdigest()
        file = self.root / digest
        if file.is_symlink():
            raise ValueError("symlink in content-addressed M1 store")
        if not file.exists():
            try:
                fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
        if file.is_symlink() or file.read_bytes() != data:
            raise ValueError("content-addressed page mismatch")
        return digest

    def get_page(self, digest: str) -> bytes:
        if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("malformed page identity")
        file = self.root / digest
        if file.is_symlink():
            raise ValueError("symlink in content-addressed M1 store")
        data = file.read_bytes()
        if len(data) != PAGE_SIZE or sha256(data).hexdigest() != digest:
            raise ValueError("corrupt M1 page")
        return data


def program() -> tuple[GuardedProgram, GuardedGround, GuardedGround]:
    n = 48
    I = tuple(tuple(int(i == j) for j in range(n)) for i in range(n))
    update = (1,) + (0,) * (n-1)
    action = GuardedAction("tick", (0,1)+(0,)*(n-2), 1,
        AffineAction("tick", I, update), AffineAction("tick", I, (0,)*n))
    old = GuardedGround(2,n,(action,),((1,)+(0,)*(n-1),),(0,))
    new = GuardedGround(2,n,(action,),((1,)+(0,)*(n-1),(0,0,1)+(0,)*(n-3)),(0,0))
    return GuardedProgram.admit(((old, discover_guarded_reduction(old)),
                                 (new, discover_guarded_reduction(new)))), old, new


def session(root: Path, node: str, prg: GuardedProgram, source_observer=None) -> VGIDurableGroundSession:
    artifact, _ = admit_vgi_guarded_runtime()
    backend = vgi_guarded_backend_profile(artifact)
    member = SeedCommitMembership(SESSION,1,("A","B","C"),"A",1,GENESIS)
    authorities = {key: RecoveryLineageAuthority(
        member, key, root / "quorum" / f"{key}.jsonl") for key in member.member_ids}
    lineage = RecoveryLineageCoordinator(member, authorities)
    objects = ComputationalObjectStore(FilesystemPages(root / node / "pages"), chunk_size=PAGE_SIZE)
    store = ComputationalSessionStore(root / node / "checkpoints", objects, lineage,
        artifact_manifest_digest=artifact.manifest_digest,
        backend_fingerprint=backend.fingerprint,
        state_schema_id=STATE_SCHEMA,
        state_media_type="application/vnd.mailcpu.guarded-session+json")
    return VGIDurableGroundSession(store, prg, source_observer=source_observer)


def _write(root: Path, name: str, data: bytes) -> None:
    path = root / name
    temp = root / (name + ".temporary")
    with temp.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)


def _json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def bootstrap(root: Path) -> dict:
    prg, old, _ = program()
    receiver = session(root, "receiver-A", prg)
    state = (0,1,1)+(0,)*45
    initial = receiver.initialize(state)
    first = receiver.advance(("tick",)*16, operation_id="phase-A-16",
        expected_revision=initial.revision, expected_checkpoint_digest=initial.checkpoint_digest)
    for _ in range(16):
        state = old.step(state, "tick")
    _write(root, "transfer.json", _json(receiver.export_latest()))
    _write(root, "state-pages.bin", first.state_bytes)
    _write(root, "source-observation.json", _json({
        "checkpoint_digest": first.checkpoint_digest, "source_state": list(state)}))
    return {"phase":"bootstrap", "pid":os.getpid(), "revision":first.revision,
            "checkpoint_digest":first.checkpoint_digest,
            "lineage_digest":first.lineage_manifest.digest,
            "quotient":receiver.inspect()["coordinates"],
            "source_dimensions":old.dimension}


def resume(root: Path) -> dict:
    prg, _, new = program()
    observation = json.loads((root / "source-observation.json").read_text())
    def receiver_observe(context):
        return CheckpointSourceObservation(observation["checkpoint_digest"],
                                           tuple(observation["source_state"]))
    receiver = session(root, "receiver-B", prg, source_observer=receiver_observe)
    export = json.loads((root / "transfer.json").read_text())
    prior = ComputationalSessionCheckpoint.from_dict(export["checkpoint"])
    state = (root / "state-pages.bin").read_bytes()
    reanchored = receiver.store.object_store.put_bytes(state,
        media_type=receiver.store.state_media_type)
    if reanchored.manifest_digest != prior.state_manifest.manifest_digest:
        raise ValueError("transferred M1 state bytes do not match committed checkpoint")
    imported = receiver.restore_export(export)
    migration = receiver.migrate(operation_id="phase-B-migration", target=1,
        expected_revision=imported.revision, expected_checkpoint_digest=imported.checkpoint_digest)
    current = receiver.inspect()
    x = tuple(observation["source_state"])
    assert current["coordinates"] == list(prg.stages[1].admitted.project(x))
    next_rev = receiver.advance(("tick",)*7, operation_id="phase-B-7",
        expected_revision=migration.revision, expected_checkpoint_digest=migration.checkpoint_digest)
    for _ in range(7):
        x = new.step(x,"tick")
    assert receiver.inspect()["coordinates"] == list(prg.stages[1].admitted.project(x))
    return {"phase":"resume", "pid":os.getpid(), "revision":next_rev.revision,
            "checkpoint_digest":next_rev.checkpoint_digest,
            "lineage_digest":next_rev.lineage_manifest.digest,
            "quotient":receiver.inspect()["coordinates"],
            "one_probe":len(current["last_event"]["probes"])==1,
            "total_virtual_steps":receiver.inspect()["virtual_steps"]}


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("phase", choices=("bootstrap","resume"))
    parser.add_argument("root", type=Path)
    args=parser.parse_args()
    args.root.mkdir(parents=True,exist_ok=True)
    output = bootstrap(args.root) if args.phase=="bootstrap" else resume(args.root)
    print(json.dumps(output,sort_keys=True))


if __name__ == "__main__":
    main()
