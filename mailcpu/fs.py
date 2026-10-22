"""Content-addressed virtual filesystem with Unix-shaped inode operations."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .providers import ProceduralProvider, ProviderRegistry


class FsError(Exception):
    """Filesystem operation failed without mutating the filesystem."""


class NodeKind(str, Enum):
    """The initial inode kinds exposed by the virtual filesystem."""

    DIRECTORY = "directory"
    FILE = "file"


@dataclass
class Inode:
    """Mutable metadata node; file bytes live in the content-addressed blob store."""

    inode_id: str
    kind: NodeKind
    mode: int
    owner: int
    blob_id: str | None = None
    provider_key: str | None = None
    children: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FileStat:
    """Stable stat projection used by syscalls and replay tests."""

    inode_id: str
    kind: str
    mode: int
    owner: int
    size: int


class BlobStore:
    """Immutable content-addressed byte storage."""

    def __init__(self) -> None:
        """Mathematics: initialize the finite partial map `B : SHA256(bytes) ⇀ bytes` as empty."""

        self._blobs: dict[str, bytes] = {}

    def put(self, data: bytes) -> str:
        """Mathematics: store under `h = SHA256(data)` and return the content address `h`."""

        value = bytes(data)
        digest = hashlib.sha256(value).hexdigest()
        existing = self._blobs.get(digest)
        if existing is not None and existing != value:
            raise RuntimeError("hash collision detected")
        self._blobs[digest] = value
        return digest

    def get(self, digest: str) -> bytes:
        """Mathematics: perform the partial lookup `B[digest]`, failing on an absent content address."""

        try:
            return self._blobs[digest]
        except KeyError as exc:
            raise FsError(f"missing blob: {digest}") from exc

    def snapshot(self) -> dict[str, str]:
        """Mathematics: serialize `B` as a hex-addressed map with reversible byte encoding."""

        return {digest: value.hex() for digest, value in sorted(self._blobs.items())}

    @classmethod
    def from_snapshot(cls, payload: dict[str, str]) -> "BlobStore":
        """Mathematics: reconstruct `B` and require `key = SHA256(value)` for every content address."""

        store = cls()
        for digest, encoded in sorted(payload.items()):
            data = bytes.fromhex(encoded)
            if hashlib.sha256(data).hexdigest() != digest:
                raise FsError(f"invalid blob digest: {digest}")
            store._blobs[digest] = data
        return store


def normalize_path(path: str) -> str:
    """Mathematics: compute the canonical root-contained path `N(p)` by eliminating `.` and balanced `..` pairs."""

    if not path.startswith("/"):
        raise FsError("only absolute paths are supported")
    parts: list[str] = []
    for component in path.split("/"):
        if component in ("", "."):
            continue
        if component == "..":
            if not parts:
                raise FsError("path escapes the virtual root")
            parts.pop()
        else:
            parts.append(component)
    return "/" + "/".join(parts)


class VirtualFileSystem:
    """A Unix-shaped filesystem whose file contents are immutable content-addressed blobs."""

    def __init__(self) -> None:
        """Mathematics: initialize root inode `i1`, inode map `I = {i1}`, and blob map `B = ∅`."""

        self.blobs = BlobStore()
        self._inodes: dict[str, Inode] = {
            "i00000001": Inode("i00000001", NodeKind.DIRECTORY, 0o755, 0)
        }
        self._next_inode = 2
        self.root_inode = "i00000001"
        self.providers = ProviderRegistry()

    def _new_inode(self, kind: NodeKind, mode: int, owner: int, data: bytes = b"") -> Inode:
        """Mathematics: allocate a fresh inode identity `i_n` and, for files, bind `blob = SHA256(data)`."""

        inode_id = f"i{self._next_inode:08d}"
        while inode_id in self._inodes:
            self._next_inode += 1
            inode_id = f"i{self._next_inode:08d}"
        self._next_inode += 1
        inode = Inode(inode_id, kind, mode, owner)
        if kind is NodeKind.FILE:
            inode.blob_id = self.blobs.put(data)
        self._inodes[inode_id] = inode
        return inode

    def _resolve(self, path: str) -> Inode:
        """Mathematics: fold path components through directory edges, `i_{k+1} = children(i_k)[name_k]`."""

        canonical = normalize_path(path)
        inode = self._inodes[self.root_inode]
        if canonical == "/":
            return inode
        for component in canonical.strip("/").split("/"):
            if inode.kind is not NodeKind.DIRECTORY or component not in inode.children:
                raise FsError(f"path not found: {canonical}")
            inode = self._inodes[inode.children[component]]
        return inode

    def _parent_and_name(self, path: str) -> tuple[Inode, str]:
        """Mathematics: decompose `p = parent(p) / name(p)` with `name(p) ∉ {'', '.', '..'}`."""

        canonical = normalize_path(path)
        if canonical == "/":
            raise FsError("root has no parent entry")
        parent_path, _, name = canonical.rpartition("/")
        parent = self._resolve(parent_path or "/")
        if parent.kind is not NodeKind.DIRECTORY:
            raise FsError(f"parent is not a directory: {parent_path or '/'}")
        return parent, name

    def mkdir(self, path: str, mode: int = 0o755, owner: int = 0) -> None:
        """Mathematics: add one directory edge `parent.children[name] := i_new` when `name ∉ children(parent)`."""

        parent, name = self._parent_and_name(path)
        if name in parent.children:
            raise FsError(f"path already exists: {normalize_path(path)}")
        inode = self._new_inode(NodeKind.DIRECTORY, mode, owner)
        parent.children[name] = inode.inode_id

    def create_file(self, path: str, data: bytes = b"", mode: int = 0o644, owner: int = 0) -> None:
        """Mathematics: create a file inode and content address `h = SHA256(data)` under its parent edge."""

        parent, name = self._parent_and_name(path)
        if name in parent.children:
            raise FsError(f"path already exists: {normalize_path(path)}")
        inode = self._new_inode(NodeKind.FILE, mode, owner, data)
        parent.children[name] = inode.inode_id

    def register_procedural_file(
        self,
        path: str,
        provider: ProceduralProvider,
        mode: int = 0o444,
        owner: int = 0,
    ) -> None:
        """Mathematics: add a read-only inode whose bytes are the provider function `P(offset, count)`, not a blob."""

        parent, name = self._parent_and_name(path)
        if name in parent.children:
            raise FsError(f"path already exists: {normalize_path(path)}")
        provider_key = f"provider:{len(self.providers.snapshot()) + 1}:{normalize_path(path)}"
        self.providers.register(provider_key, provider)
        inode = self._new_inode(NodeKind.FILE, mode, owner)
        inode.blob_id = None
        inode.provider_key = provider_key
        parent.children[name] = inode.inode_id

    def read_file(self, path: str, offset: int = 0, size: int = -1) -> bytes:
        """Mathematics: return the slice `B[h][offset : offset + size]`, or the suffix when `size < 0`."""

        if offset < 0:
            raise FsError("offset must be non-negative")
        inode = self._resolve(path)
        if inode.kind is not NodeKind.FILE:
            raise FsError(f"not a regular file: {normalize_path(path)}")
        if inode.provider_key is not None:
            provider = self.providers.get(inode.provider_key)
            return provider.read(offset, size if size >= 0 else max(0, provider.size - offset))
        if inode.blob_id is None:
            raise FsError(f"file has no content source: {normalize_path(path)}")
        data = self.blobs.get(inode.blob_id)
        return data[offset:] if size < 0 else data[offset : offset + size]

    def write_file(self, path: str, data: bytes, offset: int = 0, truncate: bool = False) -> int:
        """Mathematics: update `B[h'] = old[:o] || data || old[o+|data|:]`, with optional truncation to `old[:o] || data`."""

        if offset < 0:
            raise FsError("offset must be non-negative")
        inode = self._resolve(path)
        if inode.kind is not NodeKind.FILE:
            raise FsError(f"not a regular file: {normalize_path(path)}")
        if inode.provider_key is not None:
            raise FsError(f"procedural file is read-only: {normalize_path(path)}")
        if inode.blob_id is None:
            raise FsError(f"file has no content source: {normalize_path(path)}")
        old = self.blobs.get(inode.blob_id)
        prefix = old[:offset]
        if len(prefix) < offset:
            prefix += b"\x00" * (offset - len(prefix))
        suffix = b"" if truncate else old[offset + len(data) :]
        inode.blob_id = self.blobs.put(prefix + bytes(data) + suffix)
        return len(data)

    def listdir(self, path: str) -> tuple[str, ...]:
        """Mathematics: return the sorted key set `sort(dom(children(resolve(path))))`."""

        inode = self._resolve(path)
        if inode.kind is not NodeKind.DIRECTORY:
            raise FsError(f"not a directory: {normalize_path(path)}")
        return tuple(sorted(inode.children))

    def remove(self, path: str) -> None:
        """Mathematics: delete edge `parent.children[name]` only when the target is a file or empty directory."""

        parent, name = self._parent_and_name(path)
        if name not in parent.children:
            raise FsError(f"path not found: {normalize_path(path)}")
        inode_id = parent.children[name]
        inode = self._inodes[inode_id]
        if inode.kind is NodeKind.DIRECTORY and inode.children:
            raise FsError("directory not empty")
        del parent.children[name]
        del self._inodes[inode_id]

    def rename(self, old_path: str, new_path: str, replace: bool = False) -> None:
        """Mathematics: move inode edge `parent(old)[old] → parent(new)[new]`, preserving inode identity and rejecting descendant cycles."""

        old = normalize_path(old_path)
        new = normalize_path(new_path)
        if old == "/" or new == "/":
            raise FsError("cannot rename the virtual root")
        if old == new:
            return
        old_parent, old_name = self._parent_and_name(old)
        source_id = old_parent.children.get(old_name)
        if source_id is None:
            raise FsError(f"path not found: {old}")
        source = self._inodes[source_id]
        new_parent_path, _, new_name = new.rpartition("/")
        new_parent = self._resolve(new_parent_path or "/")
        if new_parent.kind is not NodeKind.DIRECTORY:
            raise FsError(f"parent is not a directory: {new_parent_path or '/'}")
        if source.kind is NodeKind.DIRECTORY and (
            new_parent_path == old or new_parent_path.startswith(old.rstrip("/") + "/")
        ):
            raise FsError("cannot move a directory into its own subtree")
        existing_id = new_parent.children.get(new_name)
        if existing_id is not None:
            if not replace:
                raise FsError(f"path already exists: {new}")
            if existing_id == source_id:
                return
            existing = self._inodes[existing_id]
            if existing.kind is NodeKind.DIRECTORY and existing.children:
                raise FsError("replacement directory is not empty")
        del old_parent.children[old_name]
        if existing_id is not None:
            del new_parent.children[new_name]
            del self._inodes[existing_id]
        new_parent.children[new_name] = source_id

    def stat(self, path: str) -> FileStat:
        """Mathematics: project inode state to `(id, kind, mode, owner, size)` with `size = |B[blob]|` for files."""

        inode = self._resolve(path)
        if inode.kind is NodeKind.DIRECTORY:
            size = 0
        elif inode.provider_key is not None:
            size = self.providers.get(inode.provider_key).size
        else:
            size = len(self.blobs.get(inode.blob_id or ""))
        return FileStat(inode.inode_id, inode.kind.value, inode.mode, inode.owner, size)

    def snapshot(self) -> dict[str, Any]:
        """Mathematics: serialize the inode graph `I`, blob map `B`, and allocation counter for restoration."""

        return {
            "root_inode": self.root_inode,
            "next_inode": self._next_inode,
            "blobs": self.blobs.snapshot(),
            "providers": self.providers.snapshot(),
            "inodes": {
                inode_id: {
                    "inode_id": inode.inode_id,
                    "kind": inode.kind.value,
                    "mode": inode.mode,
                    "owner": inode.owner,
                    "blob_id": inode.blob_id,
                    "provider_key": inode.provider_key,
                    "children": dict(sorted(inode.children.items())),
                }
                for inode_id, inode in sorted(self._inodes.items())
            },
        }

    @classmethod
    def from_snapshot(cls, payload: dict[str, Any]) -> "VirtualFileSystem":
        """Mathematics: reconstruct filesystem graph `F = (I, B, P)` and reject dangling or inconsistent inode edges."""

        filesystem = cls()
        filesystem.root_inode = str(payload["root_inode"])
        filesystem._next_inode = int(payload["next_inode"])
        if filesystem._next_inode <= 0:
            raise FsError("snapshot next_inode must be positive")
        filesystem.blobs = BlobStore.from_snapshot(dict(payload["blobs"]))
        filesystem.providers = ProviderRegistry.from_snapshot(dict(payload.get("providers", {})))
        filesystem._inodes = {}
        for inode_id, raw in payload["inodes"].items():
            if not isinstance(inode_id, str) or not inode_id.startswith("i") or not inode_id[1:].isdigit():
                raise FsError(f"invalid inode identity: {inode_id}")
            if int(inode_id[1:]) <= 0:
                raise FsError(f"invalid inode identity: {inode_id}")
            inode = Inode(
                str(raw["inode_id"]),
                NodeKind(raw["kind"]),
                int(raw["mode"]),
                int(raw["owner"]),
                raw.get("blob_id"),
                raw.get("provider_key"),
                dict(raw.get("children", {})),
            )
            if inode.inode_id != inode_id:
                raise FsError(f"inode key mismatch: {inode_id}")
            filesystem._inodes[inode_id] = inode
        if filesystem.root_inode not in filesystem._inodes:
            raise FsError("snapshot root inode is missing")
        root = filesystem._inodes[filesystem.root_inode]
        if root.kind is not NodeKind.DIRECTORY:
            raise FsError("snapshot root inode is not a directory")
        max_inode = max(int(inode_id[1:]) for inode_id in filesystem._inodes)
        if filesystem._next_inode <= max_inode:
            raise FsError("snapshot next_inode collides with an existing inode")
        for inode in filesystem._inodes.values():
            if inode.kind is NodeKind.FILE:
                if inode.provider_key is not None:
                    filesystem.providers.get(inode.provider_key)
                elif inode.blob_id is None:
                    raise FsError(f"file has no content source: {inode.inode_id}")
                else:
                    filesystem.blobs.get(inode.blob_id)
            for child_id in inode.children.values():
                if child_id not in filesystem._inodes:
                    raise FsError(f"dangling inode edge: {child_id}")
        filesystem._resolve("/")
        return filesystem
