"""IPS-006 fixture: independently killed and reopened generated-Ground owner.

The owner is never given an IPS-005 checkpoint on its recovery invocation.
It has only the fixed code palette/intention, configured trust, its durable
owner authority journal, and a separate content-addressed state archive.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import ssl
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mailcpu import (  # noqa: E402
    HeadlessOS, SeedCommitMembership, SystemIdentity, SystemSeed,
    SystemSeedEnvelope, VirtualGroundRef,
)
from mailcpu.evidence_path_resolver import RouteMetric  # noqa: E402
from mailcpu.generative_ground_construction import (  # noqa: E402
    AffineBehaviorIntention, AffinePrimitive, synthesize_ground,
)
from mailcpu.generated_ground_authority_fabric import (  # noqa: E402
    PinnedRecoveryAuthority, connect_generated_ground_quorum,
)
from mailcpu.inverse_architecture_synthesis import ProposedRelation  # noqa: E402
from mailcpu.qualified_generated_ground import QualifiedGroundExecution  # noqa: E402
from mailcpu.semantic_translation import RepresentationRef  # noqa: E402

GENESIS = hashlib.sha256(b"ips006-independent-authority-genesis-v1").hexdigest()


def _plan():
    """Reconstruct the exact intended mathematical law and available palette."""
    relation = ProposedRelation(
        "e"*64,
        RepresentationRef.from_payload("ips005", 1, {"end":"in"}),
        RepresentationRef.from_payload("ips005", 1, {"end":"out"}),
        "b"*64, "c"*64, "d"*64,
        (RouteMetric("latency_us","us",1),),
    )
    goal = AffineBehaviorIntention(relation, 17, 4, 11, 9)
    primitives = (
        AffinePrimitive("first",17,3,2),
        AffinePrimitive("second",17,8,5),
        AffinePrimitive("distractor",17,1,1),
    )
    return goal, primitives, synthesize_ground(goal,primitives)


def _connection(root: Path, *, degraded: bool):
    """Bind only locally provisioned, server-SAN-pinned E-CPU mTLS authorities."""
    membership = SeedCommitMembership(
        "ips005-generated-machine", 1, ("A","B","C"), "A", 1, GENESIS,
    )
    endpoints = json.loads((root/"authority-endpoints.json").read_text(encoding="utf-8"))
    if not isinstance(endpoints, dict) or set(endpoints) != {"B", "C"}:
        raise ValueError("expected exact trusted recovery membership endpoints")
    identities = {"B": "member-b.mailcpu.test", "C": "member-c.mailcpu.test"}
    pins = []
    for member in ("B","C"):
        ep = endpoints[member]
        if not isinstance(ep, dict) or set(ep) != {"host","port","dns"}:
            raise ValueError("invalid pinned member endpoint")
        if ep["dns"] != identities[member] or type(ep["port"]) is not int:
            raise ValueError("remote authority certificate identity not trusted")
        pins.append(PinnedRecoveryAuthority(
            member, ep["host"], ep["port"], ep["dns"],
        ))
    client = ssl.create_default_context(
        ssl.Purpose.SERVER_AUTH, cafile=str(root/"ca.pem"),
    )
    client.minimum_version = ssl.TLSVersion.TLSv1_2
    client.load_cert_chain(str(root/"A.pem"), str(root/"A.key"))
    goal, primitives, plan = _plan()
    return connect_generated_ground_quorum(
        membership, root/"authorities"/"A.jsonl",
        tuple(pins), client, root/"ground-artifacts",
        plan, goal, primitives, degraded=degraded,
        timeout=.6, handshake_timeout=.6, connection_attempts=5,
    )


def _mark(path: Path, value: dict) -> None:
    """Flush a bounded JSON readiness/result record before reporting success."""
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()
    with path.open("wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: list[str]) -> int:
    """Seal then remain running for a real SIGKILL, or recover without input."""
    if len(argv) != 2 or argv[0] not in ("seal", "recover"):
        raise ValueError("expected seal/recover and root directory")
    action, root_string = argv
    root = Path(root_string)
    with _connection(root, degraded=action=="recover") as connection:
        if action=="seal":
            os_instance = HeadlessOS()
            identity = SystemIdentity("ips005-generated-machine",1)
            envelope = SystemSeedEnvelope(
                identity, "executor", "ips006",
                SystemSeed.from_system(os_instance),
            )
            if not os_instance.seed_admission.admit(envelope).accepted:
                raise ValueError("generated Ground seed was refused")
            ground = VirtualGroundRef.from_envelope(envelope)
            goal, primitives, plan = _plan()
            session = QualifiedGroundExecution(
                plan,goal,primitives,identity,ground,
            )
            committed = connection.publisher.bootstrap(session)
            _mark(root/"owner-committed.json", {
                "generation":committed.manifest.generation,
                "root":committed.manifest.digest,
                "checkpoint_digest":committed.checkpoint["digest"],
                "members": list(connection.connected_members),
            })
            # The fixture intentionally remains a live owner after sealing;
            # the parent harness performs a hard OS kill, not graceful exit.
            while True:
                time.sleep(.1)
        else:
            # No original checkpoint path/digest is passed to this process.
            # A restored root is discovered through the majority journals.
            head = connection.restore_latest()
            _mark(root/"owner-recovered.json", {
                "generation":head.manifest.generation,
                "root":head.manifest.digest,
                "checkpoint_digest":head.checkpoint["digest"],
                "members":list(connection.connected_members),
                "unavailable":list(connection.unavailable_members),
                "stages":len(head.checkpoint["payload"]["stages"]),
                "assignment":head.assignment,
            })
    return 0


if __name__=="__main__":
    raise SystemExit(main(sys.argv[1:]))
