"""Restartable standalone recovery-lineage anchor for federated relay process tests."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mailcpu import (  # noqa: E402
    RecoveryLineageProcessParticipant,
    SeedCommitMembership,
    SocketTransport,
)


def main(arguments: list[str]) -> int:
    """Mathematics: serve one durable authority journal across repeated owner reconnects."""
    if len(arguments) != 3:
        raise ValueError("anchor worker requires member id, membership file, and journal path")
    member_id, membership_path, journal_path = arguments
    membership = SeedCommitMembership.from_snapshot(
        json.loads(Path(membership_path).read_text(encoding="utf-8"))
    )
    listener = SocketTransport.listen("127.0.0.1", 0)
    print(json.dumps({
        "member_id": member_id,
        "port": listener.getsockname()[1],
        "pid": __import__("os").getpid(),
    }, sort_keys=True), flush=True)
    while True:
        transport = SocketTransport.accept(listener, member_id, membership.owner_id)
        participant = RecoveryLineageProcessParticipant(
            membership,
            member_id,
            journal_path,
            transport,
        )
        try:
            while not transport.closed:
                participant.service_once()
                time.sleep(0.002)
        except Exception:
            # The owner may be hard-killed between any two durable authority
            # transitions. Reopen the same journal for the next owner stream.
            pass
        finally:
            transport.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
