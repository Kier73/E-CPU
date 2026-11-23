"""One-shot original VL-I TIME-001/002 observer-host in an independent interpreter.

The request carries a bounded exact VL-I state snapshot supplied by a trusted
M3 controller and is checked against the content-admitted source package.
Only locally registered TIME-001/002 methods are executable. This subprocess
pipe is not remote peer authentication.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from threading import Event

from .computational_host import ComputationalHostRequest, LocalComputationalHost
from .vli_temporal_host import (
    VLITemporalBackendAdapter, admit_vli_temporal_runtime,
    vli_temporal_backend_profile,
)

WORKER_SCHEMA = "mailcpu.vli-temporal-one-shot.v1"
MAX_WORKER_INPUT = 1_048_576


def execute_one_shot(payload: dict[str, object]) -> dict[str, object]:
    """Verify exact original VL-I source and run a single finite M2 operation."""
    if not isinstance(payload, dict) or set(payload) != {
        "schema", "host_id", "context_binding_digest", "artifact_manifest_digest",
        "backend_fingerprint", "operation_id", "session_id", "logical_time",
        "operation", "arguments",
    } or payload["schema"] != WORKER_SCHEMA:
        raise ValueError("VL-I worker request fields or schema differ")
    context_digest = payload["context_binding_digest"]
    if (not isinstance(context_digest, str) or len(context_digest) != 64
        or any(d not in "0123456789abcdef" for d in context_digest)):
        raise ValueError("VL-I worker requires an exact M3 context digest")
    manifest, source_root = admit_vli_temporal_runtime()
    profile = vli_temporal_backend_profile(manifest)
    if (payload["artifact_manifest_digest"] != manifest.manifest_digest
        or payload["backend_fingerprint"] != profile.fingerprint):
        raise ValueError("VL-I worker source identity or backend profile differs")
    host = LocalComputationalHost(
        host_id=payload["host_id"],
        manifest=manifest, artifact_root=source_root, profile=profile,
        adapter=VLITemporalBackendAdapter(),
    )
    operation = ComputationalHostRequest(
        request_id=payload["operation_id"],
        artifact_manifest_digest=manifest.manifest_digest,
        operation=payload["operation"], input_value=payload["arguments"],
        workload_id=payload["session_id"], logical_time=payload["logical_time"],
    )
    completed = host.execute(operation)
    host.unload()
    return {
        "context_binding_digest": context_digest,
        "receipt": completed.receipt.to_dict(),
        "output": completed.output,
    }


def main() -> None:
    """Read one admitted one-shot request and publish one genuine VL-I result."""
    parser = argparse.ArgumentParser(description="Source-admitted VL-I observer host")
    parser.add_argument("--crash-cut", choices=("before_publish", "after_publish"))
    args = parser.parse_args()
    data = sys.stdin.buffer.read(MAX_WORKER_INPUT + 1)
    if not data or len(data) > MAX_WORKER_INPUT:
        raise ValueError("VL-I worker input exceeds finite M2 byte bound")
    result = execute_one_shot(json.loads(data))
    if args.crash_cut == "before_publish":
        os._exit(73)
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False), flush=True)
    if args.crash_cut == "after_publish":
        Event().wait(30)


if __name__ == "__main__":
    main()
