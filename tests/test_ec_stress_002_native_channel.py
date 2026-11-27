"""EC-STRESS-002: native channel + affine observation + DAG checkpoint stress.

Loopback only. Channel closure is not process death, and this test does not
qualify WAN, TLS, VL-K integration, or a distributed commit authority.
"""
import hashlib
import json
import random
import socket

import pytest

from mailcpu import ReliableChannel, SocketTransport
from mailcpu.computation_dag import (
    ComputationDAGError, ComputationNode, NavigableComputationDAG,
)
from mailcpu.rrns import affine_orbit_jump, encode_rrns, recover_rrns

MOD = 1 << 64
MODS = [65521, 65519, 65497, 65479, 65449, 65447]


def digest(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def oracle(q):
    a, b, x, n = (q[k] for k in ("a", "b", "x", "n"))
    # Independent closed form; division is exact before reduction.
    geom = n if a == 1 else (pow(a, n, (a - 1) * MOD) - 1) // (a - 1)
    return (pow(a, n, MOD) * x + b * geom) % MOD


def realize(q):
    A, B = affine_orbit_jump(q["a"], q["b"], MOD, q["n"])
    y = (A * q["x"] + B) % MOD
    return {"query": digest(q), "value": y, "residues": encode_rrns(y, MODS)}


def verify(q, result):
    y = result["value"]
    return (result["query"] == digest(q)
            and len(result["residues"]) == len(MODS)
            and recover_rrns(list(zip(MODS, result["residues"])), 5, MODS) == (y, True)
            and y == oracle(q))


def pair(origin, peer, channel):
    listener = SocketTransport.listen("127.0.0.1", 0)
    try:
        a = SocketTransport.connect("127.0.0.1", listener.getsockname()[1], origin, peer)
        b = SocketTransport.accept(listener, peer, origin)
    finally:
        listener.close()
    return a, b, ReliableChannel(a, origin, peer, channel), ReliableChannel(b, peer, peer, channel, peer=origin)


def exchange(tx, rx, obj):
    seq = tx.send((obj,))
    assert rx.receive() == (seq, (obj,))
    assert tx.process_ack() == (seq,)


def test_native_channel_replacement_preserves_affine_observation_dag():
    rng = random.Random(7723)
    queries = [
        {"a": 1 + 4 * rng.randrange(1, 65536), "b": 2 * rng.randrange(65536) + 1,
         "x": rng.getrandbits(64), "n": rng.getrandbits(64)}
        for _ in range(128)
    ]
    nodes = [
        ComputationNode(f"q{i:03}", 1, "affine.observe", "/test/affine",
                        "a" * 64, (), q)
        for i, q in enumerate(queries)
    ]
    dag = NavigableComputationDAG(nodes)
    identity = dag.digest
    for epoch in range(8):
        peer = f"worker-{epoch}"
        a, b, tx, rx = pair("requester", peer, f"request-{epoch}")
        c, d, reply, receive_reply = pair(peer, "requester", f"reply-{epoch}")
        try:
            for node in nodes[epoch * 16:(epoch + 1) * 16]:
                q = node.payload
                exchange(tx, rx, q)
                result = realize(q)
                exchange(reply, receive_reply, result)
                assert verify(q, result)
                # Consistent residue coding does not certify the mathematical law.
                wrong = result["value"] ^ 1
                forged = dict(result, value=wrong, residues=encode_rrns(wrong, MODS))
                assert recover_rrns(list(zip(MODS, forged["residues"])), 5, MODS) == (wrong, True)
                assert not verify(q, forged)
                assert dag.commit(node.node_id, result) is False
                assert dag.commit(node.node_id, result) is True
                with pytest.raises(ComputationDAGError):
                    dag.commit(node.node_id, forged)
        finally:
            for transport in (a, b, c, d):
                transport.close()
        # Reconstruct the actual DAG, independent of the retired channels.
        dag = NavigableComputationDAG.from_snapshot(json.loads(json.dumps(dag.snapshot())))
        assert dag.digest == identity
        assert len(dag.committed_nodes) == (epoch + 1) * 16

    assert dag.is_complete
    for node in nodes:
        assert verify(node.payload, dag.result(node.node_id))


def test_closed_port_is_negative_observation_not_execution_receipt():
    # Own a reserved, non-listening port. No public probes.
    with socket.socket() as endpoint:
        endpoint.bind(("127.0.0.1", 0))
        with pytest.raises(ConnectionRefusedError):
            socket.create_connection(endpoint.getsockname(), timeout=1)
