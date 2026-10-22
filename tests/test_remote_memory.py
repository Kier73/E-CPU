from __future__ import annotations

import socket

import pytest

from mailcpu import (
    ReliabilityPolicy,
    ReliableChannel,
    ReplicatedMailboxNode,
    ReplicatedMailboxStore,
    SocketTransport,
    VirtualMemory,
)
from mailcpu.remote_memory import RemotePageError, RemotePageStore


def _page_nodes(tmp_path, page_size: int = 8):
    """Mathematics: construct two nodes with independent sequence spaces for `A→B` and `B→A`."""

    left, right = socket.socketpair()
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=4, window_size=16)
    transport_a = SocketTransport(left, "A", "B")
    transport_b = SocketTransport(right, "B", "A")
    a_out = ReliableChannel(transport_a, "A", "B", "replication", policy)
    a_in = ReliableChannel(transport_a, "A", "A", "replication", policy, peer="B")
    b_out = ReliableChannel(transport_b, "B", "A", "replication", policy)
    b_in = ReliableChannel(transport_b, "B", "B", "replication", policy, peer="A")
    node_a = ReplicatedMailboxNode(
        ReplicatedMailboxStore(tmp_path / "a.mailbox.log", "A"),
        outbound={"B": a_out},
        inbound={"B": a_in},
        quorum=2,
    )
    node_b = ReplicatedMailboxNode(
        ReplicatedMailboxStore(tmp_path / "b.mailbox.log", "B"),
        outbound={"A": b_out},
        inbound={"A": b_in},
        quorum=2,
    )
    store_a = RemotePageStore(
        tmp_path / "pages-a",
        node_a,
        page_size=page_size,
        default_peer="B",
        pump=lambda: store_b.service(),
    )
    store_b = RemotePageStore(
        tmp_path / "pages-b",
        node_b,
        page_size=page_size,
        pump=lambda: store_a.service(),
    )
    return transport_a, transport_b, store_a, store_b


def test_remote_page_put_fetch_restart_and_duplicate_are_content_addressed(tmp_path) -> None:
    """Mathematics: `h=SHA256(b)` remains single-valued through durable put, request, restart, and retransmission."""

    transport_a, transport_b, store_a, store_b = _page_nodes(tmp_path)
    try:
        payload = b"remote!!"
        digest = store_a.put_page(payload)
        assert store_b.has_page(digest)
        assert store_b.page_ids() == (digest,)

        store_a.drop_local_cache(digest)
        assert store_a.get_page(digest) == payload
        store_a.drop_local_cache(digest)

        restarted_b = RemotePageStore(tmp_path / "pages-b", store_b.node, page_size=8)
        assert restarted_b.get_page(digest) == payload
        store_a.put_page(payload)
        assert restarted_b.page_ids() == (digest,)
    finally:
        transport_a.close()
        transport_b.close()


def test_remote_page_corruption_is_rejected_without_zero_fill(tmp_path) -> None:
    """Mathematics: a present object is admissible only when `SHA256(CAS[h])=h`; corruption remains a hard failure."""

    transport_a, transport_b, store_a, store_b = _page_nodes(tmp_path)
    try:
        digest = store_a.put_page(b"remote!!")
        store_a.drop_local_cache(digest)
        (store_b.root / f"{digest}.page").write_bytes(b"corrupt!")
        with pytest.raises(RemotePageError, match="digest mismatch"):
            store_a.get_page(digest)
    finally:
        transport_a.close()
        transport_b.close()


def test_virtual_memory_reclaim_faults_through_remote_page_backing(tmp_path) -> None:
    """Mathematics: `M[p]=h → reclaim → R[p]=(w,h) → fault` restores exact bytes from the remote CAS path."""

    transport_a, transport_b, store_a, _store_b = _page_nodes(tmp_path, page_size=8)
    try:
        memory = VirtualMemory(page_size=8, page_backing=store_a)
        memory.map(0, 8)
        assert memory.write(0, b"remote!!") == 8
        digest = memory.mapped_pages()[0].blob_id
        assert memory.reclaim(page_numbers=(0,)) == (0,)
        assert digest not in memory.snapshot()["blobs"]
        store_a.drop_local_cache(digest)
        assert memory.read(0, 8) == b"remote!!"

        memory.reclaim(page_numbers=(0,))
        restored = VirtualMemory.from_snapshot(memory.snapshot(), page_backing=store_a)
        store_a.drop_local_cache(digest)
        assert restored.read(0, 8) == b"remote!!"
    finally:
        transport_a.close()
        transport_b.close()
