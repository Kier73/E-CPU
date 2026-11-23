"""One-shot real VL-I generated neural model worker on an independent host process.

Only locally admitted original VL-I/VLD neural operators execute. The exact
M3 context digest is correlation evidence, not sender authentication.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from threading import Event

from .computational_host import ComputationalHostRequest, LocalComputationalHost
from .vli_neural_model import (
    VLIGenerativeModelAdapter, admit_vli_neural_runtime, vli_neural_profile,
)

SCHEMA = "mailcpu.vli-neural-model-one-shot.v1"
MAX_REQUEST_BYTES = 2_097_152


def execute_one_shot(payload: dict) -> dict:
    """Verify the real original model and compiler source before running it."""
    if (not isinstance(payload, dict)
        or set(payload) != {
            "schema", "host_id", "context_binding_digest",
            "artifact_manifest_digest", "vld_manifest_digest",
            "backend_fingerprint", "operation_id", "session_id", "logical_time",
            "operation", "arguments",
        } or payload["schema"] != SCHEMA):
        raise ValueError("neural worker request fields differ")
    digest = payload["context_binding_digest"]
    if (not isinstance(digest, str) or len(digest) != 64
        or any(ch not in "0123456789abcdef" for ch in digest)):
        raise ValueError("neural worker context requires SHA-256")
    manifest, dependency, root = admit_vli_neural_runtime()
    profile = vli_neural_profile(manifest, dependency)
    if (payload["artifact_manifest_digest"] != manifest.manifest_digest
        or payload["vld_manifest_digest"] != dependency.manifest_digest
        or payload["backend_fingerprint"] != profile.fingerprint):
        raise ValueError("neural worker model or compiler source is unadmitted")
    host = LocalComputationalHost(
        host_id=payload["host_id"],
        manifest=manifest, artifact_root=root, profile=profile,
        adapter=VLIGenerativeModelAdapter(dependency),
    )
    request = ComputationalHostRequest(
        request_id=payload["operation_id"],
        artifact_manifest_digest=manifest.manifest_digest,
        operation=payload["operation"],
        input_value=payload["arguments"],
        workload_id=payload["session_id"],
        logical_time=payload["logical_time"],
    )
    result = host.execute(request)
    host.unload()
    return {
        "context_binding_digest": digest,
        "receipt": result.receipt.to_dict(),
        "output": result.output,
    }


def main() -> None:
    """Execute an exact bounded request and optionally inject real hard-kill cuts."""
    parser = argparse.ArgumentParser(description="Original VL-I neural host")
    parser.add_argument("--crash-cut", choices=("before_publish", "after_publish"))
    options = parser.parse_args()
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if not raw or len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("neural worker request exceeds finite M2 envelope")
    result = execute_one_shot(json.loads(raw))
    if options.crash_cut == "before_publish":
        os._exit(73)
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False), flush=True)
    if options.crash_cut == "after_publish":
        Event().wait(45)


if __name__ == "__main__":
    main()
