"""SOI-010: original eight-layer Qwen GDN/GQA state through E-CPU's actual M1.

Original numerical source is VL-I/VL-64's independently verified small
F32 model fixture, **not** original 27B pretrained weight payload. The
unmodified QwenArchitectureCausalPrefix and original layer/attention state
serializer are exercised; their LocalStatePages contract is implemented over
real M1 4-KiB page manifests without copying or redefining any Qwen math.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.vli_qwen_pages import (
    DurableModelPageBacking, m1_qwen_causal_pages,
    check_original_qwen_checkpoint_pages,
)

original = pytest.importorskip("test_qwen_architecture_navigator")
pytest.importorskip("experiments.model_fabric.complete_native_layers")
from vli.qwen_architecture_navigator import QwenArchitectureCausalPrefix

LINEAGE = "a" * 64


def _source():
    """Use the full, original eight-layer VL-I test navigator from pinned source."""
    return original.auto_eight()


def _recreate(raw: dict, backing_root: Path):
    """Reopen raw M1 pages through different E-CPU object and original VL-I runtimes."""
    backing = DurableModelPageBacking(backing_root)
    store = ComputationalObjectStore(backing, chunk_size=4096)
    page_store = m1_qwen_causal_pages(store, bundle=raw["bundle"])
    navigator = original.nav_eight_layers()
    prefix = QwenArchitectureCausalPrefix.restore(
        navigator, original.plan_for(navigator), page_store,
        raw["checkpoint"],
        expected_digest=raw["checkpoint"]["checkpoint_digest"],
        expected_input_sequence_digest=LINEAGE,
        expected_plan_digest=raw["checkpoint"]["plan_digest"],
        max_positions=64,
    )
    return prefix, page_store


def test_real_qwen_eight_layer_gdn_gqa_kv_pages_roundtrip_through_m1(tmp_path: Path) -> None:
    """6 full GDN matrices and 2 gated GQA KV histories persist as M1 bytes."""
    model = _source()
    first, receipt = model.step([.5, -.2, .3], token_id=63204)
    store = ComputationalObjectStore(
        DurableModelPageBacking(tmp_path / "native-m1"), chunk_size=4096,
    )
    pages = m1_qwen_causal_pages(store)
    checkpoint = model.checkpoint(pages, input_sequence_digest=LINEAGE)
    bundle = pages.export_bundle()
    stats = check_original_qwen_checkpoint_pages(checkpoint, pages)
    assert checkpoint["position"] == 1
    assert checkpoint["stop_layer"] == 8
    assert stats["gdn_layers"] == 6
    assert stats["gqa_layers"] == 2
    assert stats["source_page_refs"] >= 8
    assert bundle["total_bytes"] == stats["source_bytes"]
    assert pages.verify_bundle()
    assert len(bundle["pages"]) > 0
    for digest, manifest in bundle["pages"].items():
        assert manifest["content_digest"] == digest
        assert manifest["size_bytes"] <= 65536
        assert all(chunk["byte_length"] <= 4096 for chunk in manifest["chunks"])

    restored, newpages = _recreate(
        {"checkpoint": checkpoint, "bundle": bundle},
        tmp_path / "native-m1",
    )
    assert restored.position == model.position
    assert restored.head == model.head
    assert restored._snapshot() == model._snapshot()
    assert newpages.verify_bundle()

    for token, hidden in ((628, [-.1, .2, .8]), (123, [.7, .6, -.3])):
        expected, old_receipt = model.step(hidden, token_id=token)
        actual, new_receipt = restored.step(hidden, token_id=token)
        assert actual == expected
        assert new_receipt["chain_head"] == old_receipt["chain_head"]
        assert restored._snapshot() == model._snapshot()
    assert len(new_receipt["layer_witnesses"]) == 8
    assert [row["kind"] for row in new_receipt["layer_witnesses"]] == (
        ["GDN", "GDN", "GDN", "GATED_GQA"] * 2
    )
    assert not new_receipt["complete_decoder"]
    assert not new_receipt["vocabulary_logits_computed"]


def test_original_qwen_m1_bundle_refuses_missing_replaced_and_broken_pages(tmp_path: Path) -> None:
    """Typed M1 bytes and source-recovered GDN/GQA pages resist replacement."""
    store = ComputationalObjectStore(
        DurableModelPageBacking(tmp_path / "m1"), chunk_size=4096,
    )
    pages = m1_qwen_causal_pages(store, max_pages=16)
    checkpoint = _source()
    checkpoint.step([.5, -.2, .3], token_id=63204)
    native = checkpoint.checkpoint(pages, input_sequence_digest=LINEAGE)
    bundle = pages.export_bundle()
    chosen = next(iter(bundle["pages"]))
    altered = json.loads(json.dumps(bundle))
    altered["pages"][chosen]["content_digest"] = "f" * 64
    with pytest.raises(ValueError, match="bundle digest"):
        m1_qwen_causal_pages(store, bundle=altered)

    # Test actual durable E-CPU 4 KiB backing corruption, not only JSON hashes.
    manifest = bundle["pages"][chosen]
    physical_page = manifest["chunks"][0]["page_digest"]
    (tmp_path / "m1" / physical_page).write_bytes(b"corrupted")
    reread = m1_qwen_causal_pages(store, bundle=bundle)
    with pytest.raises((ValueError, OSError), match="corrupt"):
        check_original_qwen_checkpoint_pages(native, reread)
    with pytest.raises((ValueError, OSError), match="corrupt"):
        reread.verify_bundle()


CHILD = r"""
import json, os, sys, time
from pathlib import Path
from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.vli_qwen_pages import (
    DurableModelPageBacking, m1_qwen_causal_pages,
    check_original_qwen_checkpoint_pages,
)
from vli.qwen_architecture_navigator import QwenArchitectureCausalPrefix
from test_qwen_architecture_navigator import auto_eight, nav_eight_layers, plan_for
payload = json.loads(sys.stdin.buffer.read())
store = ComputationalObjectStore(
    DurableModelPageBacking(Path(payload["root"])), chunk_size=4096,
)
if payload["mode"] == "start":
    model = auto_eight()
    pages = m1_qwen_causal_pages(store)
else:
    pages = m1_qwen_causal_pages(store, bundle=payload["bundle"])
    nav = nav_eight_layers()
    cp = payload["checkpoint"]
    model = QwenArchitectureCausalPrefix.restore(
        nav, plan_for(nav), pages, cp,
        expected_digest=cp["checkpoint_digest"],
        expected_input_sequence_digest=payload["lineage"],
        expected_plan_digest=cp["plan_digest"],
        max_positions=64,
    )
result, receipt = model.step(payload["hidden"], token_id=payload["token"])
cp = model.checkpoint(pages, input_sequence_digest=payload["lineage"])
stats = check_original_qwen_checkpoint_pages(cp, pages)
evidence = {
    "pid": os.getpid(), "position": model.position,
    "result": result, "receipt": receipt, "checkpoint": cp,
    "bundle": pages.export_bundle(), "stats": stats,
}
print(json.dumps(evidence, sort_keys=True, separators=(",",":")), flush=True)
if payload["mode"] == "start":
    while True: time.sleep(1)
"""


def _child(payload: dict, *, kill_after_publish=False) -> dict:
    """Run the real original Qwen eight-layer prefix in a separate Python process."""
    child = subprocess.Popen(
        [sys.executable, "-u", "-c", CHILD],
        cwd=Path(__file__).resolve().parents[1],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    assert child.stdin is not None and child.stdout is not None
    try:
        if kill_after_publish:
            child.stdin.write(data)
            child.stdin.close()
            response = child.stdout.readline()
            assert response, "original Qwen model never published M1 causal state"
            assert child.poll() is None
            child.kill()
            child.wait(timeout=20)
            return json.loads(response)
        output, errors = child.communicate(data, timeout=90)
        if child.returncode != 0:
            raise RuntimeError(errors.decode(errors="replace")[-2500:])
        return json.loads(output)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=20)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None:
                stream.close()


def test_two_full_original_qwen_hybrid_blocks_move_across_killed_processes(tmp_path: Path) -> None:
    """Kill original executing model, reopen E-CPU M1 and continue all 8 causal layers."""
    root = tmp_path / "durable-native-m1"
    first = _child({
        "mode": "start", "root": str(root), "lineage": LINEAGE,
        "hidden": [.5, -.2, .3], "token": 63204,
    }, kill_after_publish=True)
    assert first["position"] == 1
    assert first["stats"]["gdn_layers"] == 6
    assert first["stats"]["gqa_layers"] == 2
    assert first["bundle"]["total_bytes"] > 0
    second = _child({
        "mode": "recover", "root": str(root), "lineage": LINEAGE,
        "checkpoint": first["checkpoint"], "bundle": first["bundle"],
        "hidden": [-.1, .2, .8], "token": 628,
    })
    assert second["pid"] != first["pid"]
    assert second["position"] == 2
    assert second["checkpoint"]["position"] == 2
    assert second["checkpoint"]["plan_digest"] == first["checkpoint"]["plan_digest"]
    assert second["stats"]["gdn_layers"] == 6
    assert second["stats"]["gqa_layers"] == 2
    assert len(second["receipt"]["layer_witnesses"]) == 8
    assert [row["kind"] for row in second["receipt"]["layer_witnesses"]] == (
        ["GDN", "GDN", "GDN", "GATED_GQA"] * 2
    )
    assert all(layer["position"] == 2 for layer in second["checkpoint"]["layer_checkpoints"])
    uninterrupted = _source()
    uninterrupted.step([.5, -.2, .3], token_id=63204)
    result, actual_receipt = uninterrupted.step([-.1, .2, .8], token_id=628)
    assert second["result"] == result
    assert second["receipt"]["chain_head"] == actual_receipt["chain_head"]
    reread, _ = _recreate(second, root)
    assert reread._snapshot() == uninterrupted._snapshot()
    assert reread.head == uninterrupted.head
