"""Observe an externally hosted model/page as an E-CPU source address catalogue.

This process never loads a model, executes external code or downloads weight
shards. It resolves a human-visible Hugging Face page URL through the host's
structured API to an immutable revision and all declared source file addresses.

Example:
  python scripts/observe_hosted_surface.py \
    --url https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/tree/main \
    --out artifacts/deepseek-source-addresses.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from mailcpu.external_surface_streams import (
    BoundedHTTPSObserver, HostedSurfaceNavigator,
)


def run(url: str, *, expected_revision: str | None = None) -> dict:
    """Compile one remote model page into a source-pinned typed inventory."""
    observer = BoundedHTTPSObserver(("huggingface.co",), timeout=15.0)
    tree = HostedSurfaceNavigator(observer).discover(url)
    if expected_revision is not None and expected_revision != tree.revision:
        raise ValueError("model page resolved to a different immutable source")
    source = tree.to_dict()
    original_sha = tree.ground_digest
    # Verify that the catalogue does not depend on the first observer's Python objects.
    assert type(source) is dict
    from mailcpu.external_surface_streams import HostedTree
    assert HostedTree.restore(source, original_sha).ground_digest == original_sha
    sizes = sorted((f.size_bytes for f in tree.files), reverse=True)
    result = {
        "schema": "mailcpu.hosted-external-surface-discovery.v1",
        "page_url": url, "source_repository": tree.repository,
        "source_revision": tree.revision,
        "inventory_head": original_sha,
        "interpretation_hint": tree.interpretation_hint,
        "observed_file_count": len(tree.files),
        "declared_source_bytes": tree.declared_bytes,
        "largest_file_bytes": sizes[0],
        "safetensors_shards": sum(f.path.endswith(".safetensors") for f in tree.files),
        "sample_paths": [f.path for f in tree.files[:12]],
        "source_weight_payload_bytes_acquired": 0,
        "source_weight_payload_files_acquired": 0,
        "source_execution": "none",
        "model_runtime_installed": False,
        "inventory": source,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Qualify remotely hosted model address structures")
    parser.add_argument("--url", required=True)
    parser.add_argument("--expected-revision")
    parser.add_argument("--out", type=Path)
    opts = parser.parse_args()
    result = run(opts.url, expected_revision=opts.expected_revision)
    text = json.dumps(result, sort_keys=True, indent=2, allow_nan=False)
    print(json.dumps({k:v for k,v in result.items() if k != "inventory"},
                     indent=2, sort_keys=True))
    if opts.out is not None:
        opts.out.parent.mkdir(parents=True, exist_ok=True)
        opts.out.write_text(text+"\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
