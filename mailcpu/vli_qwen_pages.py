"""SOI-010: original VL-I Qwen causal GDN/GQA state pages on E-CPU M1.

The actual VL-I QwenArchitectureCausalPrefix and VL-64 LocalStatePages use
put/get on a native 64-KiB content-addressed state store. This module adapts
those exact interfaces to E-CPU ComputationalObjectStore, which materializes
each source page as independently verified immutable M1 chunks. No parallel
KV/recurrent interpretation is implemented here.

A Qwen checkpoint contains the original full layer-level geometry and
causal head; the exported M1 page bundle contains typed immutable object
manifests. The externally trusted checkpoint/bundle digests belong to M3.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

from .computational_objects import (
    ComputationalObjectManifest, ComputationalObjectStore,
)

PAGE_BUNDLE_SCHEMA = "mailcpu.vli-qwen-causal-m1-bundle.v1"
_MAX_SOURCE_PAGE = 65536
_HEX = re.compile(r"[0-9a-f]{64}\Z")


def _wire(obj: Any) -> bytes:
    """Canonicalize a finite typed page index."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _require_digest(value: Any) -> str:
    """Refuse unqualified content-address identity."""
    if not isinstance(value, str) or _HEX.fullmatch(value) is None:
        raise ValueError("native causal page digest must be lowercase SHA-256")
    return value


class DurableModelPageBacking:
    """Fsynced immutable E-CPU M1 4-KiB bytes, reopenable by independent processes.

    This is a *single physical filesystem-backed page store*, not a quorum
    replication or distributed page authority. M3 still holds the only
    application-state publication authority.
    """

    page_size = 4096

    def __init__(self, root: Path | str) -> None:
        """Select one explicit durable digest directory."""
        self.root = Path(root)
        if self.root.is_symlink():
            raise ValueError("M1 page root cannot be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise ValueError("M1 page root is not a directory")

    def _target(self, digest: str) -> Path:
        """Resolve only an exact SHA-256 relative page filename."""
        return self.root / _require_digest(digest)

    def put_page(self, data: bytes) -> str:
        """Publish one immutable page with fsync and atomic replacement."""
        if not isinstance(data, bytes) or len(data) != self.page_size:
            raise ValueError("E-CPU M1 page must contain 4096 bytes")
        digest = hashlib.sha256(data).hexdigest()
        target = self._target(digest)
        if target.exists():
            if self.get_page(digest) != data:
                raise ValueError("existing M1 page has conflicting content")
            return digest
        fd, name = tempfile.mkstemp(prefix=".pending-m1-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            if target.exists():
                if self.get_page(digest) != data:
                    raise ValueError("M1 concurrent page collision")
            else:
                os.replace(name, target)
                if os.name == "posix":
                    directory_fd = os.open(self.root, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return digest

    def get_page(self, digest: str) -> bytes:
        """Reject replaced, truncated or symlinked immutable M1 content."""
        target = self._target(digest)
        if target.is_symlink() or not target.is_file():
            raise ValueError("missing or unqualified M1 page")
        raw = target.read_bytes()
        if len(raw) != self.page_size or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("corrupt native M1 page")
        return raw


def _original_local_pages():
    """Resolve the real VL-64 causal store type required by original Qwen."""
    try:
        from experiments.model_fabric.complete_native_layers import LocalStatePages
    except ImportError as exc:
        raise RuntimeError(
            "install the original pinned VL-64 model-fabric experiments to host Qwen causal state"
        ) from exc
    return LocalStatePages


def m1_qwen_causal_pages(
    object_store: ComputationalObjectStore,
    *,
    bundle: Mapping[str, Any] | None = None,
    max_pages: int = 8192,
):
    """Construct a compatible original LocalStatePages with E-CPU M1 backing.

    The returned instance subclasses the original type and therefore passes
    original VL-I QwenArchitectureCausalPrefix's existing isinstance checks.
    A portable bundle can be reopened in a new interpreter with a newly
    constructed ComputationalObjectStore against the *same admitted M1 pages*.
    """
    if not isinstance(object_store, ComputationalObjectStore):
        raise TypeError("original causal model requires E-CPU M1 ComputationalObjectStore")
    if type(max_pages) is not int or not 1 <= max_pages <= 8192:
        raise ValueError("M1 causal page count budget must be between 1 and 8192")
    LocalStatePages = _original_local_pages()

    class M1LocalStatePages(LocalStatePages):
        """Exactly the original 64-KiB LocalStatePages contract, projected into M1."""

        def __init__(self):
            """Retain immutable M1 objects keyed by original causal SHA-256 descriptor."""
            self.object_store = object_store
            self.max_pages = max_pages
            self.manifests: dict[str, ComputationalObjectManifest] = {}
            if bundle is not None:
                if not isinstance(bundle, Mapping) or set(bundle) != {
                    "schema", "pages", "total_bytes", "bundle_digest",
                } or bundle["schema"] != PAGE_BUNDLE_SCHEMA:
                    raise ValueError("original Qwen M1 source bundle format differs")
                if bundle["bundle_digest"] != self._digest(
                    {key: value for key, value in bundle.items() if key != "bundle_digest"}
                ):
                    raise ValueError("causal page bundle digest differs from authority")
                refs = bundle["pages"]
                if not isinstance(refs, dict) or len(refs) > self.max_pages:
                    raise ValueError("original Qwen M1 page budget exceeded")
                for digest, payload in refs.items():
                    _require_digest(digest)
                    item = ComputationalObjectManifest.from_dict(payload)
                    if (item.content_digest != digest or item.size_bytes < 1
                        or item.size_bytes > _MAX_SOURCE_PAGE
                        or item.media_type != "application/octet-stream"):
                        raise ValueError("original causal page manifest source does not match digest")
                    self.manifests[digest] = item
                if sum(item.size_bytes for item in self.manifests.values()) != bundle["total_bytes"]:
                    raise ValueError("original Qwen M1 declared size differs from manifest bytes")

        @staticmethod
        def _digest(body):
            """Identify the exact page-manifest table by a versioned domain hash."""
            return hashlib.sha256(PAGE_BUNDLE_SCHEMA.encode() + b"\0" + _wire(body)).hexdigest()

        def put(self, data):
            """Admit a real original Qwen 64-KiB page as E-CPU M1 typed byte object."""
            if not isinstance(data, bytes) or not 1 <= len(data) <= _MAX_SOURCE_PAGE:
                raise ValueError("Qwen causal page exceeds original 64-KiB extent")
            digest = hashlib.sha256(data).hexdigest()
            if digest not in self.manifests and len(self.manifests) >= self.max_pages:
                raise ValueError("M1 model causal page count exceeded")
            manifest = self.object_store.put_bytes(data)
            if manifest.content_digest != digest or manifest.size_bytes != len(data):
                raise ValueError("E-CPU M1 model source bytes differ from original causal page")
            existing = self.manifests.get(digest)
            if existing is not None and existing.to_dict() != manifest.to_dict():
                raise ValueError("original causal page identity changed")
            self.manifests[digest] = manifest
            return {"sha256": digest, "size": len(data)}

        def get(self, descriptor):
            """Verify original Qwen descriptor and every underlying native M1 page."""
            if (not isinstance(descriptor, dict)
                or set(descriptor) != {"sha256", "size"}
                or type(descriptor["size"]) is not int
                or not 1 <= descriptor["size"] <= _MAX_SOURCE_PAGE):
                raise ValueError("original causal page descriptor malformed")
            digest = _require_digest(descriptor["sha256"])
            if digest not in self.manifests:
                raise ValueError("original Qwen source page missing from M1 authority")
            manifest = self.manifests[digest]
            if manifest.size_bytes != descriptor["size"]:
                raise ValueError("original Qwen source page size differs")
            raw = self.object_store.read_bytes(manifest, max_bytes=_MAX_SOURCE_PAGE)
            if len(raw) != descriptor["size"] or hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("original Qwen source page corrupt after M1 reconstruction")
            return raw

        def export_bundle(self):
            """Export only typed immutable byte manifests for publication under M3."""
            pages = {
                digest: manifest.to_dict()
                for digest, manifest in sorted(self.manifests.items())
            }
            body = {
                "schema": PAGE_BUNDLE_SCHEMA,
                "pages": pages,
                "total_bytes": sum(manifest.size_bytes for manifest in self.manifests.values()),
            }
            return {**body, "bundle_digest": self._digest(body)}

        def verify_bundle(self):
            """Independently read every original causal page via E-CPU's checked M1 store."""
            for digest, manifest in self.manifests.items():
                if not self.object_store.verify(manifest):
                    raise ValueError("original causal page failed M1 verification")
                self.get({"sha256": digest, "size": manifest.size_bytes})
            return True

    return M1LocalStatePages()


def check_original_qwen_checkpoint_pages(checkpoint: Mapping[str, Any], pages) -> dict[str, int]:
    """Verify every original GDN recurrent and GQA KV page is M1-addressable."""
    if not isinstance(checkpoint, Mapping) or not isinstance(checkpoint.get("layer_checkpoints"), list):
        raise ValueError("missing source-qualified Qwen causal layer checkpoint")
    gdn = gqa = count = size = 0
    for idx, layer in enumerate(checkpoint["layer_checkpoints"]):
        if not isinstance(layer, dict) or layer.get("layer") != idx:
            raise ValueError("Qwen checkpoint layer order changed")
        is_gdn = "causal_pages" in layer
        is_gqa = "kv_pages" in layer
        if is_gdn == is_gqa:
            raise ValueError("Qwen layer lacks unique GDN or GQA source pages")
        gdn += int(is_gdn)
        gqa += int(is_gqa)
        entries = layer["causal_pages"] if is_gdn else layer["kv_pages"]
        if not isinstance(entries, list) or not entries:
            raise ValueError("Qwen causal layer source is empty")
        for item in entries:
            raw = pages.get(item)
            count += 1
            size += len(raw)
    return {
        "gdn_layers": gdn, "gqa_layers": gqa,
        "source_page_refs": count, "source_bytes": size,
    }
