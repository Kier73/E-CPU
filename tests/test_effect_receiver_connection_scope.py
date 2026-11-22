"""Receiver SQLite handles must close even when the receiver object survives.

The standard sqlite3 connection context manager only commits/rolls back:
it is not a resource-lifetime manager. A leaked handle prevents Windows
deleting a source-recovered receiver's SQLite state after the test process.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile

import pytest

from mailcpu.fenced_effect_receiver import FencedGroundEffectReceiver

RESOURCE = "/virtual-layer/effects/ips008-scoped-connection"


def test_scoped_receiver_connection_closes_after_success_and_failure(
    tmp_path: Path,
) -> None:
    receiver = FencedGroundEffectReceiver(
        tmp_path / "receiver.sqlite", resource=RESOURCE,
        plan_digest="a"*64,
    )
    with receiver._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM receiver_policy").fetchone() == (1,)
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        db.execute("SELECT 1")

    with pytest.raises(RuntimeError, match="simulated failure"):
        with receiver._connect() as interrupted:
            assert interrupted.execute("SELECT 1").fetchone() == (1,)
            raise RuntimeError("simulated failure")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        interrupted.execute("SELECT 1")

    # Every public read reopens and then closes a fresh handle.
    for _ in range(6):
        assert receiver.snapshot()["installed_root"] is None


def test_temporary_receiver_storage_is_removable_with_receiver_object_alive():
    """Windows rejects rmtree while any previously used SQLite handle is open."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        receiver = FencedGroundEffectReceiver(
            root/"receiver.sqlite", resource=RESOURCE,
            plan_digest="b"*64,
        )
        for _ in range(3):
            receiver.snapshot()
        assert (root/"receiver.sqlite").is_file()
    # Receiver object remains alive here. No GC or process exit is required.
    assert not Path(directory).exists()
    assert receiver.resource == RESOURCE
