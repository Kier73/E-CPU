from __future__ import annotations

from pathlib import Path

import pytest

from mailcpu import MailCPUVirtualMachine, TrajectoryError, TrajectoryReader, TrajectoryWriter
from mailcpu.model import Instruction, Op, Program


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
