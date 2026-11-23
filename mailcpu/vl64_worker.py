"""Bounded one-shot real VL-64 observer-host for M3 session experiments.

Run with python -m mailcpu.vl64_worker. It accepts one exact JSON request
on stdin and emits one M2 receipt + semantic value on stdout. Host operations
are finite, locally installed and content-admitted. The binding digest is
correlation evidence, not network authentication or a trusted sender proof.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from threading import Event

from .computational_host import (
    ComputationalHostRequest,
    LocalComputationalHost,
)
from .vl64_runtime import (
    VL64BackendAdapter,
    admit_vl64_runtime,
    vl64_backend_profile,
)

_WORKER_SCHEMA = "mailcpu.vl64-one-shot-host.v1"
_MAX_REQUEST_BYTES = 8192


def execute_one_shot(payload: dict[str, object]) -> dict[str, object]:
    """Admit the real VL-64 source and execute one typed bound M2 operation."""
    if not isinstance(payload, dict) or set(payload) != {
        "schema", "host_id", "context_binding_digest", "artifact_manifest_digest",
        "backend_fingerprint", "operation_id", "session_id", "logical_time",
        "operation", "arguments",
    }:
        raise ValueError("one-shot VL-64 request fields differ")
    if payload["schema"] != _WORKER_SCHEMA:
        raise ValueError("one-shot VL-64 request schema differs")
    digest = payload["context_binding_digest"]
    if not isinstance(digest, str) or len(digest) != 64 or any(x not in "0123456789abcdef" for x in digest):
        raise ValueError("one-shot VL-64 context digest must be SHA-256")
    manifest, root = admit_vl64_runtime()
    profile = vl64_backend_profile(manifest)
    if (payload["artifact_manifest_digest"] != manifest.manifest_digest
        or payload["backend_fingerprint"] != profile.fingerprint):
        raise ValueError("worker VL-64 source or backend differs from dispatch authority")
    host = LocalComputationalHost(
        host_id=payload["host_id"], manifest=manifest,
        artifact_root=root, profile=profile, adapter=VL64BackendAdapter(),
    )
    request = ComputationalHostRequest(
        request_id=payload["operation_id"],
        artifact_manifest_digest=manifest.manifest_digest,
        operation=payload["operation"],
        input_value=payload["arguments"],
        logical_time=payload["logical_time"],
        workload_id=payload["session_id"],
    )
    completed = host.execute(request)
    host.unload()
    return {
        "context_binding_digest": digest,
        "receipt": completed.receipt.to_dict(),
        "output": completed.output,
    }


def main() -> None:
    """Read a bounded JSON request, execute it once, and write a typed receipt."""
    parser = argparse.ArgumentParser(description="Real VL-64 one-shot host")
    parser.add_argument("--crash-cut", choices=("before_publish", "after_publish"))
    arguments = parser.parse_args()
    data = sys.stdin.buffer.read(_MAX_REQUEST_BYTES + 1)
    if not data or len(data) > _MAX_REQUEST_BYTES:
        raise ValueError("one-shot VL-64 request length exceeds the admitted bound")
    payload = json.loads(data)
    output = execute_one_shot(payload)
    if arguments.crash_cut == "before_publish":
        os._exit(73)  # Local test fault injection; candidate stays private.
    print(json.dumps(output, sort_keys=True, separators=(",", ":"), allow_nan=False), flush=True)
    if arguments.crash_cut == "after_publish":
        Event().wait(30)  # Parent kills us after receiving the exact result frame.


if __name__ == "__main__":
    main()
