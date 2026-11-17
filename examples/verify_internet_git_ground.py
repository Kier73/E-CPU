"""INTERNET-001: independent observer of an existing Internet Git state machine.

This is a read-only HTTPS client, not an agent installed at the Git service.
The state-changing Git service API is exercised by a separately authorized
experimenter. The caller must pin expected ref AND content identities outside
this observer. TLS authenticates the HTTPS origin, not remote hardware or routers.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from typing import Callable, Mapping
from urllib.parse import quote
from urllib.request import Request, urlopen


class InternetGroundRefused(ValueError):
    """The remote observation does not satisfy receiver-owned pins."""


def _sha1_git_blob(payload: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()


def _pairs_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InternetGroundRefused("duplicate JSON field")
        result[key] = value
    return result


def get_github_json(resource: str) -> Mapping:
    """Observe existing GitHub state using HTTPS; performs no remote mutation."""
    if not resource.startswith("/repos/"):
        raise InternetGroundRefused("disallowed resource path")
    request = Request("https://api.github.com" + resource,
                      headers={"Accept": "application/vnd.github+json",
                               "User-Agent": "E-CPU-INTERNET-001-observer"})
    with urlopen(request, timeout=15) as connection:
        if connection.status != 200:
            raise InternetGroundRefused("unexpected response status")
        raw = connection.read(1_000_001)
    if len(raw) > 1_000_000:
        raise InternetGroundRefused("remote observation exceeds byte budget")
    return json.loads(raw, object_pairs_hook=_pairs_no_duplicates)


def verify_remote_ground(
    read: Callable[[str], Mapping], *, repo: str, branch: str,
    expected_commit: str, path: str, expected_blob_sha1: str,
    expected_content_sha256: str,
) -> dict:
    """Validate a ref -> commit -> tree -> blob route against outside pins.

    Only the Git service is the stateful locus. This proves the particular
    observed service response and source-byte continuity, NOT router/optical
    computation, a globally atomic multi-service update, or persistent lease.
    """
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", repo):
        raise InternetGroundRefused("invalid repository identity")
    if not re.fullmatch(r"[A-Za-z0-9_./-]{1,160}", branch) or ".." in branch or "//" in branch:
        raise InternetGroundRefused("invalid branch identity")
    if not re.fullmatch(r"[A-Za-z0-9_./-]{1,250}", path) or ".." in path or "//" in path:
        raise InternetGroundRefused("invalid relative object path")
    if any(not re.fullmatch("[0-9a-f]{%d}" % n, value) for n, value in (
        (40, expected_commit), (40, expected_blob_sha1), (64, expected_content_sha256))):
        raise InternetGroundRefused("receiver requires exact outside identities")

    ref = read("/repos/" + repo + "/git/ref/heads/" + quote(branch, safe="/"))
    if not isinstance(ref, Mapping) or ref.get("object", {}).get("type") != "commit" or ref["object"].get("sha") != expected_commit:
        raise InternetGroundRefused("internet service ref differs from pinned intention")
    commit = read("/repos/" + repo + "/git/commits/" + expected_commit)
    tree_sha = commit.get("tree", {}).get("sha") if isinstance(commit, Mapping) else None
    if not isinstance(tree_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", tree_sha):
        raise InternetGroundRefused("unusable service commit observation")
    tree = read("/repos/" + repo + "/git/trees/" + tree_sha + "?recursive=1")
    if not isinstance(tree, Mapping) or tree.get("truncated") is not False or not isinstance(tree.get("tree"), list):
        raise InternetGroundRefused("incomplete service tree observation")
    selected = [entry for entry in tree["tree"] if entry.get("path") == path]
    if len(selected) != 1 or selected[0].get("type") != "blob" or selected[0].get("sha") != expected_blob_sha1:
        raise InternetGroundRefused("ref does not address externally pinned content")
    blob = read("/repos/" + repo + "/git/blobs/" + expected_blob_sha1)
    if not isinstance(blob, Mapping) or blob.get("encoding") != "base64" or not isinstance(blob.get("content"), str):
        raise InternetGroundRefused("unsupported remote blob representation")
    try:
        content = base64.b64decode(blob["content"].replace("\n", ""), validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise InternetGroundRefused("invalid blob encoding") from exc
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if (_sha1_git_blob(content) != expected_blob_sha1 or
            actual_sha256 != expected_content_sha256 or blob.get("sha") != expected_blob_sha1):
        raise InternetGroundRefused("content-addressed internet state fails independent reconstruction")
    return {
        "schema": "mailcpu.internet-native-git-observation.v1",
        "repo": repo, "ref": branch, "observed_commit": expected_commit,
        "object_path": path, "observed_git_blob_sha1": expected_blob_sha1,
        "observed_content_sha256": actual_sha256, "bytes": len(content),
        "observed": "git-service-state-over-https",
        "not": "not-fiber-arithmetic-or-global-internet-attestation",
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    for flag in ("repo", "branch", "expected-commit", "path", "expected-blob-sha1", "expected-content-sha256"):
        cli.add_argument("--" + flag, required=True)
    args = vars(cli.parse_args())
    print(json.dumps(verify_remote_ground(get_github_json,
        repo=args["repo"], branch=args["branch"],
        expected_commit=args["expected_commit"], path=args["path"],
        expected_blob_sha1=args["expected_blob_sha1"],
        expected_content_sha256=args["expected_content_sha256"]), indent=2))


if __name__ == "__main__":
    main()
