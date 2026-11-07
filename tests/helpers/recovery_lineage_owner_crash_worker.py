"""Owner-authority crash-cut helper for recovery-lineage process tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mailcpu import RecoveryLineageAuthority, RecoveryLineageCoordinator, SeedCommitMembership  # noqa: E402
from mailcpu.recovery_lineage import RecoveryCheckpointManifest  # noqa: E402


def _write_marker(path: Path, payload: dict[str, object]) -> None:
    """Mathematics: fsync one owner-vote witness and atomically publish its crash-cut marker."""

    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main(arguments: list[str]) -> int:
    """Mathematics: durably prepare the fixed owner vote, publish the witness, and hard-exit before coordination can continue."""

    if len(arguments) != 4:
        raise ValueError("owner worker requires membership, journal, manifest, and marker paths")
    membership_path, journal_path, manifest_path, marker_path = arguments
    membership = SeedCommitMembership.from_snapshot(
        json.loads(Path(membership_path).read_text(encoding="utf-8"))
    )
    manifest = RecoveryCheckpointManifest.from_snapshot(
        json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    )
    authority = RecoveryLineageAuthority(membership, membership.owner_id, journal_path)
    coordinator = RecoveryLineageCoordinator(membership, {membership.owner_id: authority})
    proposal = coordinator.proposal_for(manifest)
    vote = authority.prepare(proposal)
    _write_marker(
        Path(marker_path),
        {"member_id": membership.owner_id, "proposal": proposal.snapshot(), "vote": vote.snapshot(), "pid": os.getpid()},
    )
    os._exit(91)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
