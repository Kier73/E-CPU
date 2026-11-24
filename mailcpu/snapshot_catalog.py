"""Durable local catalog of one-hop structural snapshot representations."""
from contextlib import closing, contextmanager
from pathlib import Path
import re
import sqlite3

from .snapshot_delta import SnapshotDelta

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_MAX_REFERENCE = 1_048_576


def _digest(value):
    """Validate a canonical content identity."""
    if type(value) is not str or not _HEX.fullmatch(value):
        raise ValueError("invalid catalog digest")
    return value


class SnapshotCatalog:
    """Store immutable representations under their native manifest identity.

    One catalog pins one raw base reference. SQLite transactions publish one
    immutable representation before M3 may reference it. This local catalog
    is not a quorum, a machine registry, or proof of current state.
    """

    def __init__(self, path, *, base_digest=None, base_reference=None):
        """Create explicitly or reopen a catalog without silently changing its base."""
        self.path = Path(path).resolve()
        supplied = base_digest is not None or base_reference is not None
        if supplied:
            _digest(base_digest)
            if type(base_reference) is not bytes or not 0 < len(base_reference) <= _MAX_REFERENCE:
                raise ValueError("invalid base reference")
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection(create=supplied) as db:
            if supplied:
                db.execute("BEGIN IMMEDIATE")
                db.execute("CREATE TABLE IF NOT EXISTS base (singleton INTEGER PRIMARY KEY CHECK(singleton=1), digest TEXT NOT NULL, reference BLOB NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS delta (manifest TEXT PRIMARY KEY, target TEXT NOT NULL, size INTEGER NOT NULL, patch BLOB NOT NULL) WITHOUT ROWID")
                db.execute("INSERT OR IGNORE INTO base VALUES (1,?,?)", (base_digest, base_reference))
            row = db.execute("SELECT digest,reference FROM base WHERE singleton=1").fetchone()
            if row is None:
                raise ValueError("catalog base is missing")
            self.base_digest = _digest(row[0])
            self.base_reference = row[1]
            if type(self.base_reference) is not bytes or not 0 < len(self.base_reference) <= _MAX_REFERENCE:
                raise ValueError("invalid stored base reference")
            if supplied and row != (base_digest,base_reference):
                raise ValueError("catalog base differs")
            # Opening an incomplete catalog must fail rather than create an empty one.
            db.execute("SELECT manifest FROM delta LIMIT 0")
            db.commit()

    @contextmanager
    def _connection(self, *, create=False):
        """Open an exact local database; commit durability is SQLite FULL."""
        uri = self.path.as_uri() + ("?mode=rwc" if create else "?mode=rw")
        with closing(sqlite3.connect(uri, uri=True, timeout=30)) as db:
            db.execute("PRAGMA synchronous=FULL")
            yield db

    def _check_base(self, db):
        """Refuse a substituted catalog even after construction."""
        row = db.execute("SELECT digest,reference FROM base WHERE singleton=1").fetchone()
        if row != (self.base_digest,self.base_reference):
            raise ValueError("catalog base changed")

    def record(self, manifest_digest, delta):
        """Durably publish one exact immutable alternate representation."""
        _digest(manifest_digest)
        if not isinstance(delta,SnapshotDelta) or delta.base_digest!=self.base_digest:
            raise ValueError("delta base differs from catalog")
        row=(delta.target_digest,delta.target_size,delta.patch)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_base(db)
            db.execute("INSERT OR IGNORE INTO delta VALUES (?,?,?,?)", (manifest_digest,*row))
            if db.execute("SELECT target,size,patch FROM delta WHERE manifest=?",(manifest_digest,)).fetchone()!=row:
                raise ValueError("immutable representation conflict")
            db.commit()

    def get(self, manifest_digest):
        """Resolve one alternate record, or None if this catalog has no such observation."""
        _digest(manifest_digest)
        with self._connection() as db:
            db.execute("BEGIN")
            self._check_base(db)
            row=db.execute("SELECT target,size,patch FROM delta WHERE manifest=?",(manifest_digest,)).fetchone()
            return None if row is None else SnapshotDelta(self.base_digest,*row)
