"""USM-006: run E-CPU's *existing* durable quorum services as model hosts.

This module does not implement a new consensus algorithm. It configures
RecoveryLineageAuthorityService, RecoveryLineagePeerClient and
DistributedRecoveryLineageCoordinator for the USM-005 receiver-crash loop.
All processes run on one physical CI machine; journals are distinct but
their physical failure domain remains shared.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable, Mapping

from examples.model_authenticated_fabric import model_tls_context, server_tls_context
from examples.model_ground_os import _digest
from examples.run_model_authenticated_experiment import _openssl
from examples.model_receiver_recovery import GENESIS, MACHINE, run_demo
from mailcpu.recovery_lineage import RecoveryLineageAuthority
from mailcpu.recovery_lineage_service import RecoveryLineageAuthorityService
from mailcpu.recovery_lineage_transport import (
    DistributedRecoveryLineageCoordinator,
    RecoveryLineagePeerClient,
    RecoveryLineageTransportError,
)
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.socket_transport import SocketTransport

CONFIG_SCHEMA = "mailcpu.usm006.remote-authorities.v1"
OWNER_DNS = "owner-model.local"
AUTHORITY_NAMES = {"B": "member-b.model.local", "C": "member-c.model.local"}


def issue_authority_certificates(directory: Path) -> dict[str, Path]:
    """Issue host-specific TLS leaf identities under USM-005's ephemeral CA."""
    files = {"ca": directory / "ca.pem"}
    ca_key = directory / "ca.key"
    if not files["ca"].exists() or not ca_key.exists():
        raise ValueError("a local ephemeral test CA must exist before authority setup")
    for member_id, name in (("A", OWNER_DNS), ("B", AUTHORITY_NAMES["B"]),
                            ("C", AUTHORITY_NAMES["C"])):
        key = directory / f"authority-{member_id}.key"
        csr = directory / f"authority-{member_id}.csr"
        cert = directory / f"authority-{member_id}.pem"
        ext = directory / f"authority-{member_id}.ext"
        _openssl(directory, "req", "-new", "-newkey", "rsa:2048", "-nodes",
                 "-keyout", str(key), "-out", str(csr), "-subj", f"/CN={name}")
        ext.write_text(
            f"subjectAltName=DNS:{name}\n"
            "extendedKeyUsage=clientAuth,serverAuth\n"
            "basicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n",
            encoding="utf-8",
        )
        _openssl(directory, "x509", "-req", "-in", str(csr),
                 "-CA", str(files["ca"]), "-CAkey", str(ca_key),
                 "-CAcreateserial", "-out", str(cert), "-days", "1",
                 "-sha256", "-extfile", str(ext))
        files[f"{member_id}_cert"] = cert
        files[f"{member_id}_key"] = key
    return files


def open_distributed_lineage(
    membership: SeedCommitMembership,
    store_root: Path,
    config_path: Path,
) -> DistributedRecoveryLineageCoordinator:
    """Bind the latest E-CPU lineage protocol to two authenticated remote peers.

    This reuses the existing fixed owner in the native seed-quorum membership;
    it does not implement cross-owner epochs or a new leader election.
    """
    config = json.loads(config_path.read_text(encoding="utf-8"))
    expected = {"schema", "membership_digest", "owner_dns", "members"}
    if (type(config) is not dict or set(config) != expected
            or config["schema"] != CONFIG_SCHEMA
            or config["membership_digest"] != membership.digest
            or config["owner_dns"] != OWNER_DNS
            or type(config["members"]) is not dict
            or set(config["members"]) != set(AUTHORITY_NAMES)):
        raise ValueError("remote lineage configuration is not bound to the fixed membership")
    certificates = store_root.parent / "certificates"
    client_context = model_tls_context(
        certificates / "authority-A.pem",
        certificates / "authority-A.key",
        certificates / "ca.pem",
    )
    peers: dict[str, RecoveryLineagePeerClient] = {}
    try:
        for member in ("B", "C"):
            record = config["members"][member]
            if (type(record) is not dict or set(record) != {"host", "port", "dns"}
                    or record["host"] != "127.0.0.1"
                    or type(record["port"]) is not int
                    or not 1 <= record["port"] <= 65535
                    or record["dns"] != AUTHORITY_NAMES[member]):
                raise ValueError("remote authority endpoint changed its expected identity")
            last_failure = None
            for _ in range(25):
                try:
                    peer = RecoveryLineagePeerClient.connect_mutual_tls(
                        membership, member, record["host"], record["port"],
                        client_context, server_hostname=record["dns"],
                        timeout=0.6, handshake_timeout=1.0,
                    )
                    peers[member] = peer
                    break
                except RecoveryLineageTransportError as exc:
                    last_failure = exc
                    time.sleep(0.04)
            else:
                raise RecoveryLineageTransportError(
                    f"authenticated authority {member} could not reconnect: {last_failure}"
                )
        owner = RecoveryLineageAuthority(
            membership, membership.owner_id,
            store_root / f"anchor-{membership.owner_id}.jsonl",
        )
        return DistributedRecoveryLineageCoordinator(
            membership, {membership.owner_id: owner, **peers},
        )
    except Exception:
        for peer in peers.values():
            peer.close()
        raise


def authority_process(root: Path, member: str) -> None:
    """Launch one existing E-CPU authority service, no novel RPC implementation."""
    if member not in AUTHORITY_NAMES:
        raise ValueError("authority must be configured non-owner member B or C")
    checkpoint = root / "checkpoint"
    membership = SeedCommitMembership(
        MACHINE, 1, ("A", "B", "C"), "A", 1, GENESIS,
    )
    certificates = root / "certificates"
    tls = server_tls_context(
        certificates / f"authority-{member}.pem",
        certificates / f"authority-{member}.key",
        certificates / "ca.pem",
    )
    listener = SocketTransport.listen("127.0.0.1", 0)
    service = RecoveryLineageAuthorityService(
        membership, member, checkpoint / f"anchor-{member}.jsonl",
        listener, tls, expected_owner_dns=OWNER_DNS,
    )
    print(json.dumps({
        "member": member,
        "port": service.address[1],
        "dns": AUTHORITY_NAMES[member],
    }, sort_keys=True), flush=True)
    service.serve_forever()


def prepare_distributed_authorities(root: Path, _model_keys: Mapping[str, Path]) -> tuple[
    Callable[[], None], dict[str, Any],
]:
    """Spawn B and C in independent Python interpreters with distinct journals.

    Returns an idempotent cleanup and a record of process identity/liveness.
    The caller must keep these services running through both receiver lifetimes.
    """
    checkpoint = root / "checkpoint"
    checkpoint.mkdir(parents=True, exist_ok=True)
    certificates = root / "certificates"
    issue_authority_certificates(certificates)
    members: dict[str, Any] = {}
    workers: dict[str, subprocess.Popen[str]] = {}
    status: dict[str, Any] = {"alive_through_receiver_replacement": False}
    config_path = checkpoint / "remote-authorities.json"

    def stop() -> None:
        status["alive_through_receiver_replacement"] = (
            len(workers) == 2 and all(proc.poll() is None for proc in workers.values())
        )
        config_path.unlink(missing_ok=True)
        for process in workers.values():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)

    try:
        for member in ("B", "C"):
            child = subprocess.Popen(
                (sys.executable, "-m", "examples.model_distributed_lineage",
                 "authority", "--root", str(root), "--member", member),
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            workers[member] = child
            line = child.stdout.readline() if child.stdout is not None else ""
            if not line:
                raise RuntimeError(f"remote authority {member} failed to publish its bound port")
            ready = json.loads(line)
            if (set(ready) != {"member", "port", "dns"}
                    or ready["member"] != member or ready["dns"] != AUTHORITY_NAMES[member]
                    or type(ready["port"]) is not int or not 1 <= ready["port"] <= 65535):
                raise RuntimeError("remote authority reported wrong peer identity")
            members[member] = {
                "host": "127.0.0.1", "port": ready["port"], "dns": ready["dns"],
            }
        membership = SeedCommitMembership(MACHINE, 1, ("A", "B", "C"), "A", 1, GENESIS)
        config = {"schema": CONFIG_SCHEMA, "membership_digest": membership.digest,
                  "owner_dns": OWNER_DNS, "members": members}
        config_path.write_text(
            json.dumps(config, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    except Exception:
        stop()
        raise
    status["authority_process_ids"] = {member: workers[member].pid for member in workers}
    status["authority_dns"] = dict(AUTHORITY_NAMES)
    return stop, status


def run_distributed_demo(root: Path) -> dict[str, Any]:
    """Run the actual USM-005 model hard-crash across a remote majority."""
    state: dict[str, Any] = {}

    def setup(path: Path, keys: Mapping[str, Path]) -> Callable[[], None]:
        stop, results = prepare_distributed_authorities(path, keys)
        state["authority_status"] = results
        return stop

    baseline = run_demo(root, configure_lineage=setup)
    authority_status = state["authority_status"]
    if not authority_status.get("alive_through_receiver_replacement"):
        raise RuntimeError("remote authority processes did not survive receiver replacement")
    pids = list(authority_status["authority_process_ids"].values())
    if (len(set(pids)) != 2 or any(
        pid in (baseline["model_process"], baseline["first_receiver_process"],
                baseline["replacement_receiver_process"]) for pid in pids
    )):
        raise RuntimeError("authority identities were not independent OS processes")
    if baseline["result"]["first_quorum_generation"] != 1 or (
        baseline["result"]["latest_quorum_generation"] != 2
    ):
        raise RuntimeError("distributed recovery checkpoints did not advance their quorum")
    # After authenticated workers exit, re-open the same *durable* journal
    # files offline to check they really sealed the receiver's state.
    from examples.model_receiver_recovery import ModelRecoveryStore
    reconstructed = ModelRecoveryStore(root / "checkpoint")
    artifact, manifest = reconstructed.load()
    if manifest.generation != 2 or artifact["phase"] != "complete":
        raise RuntimeError("offline post-service durable quorum disagrees with recovery")
    core = {
        "schema": "mailcpu.usm006.distributed-model-lineage-report.v1",
        "recovered_model": baseline,
        "authenticated_authority_processes": authority_status["authority_process_ids"],
        "authenticated_authority_dns": authority_status["authority_dns"],
        "authorities_survived_receiver_restart": True,
        "independent_os_authority_processes": 2,
        "single_physical_failure_domain": True,
        "offline_reconstructed_quorum_generation": manifest.generation,
        "offline_reconstructed_state_digest": manifest.state_digest,
    }
    return {**core, "report_digest": _digest(core)}


def main() -> None:
    """Select the native authority service or run the full distributed recovery."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("demo", "authority"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--member", choices=("B", "C"))
    parser.add_argument("--output", type=Path, default=Path("usm006-report.json"))
    args = parser.parse_args()
    if args.role == "authority":
        if args.root is None or args.member is None:
            parser.error("authority requires --root and --member")
        authority_process(args.root, args.member)
        return
    import tempfile
    with tempfile.TemporaryDirectory(prefix="usm006-") as folder:
        report = run_distributed_demo(Path(folder))
    args.output.write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"report_digest": report["report_digest"],
                      "authenticated_authorities": 2,
                      "quorum_generation":
                      report["offline_reconstructed_quorum_generation"]}, sort_keys=True))


if __name__ == "__main__":
    main()
