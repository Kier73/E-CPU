"""BOOT-001B: network retention across worker and storage-service restarts."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile

import pytest

from mailcpu import bootstrap_001 as boot
from mailcpu import internet_intention_ingress as ingress
from mailcpu.bootstrap_retention import ImmutableRetention, NetworkRetention, RetentionError, serve_one
from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.computational_session import ComputationalSessionStore
from mailcpu.continuous_session import SessionRejoinAddress
from mailcpu.mtls_transport import MutualTLSTransportError
from mailcpu.socket_transport import SocketTransportError
from mailcpu.recovery_lineage import RecoveryLineageAuthority
from test_internet_intention_ingress import MANIFEST_PATH, fake_get
from test_recovery_lineage_service import (
    _membership, _make_certificates, _start_member, _reconnect_peer,
    _coordinator, _stop, _server_context, _owner_context, OWNER_DNS,
)


def test_retention_immutable_scope_and_corruption(tmp_path):
    store = ImmutableRetention(tmp_path)
    key = "p-" + hashlib.sha256(b"x"*4096).hexdigest()
    store.put(key, b"x"*4096)
    store.put(key, b"x"*4096)
    with pytest.raises(RetentionError):
        store.put(key, b"y"*4096)
    with pytest.raises(RetentionError):
        store.get("../outside")
    record = "r-generation-" + "0"*19 + "1-" + "a"*64 + ".json"
    store.put(record, b"first")
    with pytest.raises(RetentionError):
        store.put(record, b"second")
    (tmp_path / key).write_bytes(b"y"*4096)
    with pytest.raises(RetentionError):
        store.get(key)


def certificates(root):
    return {"ca": root/"ca.pem", **{m+"_"+k: root/(m+ext)
            for m in ("A","B","C") for k,ext in (("cert",".pem"),("key",".key"))}}


def server(root):
    # Reuse fixture CA and B certificate in a distinct test service process.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        print(json.dumps({"port": listener.getsockname()[1]}), flush=True)
        context = _server_context(certificates(root), "B")
        storage = ImmutableRetention(root / "network-store")
        while True:
            try:
                serve_one(listener, context, storage, client_dns=OWNER_DNS)
            except (MutualTLSTransportError, SocketTransportError, RetentionError, OSError):
                continue


def worker(root, mode):
    membership = _membership()
    manifest = ingress.admit_manifest(json.loads(MANIFEST_PATH.read_text()))
    certs = certificates(root)
    endpoints = json.loads((root/"endpoints.json").read_text())
    peers = {}
    try:
        for member in ("B","C"):
            peers[member] = _reconnect_peer(membership, certs, member, endpoints[member])
        backing = NetworkRetention("127.0.0.1", endpoints["storage"]["port"],
                                   _owner_context(certs), server_dns="member-b.mailcpu.test")
        owner = RecoveryLineageAuthority(membership, "A", root/"authorities/A.jsonl")
        # Every invocation has a new empty native checkpoint directory.
        with tempfile.TemporaryDirectory() as cache:
            store = ComputationalSessionStore(
                cache, ComputationalObjectStore(backing), _coordinator(membership, owner, peers),
                artifact_manifest_digest=ingress.digest(manifest),
                backend_fingerprint=hashlib.sha256(b"boot001b").hexdigest(),
                state_schema_id=boot.STATE_SCHEMA, record_backing=backing,
            )
            locator = root/"address.json"
            if mode == "init":
                address = boot.initialize(store, manifest)
                address.save(locator)
                print(json.dumps(address.to_dict()))
                return
            address = SessionRejoinAddress.load(locator)
            before = boot.recover(store, manifest, address)
            if mode == "inspect":
                print(json.dumps({"checkpoint": before.checkpoint_digest,
                                  "state": json.loads(before.state_bytes)}))
                return
            def get(*args):
                if mode == "terminal":
                    raise AssertionError("terminal must not read source")
                return fake_get(*args)
            result = boot.step(store, manifest, address,
                               expected_checkpoint=before.checkpoint_digest, get=get)
            assert not list(Path(cache).rglob("*.json"))
            if mode == "after":
                os._exit(72)
            print(json.dumps(asdict(result)))
    finally:
        for peer in peers.values():
            peer.close()


@pytest.mark.skipif(shutil.which("openssl") is None, reason="requires test CA")
def test_network_retention_survives_worker_and_provider_death(tmp_path):
    _make_certificates(tmp_path)
    membership = _membership()
    processes = []
    endpoints = {}
    env = dict(os.environ)
    cwd = str(MANIFEST_PATH.parents[2])
    env["PYTHONPATH"] = cwd + os.pathsep + env.get("PYTHONPATH","")
    def run(mode, code=0):
        result = subprocess.run([sys.executable, __file__, str(tmp_path), mode],
                                cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
        assert result.returncode == code, result.stderr
        return json.loads(result.stdout) if result.stdout.strip() else None
    def start_storage():
        proc = subprocess.Popen([sys.executable, __file__, str(tmp_path), "server"],
                                cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        processes.append(proc)
        endpoints["storage"] = json.loads(proc.stdout.readline())
        (tmp_path/"endpoints.json").write_text(json.dumps(endpoints))
        return proc
    try:
        certs = certificates(tmp_path)
        for member in ("B","C"):
            proc, ready = _start_member(tmp_path, membership, certs, member)
            processes.append(proc)
            endpoints[member] = ready
        storage = start_storage()
        address = run("init")
        genesis = run("inspect")
        run("after", 72)
        committed = run("inspect")
        assert committed["state"]["revision"] == 1
        assert committed["state"]["previous_digest"] == genesis["state"]["digest"]
        _stop(storage)
        # No provider means no accepted recovery; an empty worker cannot invent state.
        result = subprocess.run([sys.executable, __file__, str(tmp_path), "inspect"],
                                cwd=cwd, env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode != 0
        storage = start_storage()
        assert run("inspect") == committed
        prior = committed["checkpoint"]
        for rev in range(2,6):
            q = run("step")
            assert q["address_digest"] == address["digest"]
            assert q["intention_revision"] == rev and q["before_checkpoint"] == prior
            prior = q["after_checkpoint"]
        terminal = run("terminal")
        assert terminal["complete"] and terminal["operation"] is None
        assert terminal["after_checkpoint"] == prior
    finally:
        for proc in processes:
            _stop(proc)


if __name__ == "__main__":
    root, mode = Path(sys.argv[1]), sys.argv[2]
    if mode == "server":
        server(root)
    else:
        worker(root, mode)
