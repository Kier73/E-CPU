"""PATH-GROUND-003 local verifier tests for the Internet-native conditional observer.

Synthetic HTTP receipts test exact contracts and refusal behavior. The
separate explicit live probe in CI is required for a real GitHub HTTPS claim.
"""
from __future__ import annotations

import base64
from dataclasses import replace
from hashlib import sha1, sha256
import json

import pytest

from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.http_conditional_ground import (
    ConditionalHTTPGround, GitContentAddress, HTTPObservation,
    InternetGroundRefused, _git_blob_oid, fetch_https_observation,
    probe_conditional_http_ground,
)


COMMIT = "6fd416facdb2aefd6fc7d66a06b014e3d31b5a52"
CONTENT = b"E-CPU path-host HTTP conditional control\n" + bytes(range(32))
ETAG = '"ecpu-representation-v1"'


class MemoryPageBacking:
    """Finite, receiver-owned page backing for E-CPU's existing object store."""

    def __init__(self):
        """Establish an exact immutable content-addressed local page map."""
        self.page_size = 4096
        self.pages = {}

    def put_page(self, data):
        """Mathematics: commit the page only under the digest of its exact bytes."""
        assert len(data) == self.page_size
        oid = sha256(data).hexdigest()
        assert oid not in self.pages or self.pages[oid] == data
        self.pages[oid] = data
        return oid

    def get_page(self, oid):
        """Mathematics: resolve only the requested page identity."""
        return self.pages[oid]


def _response(url, body, condition=None, status=200, etag=ETAG, request_id=None):
    """Build one honest HTTP response frame for a fixed injected service."""
    return HTTPObservation(url, condition, status, etag, body, request_id)


def _fixture(content=CONTENT):
    """Build the same exact Git object in contents, raw and blob representations."""
    address = GitContentAddress(COMMIT)
    oid = _git_blob_oid(content)
    contents = json.dumps({
        "type": "file", "encoding": "base64",
        "content": base64.b64encode(content).decode(),
        "size": len(content), "sha": oid,
    }, separators=(",", ":")).encode()
    blob = json.dumps({
        "encoding": "base64", "content": base64.b64encode(content).decode(),
        "size": len(content), "sha": oid,
    }, separators=(",", ":")).encode()
    baseline = _response(address.contents_url, contents)
    equal = _response(address.contents_url, b"", ETAG, 304)
    mismatch = _response(
        address.contents_url, contents, '"ecpu-unmatched-validation-control"',
    )
    raw = _response(address.raw_url, content, etag=None)
    git = _response(address.blob_url(oid), blob, etag=None)
    return address, (baseline, equal, mismatch, raw, git), oid


def _ground():
    """Exercise exactly the public probe's five-request transition graph."""
    address, (baseline, equal, mismatch, raw, git), oid = _fixture()
    requests = []
    def wire(url, validator):
        """Mathematics: dispatch a deterministic fixture by the typed conditional address."""
        requests.append((url, validator))
        return {
            (address.contents_url, None): baseline,
            (address.contents_url, ETAG): equal,
            (address.contents_url, '"ecpu-unmatched-validation-control"'): mismatch,
            (address.raw_url, None): raw,
            (address.blob_url(oid), None): git,
        }[(url, validator)]
    ground = probe_conditional_http_ground(address, fetch=wire)
    assert len(requests) == 5
    return ground


def test_remote_conditional_intention_is_a_bounded_observer_predicate():
    """HTTP service produces 200/304/200 instead of sending an entire object thrice."""
    ground = _ground()
    assert ground.content_sha256 == sha256(CONTENT).hexdigest()
    assert ground.git_blob_oid == _git_blob_oid(CONTENT)
    assert ground.content_size == len(CONTENT)
    assert ground.baseline.body_bytes > 0
    assert ground.equal.body_bytes == 0
    assert ground.mismatch.body_bytes > 0
    equal = ground.navigate("is_current_validator_equal")
    stale = ground.navigate("retrieve_on_mismatch")
    assert equal["condition_matched"] is True and equal["status"] == 304
    assert equal["response_body_bytes"] == 0
    assert stale["condition_matched"] is False and stale["status"] == 200
    assert equal["ground_digest"] == stale["ground_digest"]
    assert "past_recorded" in equal["observation_scope"]


def test_native_computational_object_store_consumes_independently_checked_content():
    """The existing E-CPU page CAS retains verified remote bytes, not a new ETag cache."""
    ground = _ground()
    store = ComputationalObjectStore(MemoryPageBacking())
    manifest = ground.place_in_existing_object_store(store)
    assert manifest.content_digest == ground.content_sha256
    assert store.read_bytes(manifest) == CONTENT
    assert len(manifest.manifest_digest) == 64


def test_externally_verified_git_oid_is_independent_of_rest_json_envelope():
    """Git object content identity is reconstructed from a typed blob header and bytes."""
    ground = _ground()
    independent = sha1(
        b"blob " + str(len(CONTENT)).encode() + b"\x00" + CONTENT,
    ).hexdigest()
    assert independent == ground.git_blob_oid
    assert ground.raw.body == CONTENT
    assert ground.blob.body != CONTENT


@pytest.mark.parametrize("index,changes", [
    (0, {"etag": None}),
    (1, {"status": 200, "body": b"x"}),
    (1, {"etag": '"different-etag"'}),
    (2, {"status": 304, "body": b""}),
    (3, {"body": b"not the same bytes"}),
    (4, {"body": b'{"type":"blob","sha":"bad"}'}),
])
def test_negative_evidence_must_refuse_without_upgrading_trust(index, changes):
    """Each independent HTTP evidence class must preserve its declared meaning."""
    addr, original, oid = _fixture()
    changed = list(original)
    changed[index] = replace(changed[index], **changes)
    with pytest.raises(InternetGroundRefused):
        ConditionalHTTPGround(
            addr, *changed, sha256(CONTENT).hexdigest(), oid, len(CONTENT),
        )


def test_exact_validator_scope_cannot_be_rebound_to_different_path():
    """A positive conditional response from one URL cannot authorize another URL."""
    g = _ground()
    addr = GitContentAddress("a" * 40)
    with pytest.raises(InternetGroundRefused):
        replace(g, address=addr)
    with pytest.raises(InternetGroundRefused):
        replace(g, raw=replace(g.raw, url=g.baseline.url))


def test_untrusted_raw_body_or_wrong_git_object_refused():
    """Content identity has separate checks against the direct raw access and Git blob."""
    g = _ground()
    with pytest.raises(InternetGroundRefused):
        replace(g, content_sha256="0" * 64)
    with pytest.raises(InternetGroundRefused):
        replace(g, git_blob_oid="0" * 40)
    with pytest.raises(InternetGroundRefused):
        replace(g, scope="public_fiber_executed_http_predicate")


def test_replay_uses_recorded_observations_not_an_invented_live_future_measurement():
    """Navigation of past evidence must never claim a new remote request or future certainty."""
    g = _ground()
    result = g.navigate("is_current_validator_equal")
    assert result["observation_scope"] == "past_recorded_https_response_not_a_future_predicted_network_result"
    with pytest.raises(InternetGroundRefused):
        g.navigate("infinite_time_future_state")


def test_address_is_only_a_pinned_owned_public_git_repo():
    """No caller-controlled URI, mutable branch, private repo, or traversal is admitted."""
    for obj in (
        {"commit": "main"},
        {"commit": "f" * 64},
        {"commit": COMMIT, "repository": "attacker/repo"},
        {"commit": COMMIT, "path": "../secrets"},
        {"commit": COMMIT, "path": "README.md"},
    ):
        with pytest.raises(InternetGroundRefused):
            GitContentAddress(**obj)
    with pytest.raises(InternetGroundRefused):
        _ground().address.blob_url("0" * 64)
    with pytest.raises(InternetGroundRefused):
        fetch_https_observation("https://example.org/stolen")


def test_short_status_304_is_not_allowed_without_conditional_header_or_with_body():
    """An empty HTTP body is evidence only when the original predicate was sent."""
    addr = GitContentAddress(COMMIT)
    with pytest.raises(InternetGroundRefused):
        HTTPObservation(addr.contents_url, None, 304, ETAG, b"", None)
    with pytest.raises(InternetGroundRefused):
        HTTPObservation(addr.contents_url, ETAG, 304, ETAG, b"spoof", None)
    with pytest.raises(InternetGroundRefused):
        HTTPObservation(addr.contents_url, 'x\r\nInjected: true', 304, ETAG, b"", None)


def test_repository_identity_and_received_body_are_distinct_evidence_classes():
    """A self-hash alone can never turn one failed origin response into a true 304."""
    g = _ground()
    altered = replace(
        g.mismatch,
        body=g.mismatch.body + b" ",
    )
    with pytest.raises(InternetGroundRefused):
        replace(g, mismatch=altered)
