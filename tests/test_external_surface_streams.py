"""HSS-001: source trees of any model family become bounded native E-CPU streams.

No GPU, original checkpoint payload, pretrained parameter semantics or external
source runtime is necessary to discover model addresses and validate them.
Synthetic HTTP fixtures test 48 large remote shards without allocating weights;
all byte observations are exact, with negative provenance/sequence tests.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.external_surface_streams import (
    BoundedHTTPSObserver, HostedFile, HostedSurfaceNavigator, HostedTree,
    HTTPSObservation, SourceBytes, SurfaceRefused, _url, html_surface,
    huggingface_page, publish_stream, verify_stream,
)

SHA = "08c8657f02291e11b6f6b63e0e16014f8e748518"
REPO = "deepseek-ai/DeepSeek-V4.1-Flash-1017"
WEB = "https://huggingface.co/" + REPO + "/tree/main"
BASE = "https://huggingface.co/api/models/" + REPO
H = hashlib.sha256


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class MemoryPages:
    """Original native E-CPU M1 object store page contract, not a new cache."""
    page_size = 4096

    def __init__(self):
        self.pages = {}

    def put_page(self, raw):
        assert type(raw) is bytes and len(raw) == 4096
        head = H(raw).hexdigest()
        assert self.pages.setdefault(head, raw) == raw
        return head

    def get_page(self, head):
        return self.pages[head]


class SyntheticHTTP:
    """Receiver-installed HTTPS observer with reproducible source responses."""

    approved_hosts = frozenset(("huggingface.co",))

    def __init__(self, *, model_type="deepseek_v41", shard_count=48):
        self.calls = []
        self.config = canonical({"model_type": model_type,
                                 "architectures": ["SourceUnknownModel"]})
        self.seed = b"0123456789ABCDEF" * 4
        self.files = [
            {"path": "config.json", "size": len(self.config), "type": "file"},
            {"path": "tokenizer.json", "size": 2048, "type": "file"},
            {"path": "encoding", "type": "directory"},
            {"path": "inference/convert.py", "size": 123456, "type": "file"},
        ] + [
            {"path": f"model-{i:05d}-of-{shard_count:05d}.safetensors",
             "size": 8_000_000_000 + i * 4096, "type": "file",
             "lfs": {"sha256": ("%064x" % i)}}
            for i in range(1, shard_count + 1)
        ]

    def fetch(self, url, *, max_bytes, byte_range=None):
        assert url.startswith("https://huggingface.co/")
        self.calls.append((url, byte_range))
        if url == BASE:
            body = canonical({"sha": SHA})
            headers = {}
            status = 200
        elif url == BASE + "/revision/" + SHA:
            body = canonical({"sha": SHA})
            headers = {}
            status = 200
        elif url == BASE + "/tree/" + SHA + "?recursive=true":
            body = canonical(self.files[:25])
            headers = {"link": f'<{BASE}/tree/{SHA}?recursive=true&cursor=25>; rel="next"'}
            status = 200
        elif url == BASE + "/tree/" + SHA + "?recursive=true&cursor=25":
            body = canonical(self.files[25:])
            headers = {}
            status = 200
        elif "/resolve/" + SHA + "/config.json" in url:
            body = self.config
            headers = {"content-range": f"bytes 0-{len(body)-1}/{len(body)}"}
            status = 206
        elif "/resolve/" + SHA + "/model-00001-of-00048.safetensors" in url:
            assert byte_range is not None
            lo, hi = byte_range
            body = self.seed[lo:hi]
            assert len(body) == hi-lo
            headers = {"content-range": f"bytes {lo}-{hi-1}/{8_000_004_096}"}
            status = 206
        else:
            raise AssertionError("unexpected source request " + url)
        assert len(body) <= max_bytes
        return HTTPSObservation(status, headers, body, "huggingface.co")


def test_page_discovery_scales_to_48_original_safetensors_shards_without_loading_weights():
    """Model source is 48 huge shards; total metadata stays bounded by pages."""
    http = SyntheticHTTP()
    tree = HostedSurfaceNavigator(http).discover(WEB)
    assert tree.repository == REPO
    assert tree.revision == SHA
    assert tree.interpretation_hint == "deepseek_v41"
    assert len(tree.files) == 51
    assert tree.declared_bytes > 384_000_000_000
    assert tree.file("model-00048-of-00048.safetensors").size_bytes > 8_000_000_000
    assert len(http.calls) == 4  # revision, 2 tree pages, exact config
    assert not any("model-000" in url for url, _ in http.calls)
    assert HostedTree.restore(tree.to_dict(), tree.ground_digest) == tree
    assert tree.ground_digest == HostedTree.restore(tree.to_dict(), tree.ground_digest).ground_digest


@pytest.mark.parametrize("model_type", ["deepseek_v41", "qwen3", "llama", "mamba", "audio", "diffusion", "custom_experimental"])
def test_same_reader_admits_unseen_model_architectures_without_operator_assumptions(model_type):
    """Discovery is independent of pretrained/post-trained model family."""
    tree = HostedSurfaceNavigator(SyntheticHTTP(model_type=model_type)).discover(WEB)
    assert tree.interpretation_hint == model_type
    assert tree.file("tokenizer.json").size_bytes == 2048
    assert tree.declared_bytes > 300_000_000_000


def test_exact_shard_range_becomes_hash_linked_native_m1_stream_with_process_reconstruction():
    """A small source read survives observer process loss as native E-CPU bytes."""
    http = SyntheticHTTP()
    navigator = HostedSurfaceNavigator(http)
    tree = navigator.discover(WEB)
    source = navigator.observe(tree, "model-00001-of-00048.safetensors", offset=8, length=32)
    assert source.body == http.seed[8:40]
    assert len(http.calls) == 5
    assert source.tree_digest == tree.ground_digest
    backing = MemoryPages()
    controller = ComputationalObjectStore(backing)
    record = publish_stream(source, controller, frame_bytes=7)
    assert len(record["frames"]) == 5
    assert record["source_observation_bytes"] == 32
    assert record["content_sha256"] == H(source.body).hexdigest()
    # A new process can use only native M1 saved pages and retained admission record.
    recovered_store = ComputationalObjectStore(backing)
    assert verify_stream(record, recovered_store, expected_head=record["stream_head"]) == source.body
    assert record["object_manifest"]["content_digest"] == H(source.body).hexdigest()


def test_original_source_range_and_existing_native_m1_reject_forged_evidence():
    tree = HostedSurfaceNavigator(SyntheticHTTP()).discover(WEB)
    navigator = HostedSurfaceNavigator(SyntheticHTTP())
    with pytest.raises(SurfaceRefused, match="declared"):
        navigator.observe(tree, "model-00001-of-00048.safetensors", offset=0, length=65537)
    with pytest.raises(SurfaceRefused, match="absent"):
        navigator.observe(tree, "model-00000-of-00048.safetensors", offset=0, length=16)
    with pytest.raises(SurfaceRefused):
        navigator.observe(tree, "inference/../config.json", offset=0, length=1)
    source = navigator.observe(tree, "model-00001-of-00048.safetensors", offset=8, length=32)
    backing = MemoryPages()
    store = ComputationalObjectStore(backing)
    correct = publish_stream(source, store, frame_bytes=11)
    for fake in (
        dict(correct, stream_head="0" * 64),
        dict(correct, address=dict(correct["address"], path="other.safetensors")),
        dict(correct, frames=list(reversed(correct["frames"]))),
    ):
        with pytest.raises(SurfaceRefused):
            verify_stream(fake, store, expected_head=correct["stream_head"])
    mutated = copy.deepcopy(correct)
    mutated["frames"][0]["relative_offset"] = 2
    with pytest.raises(SurfaceRefused):
        verify_stream(mutated, store, expected_head=correct["stream_head"])
    # Tamper native M1 content, not only the receipt.
    chunk_head = correct["object_manifest"]["chunks"][0]["page_digest"]
    backing.pages[chunk_head] = b"z" * 4096
    with pytest.raises(SurfaceRefused, match="native M1"):
        verify_stream(correct, store, expected_head=correct["stream_head"])


def test_metadata_refuses_mutated_revision_and_duplicate_inventory():
    http = SyntheticHTTP()
    tree = HostedSurfaceNavigator(http).discover(WEB)
    bad = tree.to_dict()
    bad["revision"] = "0"*40
    with pytest.raises(SurfaceRefused, match="identity"):
        HostedTree.restore(bad, tree.ground_digest)
    broken = SyntheticHTTP()
    broken.files.append(dict(broken.files[0], size=100))
    with pytest.raises(SurfaceRefused, match="contradictory"):
        HostedSurfaceNavigator(broken).discover(WEB)
    unsigned = SyntheticHTTP()
    # A 40-character revision request is never satisfied by a different SHA.
    with pytest.raises(SurfaceRefused, match="changed"):
        HostedSurfaceNavigator(unsigned).discover(
            "https://huggingface.co/"+REPO+"/tree/"+"f"*40)


def test_static_html_page_links_are_grounded_without_executing_page_javascript():
    class HTML:
        approved_hosts = frozenset(("huggingface.co",))
        def fetch(self, url, *, max_bytes, byte_range=None):
            source = (
                '<html><a href="/deepseek-ai/DeepSeek-V4.1-Flash-1017/tree/main">model</a>'
                '<a href="https://example.org/elsewhere">outside</a>'
                '<a href="javascript:alert(1)">run me</a>'
                '<a href="/deepseek-ai/DeepSeek-V4.1-Flash-1017/tree/main">again</a>'
                '<script>window.evil = 1</script></html>'
            ).encode()
            return HTTPSObservation(200, {"content-type": "text/html; charset=utf-8"},
                                    source, "huggingface.co")
    page = html_surface(WEB, HTML())
    assert page["execution"] == "static_html_links_only"
    assert page["linked_addresses"] == [WEB]
    assert len(page["observed_sha256"]) == 64
    assert len(page["ground_digest"]) == 64


@pytest.mark.parametrize("bad", [
    "http://huggingface.co/a",
    "https://127.0.0.1/admin",
    "https://huggingface.co.evil.test/a",
    "https://evil@huggingface.co/a",
    "https://huggingface.co:8080/a",
    "https://huggingface.co/a#fake",
])
def test_untrusted_url_cannot_acquire_receiver_network_authority(bad):
    with pytest.raises(SurfaceRefused):
        _url(bad, frozenset({"huggingface.co"}))
    with pytest.raises(SurfaceRefused):
        html_surface(bad, SyntheticHTTP())


def test_fixed_source_names_and_cross_model_source_bytes_refused():
    with pytest.raises(SurfaceRefused):
        HostedFile("../private", 3)
    with pytest.raises(SurfaceRefused):
        HostedFile("weights", -1)
    with pytest.raises(SurfaceRefused):
        HostedTree("deepseek-ai/example", "main", (HostedFile("a", 1),))
    source = SourceBytes(
        "a"*64, REPO, SHA, "config.json", 0, b"{}",
        2, "huggingface.co",
    )
    backing = MemoryPages()
    record = publish_stream(source, ComputationalObjectStore(backing))
    assert verify_stream(record, ComputationalObjectStore(backing),
                         expected_head=record["stream_head"]) == b"{}"


def test_human_page_address_requires_explicit_revision_and_fixed_repo():
    assert huggingface_page(WEB) == (REPO, "main")
    assert huggingface_page("https://huggingface.co/"+REPO+"/tree/"+SHA) == (REPO, SHA)
    with pytest.raises(SurfaceRefused):
        huggingface_page("https://huggingface.co/"+REPO+"/tree/dev")
    with pytest.raises(SurfaceRefused):
        huggingface_page("https://example.org/a/b/tree/main")
