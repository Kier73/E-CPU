"""Child process running a mutually authenticated recovery authority service."""

from __future__ import annotations

import json
import os
import ssl
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mailcpu import (  # noqa: E402
    RecoveryLineageAuthorityService,
    SeedCommitMembership,
    SocketTransport,
)


def main(arguments: list[str]) -> int:
    """Mathematics: host one fixed non-owner journal behind a TLS server identity that accepts only the fixed owner's certificate."""

    if len(arguments) != 7:
        raise ValueError(
            "worker requires member id, membership, journal, certificate, private key, client CA, and owner DNS"
        )
    member_id, membership_path, journal_path, certificate, private_key, client_ca, owner_dns = arguments
    membership = SeedCommitMembership.from_snapshot(
        json.loads(Path(membership_path).read_text(encoding="utf-8"))
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certificate, private_key)
    context.load_verify_locations(cafile=client_ca)
    context.verify_mode = ssl.CERT_REQUIRED
    listener = SocketTransport.listen("127.0.0.1", 0)
    service = RecoveryLineageAuthorityService(
        membership,
        member_id,
        journal_path,
        listener,
        context,
        expected_owner_dns=owner_dns,
    )
    host, port = service.address
    print(
        json.dumps(
            {"member_id": member_id, "host": host, "port": port, "pid": os.getpid()},
            sort_keys=True,
        ),
        flush=True,
    )
    service.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
