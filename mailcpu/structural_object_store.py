"""Transparent exact structural representations for native M1 objects."""
from hashlib import sha256
import json

from .computational_objects import ComputationalObjectError, ComputationalObjectManifest, ComputationalObjectStore
from .snapshot_catalog import SnapshotCatalog
from .snapshot_delta import MAX_BYTES, form_snapshot_delta


class _DigestOnlyBacking:
    """Describe native pages without retaining a second raw copy."""

    def __init__(self, page_size):
        """Match the native object geometry exactly."""
        self.page_size=page_size

    def put_page(self, data):
        """Return content identity, not a storage admission claim."""
        return sha256(data).hexdigest()

    def get_page(self, digest):
        """Never pretend a described page has been retained."""
        raise KeyError(digest)


class StructuralObjectStore(ComputationalObjectStore):
    """Preserve M1 manifests while selecting a durable alternate representation.

    The base remains a raw native M1 object; the local catalog stores exact
    deltas. Native M3 verifies the same immutable manifest and checkpoint.
    Stream puts and nonqualifying bytes retain the original M1 storage path.
    Range reads of structural objects materialize the entire verified object.
    """

    def __init__(self, page_backing, catalog_path, *, base_manifest=None,
                 chunk_size=None, max_object_bytes=1<<40):
        """Pin or reopen a verified raw M1 base without changing object identity."""
        super().__init__(page_backing,chunk_size=chunk_size,max_object_bytes=max_object_bytes)
        self._raw=ComputationalObjectStore(page_backing,chunk_size=self.chunk_size,max_object_bytes=max_object_bytes)
        if base_manifest is not None:
            base_manifest=self._coerce_manifest(base_manifest)
            base=self._raw.read_bytes(base_manifest,max_bytes=MAX_BYTES)
            form_snapshot_delta(base,base)
            self.catalog=SnapshotCatalog(catalog_path,base_digest=base_manifest.content_digest,
                                         base_reference=base_manifest.canonical_bytes())
        else:
            self.catalog=SnapshotCatalog(catalog_path)
        descriptor=ComputationalObjectManifest.from_dict(json.loads(self.catalog.base_reference))
        if descriptor.canonical_bytes()!=self.catalog.base_reference or descriptor.content_digest!=self.catalog.base_digest:
            raise ComputationalObjectError("invalid pinned base manifest")
        self.base_manifest=descriptor
        # Verify availability on open. Each reconstruction reads the pinned base
        # again; loss of a retained base is not hidden by a process-local cache.
        base=self._raw.read_bytes(descriptor,max_bytes=MAX_BYTES)
        form_snapshot_delta(base,base)
        self._describer=ComputationalObjectStore(_DigestOnlyBacking(self.chunk_size),
                                                chunk_size=self.chunk_size,max_object_bytes=max_object_bytes)

    def put_bytes(self, data, *, media_type="application/octet-stream"):
        """Admit a smaller structural description, otherwise use native raw pages."""
        if not isinstance(data,bytes) or len(data)>self.max_object_bytes:
            raise ComputationalObjectError("invalid object bytes or size")
        if media_type!="application/json" or not 0<len(data)<=MAX_BYTES:
            return super().put_bytes(data,media_type=media_type)
        base=self._raw.read_bytes(self.base_manifest,max_bytes=MAX_BYTES)
        try:
            delta=form_snapshot_delta(base,data)
        except ValueError:
            return super().put_bytes(data,media_type=media_type)
        # Charge the digest metadata and a conservative per-record allowance;
        # this is a selection heuristic, not a measured physical-space oracle.
        if delta.encoded_size+128>=len(data):
            return super().put_bytes(data,media_type=media_type)
        manifest=self._describer.put_bytes(data,media_type=media_type)
        if manifest==self.base_manifest:
            return manifest
        self.catalog.record(manifest.manifest_digest,delta)
        return manifest

    def _resolve(self, descriptor):
        """Recover bytes and independently reproduce every native manifest field."""
        delta=self.catalog.get(descriptor.manifest_digest)
        if delta is None:
            return None
        if descriptor.size_bytes>min(MAX_BYTES,self.max_object_bytes) or delta.target_size!=descriptor.size_bytes or delta.target_digest!=descriptor.content_digest:
            raise ComputationalObjectError("structural target identity differs")
        base=self._raw.read_bytes(self.base_manifest,max_bytes=MAX_BYTES)
        result=delta.reconstruct(base)
        if self._describer.put_bytes(result,media_type=descriptor.media_type)!=descriptor:
            raise ComputationalObjectError("reconstructed native manifest differs")
        return result

    def read_range(self, manifest, offset, length=None):
        """Resolve a bounded range only after verifying its full structural object."""
        descriptor=self._coerce_manifest(manifest)
        self._require_compatible_manifest(descriptor)
        if type(offset) is not int or not 0<=offset<=descriptor.size_bytes:
            raise ComputationalObjectError("invalid range offset")
        selected=descriptor.size_bytes-offset if length is None else length
        if type(selected) is not int or not 0<=selected<=min(descriptor.size_bytes-offset,self.max_object_bytes):
            raise ComputationalObjectError("invalid range length")
        result=self._resolve(descriptor)
        if result is None:
            return super().read_range(descriptor,offset,length)
        return result[offset:offset+selected]

    def verify(self, manifest):
        """Use exact native manifest verification regardless of representation."""
        descriptor=self._coerce_manifest(manifest)
        self._require_compatible_manifest(descriptor)
        if self._resolve(descriptor) is None:
            return super().verify(descriptor)
        return True
