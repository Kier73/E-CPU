"""True process-boundary persistence through E-CPU M1/M3/M4, no shared Python state."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest
pytest.importorskip("vgi.guarded_reduction")


def test_two_python_receivers_resume_checkpoint_and_run_new_ground(tmp_path: Path):
    demo = Path(__file__).resolve().parents[1] / "examples" / "vgi_guarded_recovery_demo.py"
    outputs=[]
    for phase in ("bootstrap", "resume"):
        result=subprocess.run([sys.executable, str(demo), phase, str(tmp_path)],
            text=True, capture_output=True, timeout=50, check=False)
        assert result.returncode == 0, result.stderr
        outputs.append(json.loads(result.stdout))
    source, target=outputs
    assert source["pid"] != target["pid"]
    assert source["revision"] == 2
    assert target["revision"] == 4
    assert target["checkpoint_digest"] != source["checkpoint_digest"]
    assert target["lineage_digest"] != source["lineage_digest"]
    assert source["source_dimensions"] == 48
    assert target["one_probe"] is True
    assert target["total_virtual_steps"] == "23"
