# INTERNET-003 — An active communication path retains and transforms an observation

**Research status (2026-11-16):** real Nginx proxy/cache and a separate Nginx origin communicating over actual localhost TCP; **26 local tests: 22 passing, 4 native MailCPU adapter tests skipped** because MailCPU is not installed in the local runner. A bounded, read-only remote HTTPS conditional probe is implemented but **has not been executed against the public internet** in this environment. The hosted workflow is required for that claim. No passive-fiber arithmetic, physically independent hosts, or general network intelligence is claimed.

## Architectural role

This builds directly on [The Internet Is the Computer](THE_INTERNET_IS_THE_COMPUTER.md), [Communication Host Model](COMMUNICATION_HOST_MODEL.md), [Latent Path Capacity](LATENT_PATH_CAPACITY.md), [PATH-GROUND-001](PATH_GROUND_001_COMMUNICATION_OBSERVATION.md), [INTERNET-001](INTERNET_NATIVE_GROUND_001.md), and [INTERNET-002](INTERNET_NATIVE_GROUND_002.md).

INTERNET-001/002 recognized a pre-existing remote Git-service relation. PATH-GROUND-001 tested local kernel TCP byte transport and a separate software FIR transfer reference. INTERNET-003 asks something more specific: **can a distinct intermediary on an actual communication path retain information and realize observations that are no longer obtainable from the source?**

The intermediary uses **installed, unmodified Nginx HTTP cache, conditional selection, range handling, and gzip functionality**. E-CPU code is not installed at either Nginx process. A receiver probes its declared operations through real sockets and qualifies them against source bytes from a different trust/observation context. An operator available in Nginx is not evidence for that operator in an uninstrumented optical fiber.

## Realization and declared mathematical Ground

```text
               bypass: client ───────────────> Nginx origin
                         |                       ^
                         | proxy path            | TCP cache misses
                         v                       |
                     Nginx proxy ---------------+
                       │   existing cache state C
                       │   gzip / ranges / conditional requests
                       └──→ requested observation
```

The program manages **two Nginx processes**, two distinct localhost listening ports, an independently known origin file, an observed client, and an isolated on-disk proxy cache. The proxy's standard implementation supplies the active HTTP operation. The experiment supplies *configuration*, source material, timing probes, independent verifier and bounded requests.

A typed intention is `(source_version, request_headers, desired_projection, freshness_policy)`. The path has an internal cache state `C`: empty, a stored representation and its validation metadata, or an expired/reconfigured representation. The observed operation is a conditional relation rather than a scalar function of input bytes alone:

- Ordinary GET returns 200 and the selected response body.
- `Range: bytes=i-j` selects a bounded slice and returns 206 and a Content-Range field.
- `If-None-Match` can select 304 and no response body when its validator matches the selected representation.
- `Accept-Encoding: gzip` can realize a compressed wire representation; the receiver independently decompresses and compares the original bytes.
- A warm cache may supply an earlier **versioned** representation without an origin request. This does **not** mean it is the *current* origin representation.

The receiver pins the source SHA-256 independently of the packet; it does not let a response claim its own truth. A conditional 304 is admitted only against a receiver-verified prior 200 response with the same source version and ETag. A changed source pin makes an old cache answer invalid as a current-source realization. A response's `X-ECpu-Cache` header is diagnostic; the run also observes the separate origin's access log and tests origin loss.

This is a **bounded, snapshot- and version-relative Ground**. It is not an exhaustive proof of HTTP under all caching conditions or a guarantee about arbitrary proxy deployment. The endpoint, proxy, and origin clocks are not assumed synchronized; durations are sampled using one client process's monotonic clock. Local Nginx service time, kernel scheduling and TCP are included in these durations; propagation time is not isolated.

### Measured local experiment

One ephemeral run (Debian 13, Python 3.13, Nginx 1.26.3):

| Check | Actual result |
|---|---|
| Source representation | 71,980 bytes |
| Proxy-gzip body | 3,163 bytes (95.6% smaller) |
| Proxy cached GET | MISS then HIT; origin request count unchanged on warm response |
| Bounded byte-range | HTTP 206, exact 4,096 bytes |
| Matching conditional GET | HTTP 304, zero body bytes |
| Changed origin version, warm cached copy | Original copy returned; verifier rejected it against new origin SHA-256 |
| Origin terminated | Direct TCP connection unavailable, forced proxy bypass returned 502 |
| Qualified queries **after origin termination** | **80/80** (40 complete/gzip, 20 range, 20 conditional) against independently retained original source |
| Median origin-offline proxy query | 0.171 ms on this local runner |

The origin's file was deliberately changed after the cache was populated, and then its process was shut down. The proxy continued answering from retained state. The client deliberately checked *both* old and new source identities, and refused to call an old cached version the current new one. The checked-in local report retains all 80 per-request consistency receipts, measured monotonic spans and response-body digests. `examples/verify_internet_path_report.py` can independently check the **internal consistency** of that exported record against receiver-owned source bytes. This cannot independently attest whether a remote network path executed: exported receipts and Nginx logs are unsigned.

The measured body size reduction is not a claim of overall network traffic or energy reduction. HTTP/TCP/TLS headers, gzip CPU work, source procurement, verification, service startup and cache storage are additional costs. Successful local recovery does not imply independent failure domains (both services share the same machine).

## Integration with native E-CPU

[`examples/native_http_path_bridge.py`](../examples/native_http_path_bridge.py) reuses **`mailcpu.observer_orbit.ObserverContract` / `ObserverReceipt`** and **`mailcpu.observer_path_evidence.ObserverPathStage` / `verify_observer_path`**. It represents one active proxy observation as an explicitly source-bound **transform stage**. The receiver must provide a local admission callback and fixed policy digest; a changed source, invalid response or policy denial refuses. No passenger frame confers permission; no artificial passive carrier is added as if the physical medium had executed gzip.

The adapter is a **description and receipt**, not a full native Hypervisor operation, a verified remote TLS peer, M3 recovery, or physical path attribution. The HTTP probe is ordinary unencrypted TCP confined to localhost; it does not claim general internet service security.

## Separate WAN observation gate

[`examples/probe_internet_https_conditional.py`](../examples/probe_internet_https_conditional.py) performs a **read-only, tightly pinned** pair of HTTPS requests against the known original 358-byte GitHub blob from INTERNET-001: first unconditional GET, then `If-None-Match` with the returned ETag. It independently reconstructs the Git blob hash and SHA-256 and records whether a live HTTP 304 was actually observed. If the service instead returns 200, it must be reported as 200; **the verifier cannot invent a 304**. This test distinguishes service-level HTTP semantics from a path-element or fiber claim. It has not run from this local environment because public DNS resolution is unavailable. Exact-head CI, if it runs successfully, supplies a bounded public-Internet observation.

The WAN service must not be assumed to have the same cache topology as the local controlled proxy. A service returning HTTP 304 does **not** by itself identify which origin, CDN, or intermediary evaluated the validator. Such attribution needs a separately controlled path and endpoint or instrumented path evidence.

## Test and deployment

```bash
python -m unittest discover -s tests -p 'test_internet_path_*.py' -v
python -m unittest discover -s tests -p 'test_internet_https_conditional.py' -v
python examples/probe_internet_path_nginx.py --output /tmp/internet-003-local.json
python examples/verify_internet_path_report.py \
  --report reports/internet_native_ground/internet_003_local_nginx_path.json \
  --expected-source-sha256 35a9bbca78d45eaf7b29ea644816a1cd07f76dee7b640c3c1e995120a8446155

# On a GitHub Actions runner with actual public HTTPS access, use exact external pins:
python examples/probe_internet_https_conditional.py \
  --expected-blob-sha1 46958c491ec504e2f8562ca37b8b152d441376f0 \
  --expected-source-sha256 ece11d917a3c4bf1240e8e02a29b94ff2761fcdf8e37504bc9660d382b0f5c67 \
  --output /tmp/internet-003-wan.json
```

A Linux host with `nginx` on `PATH` is required for the real controlled-path tests. The source and cache are ephemeral. The tests use real loopback TCP and explicitly refuse invalid range, validator and source identities. Native observer-path tests must run where the **real MailCPU package** is installed; local skips cannot count as passing.

## Reuse and next harder experiment

The next experiment should use two *separately controlled, physically separated* observer loci and at least one independently instrumented path segment. Preserve a zero-computation bypass, source-only and intermediary-only controls, cold/warm/recovery cuts, independent source pins and client-clock timings. Measure real bytes at each interface, computation performed by each active element, and path/instrument influence separately. Couple the admitted path operator into existing `EvidencePathResolver`, `VirtualGround`, M1/M3 and Hypervisor authority, rather than inventing a new network scheduler or authority stack. This is also the proper path toward integrating RCG-007's observer-relative atlas as a source of intentions.

## External standards

- RFC 9110 (HTTP Semantics): https://www.rfc-editor.org/rfc/rfc9110 — preconditions, 200/206/304, Range/If-Range.
- RFC 9111 (HTTP Caching): https://www.rfc-editor.org/rfc/rfc9111 — cache representation selection, freshness, revalidation and response reuse.
- RFC 9293 (TCP): https://www.rfc-editor.org/rfc/rfc9293 — byte stream, ACK/sequence state and segmentation semantics.
