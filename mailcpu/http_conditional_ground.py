"""PATH-GROUND-003: observe a live Internet service's conditional HTTP transition.

A remote GitHub HTTPS observer-host compares an If-None-Match validator to
its resource representation. E-CPU independently verifies the 200/304/200
transition against one exact Git blob, including an alternative raw HTTPS
access path and a content-addressed Git blob lookup.

The web service or an authorized intermediary performs HTTP condition handling;
neither passive fiber nor a public router is claimed to compute an arbitrary
operator. Source authority is not inferred from an ETag or content digest.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from hashlib import sha1, sha256
import json
import re
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import (
    HTTPRedirectHandler, HTTPSHandler, Request, build_opener,
)

from .computational_objects import ComputationalObjectStore

SCHEMA = "mailcpu.path-ground-003.conditional-http.v1"
_REPO = "Kier73/E-CPU"
_MAX_CONTENT = 64 * 1024
_MAX_HTTP_BYTES = 128 * 1024
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PATH = re.compile(r"[A-Za-z0-9_./-]+\Z")
_ALLOWED_PATH = "docs/THE_INTERNET_IS_THE_COMPUTER.md"
_GITHUB_HEADERS = {
    "User-Agent": "E-CPU-PATH-GROUND-003-observer",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "Accept-Encoding": "identity",
}


class InternetGroundRefused(ValueError):
    """Refuse an unsupported service, invalid observation, or unproven comparison."""


def _canonical(value: Any) -> bytes:
    """Mathematics: serialize one evidence identity with deterministic JSON bytes."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise InternetGroundRefused("noncanonical HTTP observation") from exc


def _digest(value: Any) -> str:
    """Mathematics: SHA-256 identifies observation content, not remote authority."""
    return sha256(_canonical(value)).hexdigest()


def _git_blob_oid(raw: bytes) -> str:
    """Mathematics: Git SHA-1 blob ID = SHA1('blob N\\0' || exact body)."""
    return sha1(b"blob " + str(len(raw)).encode("ascii") + b"\x00" + raw).hexdigest()


def _json_object(raw: bytes, kind: str) -> dict[str, Any]:
    """Mathematics: accept a bounded JSON object with finite ASCII keys only."""
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise InternetGroundRefused(kind + " response was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise InternetGroundRefused(kind + " response must be a JSON object")
    return parsed


def _decoded_blob(raw: bytes, *, kind: str) -> tuple[bytes, str]:
    """Mathematics: verify Git's canonical SHA-1 content identity from decoded bytes."""
    data = _json_object(raw, kind)
    if ((kind == "contents API" and data.get("type") != "file")
            or (kind != "contents API" and data.get("type") not in (None, "blob"))
            or data.get("encoding") != "base64"
            or type(data.get("size")) is not int
            or not 0 < data["size"] <= _MAX_CONTENT
            or type(data.get("content")) is not str
            or type(data.get("sha")) is not str or not _SHA1.fullmatch(data["sha"])):
        raise InternetGroundRefused(kind + " is not an exact bounded Git blob representation")
    try:
        encoded = data["content"].strip()
        payload = base64.b64decode(encoded, validate=False)
        # Refuse a lenient decoder accepting altered, non-base64 characters.
        if base64.b64encode(payload).decode("ascii") != "".join(encoded.split()):
            raise ValueError("noncanonical base64")
    except (ValueError, UnicodeEncodeError) as exc:
        raise InternetGroundRefused(kind + " has altered base64 payload") from exc
    if len(payload) != data["size"] or _git_blob_oid(payload) != data["sha"]:
        raise InternetGroundRefused(kind + " Git blob identity differs from actual bytes")
    return payload, data["sha"]


@dataclass(frozen=True)
class GitContentAddress:
    """An immutable owned Git object, not an untrusted caller-provided URL."""

    commit: str
    path: str = _ALLOWED_PATH
    repository: str = _REPO

    def __post_init__(self) -> None:
        """Mathematics: restrict all network access to a known public repository at a 40-hex commit."""
        if (type(self.commit) is not str or not _SHA1.fullmatch(self.commit)
                or self.repository != _REPO or self.path != _ALLOWED_PATH
                or not _PATH.fullmatch(self.path) or ".." in self.path.split("/")):
            raise InternetGroundRefused("only the exact owned, commit-pinned public Ground is allowed")

    @property
    def contents_url(self) -> str:
        """Mathematics: compile the exact commit-and-path GitHub REST state address."""
        return (f"https://api.github.com/repos/{_REPO}/contents/"
                f"{quote(self.path, safe='/')}?ref={self.commit}")

    @property
    def raw_url(self) -> str:
        """Mathematics: select a second GitHub-managed HTTPS access representation."""
        return f"https://raw.githubusercontent.com/{_REPO}/{self.commit}/{self.path}"

    def blob_url(self, oid: str) -> str:
        """Mathematics: navigate the Git object graph by immutable content identity."""
        if type(oid) is not str or not _SHA1.fullmatch(oid):
            raise InternetGroundRefused("invalid immutable Git blob address")
        return f"https://api.github.com/repos/{_REPO}/git/blobs/{oid}"


@dataclass(frozen=True)
class HTTPObservation:
    """One actual HTTPS 200/304 exchange, before semantic interpretation."""

    url: str
    condition: str | None
    status: int
    etag: str | None
    body: bytes
    request_id: str | None

    def __post_init__(self) -> None:
        """Mathematics: reject unbounded frames, invalid validator encodings and unsupported statuses."""
        if (type(self.url) is not str or not self.url.startswith("https://")
                or type(self.status) is not int or self.status not in (200, 304)
                or type(self.body) is not bytes or len(self.body) > _MAX_HTTP_BYTES):
            raise InternetGroundRefused("malformed HTTPS observation")
        if self.status == 304 and (self.condition is None or self.body):
            raise InternetGroundRefused("304 requires a conditional request and no response body")
        if self.status == 200 and not self.body:
            raise InternetGroundRefused("200 must carry a nonempty bounded response")
        if self.condition is not None and not _valid_etag(self.condition):
            raise InternetGroundRefused("noncanonical requested HTTP ETag")
        if self.etag is not None and not _valid_etag(self.etag):
            raise InternetGroundRefused("noncanonical received HTTP ETag")
        if self.request_id is not None and (
            type(self.request_id) is not str or len(self.request_id) > 160
            or any(ord(ch) < 32 or ord(ch) > 126 for ch in self.request_id)
        ):
            raise InternetGroundRefused("invalid HTTP request-id evidence")

    @property
    def receipt_digest(self) -> str:
        """Mathematics: bind URL, request predicate, status, ETag and exact returned bytes."""
        return _digest({
            "schema": SCHEMA + ".http", "url": self.url,
            "condition": self.condition, "status": self.status,
            "etag": self.etag, "body_sha256": sha256(self.body).hexdigest(),
            "body_length": len(self.body), "request_id": self.request_id,
        })

    @property
    def body_bytes(self) -> int:
        """Mathematics: count observed application-layer response-body bytes, not wire bandwidth."""
        return len(self.body)


def _valid_etag(value: Any) -> bool:
    """Mathematics: require a finite quoted HTTP validator, preserving weak-prefix semantics."""
    return (type(value) is str and 3 <= len(value) <= 256
            and (value.startswith('"') or value.startswith('W/"'))
            and value.endswith('"') and all(32 <= ord(c) <= 126 for c in value)
            and "\r" not in value and "\n" not in value)


class _NoRedirect(HTTPRedirectHandler):
    """Mathematics: refuse an unverified change of HTTPS service identity."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Mathematics: a redirect is a new path and cannot inherit this path's witness."""
        raise InternetGroundRefused("HTTP redirect changed the pinned service path")


def fetch_https_observation(url: str, condition: str | None = None, *,
                            timeout: float = 8.0) -> HTTPObservation:
    """Mathematics: measure one serial, capped HTTPS response under the default TLS verifier.

    This function is intentionally no generic URL fetcher: the target must
    be generated by GitContentAddress and supplied via the probe. No raw token
    or authentication credential is transmitted or logged.
    """
    if (type(url) is not str or
            not (url.startswith(f"https://api.github.com/repos/{_REPO}/")
                 or url.startswith(f"https://raw.githubusercontent.com/{_REPO}/"))
            or type(timeout) not in (int, float) or not 0 < timeout <= 15):
        raise InternetGroundRefused("HTTPS request is outside the selected owned provider")
    if condition is not None and not _valid_etag(condition):
        raise InternetGroundRefused("conditional request has invalid validator")
    headers = dict(_GITHUB_HEADERS)
    if condition is not None:
        headers["If-None-Match"] = condition
    opener = build_opener(_NoRedirect, HTTPSHandler())
    req = Request(url, headers=headers, method="GET")
    try:
        try:
            res = opener.open(req, timeout=timeout)
        except HTTPError as exc:
            if exc.code != 304:
                raise InternetGroundRefused(f"GitHub refused HTTP request with {exc.code}") from exc
            res = exc
        with res:
            status = res.code
            body = res.read(_MAX_HTTP_BYTES + 1)
            if len(body) > _MAX_HTTP_BYTES:
                raise InternetGroundRefused("HTTP response exceeded observer byte budget")
            etag = res.headers.get("ETag")
            request_id = res.headers.get("X-GitHub-Request-Id")
    except (URLError, TimeoutError, OSError) as exc:
        raise InternetGroundRefused(f"remote HTTPS path unavailable: {type(exc).__name__}") from exc
    return HTTPObservation(url, condition, status, etag, body, request_id)


@dataclass(frozen=True)
class ConditionalHTTPGround:
    """Evidence-scoped interpretation of a remote HTTP equality predicate."""

    address: GitContentAddress
    baseline: HTTPObservation
    equal: HTTPObservation
    mismatch: HTTPObservation
    raw: HTTPObservation
    blob: HTTPObservation
    content_sha256: str
    git_blob_oid: str
    content_size: int
    scope: str = "observed_live_https_conditional_predicate_not_physical_router_arithmetic"

    def __post_init__(self) -> None:
        """Mathematics: independently reconstruct all GET representations and predicate cases."""
        if not isinstance(self.address, GitContentAddress):
            raise InternetGroundRefused("typed address required")
        if self.scope != "observed_live_https_conditional_predicate_not_physical_router_arithmetic":
            raise InternetGroundRefused("unsupported claim about a public network service")
        if any(not isinstance(x, HTTPObservation) for x in (
            self.baseline, self.equal, self.mismatch, self.raw, self.blob,
        )):
            raise InternetGroundRefused("five actual typed service observations required")
        if (self.baseline.url != self.address.contents_url
                or self.equal.url != self.baseline.url
                or self.mismatch.url != self.baseline.url
                or self.baseline.condition is not None
                or self.baseline.status != 200
                or not _valid_etag(self.baseline.etag)
                or self.equal.condition != self.baseline.etag
                or self.equal.status != 304 or self.equal.body
                or self.mismatch.condition != '"ecpu-unmatched-validation-control"'
                or self.mismatch.status != 200
                or self.mismatch.body != self.baseline.body
                or self.raw.url != self.address.raw_url
                or self.raw.condition is not None or self.raw.status != 200
                or self.blob.url != self.address.blob_url(self.git_blob_oid)
                or self.blob.condition is not None or self.blob.status != 200):
            raise InternetGroundRefused("remote HTTP equality controls did not prove both outcomes")
        contents, oid = _decoded_blob(self.baseline.body, kind="contents API")
        mismatch, mismatch_oid = _decoded_blob(self.mismatch.body, kind="stale-validator control")
        blob, blob_oid = _decoded_blob(self.blob.body, kind="Git blob API")
        if (contents != mismatch or contents != blob or contents != self.raw.body
                or oid != mismatch_oid or oid != blob_oid or oid != self.git_blob_oid
                or type(self.content_size) is not int or len(contents) != self.content_size
                or self.content_sha256 != sha256(contents).hexdigest()
                or not _SHA256.fullmatch(self.content_sha256)
                or self.mismatch.etag != self.baseline.etag):
            raise InternetGroundRefused("alternative Internet access paths disagree on immutable object")
        if self.equal.etag is not None and self.equal.etag != self.baseline.etag:
            raise InternetGroundRefused("conditional 304 returned a different resource validator")

    @property
    def ground_digest(self) -> str:
        """Mathematics: identify the object and equality predicate independently of HTTP route."""
        return _digest({
            "schema": SCHEMA + ".ground", "commit": self.address.commit,
            "path": self.address.path, "git_blob_oid": self.git_blob_oid,
            "content_sha256": self.content_sha256,
            "predicate": "current_response_representation_matches_pinned_etag",
        })

    @property
    def evidence_digest(self) -> str:
        """Mathematics: bind all five exact Internet exchange receipts."""
        return _digest({
            "schema": SCHEMA + ".evidence",
            "receipts": [x.receipt_digest for x in (
                self.baseline, self.equal, self.mismatch, self.raw, self.blob,
            )],
        })

    def navigate(self, intention: str) -> dict[str, Any]:
        """Mathematics: project the already observed HTTP condition without claiming future state."""
        if intention not in ("is_current_validator_equal", "retrieve_on_mismatch"):
            raise InternetGroundRefused("unsupported HTTP intention")
        event = self.equal if intention == "is_current_validator_equal" else self.mismatch
        return {
            "schema": SCHEMA + ".navigation", "intention": intention,
            "status": event.status, "condition_matched": event.status == 304,
            "response_body_bytes": len(event.body),
            "ground_digest": self.ground_digest,
            "evidence_digest": self.evidence_digest,
            "content_sha256": self.content_sha256,
            "git_blob_oid": self.git_blob_oid,
            "observation_scope": "past_recorded_https_response_not_a_future_predicted_network_result",
        }

    def place_in_existing_object_store(self, store: ComputationalObjectStore):
        """Mathematics: reverify five remote observations before admitting bytes to native page CAS."""
        if not isinstance(store, ComputationalObjectStore):
            raise InternetGroundRefused("native ComputationalObjectStore required")
        # Re-run every exact-typed invariant rather than trusting a serialized claim.
        self.__post_init__()
        payload, _oid = _decoded_blob(self.baseline.body, kind="contents API")
        manifest = store.put_bytes(payload, media_type="text/markdown")
        if manifest.content_digest != self.content_sha256:
            raise InternetGroundRefused("native object store changed the remote Ground's bytes")
        return manifest


def probe_conditional_http_ground(address: GitContentAddress, *,
                                  fetch: Callable[[str, str | None], HTTPObservation] =
                                  fetch_https_observation) -> ConditionalHTTPGround:
    """Mathematics: issue five serial HTTP requests then check the entire state/evidence relation."""
    if not isinstance(address, GitContentAddress) or not callable(fetch):
        raise InternetGroundRefused("typed immutable address and live HTTPS adapter required")
    baseline = fetch(address.contents_url, None)
    if baseline.status != 200 or not _valid_etag(baseline.etag):
        raise InternetGroundRefused("initial remote representation lacks a usable ETag")
    payload, oid = _decoded_blob(baseline.body, kind="contents API")
    equal = fetch(address.contents_url, baseline.etag)
    mismatch = fetch(address.contents_url, '"ecpu-unmatched-validation-control"')
    raw = fetch(address.raw_url, None)
    blob = fetch(address.blob_url(oid), None)
    return ConditionalHTTPGround(
        address, baseline, equal, mismatch, raw, blob,
        sha256(payload).hexdigest(), oid, len(payload),
    )
