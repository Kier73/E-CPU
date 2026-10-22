from __future__ import annotations

import pytest

from mailcpu.devices import DeviceBus
from mailcpu.dns_cell import DnsLatchDevice, DnsRecord, DnsResolverSim, LogicalClock
from mailcpu.kernel import VirtualKernel
from mailcpu.tcp_arithmetic import (
    MOD32,
    AimdController,
    seq_diff,
    seq_in_window,
    seq_less_than,
)


def test_dns_record_ttl_decay() -> None:
    r"""Mathematics: TTL decrements linearly with elapsed physical time `\text{TTL}(t) = \max(0, \text{TTL}_0 - \Delta t)`."""

    record = DnsRecord(
        domain="example.com",
        record_type="A",
        value="93.184.216.34",
        inserted_at=100.0,
        original_ttl=60,
    )
    assert record.remaining_ttl(now=100.0) == 60
    assert record.remaining_ttl(now=120.0) == 40
    assert record.remaining_ttl(now=160.0) == 0
    assert record.remaining_ttl(now=170.0) == 0
    assert record.is_alive(now=120.0) is True
    assert record.is_alive(now=161.0) is False


def test_dns_record_fractional_ttl_uses_documented_floor() -> None:
    r"""Mathematics: `TTL_remaining(t) = max(0, TTL0 - floor(t - t0))` at fractional boundaries."""

    record = DnsRecord("fractional.test", "A", "192.0.2.1", 100.0, 60)
    assert record.remaining_ttl(now=100.1) == 60
    assert record.remaining_ttl(now=159.9) == 1
    assert record.remaining_ttl(now=160.0) == 0
    assert record.remaining_ttl(now=99.0) == 60


def test_dns_record_and_latch_reject_negative_ttl_and_non_binary_bits() -> None:
    r"""Mathematics: the admitted state domain is `TTL0 ∈ Z_{≥0}` and `bit ∈ {0,1}`."""

    with pytest.raises(ValueError, match="TTL"):
        DnsRecord("invalid.test", "A", "192.0.2.1", 0.0, -1)

    device = DnsLatchDevice()
    with pytest.raises(ValueError, match="bit"):
        device.write(b"SET invalid.test 2 60\n")
    with pytest.raises(ValueError, match="TTL"):
        device.write(b"SET invalid.test 1 -1\n")

    invalid_snapshot = device.snapshot()
    invalid_snapshot["latches"] = {"invalid.test": 2}
    with pytest.raises(ValueError, match="bit"):
        DnsLatchDevice.from_snapshot(invalid_snapshot)


def test_dns_resolver_positive_and_negative_caching() -> None:
    r"""Mathematics: positive hits yield `NOERROR` and negative cache latches yield RFC 2308 `NXDOMAIN`."""

    resolver = DnsResolverSim()
    resolver.insert_record("valid.org", "A", "10.0.0.1", ttl=120, is_negative=False, now=50.0)
    resolver.insert_record("nonexistent.invalid", "A", "", ttl=60, is_negative=True, now=50.0)

    # Positive cache hit
    res_pos = resolver.query("valid.org", recursion_desired=False, now=60.0)
    assert res_pos["hit"] is True
    assert res_pos["status"] == "NOERROR"
    assert res_pos["ttl"] == 110

    # Negative cache latch hit
    res_neg = resolver.query("nonexistent.invalid", recursion_desired=False, now=60.0)
    assert res_neg["hit"] is True
    assert res_neg["status"] == "NXDOMAIN"
    assert res_neg["ttl"] == 50


def test_dns_resolver_cache_snoop_rd_zero() -> None:
    r"""Mathematics: non-recursive probe `RD=0` measures cache residency without triggering upstream recursion."""

    resolver = DnsResolverSim()
    miss = resolver.query("uncached.net", recursion_desired=False, now=10.0)
    assert miss["hit"] is False
    assert miss["status"] == "REFUSED"

    # Recursive fetch loads cache
    fetched = resolver.query("uncached.net", recursion_desired=True, now=10.0)
    assert fetched["status"] == "NOERROR"

    # Now RD=0 succeeds
    hit = resolver.query("uncached.net", recursion_desired=False, now=12.0)
    assert hit["hit"] is True
    assert hit["ttl"] == 298


def test_dns_multi_resolver_canary_poll() -> None:
    r"""Mathematics: canary polling queries multiple resolver vantage points to confirm global presence."""

    resolver = DnsResolverSim()
    assert resolver.multi_resolver_canary_poll("probe.test", now=1.0) is False

    resolver.insert_record("probe.test", "A", "1.2.3.4", ttl=100, now=1.0)
    assert resolver.multi_resolver_canary_poll("probe.test", now=2.0) is True


def test_dns_canary_poll_uses_explicit_independent_resolver_state() -> None:
    r"""Mathematics: canary result is the disjunction of independent cache predicates, not a duplicated local cache."""

    peer = DnsResolverSim(server_ip="9.9.9.9", canary_ips=())
    resolver = DnsResolverSim(server_ip="8.8.8.8", canary_ips=(), canary_resolvers=(peer,))
    peer.insert_record("peer-only.test", "A", "192.0.2.9", ttl=30, now=10.0)
    assert resolver.multi_resolver_canary_poll("peer-only.test", now=11.0) is True

    peer.cache.clear()
    assert resolver.multi_resolver_canary_poll("peer-only.test", now=11.0) is False


def test_dns_latch_device_read_write_snapshot() -> None:
    r"""Mathematics: `/dev/dns_latch` exposes decaying presence bits to userspace and round-trips through snapshots."""

    device = DnsLatchDevice()
    cmd = b"SET bit0.node 1 120\nSET bit1.node 0 60\n"
    written = device.write(cmd)
    assert written == len(cmd)

    output = device.read().decode("utf-8")
    assert "bit0.node=1" in output
    assert "bit1.node=0" in output

    # Checkpoint snapshot
    snap = device.snapshot()
    assert snap["kind"] == "dns_latch"

    restored = DnsLatchDevice.from_snapshot(snap)
    assert restored.latches == device.latches
    restored_out = restored.read().decode("utf-8")
    assert restored_out == output


def test_dns_resolver_uses_one_injected_logical_clock_for_latch_decay() -> None:
    r"""Mathematics: resolver/device observations use the shared coordinate `t=T.now()`, so `advance(Δ)` changes TTL by `floor(Δ)`."""

    clock = LogicalClock(100.0)
    with pytest.raises(ValueError, match="cannot move backwards"):
        clock.set(99.0)
    device = DnsLatchDevice(DnsResolverSim(clock=clock))
    device.write(b"SET shared-clock.test 1 10\n")
    assert device.read().decode("utf-8") == "shared-clock.test=1\n"

    clock.advance(9.9)
    assert device.read().decode("utf-8") == "shared-clock.test=1\n"
    clock.advance(0.1)
    assert device.read().decode("utf-8") == "shared-clock.test=0\n"


def test_dns_latch_snapshot_preserves_remaining_ttl_across_clock_domain() -> None:
    r"""Mathematics: snapshot stores `r_s=TTL_remaining(t_s)` and restore satisfies `TTL_restored(t_r)=r_s` even when `t_r≠t_s`."""

    source_clock = LogicalClock(100.0)
    device = DnsLatchDevice(DnsResolverSim(clock=source_clock))
    device.write(b"SET checkpointed.test 1 10\n")
    source_clock.advance(4.9)
    snapshot = device.snapshot()

    restored_clock = LogicalClock(10_000.0)
    restored = DnsLatchDevice.from_snapshot(snapshot, clock=restored_clock)
    assert restored.read().decode("utf-8") == "checkpointed.test=1\n"
    restored_clock.advance(1.0)
    assert restored.read().decode("utf-8") == "checkpointed.test=1\n"
    restored_clock.advance(5.0)
    assert restored.read().decode("utf-8") == "checkpointed.test=0\n"


def test_device_bus_restores_dns_latch_without_inventing_canary_state() -> None:
    r"""Mathematics: typed device projection preserves `D[dns_latch]`, while an external canary graph with missing peers is rejected."""

    clock = LogicalClock(5.0)
    bus = DeviceBus()
    bus.register("dns_latch", DnsLatchDevice(DnsResolverSim(clock=clock)))
    bus.write("dns_latch", b"SET bus.test 1 20\n")
    restored = DeviceBus.from_snapshot(bus.snapshot())
    assert restored.read("dns_latch").decode("utf-8") == "bus.test=1\n"

    peer = DnsResolverSim(clock=LogicalClock(5.0))
    external = DnsLatchDevice(DnsResolverSim(clock=LogicalClock(5.0), canary_resolvers=(peer,)))
    with pytest.raises(ValueError, match="explicit canary resolvers"):
        DnsLatchDevice.from_snapshot(external.snapshot())


def test_kernel_exposes_dns_latch_as_checkpointable_device() -> None:
    r"""Mathematics: kernel device composition satisfies `"dns_latch"∈dom(D)` and preserves `/dev/dns_latch` I/O across `K' = restore(snapshot(K))`."""

    kernel = VirtualKernel()
    pid = kernel.spawn("dns-user")
    fd = kernel.syscall(pid, "open", path="/dev/dns_latch", mode="r+")
    command = b"SET kernel.test 1 30\n"
    assert kernel.syscall(pid, "write", fd=fd, data=command) == len(command)
    assert kernel.syscall(pid, "read", fd=fd) == b"kernel.test=1\n"
    assert "dns_latch" in kernel.devices.names()

    restored = VirtualKernel.from_snapshot(kernel.snapshot())
    restored_pid = next(iter(restored.processes))
    restored_fd = next(
        fd
        for fd, handle in restored.processes[restored_pid].fds.items()
        if handle.path == "/dev/dns_latch"
    )
    assert restored.syscall(restored_pid, "read", fd=restored_fd) == b"kernel.test=1\n"


def test_tcp_sequence_ring_arithmetic() -> None:
    r"""Mathematics: cyclic distance in `\mathbb{Z}_{2^{32}}` respects modular precedence across the wraparound boundary."""

    seq_a = MOD32 - 100  # near 2^32 - 1
    seq_b = 50           # wrapped past 0

    # Distance from seq_a to seq_b is 150
    assert seq_diff(seq_b, seq_a) == 150
    assert seq_diff(seq_a, seq_b) == -150

    # Circular order
    assert seq_less_than(seq_a, seq_b) is True
    assert seq_less_than(seq_b, seq_a) is False

    # Window containment [base, base + 200)
    assert seq_in_window(seq_b, seq_a, 200) is True
    assert seq_in_window(seq_a + 50, seq_a, 200) is True
    assert seq_in_window(seq_a + 300, seq_a, 200) is False


def test_aimd_controller_linear_increase_and_multiplicative_drop() -> None:
    r"""Mathematics: AIMD evaluates `W \leftarrow W + \frac{\alpha}{W}` on ACK and `W \leftarrow W \cdot \beta` on loss."""

    aimd = AimdController(window=2.0, min_window=1.0, max_window=10.0, alpha=1.0, beta=0.5)

    # ACK: increases by 1 / 2.0 = 0.5 -> 2.5
    w1 = aimd.on_ack()
    assert w1 == 2.5
    assert aimd.can_dispatch(in_flight=2) is True
    assert aimd.can_dispatch(in_flight=3) is False

    # Loss: drops by 0.5 -> 1.25
    w2 = aimd.on_loss()
    assert w2 == 1.25

    # Snapshot roundtrip
    snap = aimd.snapshot()
    restored = AimdController.from_snapshot(snap)
    assert restored.window == aimd.window
    assert restored.beta == aimd.beta
