"""Child process hosting one durable recovery-lineage authority."""

from __future__ import annotations

import json
import os
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


def _durable_marker(path: Path, stage: str, member_id: str) -> None:
    """Mathematics: persist one crash-cut witness before terminating the authority interpreter."""

    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump({"stage": stage, "member_id": member_id, "pid": os.getpid()}, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main(arguments: list[str]) -> int:
    """Mathematics: bind one participant journal and serve its reliable peer stream until externally terminated."""

    if len(arguments) != 5:
        raise ValueError("worker requires member id, membership file, journal, fault stage, and marker path")
    member_id, membership_path, journal_path, fault_stage, marker_path = arguments
    membership = SeedCommitMembership.from_snapshot(
        json.loads(Path(membership_path).read_text(encoding="utf-8"))
    )
    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    print(json.dumps({"member_id": member_id, "port": port, "pid": os.getpid()}), flush=True)
    try:
        transport = SocketTransport.accept(listener, member_id, membership.owner_id)
    finally:
        listener.close()

    selected_fault = fault_stage if fault_stage != "-" else None
    marker = Path(marker_path)

    def fault_hook(stage: str, _proposal: object) -> None:
        """Mathematics: stop after the named journal fsync and before the reliable response/ACK is published."""

        if selected_fault == stage:
            _durable_marker(marker, stage, member_id)
            os._exit(91)

    participant = RecoveryLineageProcessParticipant(
        membership,
        member_id,
        journal_path,
        transport,
        fault_hook=fault_hook,
    )
    try:
        while True:
            participant.service_once()
            time.sleep(0.002)
    finally:
        transport.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
