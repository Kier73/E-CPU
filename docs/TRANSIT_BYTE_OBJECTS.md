# Transit Byte Objects

## Status

M1 implementation note for Computational Objects and Time.

The implementation is intentionally a compositional byte-object layer. It reuses the existing PageBacking interface and does not add a new transport protocol.

## 1. Implemented interface

The module mailcpu.computational_objects provides:

- ComputationalObjectChunk: an ordered page digest and logical byte extent.
- ComputationalObjectManifest: a versioned, canonical descriptor with media type, logical size, fixed page size, content digest, ordered chunks and manifest digest.
- ComputationalObjectStore: bounded byte-stream publication, range reads, full reads and complete-content verification over an existing page backing.

The backing needs only the already-established methods:

~~~python
put_page(data: bytes) -> str
get_page(digest: str) -> bytes
~~~

RemotePageStore implements this contract and carries page put/get requests through its existing durable replicated-mailbox path. StructuralMemoryPageBacking also implements the page contract for locally admitted structural byte providers. A caller may use either without changing the object manifest.

## 2. Page representation and verification

For configured chunk size \(P\), put_stream reads exactly the declared logical byte length. Every chunk is padded to \(P\) bytes with zeroes before it is sent to the backing.

For each chunk:
\[
p_i=b_i\Vert 0^{P-\ell_i},\qquad h_i=H(p_i)
\]

The object content digest is computed over the unpadded stream:
\[
h_C=H(b_0\Vert\cdots\Vert b_{m-1})
\]

The manifest digest binds the schema, media type, logical length, page geometry, content digest and ordered chunk references.

The page size must be a power of two between 1 and 65,536 bytes. When the backing exposes a fixed page_size, the object chunk size must match it. The default is the backing's page size or 4,096 bytes when the backing does not expose one.

A short or truncated source raises an error and no manifest is returned. Pages written before a later failure remain unreferenced immutable CAS entries; M1 does not add garbage collection or a multi-page rollback transaction.

A page read validates:
1. exact fixed page length;
2. SHA-256 identity against the referenced page digest;
3. zero bytes after the chunk's logical extent.

A full-object read additionally recomputes the content digest across the reconstructed logical bytes. A partial read validates only the descriptor and pages it actually touches; it does not claim to have verified untouched pages or the complete content digest.

## 3. Basic use

~~~python
from io import BytesIO

from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.remote_memory import RemotePageStore

# remote_pages is an already configured RemotePageStore.
objects = ComputationalObjectStore(remote_pages, chunk_size=remote_pages.page_size)

source = BytesIO(b"an immutable computational artifact")
manifest = objects.put_stream(
    source,
    total_size=len(b"an immutable computational artifact"),
    media_type="application/octet-stream",
)

portable_reference = manifest.to_dict()

# A receiving host reconstructs and validates the portable descriptor.
from mailcpu.computational_objects import ComputationalObjectManifest

received = ComputationalObjectManifest.from_dict(portable_reference)
part = objects.read_range(received, offset=4, length=12)
complete = objects.read_bytes(received)
~~~

manifest_digest identifies the descriptor and its representation metadata. content_digest identifies the logical bytes. Two manifests can therefore identify the same byte content under different declared media types while retaining distinct manifest identities.

## 4. Relationship to Transit and time

M1 does not carry a large object inside a VirtualLayerWorkload JSON envelope. The workload or computational address should carry the compact manifest reference and operation identity. The selected data-plane adapter resolves the pages through the configured backing.

When the backing is RemotePageStore, page publication and retrieval reuse its existing PAGE_PUT, PAGE_GET, PAGE_DATA and PAGE_MISS mailbox transitions. The current remote page tests exercise those transitions over loopback TCP with durable mailbox state. The new object integration test publishes several object pages through that path, drops the origin's local page copies, and resolves them again from the peer.

This is a page-store transfer path, not a claim that arbitrary ComputationalFabricForwardingServer routes already stream multi-gigabyte objects. The fabric forwarding envelope remains bounded. A future object-transfer adapter can bind object manifests and range requests to an authenticated fabric route without placing the object payload in the control-plane event.

The object manifest itself has no timestamp. Request sequence, semantic execution identity, logical time, causal dependencies, local monotonic measurements and scheduler ticks continue to belong to their existing E-CPU owners. A page becoming resident is a storage transition; it does not rewrite the object's content identity or create a global time.

## 5. Intended uses

The byte-object abstraction can be reused for:

- model weight shards and tokenizer artifacts;
- KV-cache or activation pages, once their tensor layouts and mutable-state rules are separately specified;
- executable images, ELF segments and filesystem layers;
- MailCPU or other virtual-machine memory pages;
- checkpoint artifacts and other immutable binary state.

The object layer does not interpret those formats. A consumer must validate the relevant Ground, schema, layout, implementation and authority before using the bytes.

## 6. Deliberate limits

M1 does not implement:

- a global object catalogue, host advertisement or garbage collector;
- authenticated end-to-end object origins or encryption;
- automatic transfer over every Computational Fabric route;
- resumable multi-gigabyte stream sessions independent of the page-store protocol;
- tensor arithmetic, tensor layout conversion or backend-specific allocation;
- mutable session commit, KV-cache migration or distributed inference;
- automatic model sharding or an execution DAG for transformer partitions.

A SHA-256 digest binds bytes under the hash assumption; it does not authenticate who supplied them or prove that a model or program interprets them correctly. Mutual TLS and receiver-local Hypervisor authorization remain separate trust boundaries.

## 7. Verification

The M1 tests cover manifest round-trip, canonical identity, fixed-page padding, empty objects, bounded range reads, page corruption, forged non-zero padding, descriptor tampering, geometry refusal, truncated sources and size limits.

tests/test_remote_memory.py adds an end-to-end composition over the existing remote page protocol. It verifies that an object can be published page-by-page, local copies can be dropped, and the original content can be reconstructed from the peer without changing the object manifest.
