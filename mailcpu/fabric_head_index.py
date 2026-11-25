"""Immutable sparse machine-head index over the native fixed-page backing contract."""
from dataclasses import dataclass
from hashlib import sha256
from itertools import groupby
import struct
import re

PAGE_SIZE = 4096
COUNT = 1 << 24
ZERO = bytes(32)
HEADER = struct.Struct('!8s32sBI')
MAGIC = b'FABIDX01'
RECORD = struct.Struct('!Q32s')
HEX = re.compile(r'[0-9a-f]{64}\Z')


def _digest(value):
    """Parse an exact nonzero SHA-256 identity."""
    if type(value) is not str or not HEX.fullmatch(value) or value == '0'*64:
        raise ValueError('invalid digest')
    return bytes.fromhex(value)


def _identity(identity):
    """Admit only a 24-bit integer coordinate."""
    if type(identity) is not int or not 0 <= identity < COUNT:
        raise ValueError('invalid machine identity')


@dataclass(frozen=True, slots=True)
class MachineHead:
    """Observed M3 checkpoint coordinates, not a quorum proof."""
    revision: int
    checkpoint_digest: str

    def __post_init__(self):
        """Require a positive revision and exact content identity."""
        if type(self.revision) is not int or not 0 < self.revision < 2**64:
            raise ValueError('invalid revision')
        _digest(self.checkpoint_digest)


class FabricHeadIndex:
    """Four radix-64 levels, with immutable roots and path-local copy-on-write.

    The caller supplies a trusted index root, and independently checks the
    returned coordinate against native M3 before use. No session is created,
    advanced or authorized here. A missing referenced page is a hard error.
    """

    def __init__(self, backing, namespace):
        """Bind a local page backing and exact fabric namespace."""
        if not callable(getattr(backing,'get_page',None)) or not callable(getattr(backing,'put_page',None)):
            raise ValueError('page backing required')
        self.backing = backing
        self.namespace = _digest(namespace)

    def _empty(self, level, prefix):
        """Encode one empty node bound to its address prefix."""
        return bytearray(HEADER.pack(MAGIC,self.namespace,level,prefix).ljust(PAGE_SIZE,b'\0'))

    def _read(self, digest, level, prefix):
        """Verify exact content, node scope and canonical unused bytes."""
        raw = self.backing.get_page(digest.hex())
        if type(raw) is not bytes or len(raw)!=PAGE_SIZE or sha256(raw).digest()!=digest:
            raise ValueError('index page integrity failure')
        if HEADER.unpack_from(raw)!=(MAGIC,self.namespace,level,prefix):
            raise ValueError('index page scope differs')
        end = HEADER.size+64*(RECORD.size if level==3 else 32)
        if any(raw[end:]):
            raise ValueError('noncanonical index padding')
        return bytearray(raw)

    def _put(self, node):
        """Publish immutable bytes only under the expected content address."""
        raw=bytes(node)
        digest=sha256(raw).digest()
        if digest==ZERO or self.backing.put_page(raw)!=digest.hex():
            raise ValueError('index backing changed content identity')
        return digest

    def empty_root(self):
        """Form a root with no indexed observations; absence does not prove nonexistence."""
        return self._put(self._empty(0,0)).hex()

    @staticmethod
    def _leaf(node, slot):
        """Decode absent or positive-revision leaf without conflating corruption."""
        rev,digest=RECORD.unpack_from(node,HEADER.size+slot*RECORD.size)
        if rev==0 and digest==ZERO:
            return None
        if rev==0 or digest==ZERO:
            raise ValueError('invalid machine head record')
        return MachineHead(rev,digest.hex())

    def lookup(self, root, identity):
        """Resolve an observed head in at most four verified page reads; None means unindexed."""
        _identity(identity)
        digest=_digest(root)
        prefix=0
        for level in range(4):
            node=self._read(digest,level,prefix)
            slot=(identity>>(18-6*level))&63
            if level==3:
                return self._leaf(node,slot)
            start=HEADER.size+32*slot
            digest=bytes(node[start:start+32])
            if digest==ZERO:
                return None
            prefix=(prefix<<6)|slot
        raise AssertionError('invalid radix geometry')

    def update(self, root, changes):
        """Build one new root for distinct observed heads, preserving prior roots.

        Refuse regressions or same-revision conflicts. Batch writes share
        ancestors. A failed batch may leave unreachable immutable pages, but
        never returns a new root; root publication is caller responsibility.
        """
        base=_digest(root)
        entries=list(changes)
        seen=set()
        for identity,head in entries:
            _identity(identity)
            if identity in seen or not isinstance(head,MachineHead):
                raise ValueError('duplicate identity or invalid head')
            seen.add(identity)
        entries.sort(key=lambda item:item[0])

        def rewrite(digest,level,prefix,items):
            """Rewrite each affected node once per batch."""
            node=self._empty(level,prefix) if digest==ZERO else self._read(digest,level,prefix)
            old=bytes(node)
            if level==3:
                for identity,head in items:
                    slot=identity&63
                    prior=self._leaf(node,slot)
                    if prior is not None and (head.revision<prior.revision or (head.revision==prior.revision and head!=prior)):
                        raise ValueError('machine head revision conflict')
                    RECORD.pack_into(node,HEADER.size+slot*RECORD.size,head.revision,_digest(head.checkpoint_digest))
            else:
                for slot,group in groupby(items,key=lambda item:(item[0]>>(18-6*level))&63):
                    start=HEADER.size+32*slot
                    child=bytes(node[start:start+32])
                    node[start:start+32]=rewrite(child,level+1,(prefix<<6)|slot,group)
            return digest if digest!=ZERO and bytes(node)==old else self._put(node)

        return rewrite(base,0,0,entries).hex()

    def resolve_current(self, root, identity, store):
        """Match an indexed head to native M3's currently verified checkpoint.

        The store must be provided by a trusted local resolver. No execution
        capability is granted; a later transition still requires native CAS.
        """
        from .computational_session import ComputationalSessionStore

        _identity(identity)
        if not isinstance(store, ComputationalSessionStore):
            raise TypeError('native computational session store required')
        if store.session_id != f'fab127.{self.namespace.hex()}.{identity:06x}':
            raise ValueError('machine and native session identity differ')
        head = self.lookup(root, identity)
        if head is None:
            raise ValueError('machine head is not indexed')
        current = store.load_latest()
        if head != MachineHead(current.revision, current.checkpoint_digest):
            raise ValueError('indexed head differs from native M3')
        return current
