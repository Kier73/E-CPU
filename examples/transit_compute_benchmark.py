"""Compare equivalent arithmetic work in Python, direct MailCPU, and remote MailCPU.

The remote path reuses persistent loopback TCP transports and one TransitComputeWorker.
Wire-byte counts include complete ECPU frames and reliable acknowledgements.
This is a local transport benchmark, not a cross-machine network benchmark.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from typing import Any

from mailcpu import (
    Capability,
    HeadlessOS,
    HypervisorArbitrationEvent,
    HypervisorDomain,
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
    HypervisorPolicy,
    HypervisorRequest,
    ReliabilityPolicy,
    ReliableChannel,
    SocketTransport,
    TransitComputeWorker,
)
from mailcpu.socket_transport import _encode_frame
from mailcpu.transit_compute import TransitComputeHost


_OPERATION = "execute deterministic CPU arithmetic program"
_RESOURCE = "/cpu/compute"
_SOURCE = "\n".join(
    (
        "set left 19",
        "set right 23",
        "add total left right",
        "set offset 6",
        "add result total offset",
        "halt",
    )
)
_EXPECTED = 48


class CountingTransport:
    """Transparent transport decorator recording actual encoded frame bytes."""

    def __init__(self, inner: SocketTransport) -> None:
        """Mathematics: wrap transport T while preserving its message relation and accumulating exact frame lengths."""
        self.inner = inner
        self.frames: list[dict[str, Any]] = []
        self.total_bytes = 0

    def __getattr__(self, name: str) -> Any:
        """Mathematics: delegate all non-send operations to the wrapped transport without changing state semantics."""
        return getattr(self.inner, name)

    def send(self, addr: str, message: Any) -> Any:
        """Mathematics: observe |encode(T.send(m))| after forwarding the same message m to T."""
        emitted = self.inner.send(addr, message)
        frame_size = len(_encode_frame(emitted, self.inner.max_frame_size))
        self.total_bytes += frame_size
        self.frames.append(
            {
                "op": emitted.op,
                "body": emitted.body,
                "bytes": frame_size,
            }
        )
        return emitted

    def reset(self) -> None:
        """Mathematics: reset only measurement counters; transport protocol state remains unchanged."""
        self.frames.clear()
        self.total_bytes = 0

    def data_bytes(self) -> int:
        """Mathematics: sum exact encoded RDATA frame lengths in the observed send sequence."""
        return sum(item["bytes"] for item in self.frames if item["op"] == "RDATA")

    def ack_bytes(self) -> int:
        """Mathematics: sum exact encoded RACK frame lengths in the observed send sequence."""
        return sum(item["bytes"] for item in self.frames if item["op"] == "RACK")

    def reliable_retries(self) -> int:
        """Mathematics: count repeated RDATA sequence identities beyond each first transmission."""
        seen: set[tuple[str, int]] = set()
        retries = 0
        for item in self.frames:
            if item["op"] != "RDATA":
                continue
            body = item["body"]
            identity = (str(body[0]), int(body[1]))
            if identity in seen:
                retries += 1
            else:
                seen.add(identity)
        return retries


def _event(sequence: int, *, receiver_authorizes: bool) -> HypervisorArbitrationEvent:
    """Mathematics: construct the same bounded program under unique operation identity I=(client,compute,sequence)."""
    required = frozenset({"execute"})
    granted = frozenset() if receiver_authorizes else required
    return HypervisorArbitrationEvent(
        "client",
        "compute",
        sequence,
        10_000 + sequence,
        HypervisorRequest(
            _OPERATION,
            _RESOURCE,
            {
                "source": _SOURCE,
                "initial_registers": {"seed": 7},
                "max_ticks": 64,
            },
            required,
            granted,
        ),
    )


def _tcp_pair(local: str, peer: str) -> tuple[SocketTransport, SocketTransport]:
    """Mathematics: create reciprocal TCP endpoints carrying identities (local,peer) over one loopback connection."""
    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    left = SocketTransport.connect("127.0.0.1", port, local, peer)
    right = SocketTransport.accept(listener, peer, local)
    listener.close()
    return left, right


def _percentile(samples: list[float], fraction: float) -> float:
    """Mathematics: return the nearest-rank empirical percentile Q_p of a nonempty finite sample."""
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _summary(samples: list[float]) -> dict[str, float]:
    """Mathematics: summarize latency samples by median and nearest-rank 95th percentile."""
    return {
        "median_ms": statistics.median(samples) * 1_000,
        "p95_ms": _percentile(samples, 0.95) * 1_000,
        "mean_ms": statistics.fmean(samples) * 1_000,
    }


def _python_reference() -> int:
    """Mathematics: evaluate the specified integer expression directly as a reference function."""
    left = 19
    right = 23
    total = left + right
    offset = 6
    return total + offset


def _make_remote_stack() -> tuple[
    list[SocketTransport],
    CountingTransport,
    CountingTransport,
    CountingTransport,
    CountingTransport,
    HypervisorOperationChannel,
    HypervisorOperationChannel,
    HypervisorOperationResultChannel,
    HypervisorOperationResultChannel,
    TransitComputeWorker,
]:
    """Mathematics: construct persistent duplex operation channels around one receiver worker W."""
    request_sender_socket, request_worker_socket = _tcp_pair("client", "worker")
    response_worker_socket, response_client_socket = _tcp_pair("worker", "client")
    sockets = [
        request_sender_socket,
        request_worker_socket,
        response_worker_socket,
        response_client_socket,
    ]
    request_sender_transport = CountingTransport(request_sender_socket)
    request_worker_transport = CountingTransport(request_worker_socket)
    response_worker_transport = CountingTransport(response_worker_socket)
    response_client_transport = CountingTransport(response_client_socket)

    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=3, window_size=8)
    request_sender = HypervisorOperationChannel(
        ReliableChannel(
            request_sender_transport,
            "client",
            "worker",
            "compute",
            policy,
        )
    )
    request_worker = HypervisorOperationChannel(
        ReliableChannel(
            request_worker_transport,
            "worker",
            "worker",
            "compute",
            policy,
            peer="client",
        )
    )
    response_worker = HypervisorOperationResultChannel(
        ReliableChannel(
            response_worker_transport,
            "worker",
            "client",
            "compute.result",
            policy,
        ),
        "client",
        "compute",
    )
    response_client = HypervisorOperationResultChannel(
        ReliableChannel(
            response_client_transport,
            "client",
            "client",
            "compute.result",
            policy,
            peer="worker",
        ),
        "client",
        "compute",
    )
    receiver = HeadlessOS()
    worker_pid = receiver.environment.kernel.spawn(
        "transit-compute-worker",
        capabilities=(Capability("/cpu/compute", frozenset({"execute"})),),
        parent_pid=receiver.environment.init_pid,
    )
    receiver.hypervisor.policy = HypervisorPolicy(
        review_confidence=0.0,
        automatic_confidence=0.0,
        destructive_confidence=0.0,
        danger_review_probability=1.0,
    )
    worker = TransitComputeWorker(receiver, worker_pid)
    return (
        sockets,
        request_sender_transport,
        request_worker_transport,
        response_worker_transport,
        response_client_transport,
        request_sender,
        request_worker,
        response_worker,
        response_client,
        worker,
    )


def run_benchmark(iterations: int = 20, warmups: int = 2) -> dict[str, Any]:
    """Mathematics: compare equivalent result function f(x)=48 across local, direct-VM and reliable remote execution."""
    if not isinstance(iterations, int) or isinstance(iterations, bool) or iterations < 1:
        raise ValueError("iterations must be a positive integer")
    if not isinstance(warmups, int) or isinstance(warmups, bool) or warmups < 0:
        raise ValueError("warmups must be a non-negative integer")

    python_samples: list[float] = []
    direct_samples: list[float] = []
    remote_samples: list[float] = []
    direct_host = TransitComputeHost()
    direct_metrics: dict[str, int] | None = None

    for index in range(warmups + iterations):
        started = time.perf_counter()
        python_value = _python_reference()
        elapsed = time.perf_counter() - started
        if python_value != _EXPECTED:
            raise AssertionError("Python reference returned an incorrect result")
        if index >= warmups:
            python_samples.append(elapsed)

        direct_event = _event(index + 1, receiver_authorizes=False)
        started = time.perf_counter()
        direct_result = direct_host.handle(direct_event)
        elapsed = time.perf_counter() - started
        if direct_result["registers"]["result"] != _EXPECTED:
            raise AssertionError("direct MailCPU returned an incorrect result")
        if index >= warmups:
            direct_samples.append(elapsed)
            direct_metrics = {
                "instructions": int(direct_result["steps"]),
                "scheduler_events": int(direct_result["scheduler_events"]),
            }

    connection_started = time.perf_counter()
    (
        sockets,
        request_sender_transport,
        request_worker_transport,
        response_worker_transport,
        response_client_transport,
        request_sender,
        request_worker,
        response_worker,
        response_client,
        worker,
    ) = _make_remote_stack()
    remote_stack_setup_ms = (time.perf_counter() - connection_started) * 1_000

    remote_metrics: dict[str, int] | None = None
    replayed_result = False
    replay_latency_ms: float | None = None
    try:
        for index in range(warmups + iterations):
            if index == warmups:
                for counter in (
                    request_sender_transport,
                    request_worker_transport,
                    response_worker_transport,
                    response_client_transport,
                ):
                    counter.reset()
            event = _event(index + 1, receiver_authorizes=True)
            started = time.perf_counter()
            if request_sender.send(event) != index + 1:
                raise AssertionError("request channel sequence mismatch")
            served = worker.serve_once(request_worker, response_worker)
            if served is None or not served.executed:
                raise AssertionError("worker did not execute an admitted remote job")
            returned = response_client.receive()
            if returned is None or returned.effect is None:
                raise AssertionError("remote result was not received")
            acknowledged_request = request_sender.channel.process_ack()
            acknowledged_result = response_worker.channel.process_ack()
            elapsed = time.perf_counter() - started
            if acknowledged_request != (index + 1,) or acknowledged_result != (index + 1,):
                raise AssertionError("reliable request/result acknowledgement missing")
            if returned.effect["registers"]["result"] != _EXPECTED:
                raise AssertionError("remote MailCPU returned an incorrect result")
            if index >= warmups:
                remote_samples.append(elapsed)
                remote_metrics = {
                    "instructions": int(returned.effect["steps"]),
                    "scheduler_events": int(returned.effect["scheduler_events"]),
                }

        # Reuse the last semantic operation identity inside a new reliable frame.
        # The receiver must replay the effect without starting a second VM job.
        replay_event = _event(warmups + iterations, receiver_authorizes=True)
        started = time.perf_counter()
        request_sender.send(replay_event)
        replay_served = worker.serve_once(request_worker, response_worker)
        replayed = response_client.receive()
        request_sender.channel.process_ack()
        response_worker.channel.process_ack()
        replay_latency_ms = (time.perf_counter() - started) * 1_000
        replayed_result = bool(
            replay_served is not None
            and replay_served.replayed
            and replayed is not None
            and replayed.replayed
            and replayed.effect["registers"]["result"] == _EXPECTED
        )
        if not replayed_result:
            raise AssertionError("semantic replay did not return the committed effect")

        request_bytes = request_sender_transport.data_bytes()
        result_bytes = response_worker_transport.data_bytes()
        ack_bytes = request_worker_transport.ack_bytes() + response_client_transport.ack_bytes()
        reliable_retries = sum(
            transport.reliable_retries()
            for transport in (
                request_sender_transport,
                request_worker_transport,
                response_worker_transport,
                response_client_transport,
            )
        )
        wire_bytes_total = sum(
            transport.total_bytes
            for transport in (
                request_sender_transport,
                request_worker_transport,
                response_worker_transport,
                response_client_transport,
            )
        )
        request_frames = sum(
            1 for item in request_sender_transport.frames if item["op"] == "RDATA"
        )
        result_frames = sum(
            1 for item in response_worker_transport.frames if item["op"] == "RDATA"
        )
        return {
            "evidence_tier": "E0",
            "experiment": "equivalent-arithmetic-three-mode-transit-benchmark",
            "iterations": iterations,
            "warmups_per_mode": warmups,
            "expected_result": _EXPECTED,
            "all_modes_correct": True,
            "local_python": {
                **_summary(python_samples),
                "operations": iterations,
                "instructions": None,
                "scheduler_events": None,
            },
            "direct_mailcpu": {
                **_summary(direct_samples),
                **(direct_metrics or {}),
                "mode": "TransitComputeHost.handle with receiver-authorized event",
            },
            "remote_mailcpu": {
                **_summary(remote_samples),
                **(remote_metrics or {}),
                "mode": "persistent TransitComputeWorker over reused loopback TCP",
                "request_data_frames_including_replay": request_frames,
                "result_data_frames_including_replay": result_frames,
                "request_wire_bytes": request_bytes,
                "result_wire_bytes": result_bytes,
                "ack_wire_bytes": ack_bytes,
                "total_wire_bytes_all_directions": wire_bytes_total,
                "mean_request_frame_bytes": request_bytes / request_frames if request_frames else 0,
                "mean_result_frame_bytes": result_bytes / result_frames if result_frames else 0,
                "reliable_retry_frames": reliable_retries,
                "semantic_replay_count": int(replayed_result),
                "semantic_replay_latency_ms": replay_latency_ms,
                "remote_stack_setup_ms": remote_stack_setup_ms,
            },
            "measurement_notes": [
                "Remote latency includes request send, receiver authorization/arbitration, VM execution, response receive, and ACK processing.",
                "TCP connections are established once and reused; connection setup is excluded from per-job latency.",
                "Wire bytes are exact encoded ECPU frame lengths counted at transport send boundaries, including RDATA and RACK frames.",
                "Loopback endpoints run in one process on one machine; this does not predict WAN latency or physical-host throughput.",
                "Python is a minimal arithmetic reference; direct MailCPU includes parsing, isolated HeadlessOS setup, execution, and state digesting.",
                "Remote MailCPU additionally includes reliable transport, receiver-local authorization, arbitration, and result delivery.",
            ],
        }
    finally:
        for socket_transport in sockets:
            if not socket_transport.closed:
                socket_transport.close()


def main() -> None:
    """Mathematics: expose finite workload parameters and serialize reproducible benchmark observations."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        result = run_benchmark(args.iterations, args.warmups)
    except (ValueError, AssertionError, RuntimeError) as exc:
        parser.error(str(exc))
    encoded = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        from pathlib import Path

        Path(args.output).write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
