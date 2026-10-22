from __future__ import annotations

from pathlib import Path

import pytest

from mailcpu import (
    MailCPUVirtualMachine,
    ReferenceInterpreter,
    TrajectoryError,
    TrajectoryReader,
    TrajectoryWriter,
    canonical_result,
)
from mailcpu.model import Instruction, Op, Program
from mailcpu.programs import wait_send_program


def test_trajectory_receipts_index_seek_and_replay(tmp_path: Path) -> None:
    """Mathematics: verify `H_n` integrity, monotonic `t_n`, sparse seek, and replay count over scheduler events."""

    data_path = tmp_path / "run.mtrj"
    index_path = tmp_path / "run.mtrj.idx"
    with TrajectoryWriter(data_path, index_path, stride=2) as writer:
        writer.append(4, {"kind": "alpha", "value": 1})
        writer.append(2, {"kind": "beta", "value": 2})
        writer.append(9, {"kind": "gamma", "value": 3})
    with TrajectoryReader(data_path, index_path) as reader:
        assert reader.verify() == 3
        frame = reader.seek_time(3)
        assert frame is not None
        assert frame.logical_time == 4
        replayed: list[int] = []
        assert reader.replay(lambda item: replayed.append(item.sequence)) == 3
        assert replayed == [0, 1, 2]


def test_trajectory_resume_appends_one_verified_receipt_chain(tmp_path: Path) -> None:
    """Mathematics: `resume` preserves `H_last` and appends contiguous sequence `n_last+1` without rewriting the prefix."""

    data_path = tmp_path / "resume.mtrj"
    index_path = tmp_path / "resume.mtrj.idx"
    with TrajectoryWriter(data_path, index_path, stride=2) as writer:
        writer.append(1, {"kind": "alpha"})
        writer.append(2, {"kind": "beta"})
    prefix = data_path.read_bytes()
    with TrajectoryWriter.resume(data_path, index_path) as writer:
        writer.append(3, {"kind": "gamma"})
    with TrajectoryReader(data_path, index_path) as reader:
        assert reader.verify() == 3
        frames = []
        reader.replay(frames.append)
    assert data_path.read_bytes()[: len(prefix)] == prefix
    assert [frame.sequence for frame in frames] == [0, 1, 2]
    assert [frame.logical_time for frame in frames] == [1, 2, 3]


def test_trajectory_resume_refuses_tampered_prefix(tmp_path: Path) -> None:
    """Mathematics: `verify(prefix)=false` implies resume refuses before append and leaves the byte prefix unchanged."""

    data_path = tmp_path / "tampered-resume.mtrj"
    index_path = tmp_path / "tampered-resume.mtrj.idx"
    with TrajectoryWriter(data_path, index_path) as writer:
        writer.append(1, {"kind": "stable"})
    raw = bytearray(data_path.read_bytes())
    raw[-1] ^= 0x01
    data_path.write_bytes(raw)
    before = data_path.read_bytes()
    with pytest.raises(TrajectoryError):
        TrajectoryWriter.resume(data_path, index_path)
    assert data_path.read_bytes() == before


def test_vm_records_scheduler_trajectory(tmp_path: Path) -> None:
    """Mathematics: verify each scheduler event contributes exactly one trajectory frame `|F| = |events|`."""

    data_path = tmp_path / "vm.mtrj"
    index_path = tmp_path / "vm.mtrj.idx"
    program = Program((Instruction(Op.SET, ("x", 7)), Instruction(Op.HALT)))
    with TrajectoryWriter(data_path, index_path) as writer:
        vm = MailCPUVirtualMachine(trajectory=writer)
        vm.spawn_program(program, "trajectory-task")
        events = vm.run()
    with TrajectoryReader(data_path, index_path) as reader:
        assert reader.verify() == len(events)


def test_vm_semantic_trajectory_replays_reference_trace(tmp_path: Path) -> None:
    """Mathematics: persisted scheduler frames satisfy `π(trajectory(run(P))) = canonical(reference(P).trace)` including registers and output deltas."""

    data_path = tmp_path / "semantic.mtrj"
    index_path = tmp_path / "semantic.mtrj.idx"
    program = wait_send_program()
    with TrajectoryWriter(data_path, index_path) as writer:
        vm = MailCPUVirtualMachine(trajectory=writer)
        pid = vm.spawn_program(program, "semantic-task")
        vm.scheduler.inject(pid, "inbox", [42])
        events = vm.run()
    with TrajectoryReader(data_path, index_path) as reader:
        assert reader.verify() == len(events)
        frames = []
        assert reader.replay(frames.append) == len(events)

    observed = [
        {
            key: frame.payload[key]
            for key in ("step", "pc_before", "op", "args", "pc_after", "registers", "output_delta")
        }
        for frame in frames
    ]
    expected = canonical_result(
        ReferenceInterpreter(program).run(inputs={"inbox": [42]})
    )["trace"]
    assert observed == expected


def test_trajectory_corruption_is_not_silently_accepted(tmp_path: Path) -> None:
    """Mathematics: changing payload bytes changes `H_n`, so verification must reject the corrupted stream."""

    data_path = tmp_path / "corrupt.mtrj"
    index_path = tmp_path / "corrupt.mtrj.idx"
    with TrajectoryWriter(data_path, index_path) as writer:
        writer.append(1, {"kind": "stable"})
    raw = bytearray(data_path.read_bytes())
    raw[-2] ^= 0x01
    data_path.write_bytes(raw)
    with TrajectoryReader(data_path, index_path) as reader:
        with pytest.raises(TrajectoryError):
            reader.verify()
