"""IPS-008 real child-process service for one receiver-owned fenced register."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import ssl
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from mailcpu.effect_receiver_service import AuthenticatedGroundEffectService  # noqa: E402
from mailcpu.fenced_effect_receiver import FencedGroundEffectReceiver  # noqa: E402
from mailcpu.socket_transport import SocketTransport  # noqa: E402
from test_fenced_generated_ground import _lineage  # noqa: E402


def main(arguments: list[str]) -> int:
    """Launch one independently replayable mTLS receiver with protected SQLite."""
    if len(arguments) != 6:
        raise ValueError("requires root, cert, key, CA, output ready file, owner DNS")
    root, certificate, key, ca, ready, owner_dns = arguments
    directory = Path(root)
    publisher = _lineage(directory)
    receiver = FencedGroundEffectReceiver(
        directory / "receiver.sqlite",
        resource="/virtual-layer/effects/ips008-register",
        plan_digest=publisher.plan.digest,
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certificate, key)
    context.load_verify_locations(cafile=ca)
    context.verify_mode = ssl.CERT_REQUIRED
    listener = SocketTransport.listen("127.0.0.1", 0)
    listener.settimeout(.25)
    service = AuthenticatedGroundEffectService(
        receiver, publisher, listener, context, expected_owner_dns=owner_dns,
    )
    out = Path(ready)
    payload = json.dumps(
        {"host": service.address[0], "port": service.address[1]},
        sort_keys=True,
    ).encode()
    with out.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())

    while True:
        service.serve_once(handshake_timeout=.6)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
