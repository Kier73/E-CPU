"""Durable one-hop page Grounds preserving native PageBacking identities."""
from hashlib import sha256
from pathlib import Path
import sqlite3
import zlib

PAGE_SIZE = 4096
MAX_BASES = 1024
ANCHORS = (0, 512, 1024, 1536, 2048, 2560, 3072, 3584)


def digest(data):
    """Return a native SHA-256 page identity."""
    return sha256(data).hexdigest()


def inflate(data):
    """Decode exactly one bounded page without accepting trailing streams."""
    decoder = zlib.decompressobj()
    raw = decoder.decompress(data, PAGE_SIZE + 1)
    if len(raw) != PAGE_SIZE or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('invalid compressed page')
    return raw


def xor_page(left, right):
    """Realize exact fixed-width XOR using native integer operations."""
    return (int.from_bytes(left, "little") ^ int.from_bytes(right, "little")).to_bytes(PAGE_SIZE, "little")


class PageGroundBacking:
    """SQLite PageBacking with immutable raw bases and independently readable deltas.

    Every put commits before returning. A base is never represented by a delta.
    Candidate selection is advisory; exact reconstruction and hashing are authority
    for bytes only. The caller retains native M1/M3 admission and replication.
    One connection per worker; no shared connection across threads or forks.
    """
    page_size = PAGE_SIZE

    def __init__(self, path, *, create=False, bases=(), mode='ground'):
        """Explicitly create or reopen; derive the bounded candidate index from bases."""
        if mode not in ('raw', 'compressed', 'ground'):
            raise ValueError('invalid representation mode')
        self.mode = mode
        self.path = Path(path).resolve()
        self.db = sqlite3.connect(self.path.as_uri()+('?mode=rwc' if create else '?mode=rw'), uri=True, timeout=30)
        try:
            self.db.execute('PRAGMA synchronous=FULL')
            if create:
                with self.db:
                    self.db.execute('CREATE TABLE IF NOT EXISTS page (digest TEXT PRIMARY KEY, kind INTEGER NOT NULL, base TEXT, body BLOB NOT NULL) WITHOUT ROWID')
                    self.db.execute('CREATE TABLE IF NOT EXISTS basis (digest TEXT PRIMARY KEY) WITHOUT ROWID')
                    for raw in bases:
                        if self.db.execute("SELECT count(*) FROM basis").fetchone()[0] >= MAX_BASES:
                            raise ValueError("basis admission exceeds bounded candidate index")
                        self._check(raw)
                        key = digest(raw)
                        row = self.db.execute('SELECT kind,base,body FROM page WHERE digest=?',(key,)).fetchone()
                        if row is not None and row != (0,None,raw):
                            raise ValueError('basis must be an immutable raw page')
                        self.db.execute('INSERT OR IGNORE INTO page VALUES (?,0,NULL,?)',(key,raw))
                        self.db.execute('INSERT OR IGNORE INTO basis VALUES (?)',(key,))
            elif bases:
                raise ValueError('base creation requires explicit create')
            if self.db.execute("SELECT count(*) FROM basis").fetchone()[0] > MAX_BASES:
                raise ValueError("basis admission exceeds bounded candidate index")
            self._bases = {}
            self._anchors = {}
            for (key,) in self.db.execute('SELECT digest FROM basis ORDER BY digest'):
                raw = self._base(key)
                self._bases[key] = raw
                for offset in ANCHORS:
                    token = (offset,raw[offset:offset+64])
                    self._anchors.setdefault(token,[]).append(key)
        except Exception:
            self.db.close()
            raise

    @staticmethod
    def _check(raw):
        """Require exact page geometry."""
        if type(raw) is not bytes or len(raw) != PAGE_SIZE:
            raise ValueError('invalid page geometry')

    def _row(self,key):
        """Resolve a stored row without treating absence as zero memory."""
        row = self.db.execute('SELECT kind,base,body FROM page WHERE digest=?',(key,)).fetchone()
        if row is None:
            raise KeyError(key)
        return row

    def _base(self,key):
        """Read and reverify a raw basis from durable storage, not the candidate cache."""
        kind,parent,raw = self._row(key)
        if kind != 0 or parent is not None or self.db.execute('SELECT 1 FROM basis WHERE digest=?',(key,)).fetchone() is None:
            raise ValueError('invalid raw basis')
        self._check(raw)
        if digest(raw) != key:
            raise ValueError('basis digest differs')
        return raw

    def get_page(self,key):
        """Reconstruct one requested page, at most one additional raw basis read."""
        kind,base,body = self._row(key)
        if kind == 0 and base is None:
            raw = body
        elif kind == 1 and base is None:
            raw = inflate(body)
        elif kind == 2 and type(base) is str:
            prior = self._base(base)
            mask = inflate(body)
            raw = xor_page(prior,mask)
        else:
            raise ValueError('invalid page representation')
        self._check(raw)
        if digest(raw) != key:
            raise ValueError('page digest differs')
        return raw

    def put_page(self,raw):
        """Select a smaller one-page representation and durably publish exact bytes."""
        self._check(raw)
        key = digest(raw)
        if self.db.execute('SELECT 1 FROM page WHERE digest=?',(key,)).fetchone() is not None:
            if self.get_page(key) != raw:
                raise ValueError('page identity conflict')
            return key
        kind,base,body = 0,None,raw
        if self.mode != 'raw':
            packed = zlib.compress(raw)
            if len(packed) < len(body):
                kind,body = 1,packed
        if self.mode == 'ground':
            votes = {}
            for offset in ANCHORS:
                for candidate in self._anchors.get((offset,raw[offset:offset+64]),())[:8]:
                    votes[candidate] = votes.get(candidate,0)+1
            for candidate in sorted(votes,key=lambda x:(-votes[x],x))[:4]:
                prior = self._bases[candidate]
                mask = xor_page(prior,raw)
                packed = zlib.compress(mask)
                if len(packed)+64 < len(body)+(64 if base is not None else 0):
                    kind,base,body = 2,candidate,packed
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO page VALUES (?,?,?,?)',(key,kind,base,body))
            if self.get_page(key) != raw:
                raise ValueError('page publication differs')
        return key

    def counts(self):
        """Report stored representation counts and payload bytes by kind."""
        return {kind:(count,size) for kind,count,size in self.db.execute('SELECT kind,count(*),sum(length(body)) FROM page GROUP BY kind')}

    def close(self):
        """Close the durable local connection."""
        self.db.close()
