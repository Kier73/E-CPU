from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from mailcpu import (
    DurableSeedCommitJournal,
    HeadlessOS,
    HypervisorSeedCommitChannel,
    HypervisorSeedCommitRecoveryCoordinator,
    HypervisorSeedCommitResultChannel,
    RecoveryCoordinatorError,
    ReliabilityPolicy,
    ReliableChannel,
    SeedCommitJournalError,
    SeedCommitRequest,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
    SocketTransport,
)
from mailcpu.programs import wait_send_program


def _tcp_pair() -> tuple[SocketTransport, SocketTransport]:
    """Mathematics: create one reciprocal AF_INET stream `T_origin↔T_executor` for a process recovery cut."""

    listener = SocketTransport.listen("127.0.0.1", 0)
    port = listener.getsockname()[1]
    origin = SocketTransport.connect("127.0.0.1", port, "origin", "executor")
    executor = SocketTransport.accept(listener, "executor", "origin")
    listener.close()
    return origin, executor


def _machine() -> tuple[HeadlessOS, int]:
    """Mathematics: construct admitted origin state `Σ₀` and a blocked process that accepts one deterministic input."""

    machine = HeadlessOS()
    pid = machine.spawn(wait_send_program(), "durable-seed-input")
    envelope = SystemSeedEnvelope(SystemIdentity("durable-system", 1), "origin", "seed", SystemSeed.from_system(machine))
    assert machine.seed_admission.admit(envelope).accepted
    return machine, pid


def _channels(
    origin_transport: SocketTransport,
    executor_transport: SocketTransport,
) -> tuple[
    HypervisorSeedCommitChannel,
    HypervisorSeedCommitChannel,
    HypervisorSeedCommitResultChannel,
    HypervisorSeedCommitResultChannel,
]:
    """Mathematics: create reciprocal request/result channels over one physical transport per host."""

    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=5, window_size=8)
    request_origin = HypervisorSeedCommitChannel(
        ReliableChannel(origin_transport, "origin", "executor", "seed.commit.request", policy)
    )
    request_executor = HypervisorSeedCommitChannel(
        ReliableChannel(executor_transport, "executor", "executor", "seed.commit.request", policy, peer="origin")
    )
    result_executor = HypervisorSeedCommitResultChannel(
        ReliableChannel(executor_transport, "executor", "origin", "seed.commit.result", policy),
        operation_source="origin",
        operation_channel="seed.commit.request",
    )
    result_origin = HypervisorSeedCommitResultChannel(
        ReliableChannel(origin_transport, "origin", "origin", "seed.commit.result", policy, peer="executor"),
        operation_source="origin",
        operation_channel="seed.commit.request",
    )
    return request_origin, request_executor, result_executor, result_origin


def _request(machine: HeadlessOS, pid: int) -> SeedCommitRequest:
    """Mathematics: bind input request `q` to the precondition digest `d(Σ₀)` in the active host registry."""

    envelope = machine.seed_admission.current("durable-system")
    assert envelope is not None
    return SeedCommitRequest("durable-system", "resolver", 1, pid, "inbox", (42,), envelope.state_digest)


def test_durable_seed_result_and_host_state_survive_executor_process_loss(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mathematics: `fsync(result,OS)` before reply means replay after process loss returns one commit and one state advance."""

    origin_transport, executor_transport = _tcp_pair()
    origin_machine = HeadlessOS()
    executor_machine, pid = _machine()
    request_origin, request_executor, result_executor, result_origin = _channels(origin_transport, executor_transport)
    origin = HypervisorSeedCommitRecoveryCoordinator(
        origin_transport, request_origin, result_origin, origin_machine, role="origin"
    )
    executor = HypervisorSeedCommitRecoveryCoordinator(
        executor_transport, request_executor, result_executor, executor_machine, role="executor"
    )
    journal_path = tmp_path / "seed-commit.log"
    journal = DurableSeedCommitJournal(journal_path, "executor")
    observer = DurableSeedCommitJournal(journal_path, "executor")
    original_send = result_executor.send

    def lose_result(result: object) -> int:
        """Mathematics: model the crash cut after journal fsync with `send(result)=⊥` and no request ACK."""

        raise OSError("simulated executor loss after durable commit")

    monkeypatch.setattr(result_executor, "send", lose_result)
    try:
        request = _request(executor_machine, pid)
        assert origin.send(request) == 1
        with pytest.raises(OSError, match="after durable commit"):
            executor.receive_and_commit(journal)
        assert executor_machine.vm.scheduler.tick == 1
        assert journal.snapshot()["sequence"] == 1
        observed = observer.lookup(("origin", "seed.commit.request", 1), request.fingerprint)
        assert observed is not None and observed.accepted and not observed.replayed
        origin_checkpoint = origin.checkpoint()
        origin_transport.close()
        executor_transport.close()

        reopened_journal = DurableSeedCommitJournal(journal_path, "executor")
        restored_executor_machine = reopened_journal.restore_host()
        assert restored_executor_machine is not None
        assert restored_executor_machine.vm.scheduler.tick == 1
        rebound_origin, rebound_executor = _tcp_pair()
        restored_origin = HypervisorSeedCommitRecoveryCoordinator.rebind(
            origin_checkpoint, rebound_origin.socket, role="origin", peer="executor"
        )
        _, request_executor2, result_executor2, _ = _channels(rebound_origin, rebound_executor)
        restored_executor = HypervisorSeedCommitRecoveryCoordinator(
            rebound_executor,
            request_executor2,
            result_executor2,
            restored_executor_machine,
            role="executor",
        )
        try:
            assert restored_origin.retry() == ()
            replay = restored_executor.receive_and_commit(reopened_journal)
            assert replay is not None and replay.accepted and replay.replayed
            result = restored_origin.receive_result()
            assert result is not None and result.accepted and result.replayed
            assert restored_executor.service() == (1,)
            assert restored_executor.operating_system.vm.scheduler.tick == 1
            assert restored_executor.operating_system.seed_admission.current("durable-system").seed.coordinate == 1
            assert reopened_journal.verify()
        finally:
            restored_origin.close()
            restored_executor.close()
    finally:
        if not origin_transport.closed:
            origin_transport.close()
        if not executor_transport.closed:
            executor_transport.close()
        monkeypatch.setattr(result_executor, "send", original_send)


def test_durable_seed_journal_repairs_only_torn_final_suffix(tmp_path) -> None:
    """Mathematics: replay preserves every complete `R_i` and truncates only a non-newline suffix `R_partial`."""

    machine, _pid = _machine()
    journal_path = tmp_path / "seed-commit.log"
    journal = DurableSeedCommitJournal(journal_path, "executor")
    before = journal_path.read_bytes()
    with journal_path.open("ab") as stream:
        stream.write(b'{"incomplete":')
    assert not journal.verify()
    assert journal_path.read_bytes() != before
    reopened = DurableSeedCommitJournal(journal_path, "executor")
    assert reopened.snapshot()["sequence"] == 0
    assert reopened.verify()
    assert journal_path.read_bytes() == before
    assert machine.vm.scheduler.tick == 0


def test_durable_seed_journal_rejects_tampered_complete_record(tmp_path) -> None:
    """Mathematics: any altered complete record makes `SHA256(H_prev||J_i)≠receipt_i` and replay refuses."""

    origin_transport, executor_transport = _tcp_pair()
    machine, pid = _machine()
    request_origin, request_executor, result_executor, _result_origin = _channels(origin_transport, executor_transport)
    journal_path = tmp_path / "seed-commit.log"
    journal = DurableSeedCommitJournal(journal_path, "executor")
    try:
        request_origin.send(_request(machine, pid))
        result = request_executor.receive_and_commit(machine, result_executor, journal)
        assert result is not None and result.accepted
    finally:
        origin_transport.close()
        executor_transport.close()
    document = json.loads(journal_path.read_text(encoding="utf-8"))
    document["request_fingerprint"] = "0" * 64
    journal_path.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    with pytest.raises(SeedCommitJournalError, match="receipt"):
        DurableSeedCommitJournal(journal_path, "executor")


def test_durable_seed_journal_rejects_malformed_field_types_as_journal_errors(tmp_path) -> None:
    """Mathematics: malformed complete records `R∉J` map to `SeedCommitJournalError`, never leaked coercion errors."""

    journal_path = tmp_path / "seed-commit.log"
    DurableSeedCommitJournal(journal_path, "executor")
    journal_path.write_text('{"version":[],"sequence":1}\n', encoding="utf-8")
    with pytest.raises(SeedCommitJournalError, match="unsupported"):
        DurableSeedCommitJournal(journal_path, "executor")


def test_durable_seed_commit_survives_abrupt_executor_process_exit(tmp_path) -> None:
    """Mathematics: after `fsync(R)`, process-local state vanishes but replay reconstructs the same accepted host state."""

    journal_path = tmp_path / "process-loss.log"
    child = r'''# Mathematics: commit one admitted input, fsync `(result, host)`, then terminate without interpreter cleanup.
import os
import sys
import time
from pathlib import Path
from mailcpu import (
    DurableSeedCommitJournal,
    HeadlessOS,
    SeedCommitRequest,
    SeedCommitResult,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
)
from mailcpu.programs import wait_send_program
from mailcpu.seed_commit_transport import _frontier_digest

machine = HeadlessOS()
pid = machine.spawn(wait_send_program(), "child-process-seed")
before = SystemSeedEnvelope(
    SystemIdentity("process-seed", 1), "origin", "seed", SystemSeed.from_system(machine)
)
assert machine.seed_admission.admit(before).accepted
request = SeedCommitRequest(
    "process-seed", "external", 1, pid, "inbox", (73,), before.state_digest
)
admission, after = machine.commit_seed_input(
    request.system_id, request.source, request.sequence, request.pid, request.mailbox, request.values
)
assert admission.accepted
result = SeedCommitResult(
    "origin",
    "seed.commit.request",
    1,
    request.fingerprint,
    request.system_id,
    True,
    admission.replayed,
    after.state_digest,
    _frontier_digest(after),
    admission.admission_receipt,
    after,
)
journal = DurableSeedCommitJournal(Path(sys.argv[1]), "executor")
journal.record(("origin", "seed.commit.request", 1), request.fingerprint, result, machine)
os._exit(23)
'''
    process = subprocess.run(
        [sys.executable, "-c", child, str(journal_path)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 23, process.stderr

    recovered = DurableSeedCommitJournal(journal_path, "executor")
    host = recovered.restore_host()
    assert host is not None
    assert host.vm.scheduler.tick == 1
    current = host.seed_admission.current("process-seed")
    assert current is not None and current.seed.coordinate == 1
    assert recovered.snapshot()["sequence"] == 1
    assert recovered.verify()


def test_remote_retry_recovers_after_real_executor_process_death(tmp_path) -> None:
    """Mathematics: crash after `fsync(result,OS)` but before send; retry over a new TCP stream returns one committed tick."""

    journal_path = tmp_path / "remote-process-loss.log"
    child = r'''# Mathematics: receive a real reliable request, durably commit, and either die before response or replay after restart.
import os
import sys
import time
from pathlib import Path
from mailcpu import (
    DurableSeedCommitJournal,
    HeadlessOS,
    HypervisorSeedCommitChannel,
    HypervisorSeedCommitRecoveryCoordinator,
    HypervisorSeedCommitResultChannel,
    ReliabilityPolicy,
    ReliableChannel,
    SocketTransport,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
)
from mailcpu.programs import wait_send_program

journal = DurableSeedCommitJournal(Path(sys.argv[1]), "executor")
mode = sys.argv[3]
if mode == "crash":
    machine = HeadlessOS()
    pid = machine.spawn(wait_send_program(), "durable-seed-input")
    envelope = SystemSeedEnvelope(
        SystemIdentity("durable-system", 1), "origin", "seed", SystemSeed.from_system(machine)
    )
    assert machine.seed_admission.admit(envelope).accepted
else:
    machine = journal.restore_host()
    assert machine is not None

transport = SocketTransport.connect("127.0.0.1", int(sys.argv[2]), "executor", "origin")
policy = ReliabilityPolicy(lease_ticks=1, max_attempts=5, window_size=8)
request_channel = HypervisorSeedCommitChannel(
    ReliableChannel(transport, "executor", "executor", "seed.commit.request", policy, peer="origin")
)
response_channel = HypervisorSeedCommitResultChannel(
    ReliableChannel(transport, "executor", "origin", "seed.commit.result", policy),
    operation_source="origin",
    operation_channel="seed.commit.request",
)
executor = HypervisorSeedCommitRecoveryCoordinator(
    transport, request_channel, response_channel, machine, role="executor"
)
deadline = time.monotonic() + 20
while request_channel.channel.peek() is None and time.monotonic() < deadline:
    time.sleep(0.01)
assert request_channel.channel.peek() is not None
if mode == "crash":
    def die_before_response(_result):
        # Mathematics: terminate at the cut `durable record -> no response bytes`.
        os._exit(31)
    response_channel.send = die_before_response
    executor.receive_and_commit(journal)
else:
    result = executor.receive_and_commit(journal)
    assert result is not None and result.accepted and result.replayed
    assert executor.operating_system.vm.scheduler.tick == 1
    deadline = time.monotonic() + 10
    while response_channel.channel.pending_sequences() and time.monotonic() < deadline:
        response_channel.channel.process_ack()
        time.sleep(0.01)
    assert response_channel.channel.pending_sequences() == ()
    executor.close()
'''

    def launch(mode: str) -> tuple[subprocess.Popen[str], SocketTransport]:
        """Mathematics: pair one child executor process with exactly one accepted `AF_INET` stream."""

        listener = SocketTransport.listen("127.0.0.1", 0)
        listener.settimeout(10)
        port = listener.getsockname()[1]
        process = subprocess.Popen(
            [sys.executable, "-c", child, str(journal_path), str(port), mode],
            cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            transport = SocketTransport.accept(listener, "origin", "executor")
        except Exception:
            process.kill()
            process.wait(timeout=10)
            raise
        finally:
            listener.close()
        return process, transport

    initial, pid = _machine()
    first_process, first_transport = launch("crash")
    policy = ReliabilityPolicy(lease_ticks=1, max_attempts=5, window_size=8)
    origin_request = HypervisorSeedCommitChannel(
        ReliableChannel(first_transport, "origin", "executor", "seed.commit.request", policy)
    )
    origin_response = HypervisorSeedCommitResultChannel(
        ReliableChannel(first_transport, "origin", "origin", "seed.commit.result", policy, peer="executor"),
        operation_source="origin",
        operation_channel="seed.commit.request",
    )
    origin = HypervisorSeedCommitRecoveryCoordinator(
        first_transport, origin_request, origin_response, HeadlessOS(), role="origin"
    )
    try:
        request = _request(initial, pid)
        assert origin.send(request) == 1
        checkpoint = origin.checkpoint()
        first_output, first_error = first_process.communicate(timeout=30)
        assert first_process.returncode == 31, first_error
        assert first_output == ""
    finally:
        if not origin.transport.closed:
            origin.close()
        if first_process.poll() is None:
            first_process.kill()
            first_process.wait(timeout=10)

    second_process, rebound_transport = launch("recover")
    recovered_origin = None
    try:
        recovered_origin = HypervisorSeedCommitRecoveryCoordinator.rebind(
            checkpoint, rebound_transport.socket, role="origin", peer="executor"
        )
        assert recovered_origin.retry() == ()
        result = None
        deadline = time.monotonic() + 10
        while result is None and time.monotonic() < deadline:
            result = recovered_origin.receive_result()
            if result is None:
                time.sleep(0.01)
        assert result is not None and result.accepted and result.replayed
        output, error = second_process.communicate(timeout=30)
        assert second_process.returncode == 0, error
        assert output == ""
        recovered_journal = DurableSeedCommitJournal(journal_path, "executor")
        recovered_host = recovered_journal.restore_host()
        assert recovered_host is not None
        assert recovered_host.vm.scheduler.tick == 1
        current = recovered_host.seed_admission.current("durable-system")
        assert current is not None and current.seed.coordinate == 1
        assert recovered_journal.verify()
    finally:
        if recovered_origin is not None:
            recovered_origin.close()
        elif not rebound_transport.closed:
            rebound_transport.close()
        if second_process.poll() is None:
            second_process.kill()
            second_process.wait(timeout=10)


def test_durable_append_failure_rolls_back_host_and_keeps_request_pending(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mathematics: if durable publication fails, restore `OS_before` and leave request `F_s` unconsumed for retry."""

    origin_transport, executor_transport = _tcp_pair()
    machine, pid = _machine()
    before = machine.snapshot()
    request_origin, request_executor, result_executor, _result_origin = _channels(origin_transport, executor_transport)
    journal = DurableSeedCommitJournal(tmp_path / "seed-commit.log", "executor")
    request_origin.send(_request(machine, pid))

    def fail_record(*_args: object, **_kwargs: object) -> bool:
        """Mathematics: model `append(R)=failure` before durable publication."""

        raise OSError("simulated journal write failure")

    monkeypatch.setattr(journal, "record", fail_record)
    try:
        with pytest.raises(OSError, match="journal write failure"):
            request_executor.receive_and_commit(machine, result_executor, journal)
        assert machine.snapshot() == before
        assert request_executor.channel.peek() is not None
        assert journal.snapshot()["sequence"] == 0
    finally:
        origin_transport.close()
        executor_transport.close()
