"""PATH-GROUND-003: real GitHub HTTPS 200/304/200 and alternate object address.

Usage from a checked-out public E-CPU repository:
  python -m examples.run_http_conditional_ground --commit "$(git rev-parse HEAD)"

This executes five benign, serial GETs to immutable user-owned public GitHub
content over verified HTTPS. No authentication secret is required or logged.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import time

from mailcpu.http_conditional_ground import (
    GitContentAddress, InternetGroundRefused, probe_conditional_http_ground,
)


def run(commit: str, *, local_root: Path) -> dict:
    """Mathematics: recheck a remote conditional observation against local immutable source bytes."""
    address = GitContentAddress(commit)
    source = local_root / address.path
    if not source.is_file():
        raise InternetGroundRefused("local trusted Ground fixture is not available")
    expected = source.read_bytes()
    started = time.monotonic_ns()
    ground = probe_conditional_http_ground(address)
    elapsed_ns = time.monotonic_ns() - started
    if len(expected) != ground.content_size or sha256(expected).hexdigest() != ground.content_sha256:
        raise InternetGroundRefused("remote pinned public representation differs from exact local checkout")
    eq = ground.navigate("is_current_validator_equal")
    stale = ground.navigate("retrieve_on_mismatch")
    return {
        "schema": "mailcpu.path-ground-003.https-report.v1",
        "status": "validated_real_internet_https_service_predicate",
        "ground": {
            "commit": commit, "file": address.path,
            "ground_digest": ground.ground_digest,
            "content_sha256": ground.content_sha256,
            "git_blob_oid": ground.git_blob_oid,
            "content_size": ground.content_size,
            "evidence_digest": ground.evidence_digest,
        },
        "internet_observations": {
            "full_200": {
                "status": ground.baseline.status,
                "body_bytes": ground.baseline.body_bytes,
                "etag": ground.baseline.etag,
                "receipt_digest": ground.baseline.receipt_digest,
            },
            "equal_304": {
                "status": ground.equal.status,
                "body_bytes": ground.equal.body_bytes,
                "receipt_digest": ground.equal.receipt_digest,
                "validator_reused": ground.equal.condition == ground.baseline.etag,
            },
            "stale_200": {
                "status": ground.mismatch.status,
                "body_bytes": ground.mismatch.body_bytes,
                "receipt_digest": ground.mismatch.receipt_digest,
            },
            "raw_content_path": {
                "url": address.raw_url, "body_bytes": ground.raw.body_bytes,
                "receipt_digest": ground.raw.receipt_digest,
            },
            "git_content_address_path": {
                "url": address.blob_url(ground.git_blob_oid),
                "body_bytes": ground.blob.body_bytes,
                "receipt_digest": ground.blob.receipt_digest,
            },
            "total_elapsed_ns": elapsed_ns,
            "http_response_body_bytes_saved_at_equal_check":
                ground.mismatch.body_bytes - ground.equal.body_bytes,
            "client_protocol": "HTTPS_GET_conditional_If_None_Match",
            "remote_operation": "GitHub_HTTP_conditional_representation_comparison",
            "local_interpretation": "decode_Git_object_verify_sha1_sha256_and_Ground_pins",
            "remote_physical_router_arithmetic_claimed": False,
            "independently_owned_host_provider_domains_claimed": False,
            "same_provider_access_path_rebinding": True,
            "local_source_equals_remote": True,
        },
        "navigation": {
            "equal_intention": eq,
            "mismatch_intention": stale,
            "what_the_predicate_does_not_prove":
                "future state, backend identity behind CDN, remote application CPU freedom, optical or router arithmetic",
        },
    }


def main() -> None:
    """Mathematics: pin the checked-out commit and refuse unverifiable remote interpretations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", help="40-hex immutable commit; defaults to git HEAD")
    parser.add_argument("--root", default=".", help="trusted local repository checkout")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    commit = args.commit
    if commit is None:
        commit = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True, timeout=5,
        ).strip()
    report = run(commit, local_root=root)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
