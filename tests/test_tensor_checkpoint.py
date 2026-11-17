"""Process-interruption, atomic publication and bounded tensor checkpoint recovery."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from mailcpu import EGPUHost
from mailcpu.tensor_checkpoint import TensorCheckpointFile
from mailcpu.tensor_stream import TensorStreamError, execute_tiled_matmul


def _prefixes():
    """Mathematics: collect two independently verified prefixes of one dot product."""
    host, saved = EGPUHost(), []
    execute_tiled_matmul([[2, 3]], [[5], [7]],
                         lambda p: host.execute_authorized_method("tensor.matmul.tile", p),
                         tile_rows=1, tile_cols=1, chunk_depth=1, checkpoint_sink=saved.append)
    return saved


def test_tensor_file_recovers_after_worker_process_exits_without_cleanup(tmp_path):
    """Mathematics: a separately terminated process leaves two durable chunks for another host."""
    target = tmp_path / "prefix.json"
    script = '''
import os, sys
from mailcpu import EGPUHost
from mailcpu.tensor_checkpoint import TensorCheckpointFile
from mailcpu.tensor_stream import execute_tiled_matmul
store = TensorCheckpointFile(sys.argv[1])
host = EGPUHost(host_id="terminated-worker")
def persist(state):
    store.save(state)
    if len(state["tiles"]) == 2:
        os._exit(23)
execute_tiled_matmul([[2,3,4,5]], [[7],[11],[13],[17]],
    lambda p: host.execute_authorized_method("tensor.matmul.tile", p),
    tile_rows=1, tile_cols=1, chunk_depth=1, checkpoint_sink=persist)
'''
    process = subprocess.run([sys.executable, "-c", script, str(target)],
                             cwd=Path(__file__).resolve().parents[1],
                             capture_output=True, text=True, timeout=30)
    assert process.returncode == 23, process.stderr
    store = TensorCheckpointFile(target)
    checkpoint = store.load()
    assert len(checkpoint["tiles"]) == 2
    host, calls = EGPUHost(host_id="recovery-worker"), []

    def dispatch(payload):
        """Mathematics: observe which suffix operands the replacement host actually receives."""
        calls.append(payload["left"])
        return host.execute_authorized_method("tensor.matmul.tile", payload)

    result = execute_tiled_matmul([[2, 3, 4, 5]], [[7], [11], [13], [17]], dispatch,
                                 tile_rows=1, tile_cols=1, chunk_depth=1,
                                 checkpoint=checkpoint, checkpoint_sink=store.save)
    assert result["values"] == [[184]] and calls == [[4], [5]]
    assert len(store.load()["tiles"]) == 4


@pytest.mark.parametrize("failure", ["fsync", "replace"])
def test_tensor_file_failed_publication_preserves_previous_prefix(tmp_path, monkeypatch, failure):
    """Mathematics: an interrupted publication leaves the prior committed file intact."""
    import mailcpu.checkpoint as persistence

    first, second = _prefixes()
    store = TensorCheckpointFile(tmp_path / "prefix.json")
    assert store.load() is None
    store.save(first)

    def fail(*args):
        """Mathematics: inject a persistence failure before publication can complete."""
        raise OSError("injected storage failure")

    monkeypatch.setattr(persistence.os, failure, fail)
    with pytest.raises(OSError, match="injected storage failure"):
        store.save(second)
    assert store.load() == first
    assert list(tmp_path.iterdir()) == [store.path]


def test_tensor_file_rejects_corruption_and_bounds_before_replacing(tmp_path):
    """Mathematics: invalid or oversized candidates cannot replace previously committed evidence."""
    first, second = _prefixes()
    path = tmp_path / "prefix.json"
    store = TensorCheckpointFile(path)
    store.save(first)
    bounded = TensorCheckpointFile(path, max_bytes=path.stat().st_size)
    assert bounded.load() == first
    with pytest.raises(TensorStreamError, match="byte budget"):
        bounded.save(second)
    assert store.load() == first
    second["tiles"].clear()
    with pytest.raises(TensorStreamError, match="digest mismatch"):
        store.save(second)
    assert store.load() == first
    path.write_text(json.dumps(second), encoding="utf-8")
    with pytest.raises(TensorStreamError, match="digest mismatch"):
        store.load()
    path.write_bytes(b"x" * 100)
    with pytest.raises(TensorStreamError, match="byte budget"):
        TensorCheckpointFile(path, max_bytes=50).load()
    path.write_bytes(b"{")
    with pytest.raises(TensorStreamError, match="invalid tensor checkpoint JSON"):
        store.load()
