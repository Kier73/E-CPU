"""INTERNET-004: bounded, read-only public Internet navigation as E-CPU observations.

This is a narrowly scoped public RFC link navigator, NOT a general web crawler,
remote execution service, or peer-authenticated E-CPU transport.  The RFC site
is an existing Internet observer-host supplying representations and links.
The local navigator supplies intention and traversal; it does not impute those
operations to passive network carriers or the RFC server.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
from html.parser import HTMLParser
import json
import re
import time
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urldefrag
from urllib.request import HTTPRedirectHandler, Request, build_opener

HOST = "www.rfc-editor.org"
DOCUMENT = re.compile(r"/rfc/rfc([1-9][0-9]{0,4})\.html\Z")
RFC_REFERENCE = re.compile(r"/rfc/rfc([1-9][0-9]{0,4})(?:\.html)?\Z")
SCHEMA = "mailcpu.public-internet-navigation.v1"
MAX_ARCHIVE_BYTES = 8_000_000


class NavigationRefused(ValueError):
    """The declared Internet Ground, observation or resource policy is invalid."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _integer(value: object, label: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise NavigationRefused(f"{label} must lie in [{low}, {high}]")
    return value


def rfc_url(number: int) -> str:
    _integer(number, "RFC number", 1, 99999)
    return f"https://{HOST}/rfc/rfc{number}.html"


def normalize_url(url: str) -> str:
    if type(url) is not str or len(url) > 256:
        raise NavigationRefused("URL is not bounded text")
    parsed = urlsplit(url)
    # Exact host and exact canonical RFC HTML address. No user-controlled
    # hosts, credentials, port, path traversal, query, Unicode or IP literal.
    if (parsed.scheme != "https" or parsed.netloc != HOST
            or parsed.username is not None or parsed.password is not None
            or parsed.port is not None or parsed.query
            or DOCUMENT.fullmatch(parsed.path) is None):
        raise NavigationRefused("URL is outside the explicitly permitted RFC Ground")
    number = int(DOCUMENT.fullmatch(parsed.path).group(1))
    if rfc_url(number) != parsed._replace(fragment="").geturl():
        raise NavigationRefused("URL has noncanonical representation")
    return rfc_url(number)


class Links(HTMLParser):
    def __init__(self, source_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source_url = normalize_url(source_url)
        self.found: set[str] = set()
        self.in_title = False
        self.title: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self.in_title = True
        if tag != "a":
            return
        attr = dict(attrs)
        if type(attr.get("href")) is not str:
            return
        candidate, _fragment = urldefrag(urljoin(self.source_url, attr["href"]))
        # RFC pages may refer to a resource as /rfc/rfc793 (without
        # .html). Resolve the *RFC identity* from that hyperlink, then
        # fetch the explicitly qualified canonical HTML representation.
        # This is a local address translation, NOT a remote redirect.
        try:
            parsed = urlsplit(candidate)
            match = RFC_REFERENCE.fullmatch(parsed.path)
            if (parsed.scheme == "https" and parsed.netloc == HOST
                    and not parsed.query and match is not None):
                self.found.add(rfc_url(int(match.group(1))))
        except (NavigationRefused, ValueError):
            pass

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title and sum(map(len, self.title)) < 200:
            self.title.append(data[:200])


def extract_links(source_url: str, raw: bytes) -> tuple[str, tuple[str, ...]]:
    if type(raw) is not bytes:
        raise NavigationRefused("HTML observation must be bytes")
    try:
        html = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise NavigationRefused("RFC observation is not valid UTF-8") from exc
    parser = Links(source_url)
    parser.feed(html)
    return " ".join(" ".join(parser.title).split())[:160], tuple(sorted(parser.found))


@dataclass(frozen=True)
class Policy:
    seeds: tuple[int, ...]
    target: int
    max_pages: int = 6
    max_depth: int = 2
    page_budget: int = 1_800_000
    total_budget: int = 4_000_000
    timeout_seconds: int = 8

    def __post_init__(self) -> None:
        if type(self.seeds) is not tuple or not 1 <= len(self.seeds) <= 4:
            raise NavigationRefused("1..4 original seed coordinates required")
        if len(set(self.seeds)) != len(self.seeds):
            raise NavigationRefused("seeds must be distinct")
        for n in self.seeds:
            rfc_url(n)
        rfc_url(self.target)
        _integer(self.max_pages, "max_pages", 1, 12)
        _integer(self.max_depth, "max_depth", 0, 3)
        _integer(self.page_budget, "page_budget", 4096, 2_000_000)
        _integer(self.total_budget, "total_budget", self.page_budget, 6_000_000)
        _integer(self.timeout_seconds, "timeout_seconds", 1, 15)

    def as_dict(self) -> dict:
        return {"seeds": list(self.seeds), "target": self.target,
                "max_pages": self.max_pages, "max_depth": self.max_depth,
                "page_budget": self.page_budget, "total_budget": self.total_budget,
                "timeout_seconds": self.timeout_seconds,
                "allowed_host": HOST, "allowed_path": "/rfc/rfcNNN.html",
                "method": "GET", "redirects_allowed": False}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise NavigationRefused("redirects are not allowed by receiver policy")


@dataclass(frozen=True)
class Response:
    """The bytes are returned by an external fetcher, not granted authenticity."""
    body: bytes
    status: int
    content_type: str
    content_encoding: str = "identity"


class HTTPSFetcher:
    """Real public Internet HTTPS; exact host filtering happens before I/O."""
    def __init__(self) -> None:
        self.opener = build_opener(NoRedirect)

    def __call__(self, url: str, *, limit: int, timeout: int) -> Response:
        safe = normalize_url(url)
        req = Request(safe, method="GET", headers={
            "User-Agent": "E-CPU-PublicInternetNavigation/0.1 (read-only RFC research)",
            "Accept": "text/html", "Accept-Encoding": "identity",
        })
        try:
            with self.opener.open(req, timeout=timeout) as r:
                length = r.headers.get("Content-Length")
                if length is not None and int(length) > limit:
                    raise NavigationRefused("declared response exceeds bound")
                raw = r.read(limit + 1)
                return Response(raw, r.status, r.headers.get("Content-Type", ""),
                                r.headers.get("Content-Encoding", "identity"))
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise NavigationRefused("bounded HTTPS observation unavailable: " + type(exc).__name__) from exc


def _response_ok(res: Response, limit: int) -> None:
    if (not isinstance(res, Response) or type(res.body) is not bytes
            or len(res.body) > limit or type(res.status) is not int or res.status != 200
            or res.content_type.split(";", 1)[0].strip().lower() not in
            ("text/html", "application/xhtml+xml")
            or res.content_encoding.lower() != "identity"):
        raise NavigationRefused("HTTP observation does not satisfy representation contract")


def _read_node(node: Mapping[str, object], policy: Policy) -> tuple[str, tuple[str, ...]]:
    if not isinstance(node, dict) or set(node) != {"url", "parent", "depth", "status", "media_type",
                                                  "encoding", "elapsed_ns", "size_bytes", "content_sha256",
                                                  "html_b64", "title", "links"}:
        raise NavigationRefused("observation has wrong fields")
    url = normalize_url(node["url"])
    _integer(node["depth"], "depth", 0, policy.max_depth)
    _integer(node["elapsed_ns"], "observed clock duration", 1, 1 << 63)
    _integer(node["size_bytes"], "size", 0, policy.page_budget)
    if type(node["html_b64"]) is not str:
        raise NavigationRefused("missing raw observation")
    try:
        raw = base64.b64decode(node["html_b64"], validate=True)
    except Exception as exc:
        raise NavigationRefused("unparseable raw HTTP observation") from exc
    _response_ok(Response(raw, node["status"], node["media_type"], node["encoding"]),
                 policy.page_budget)
    if (len(raw) != node["size_bytes"]
            or hashlib.sha256(raw).hexdigest() != node["content_sha256"]):
        raise NavigationRefused("raw observation does not match reported identity")
    title, links = extract_links(url, raw)
    if title != node["title"] or list(links) != node["links"]:
        raise NavigationRefused("links or title differ from retained source bytes")
    return url, links


def verify_capsule(capsule: object, policy: Policy, *,
                   expected_capsule_digest: str | None = None,
                   pinned_content_sha256: Mapping[str, str] | None = None) -> dict:
    """Independent offline reconstruction: verifies *observed bytes and links*.

    Without independently pinned content hashes this proves internal integrity
    of a captured observation, NOT that a remote service was truthful or signed
    the evidence.  Never promotes a retrieved page to an executable instruction.
    """
    if not isinstance(capsule, dict) or set(capsule) != {"schema", "policy", "visits",
                                                        "status", "path", "capsule_digest",
                                                        "scope"}:
        raise NavigationRefused("wrong capsule schema")
    if capsule["schema"] != SCHEMA or capsule["policy"] != policy.as_dict() or capsule["scope"] != "observed-HTTPS-content-and-links-not-external-attestation":
        raise NavigationRefused("capsule changed Ground or evidence scope")
    body = {k: v for k, v in capsule.items() if k != "capsule_digest"}
    if capsule["capsule_digest"] != digest(body):
        raise NavigationRefused("capsule digest does not match canonical content")
    if expected_capsule_digest is not None and capsule["capsule_digest"] != expected_capsule_digest:
        raise NavigationRefused("receiver-owned capsule identity differs")
    visits = capsule["visits"]
    if type(visits) is not list or not 1 <= len(visits) <= policy.max_pages:
        raise NavigationRefused("visited count outside budget")
    url_nodes = {}
    total = 0
    for i, node in enumerate(visits):
        url, links = _read_node(node, policy)
        if url in url_nodes:
            raise NavigationRefused("repeated site visit in deterministic traversal")
        if node["parent"] is None:
            if url not in {rfc_url(n) for n in policy.seeds} or node["depth"] != 0:
                raise NavigationRefused("root observation is not an admitted seed")
        else:
            parent = url_nodes.get(node["parent"])
            if parent is None or url not in parent[1] or node["depth"] != parent[0]["depth"] + 1:
                raise NavigationRefused("child was not linked by previously verified parent")
        total += node["size_bytes"]
        if total > policy.total_budget:
            raise NavigationRefused("full navigation exceeds byte budget")
        url_nodes[url] = (node, links)
        if pinned_content_sha256 is not None and url in pinned_content_sha256 and node["content_sha256"] != pinned_content_sha256[url]:
            raise NavigationRefused("content identity differs from independent pin")
    target = rfc_url(policy.target)
    expected_path = []
    if target in url_nodes:
        at = target
        while at is not None:
            expected_path.append(at)
            at = url_nodes[at][0]["parent"]
        expected_path.reverse()
    status = "reached_observed_target" if expected_path else "unresolved_within_budget"
    if capsule["status"] != status or capsule["path"] != expected_path:
        raise NavigationRefused("claimed intention result differs from verified observations")
    return {"verified": True, "status": status, "path": expected_path,
            "pages": len(url_nodes), "observed_bytes": total,
            "capsule_sha256": capsule["capsule_digest"],
            "provenance": "captured-by-HTTPS-client-not-remotely-attested"}


def navigate(policy: Policy, fetch: Callable[..., Response] | None = None) -> dict:
    """Follow bounded public RFC links, prioritizing the requested target.

    Each fetched page remains an untrusted *observation*. A destination not
    reached within budget returns 'unresolved', never inferred success.
    """
    fetcher = HTTPSFetcher() if fetch is None else fetch
    queue: list[tuple[str, str | None, int]] = [
        (rfc_url(n), None, 0) for n in policy.seeds]
    visited = set()
    visits = []
    total_bytes = 0
    wanted = rfc_url(policy.target)
    while queue and len(visits) < policy.max_pages:
        url, parent, depth = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        now = time.monotonic_ns()
        response = fetcher(url, limit=min(policy.page_budget, policy.total_budget-total_bytes),
                           timeout=policy.timeout_seconds)
        elapsed = max(1, time.monotonic_ns()-now)
        _response_ok(response, min(policy.page_budget, policy.total_budget-total_bytes))
        title, links = extract_links(url, response.body)
        size = len(response.body)
        total_bytes += size
        visits.append({"url": url, "parent": parent, "depth": depth,
                       "status": response.status, "media_type": response.content_type,
                       "encoding": response.content_encoding, "elapsed_ns": elapsed,
                       "size_bytes": size,
                       "content_sha256": hashlib.sha256(response.body).hexdigest(),
                       "html_b64": base64.b64encode(response.body).decode("ascii"),
                       "title": title, "links": list(links)})
        if url == wanted:
            break
        if depth < policy.max_depth:
            upcoming = [(l, url, depth+1) for l in links if l not in visited]
            upcoming.sort(key=lambda item: (item[0] != wanted, item[0]))
            # deterministic bounded queue; target gets priority without losing
            # parent-link provenance. RFCs can contain many cited references.
            queue = upcoming[:256] + [x for x in queue if x[0] not in {z[0] for z in upcoming}]
    path = []
    if wanted in {v["url"] for v in visits}:
        by_url = {v["url"]: v for v in visits}
        at = wanted
        while at is not None:
            path.append(at)
            at = by_url[at]["parent"]
        path.reverse()
    body = {"schema": SCHEMA, "policy": policy.as_dict(), "visits": visits,
            "status": "reached_observed_target" if path else "unresolved_within_budget",
            "path": path, "scope": "observed-HTTPS-content-and-links-not-external-attestation"}
    result = body | {"capsule_digest": digest(body)}
    verify_capsule(result, policy)
    return result


def strict_loads(data: bytes) -> dict:
    if type(data) is not bytes or len(data) > MAX_ARCHIVE_BYTES:
        raise NavigationRefused("capsule exceeds bounded JSON archive")
    def pairs(values):
        seen = {}
        for k, v in values:
            if k in seen:
                raise NavigationRefused("duplicate JSON field")
            seen[k] = v
        return seen
    obj = json.loads(data, object_pairs_hook=pairs,
                     parse_constant=lambda value: (_ for _ in ()).throw(NavigationRefused("nonfinite JSON")))
    if type(obj) is not dict:
        raise NavigationRefused("capsule must be an object")
    return obj
