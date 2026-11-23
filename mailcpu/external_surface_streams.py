"""HSS-001: externally hosted structures as bounded E-CPU observation streams.

The source may be an HTML page, a Hugging Face model tree, or an immutable
remote byte address. A model's architecture is *not* assumed: directories,
configurations, tokenizers, images, audio, code and safetensors are addressable
as uninterpreted source bytes until a separately authorized interpreter is
installed. This adapter does not execute remote Python, scripts or models.

Receiver-approved HTTPS transports observe bounded, exact bytes. Existing
E-CPU ComputationalObjectStore is the *only* byte/persistence authority.
A hash-linked stream witnesses translation from one observed external resource
into a portable E-CPU representation; it does not authenticate the source.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
import json
import re
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

SCHEMA = "mailcpu.hosted-external-surface.v1"
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_PATH = re.compile(r"[A-Za-z0-9_.+@/-]{1,1024}\Z")
_MAX_RESPONSE = 2 * 1024 * 1024
_MAX_RANGE = 65536
_MAX_ENTRIES = 10000
_MAX_PAGES = 32
_MAX_LINKS = 128


class SurfaceRefused(ValueError):
    """A supplied page/source address, observation or stream has no Ground."""


def _canonical(value: Any) -> bytes:
    """One finite, transport-neutral source identity byte representation."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise SurfaceRefused("external representation is not finite canonical JSON") from exc


def _digest(value: Any) -> str:
    """Content digest identifies an observation, not its remote authority."""
    return sha256(_canonical(value)).hexdigest()


def _file_path(path: str) -> str:
    """Refuse ambiguous source names, control chars and traversal."""
    if (type(path) is not str or _PATH.fullmatch(path) is None
        or path.startswith("/") or "//" in path
        or any(x in (".", "..") for x in path.split("/"))):
        raise SurfaceRefused("unadmitted external source file path")
    return path


def _url(url: str, approved_hosts: frozenset[str]) -> str:
    """Only explicitly selected public HTTPS origins may be contacted."""
    if type(url) is not str or len(url) > 4096:
        raise SurfaceRefused("unadmitted external resource URL")
    p = urlsplit(url)
    if (p.scheme != "https" or not p.hostname or p.hostname not in approved_hosts
        or p.port not in (None, 443) or p.username or p.password
        or p.fragment or p.path.startswith("//")):
        raise SurfaceRefused("HTTPS resource is outside receiver-approved origins")
    return url


@dataclass(frozen=True)
class HTTPSObservation:
    """Exact observed HTTP response, as emitted by a receiver-owned observer."""
    status: int
    headers: Mapping[str, str]
    body: bytes
    observer_host: str

    def __post_init__(self) -> None:
        if (type(self.status) is not int or self.status not in (200, 206)
            or type(self.body) is not bytes or len(self.body) > _MAX_RESPONSE
            or type(self.observer_host) is not str or not self.observer_host
            or not isinstance(self.headers, Mapping)):
            raise SurfaceRefused("invalid bounded HTTPS observation")


class _NoRedirect(HTTPRedirectHandler):
    """Redirects must re-enter our exact receiver-owned origin policy."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SurfaceRefused("HTTPS redirect requires independent origin qualification")


class BoundedHTTPSObserver:
    """An actual bounded external HTTPS worker, not a generic URL-fetch proxy.

    Hostnames and redirect targets are chosen by receiver policy and never
    inferred from source HTML. Optional signed CDN hosts can be approved by
    adding their *exact* DNS names to approved_hosts. Credentials, cookies,
    custom caller headers and remote executable content are not accepted.
    """

    def __init__(self, approved_hosts: tuple[str, ...] = ("huggingface.co",),
                 *, timeout: float = 10.0, allow_redirects: int = 0):
        if (type(approved_hosts) is not tuple or not approved_hosts
            or any(type(h) is not str or
                   re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,252}", h) is None
                   for h in approved_hosts)
            or type(timeout) not in (float, int) or not 0 < timeout <= 30
            or type(allow_redirects) is not int or not 0 <= allow_redirects <= 3):
            raise SurfaceRefused("invalid receiver HTTPS source policy")
        self.approved_hosts = frozenset(approved_hosts)
        self.timeout = float(timeout)
        self.allow_redirects = allow_redirects

    def fetch(self, url: str, *, byte_range: tuple[int, int] | None = None,
              max_bytes: int = _MAX_RESPONSE) -> HTTPSObservation:
        """Read only declared bytes; never follow a redirect to an unapproved host."""
        if type(max_bytes) is not int or not 1 <= max_bytes <= _MAX_RESPONSE:
            raise SurfaceRefused("HTTPS byte budget invalid")
        if byte_range is not None:
            lo, hi = byte_range
            if (type(lo) is not int or type(hi) is not int
                or not 0 <= lo < hi or hi-lo > min(max_bytes, _MAX_RANGE)):
                raise SurfaceRefused("range exceeds bounded source observation")
        headers = {"User-Agent": "E-CPU-HSS-001-External-Observer",
                   "Accept-Encoding": "identity"}
        if byte_range is not None:
            headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]-1}"
        opener = build_opener(_NoRedirect, HTTPSHandler())
        for hop in range(self.allow_redirects + 1):
            _url(url, self.approved_hosts)
            request = Request(url, headers=headers, method="GET")
            try:
                with opener.open(request, timeout=self.timeout) as response:
                    status = response.status
                    raw = response.read(max_bytes + 1)
                    if len(raw) > max_bytes:
                        raise SurfaceRefused("external source exceeded receiver byte budget")
                    found_headers = {k.lower(): v for k, v in response.headers.items()}
                    if status not in (200, 206):
                        raise SurfaceRefused("remote source status not admitted")
                    if byte_range is not None:
                        lo, hi = byte_range
                        # Range ignored on a tiny complete resource is valid,
                        # but never silently accept 200 for a partial huge file.
                        if status == 206:
                            cr = found_headers.get("content-range", "")
                            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)", cr)
                            if (match is None or int(match[1]) != lo
                                or int(match[2]) != hi-1):
                                raise SurfaceRefused("HTTP range witness differs")
                        elif lo != 0 or len(raw) != hi:
                            raise SurfaceRefused("remote host ignored bounded partial range")
                        if len(raw) != hi-lo:
                            raise SurfaceRefused("source range is incomplete")
                    return HTTPSObservation(status, found_headers, raw,
                                            urlsplit(url).hostname or "")
            except HTTPError as exc:
                if exc.code not in (301, 302, 303, 307, 308) or hop >= self.allow_redirects:
                    raise SurfaceRefused(f"external HTTPS request returned {exc.code}") from exc
                new = exc.headers.get("Location")
                if not new:
                    raise SurfaceRefused("HTTPS redirect missing destination") from exc
                url = _url(urljoin(url, new), self.approved_hosts)
            except (URLError, TimeoutError, OSError) as exc:
                raise SurfaceRefused("external HTTPS observer unavailable") from exc
        raise SurfaceRefused("source redirect budget exceeded")


class _PageLinks(HTMLParser):
    """Read only static anchor addresses; never execute JS or fetch embed URLs."""
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[str] = []
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            for k, v in attrs:
                if k.lower() == "href" and v is not None and len(v) <= 2048:
                    self.anchors.append(v)
                    break


def _checked_json(raw: bytes, *, expected: type) -> Any:
    """Reject repeated fields and nonfinite JSON from untrusted web responses."""
    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in items:
            if key in out:
                raise SurfaceRefused("duplicate key in external source JSON")
            out[key] = value
        return out
    try:
        item = json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (ValueError, UnicodeError) as exc:
        raise SurfaceRefused("external source JSON malformed") from exc
    if type(item) is not expected:
        raise SurfaceRefused("external JSON has unexpected root type")
    return item


def html_surface(url: str, observer: BoundedHTTPSObserver) -> dict[str, Any]:
    """Convert one HTML page into source-qualified static link observations.

    Headless browser DOM snapshots can also enter this function through a
    receiver-approved observer implementing fetch; script-derived claims are
    then scoped to that specific captured HTML. Only links are interpreted.
    """
    _url(url, observer.approved_hosts)
    response = observer.fetch(url, max_bytes=524288)
    if response.status != 200:
        raise SurfaceRefused("page representation is not a complete HTTP 200")
    media = response.headers.get("content-type", "").split(";")[0].lower()
    if media != "text/html":
        raise SurfaceRefused("expected bounded HTML representation")
    try:
        parsed = _PageLinks()
        parsed.feed(response.body.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise SurfaceRefused("invalid page encoding") from exc
    addresses: list[str] = []
    for href in parsed.anchors:
        candidate = urljoin(url, href)
        try:
            _url(candidate, observer.approved_hosts)
        except (SurfaceRefused, ValueError):
            continue
        if candidate not in addresses and len(addresses) < _MAX_LINKS:
            addresses.append(candidate)
    record = {
        "schema": SCHEMA + ".html", "url": url,
        "observer_host": response.observer_host,
        "observed_sha256": sha256(response.body).hexdigest(),
        "observed_bytes": len(response.body),
        "linked_addresses": addresses,
        "execution": "static_html_links_only",
    }
    record["ground_digest"] = _digest(record)
    return record


@dataclass(frozen=True)
class HostedFile:
    """One remote path can be named before any payload is acquired."""
    path: str
    size_bytes: int
    kind: str = "file"
    lfs_sha256: str | None = None

    def __post_init__(self) -> None:
        _file_path(self.path)
        if (type(self.size_bytes) is not int or self.size_bytes < 0
            or self.kind != "file"
            or self.lfs_sha256 is not None and
                (type(self.lfs_sha256) is not str
                 or _HEX64.fullmatch(self.lfs_sha256) is None)):
            raise SurfaceRefused("invalid external hosted file extent")

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "size_bytes": self.size_bytes,
                "kind": self.kind, "lfs_sha256": self.lfs_sha256}


@dataclass(frozen=True)
class HostedTree:
    """Source-pinned, family-independent remote model/file address catalogue."""
    repository: str
    revision: str
    files: tuple[HostedFile, ...]
    interpretation_hint: str | None = None

    def __post_init__(self) -> None:
        if (type(self.repository) is not str or _REPO.fullmatch(self.repository) is None
            or type(self.revision) is not str or _HEX40.fullmatch(self.revision) is None
            or not self.files or len(self.files) > _MAX_ENTRIES
            or tuple(sorted(self.files, key=lambda f: f.path)) != self.files
            or len(set(f.path for f in self.files)) != len(self.files)
            or self.interpretation_hint is not None and
               (type(self.interpretation_hint) is not str
                or len(self.interpretation_hint) > 120)):
            raise SurfaceRefused("hosted tree has ambiguous source identity")
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA + ".tree",
            "repository": self.repository, "revision": self.revision,
            "files": [f.to_dict() for f in self.files],
            "interpretation_hint": self.interpretation_hint,
            "scope": "source-address-inventory-not-model-execution",
        }
    @property
    def ground_digest(self) -> str:
        return _digest(self.to_dict())
    @property
    def declared_bytes(self) -> int:
        return sum(f.size_bytes for f in self.files)
    def file(self, path: str) -> HostedFile:
        path = _file_path(path)
        for f in self.files:
            if f.path == path:
                return f
        raise SurfaceRefused("source path absent from admitted hosted tree")
    @classmethod
    def restore(cls, record: Mapping[str, Any], expected_digest: str) -> "HostedTree":
        """Reconstruct a source inventory under an independent accepted head."""
        if (not isinstance(record, Mapping) or type(expected_digest) is not str
            or _HEX64.fullmatch(expected_digest) is None
            or _digest(record) != expected_digest):
            raise SurfaceRefused("externally hosted inventory identity differs")
        if set(record) != {"schema", "repository", "revision", "files",
                           "interpretation_hint", "scope"} or record["schema"] != SCHEMA+".tree" or record["scope"] != "source-address-inventory-not-model-execution":
            raise SurfaceRefused("unknown hosted-tree schema")
        try:
            files = tuple(HostedFile(**f) for f in record["files"])
            result = cls(record["repository"], record["revision"], files,
                         record["interpretation_hint"])
        except (TypeError, KeyError) as exc:
            raise SurfaceRefused("hosted source inventory malformed") from exc
        if result.to_dict() != record:
            raise SurfaceRefused("hosted source inventory changed during restoration")
        return result


def huggingface_page(url: str) -> tuple[str, str]:
    """Parse human-visible tree/blob/resolve page into a source repository/ref."""
    p = urlsplit(url)
    if p.scheme != "https" or p.netloc != "huggingface.co" or p.query or p.fragment:
        raise SurfaceRefused("unadmitted model page address")
    parts = p.path.strip("/").split("/")
    if len(parts) not in (4, 5) or len(parts) == 5 and not parts[4]:
        raise SurfaceRefused("expected Hugging Face source tree, blob or resolve address")
    repo = "/".join(parts[:2])
    if _REPO.fullmatch(repo) is None or parts[2] not in ("tree", "blob", "resolve"):
        raise SurfaceRefused("not a Hugging Face hosted repository address")
    revision = parts[3]
    if revision != "main" and _HEX40.fullmatch(revision) is None:
        raise SurfaceRefused("remote revision must be main or pinned 40-hex")
    if len(parts) == 5:
        _file_path(parts[4])
    return repo, revision


class HostedSurfaceNavigator:
    """Trusted observer reads metadata once, then resolves only needed bytes."""

    def __init__(self, observer: Any) -> None:
        if (not callable(getattr(observer, "fetch", None))
            or "huggingface.co" not in getattr(observer, "approved_hosts", ())):
            raise SurfaceRefused("receiver-owned Hugging Face observation source missing")
        self.observer = observer

    def _get(self, url: str, *, limit: int = _MAX_RESPONSE,
             byte_range: tuple[int, int] | None = None) -> HTTPSObservation:
        _url(url, self.observer.approved_hosts)
        result = self.observer.fetch(url, max_bytes=limit, byte_range=byte_range)
        if not isinstance(result, HTTPSObservation) or len(result.body) > limit:
            raise SurfaceRefused("receiver observer emitted unbounded data")
        return result

    def discover(self, page_url: str, *, max_pages: int = _MAX_PAGES) -> HostedTree:
        """Resolve mutable web page to commit, then stream only bounded tree JSON."""
        repo, ref = huggingface_page(page_url)
        if type(max_pages) is not int or not 1 <= max_pages <= _MAX_PAGES:
            raise SurfaceRefused("source discovery page budget invalid")
        info_url = ("https://huggingface.co/api/models/" + repo
                    + ("/revision/" + ref if ref != "main" else ""))
        response = self._get(info_url, limit=_MAX_RESPONSE)
        if response.status != 200:
            raise SurfaceRefused("Hugging Face revision metadata unavailable")
        info = _checked_json(response.body, expected=dict)
        sha = info.get("sha")
        if type(sha) is not str or _HEX40.fullmatch(sha) is None:
            raise SurfaceRefused("host returned no immutable repository commit")
        if ref != "main" and ref != sha:
            raise SurfaceRefused("source changed between requested pin and observation")
        tree_url = f"https://huggingface.co/api/models/{repo}/tree/{sha}?recursive=true"
        entries: dict[str, HostedFile] = {}
        seen_urls = set()
        for _ in range(max_pages):
            if tree_url in seen_urls:
                raise SurfaceRefused("hosted source page pagination loop")
            seen_urls.add(tree_url)
            response = self._get(tree_url, limit=_MAX_RESPONSE)
            if response.status != 200:
                raise SurfaceRefused("source tree page was not HTTP 200")
            page = _checked_json(response.body, expected=list)
            for item in page:
                if type(item) is not dict:
                    raise SurfaceRefused("source tree entry is not typed")
                if item.get("type") == "directory":
                    continue
                if item.get("type") != "file":
                    raise SurfaceRefused("unrecognized hosted source entry type")
                lfs = item.get("lfs")
                source_sha = lfs.get("sha256") if type(lfs) is dict else None
                f = HostedFile(item.get("path"), item.get("size"), lfs_sha256=source_sha)
                if f.path in entries:
                    if entries[f.path] != f:
                        raise SurfaceRefused("contradictory source inventory entries")
                else:
                    entries[f.path] = f
                if len(entries) > _MAX_ENTRIES:
                    raise SurfaceRefused("external inventory exceeds file count budget")
            link = response.headers.get("link", "")
            next_page = None
            for segment in link.split(","):
                if 'rel="next"' in segment:
                    match = re.search(r"<([^<>]+)>", segment)
                    if match:
                        next_page = match.group(1)
            if next_page is None:
                break
            next_page = urljoin(tree_url, next_page)
            target = urlsplit(next_page)
            if (target.scheme != "https" or target.netloc != "huggingface.co"
                or target.path != urlsplit(tree_url).path):
                raise SurfaceRefused("pagination escaped pinned repository revision")
            tree_url = next_page
        else:
            raise SurfaceRefused("external inventory exceeded metadata pagination budget")
        hint = None
        if "config.json" in entries:
            config = entries["config.json"]
            if 0 < config.size_bytes <= 262144:
                try:
                    data = self.observe(tree=HostedTree(repo, sha, tuple(sorted(entries.values(),
                        key=lambda f:f.path))), path="config.json", offset=0,
                        length=config.size_bytes)
                    value = _checked_json(data.body, expected=dict)
                    mt = value.get("model_type")
                    if type(mt) is str and len(mt) <= 120:
                        hint = mt
                except SurfaceRefused:
                    # The source inventory stands independently of model-specific semantics.
                    hint = None
        return HostedTree(repo, sha, tuple(sorted(entries.values(), key=lambda f: f.path)), hint)

    def observe(self, tree: HostedTree, path: str, *,
                offset: int, length: int) -> "SourceBytes":
        """Read one 64-KiB-or-smaller source interval only from a pinned tree."""
        if not isinstance(tree, HostedTree):
            raise SurfaceRefused("source must be a qualified HostedTree")
        file = tree.file(path)
        if (type(offset) is not int or type(length) is not int
            or length < 1 or length > _MAX_RANGE
            or offset < 0 or offset + length > file.size_bytes):
            raise SurfaceRefused("source interval exceeds declared file extent")
        address = f"https://huggingface.co/{tree.repository}/resolve/{tree.revision}/" + quote(path, safe="/")
        response = self._get(address, limit=length, byte_range=(offset, offset + length))
        if response.status == 200 and (offset != 0 or length != file.size_bytes):
            raise SurfaceRefused("source ignored requested partial range")
        return SourceBytes(tree.ground_digest, tree.repository, tree.revision,
                           path, offset, response.body, file.size_bytes,
                           response.observer_host)


@dataclass(frozen=True)
class SourceBytes:
    """One immutable observation of an exact external source-byte interval."""
    tree_digest: str
    repository: str
    revision: str
    path: str
    offset: int
    body: bytes
    declared_file_size: int
    observer_host: str
    def __post_init__(self) -> None:
        if (type(self.tree_digest) is not str or _HEX64.fullmatch(self.tree_digest) is None
            or type(self.revision) is not str or _HEX40.fullmatch(self.revision) is None
            or type(self.repository) is not str or _REPO.fullmatch(self.repository) is None
            or type(self.offset) is not int or self.offset < 0
            or type(self.body) is not bytes or not 0 < len(self.body) <= _MAX_RANGE
            or type(self.declared_file_size) is not int
            or self.offset + len(self.body) > self.declared_file_size
            or type(self.observer_host) is not str or not self.observer_host):
            raise SurfaceRefused("external source bytes lack qualified immutable address")
        _file_path(self.path)
    @property
    def content_digest(self) -> str:
        return sha256(self.body).hexdigest()
    @property
    def address(self) -> dict[str, Any]:
        return {"tree_digest": self.tree_digest, "repository": self.repository,
                "revision": self.revision, "path": self.path,
                "offset": self.offset, "length": len(self.body),
                "declared_file_size": self.declared_file_size,
                "observer_host": self.observer_host}


def publish_stream(source: SourceBytes, store: Any, *, frame_bytes: int = 4096,
                   media_type: str = "application/octet-stream") -> dict[str, Any]:
    """Admit a web observation into E-CPU's *existing* content-addressed M1.

    Every frame is hash-linked; the original bytes are stored only by E-CPU's
    existing ComputationalObjectStore, not by a shadow HTTP cache.
    """
    from .computational_objects import ComputationalObjectStore
    if (not isinstance(source, SourceBytes) or not isinstance(store, ComputationalObjectStore)
        or type(frame_bytes) is not int or not 1 <= frame_bytes <= _MAX_RANGE):
        raise SurfaceRefused("external stream requires bounded native E-CPU store")
    manifest = store.put_bytes(source.body, media_type=media_type)
    if manifest.content_digest != source.content_digest:
        raise SurfaceRefused("native object store modified source bytes")
    head = _digest({"schema": SCHEMA+".stream-genesis", "address": source.address})
    frames = []
    for start in range(0, len(source.body), frame_bytes):
        raw = source.body[start:start+frame_bytes]
        frame = {
            "index": len(frames),
            "relative_offset": start,
            "byte_length": len(raw),
            "sha256": sha256(raw).hexdigest(),
            "previous_head": head,
        }
        head = _digest(frame)
        frames.append({**frame, "head": head})
    receipt = {
        "schema": SCHEMA + ".stream",
        "address": source.address,
        "content_sha256": source.content_digest,
        "object_manifest": manifest.to_dict(),
        "frames": frames,
        "stream_head": head,
        "source_observation_bytes": len(source.body),
        "scope": "bounded-external-source-observation-published-through-existing-ecpu-m1",
    }
    receipt["receipt_digest"] = _digest(receipt)
    verify_stream(receipt, store, expected_head=head)
    return receipt


def verify_stream(receipt: Mapping[str, Any], store: Any, *,
                  expected_head: str) -> bytes:
    """Reconstruct every frame from existing M1 data on a replacement host."""
    from .computational_objects import ComputationalObjectStore
    if (not isinstance(store, ComputationalObjectStore) or not isinstance(receipt, Mapping)
        or type(expected_head) is not str or _HEX64.fullmatch(expected_head) is None
        or type(receipt.get("receipt_digest")) is not str
        or _digest({k:v for k,v in receipt.items() if k != "receipt_digest"})
           != receipt.get("receipt_digest")
        or receipt.get("schema") != SCHEMA+".stream"):
        raise SurfaceRefused("remote source stream receipt differs")
    from .computational_objects import ComputationalObjectManifest
    try:
        manifest = ComputationalObjectManifest.from_dict(receipt["object_manifest"])
        data = store.read_bytes(manifest, max_bytes=_MAX_RANGE)
    except (TypeError, ValueError, KeyError) as exc:
        raise SurfaceRefused("retained native M1 source pages invalid") from exc
    addr = receipt["address"]
    if (type(addr) is not dict or
        type(addr.get("length")) is not int or addr["length"] != len(data)
        or type(addr.get("tree_digest")) is not str
        or _HEX64.fullmatch(addr["tree_digest"]) is None
        or manifest.content_digest != sha256(data).hexdigest()
        or receipt.get("content_sha256") != manifest.content_digest
        or receipt.get("source_observation_bytes") != len(data)):
        raise SurfaceRefused("external source bytes changed in native store")
    head = _digest({"schema": SCHEMA+".stream-genesis", "address": addr})
    frames = receipt.get("frames")
    if type(frames) is not list or not frames or len(frames) > _MAX_RANGE:
        raise SurfaceRefused("missing external communication frames")
    offset = 0
    for i, frame in enumerate(frames):
        if (type(frame) is not dict or type(frame.get("byte_length")) is not int
            or not 0 < frame["byte_length"] <= _MAX_RANGE
            or frame.get("index") != i or frame.get("relative_offset") != offset):
            raise SurfaceRefused("stream sequence has a gap or ambiguous extent")
        n = frame["byte_length"]
        body = data[offset:offset+n]
        if (len(body) != n or sha256(body).hexdigest() != frame.get("sha256")
            or frame.get("previous_head") != head):
            raise SurfaceRefused("stream frame content, order or predecessor differs")
        part = {k:v for k,v in frame.items() if k != "head"}
        head = _digest(part)
        if frame.get("head") != head:
            raise SurfaceRefused("stream frame hash chain changed")
        offset += n
    if (offset != len(data) or head != expected_head
        or receipt.get("stream_head") != head):
        raise SurfaceRefused("external stream terminal identity differs")
    return data
