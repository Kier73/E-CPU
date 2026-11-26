"""Real process replacement + native M3 mTLS authority, controlled source reads."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from mailcpu import bootstrap_001 as boot
from mailcpu import internet_intention_ingress as ingress
from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.computational_session import ComputationalSessionStore
from mailcpu.continuous_session import SessionRejoinAddress
from mailcpu.recovery_lineage import RecoveryLineageAuthority
from test_internet_intention_ingress import MANIFEST_PATH, fake_get
from test_recovery_lineage_service import (
    _membership, _make_certificates, _start_member, _reconnect_peer,
    _coordinator, _stop,
)


class DiskPages:
    """Test-only fixed page backing on a retained shared disk; single writer."""
    page_size = 4096

    def __init__(self, root):
        self.root = root
        root.mkdir(exist_ok=True)

    def put_page(self, data):
        assert len(data) == self.page_size
        key = hashlib.sha256(data).hexdigest()
        path = self.root / key
        if not path.exists():
            tmp = path.with_suffix(".tmp")
            with tmp.open("wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        return key

    def get_page(self, key):
        return (self.root / key).read_bytes()


def worker(root, mode):
    """Fresh owner interpreter with new TLS connections to retained authorities."""
    manifest = ingress.admit_manifest(json.loads(MANIFEST_PATH.read_text()))
    membership = _membership()
    certs = {name: root / filename for name, filename in
             {"ca": "ca.pem", "A_cert": "A.pem", "A_key": "A.key"}.items()}
    endpoints = json.loads((root / "endpoints.json").read_text())
    peers = {}
    try:
        for member in ("B", "C"):
            peers[member] = _reconnect_peer(membership, certs, member, endpoints[member])
        owner = RecoveryLineageAuthority(membership, "A", root / "authorities/A.jsonl")
        store = ComputationalSessionStore(
            root / "state", ComputationalObjectStore(DiskPages(root / "pages"), chunk_size=4096),
            _coordinator(membership, owner, peers),
            artifact_manifest_digest=ingress.digest(manifest),
            backend_fingerprint=hashlib.sha256(b"boot001-test-backend").hexdigest(),
            state_schema_id=boot.STATE_SCHEMA,
        )
        address_path = root / "address.json"
        if mode == "init":
            address = boot.initialize(store, manifest)
            address.save(address_path)
            print(json.dumps(address.to_dict()))
            return
        address = SessionRejoinAddress.load(address_path)
        before = boot.recover(store, manifest, address)
        if mode == "inspect":
            print(json.dumps({"revision": before.revision, "checkpoint": before.checkpoint_digest,
                              "state": json.loads(before.state_bytes)}))
            return
        def get(*args):
            if mode == "before":
                fake_get(*args)
                os._exit(71)
            if mode in ("terminal", "stale"):
                raise AssertionError("no source reads permitted")
            return fake_get(*args)
        if mode == "stale":
            with pytest.raises(boot.BootstrapRefused, match="stale"):
                boot.step(store, manifest, address, expected_checkpoint="0"*64, get=get)
            return
        result = boot.step(store, manifest, address,
                           expected_checkpoint=before.checkpoint_digest, get=get)
        if mode == "after":
            os._exit(72)
        print(json.dumps(asdict(result)))
    finally:
        for peer in peers.values():
            peer.close()


@pytest.mark.skipif(shutil.which("openssl") is None, reason="requires OpenSSL test CA")
def test_repository_intention_survives_owner_death_over_mtls(tmp_path):
    certs = _make_certificates(tmp_path)
    membership = _membership()
    processes = []
    try:
        endpoints = {}
        for member in ("B", "C"):
            proc, ready = _start_member(tmp_path, membership, certs, member)
            processes.append(proc)
            endpoints[member] = ready
        (tmp_path / "endpoints.json").write_text(json.dumps(endpoints))

        def run(mode, code=0):
            env = dict(os.environ)
            root = str(MANIFEST_PATH.parents[2])
            env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
            result = subprocess.run([sys.executable, __file__, str(tmp_path), mode],
                                    cwd=root, env=env, capture_output=True, text=True, timeout=60)
            assert result.returncode == code, result.stderr
            return json.loads(result.stdout) if result.stdout.strip() else None

        address = run("init")
        genesis = run("inspect")
        assert genesis["revision"] == 1
        run("before", 71)
        assert run("inspect") == genesis
        run("after", 72)
        accepted = run("inspect")
        assert accepted["revision"] == 2
        assert accepted["state"]["revision"] == 1
        assert accepted["state"]["previous_digest"] == genesis["state"]["digest"]
        run("stale")
        previous = accepted["checkpoint"]
        operations = []
        for revision in range(2, 6):
            result = run("step")
            assert result["address_digest"] == address["digest"]
            assert result["before_checkpoint"] == previous
            assert result["intention_revision"] == revision
            operations.append(result["operation"])
            previous = result["after_checkpoint"]
        assert operations == list(ingress.execution_order(
            ingress.admit_manifest(json.loads(MANIFEST_PATH.read_text()))))[1:]
        terminal = run("terminal")
        assert terminal["complete"] and terminal["operation"] is None
        assert terminal["before_checkpoint"] == terminal["after_checkpoint"] == previous
        assert run("inspect")["revision"] == 6
        assert all(proc.poll() is None for proc in processes)
    finally:
        for proc in processes:
            _stop(proc)


if __name__ == "__main__":
    worker(Path(sys.argv[1]), sys.argv[2])
