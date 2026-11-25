"""Durable, receiver-verified pure results shared by independent consumers."""
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3

_HEX = re.compile(r'[0-9a-f]{64}\Z')
_MAX_BYTES = 4 * 1024 * 1024


def _hash(raw):
    """Identify exact bytes."""
    return sha256(raw).hexdigest()


def _digest(value):
    """Require a canonical SHA-256 identity."""
    if type(value) is not str or not _HEX.fullmatch(value):
        raise ValueError('invalid digest')
    return value


def _bounded(raw, limit):
    """Refuse nonbytes or oversized payloads."""
    if type(raw) is not bytes or len(raw) > limit:
        raise ValueError('invalid payload extent')
    return raw


@dataclass(frozen=True)
class PureContract:
    """Receiver-selected semantics, context and verifier identity for reusable pure work.

    Fingerprints are supplied by the trusted caller, not runtime attestation.
    Only deterministic, side-effect-free work is eligible for this contract.
    """
    interpretation: str
    context: str
    verifier: str
    max_input: int
    max_result: int

    def __post_init__(self):
        """Validate all identity and extent fields."""
        for value in (self.interpretation, self.context, self.verifier):
            _digest(value)
        if any(type(x) is not int or not 1 <= x <= _MAX_BYTES for x in (self.max_input, self.max_result)):
            raise ValueError('invalid contract extent')

    @property
    def digest(self):
        """Bind all semantic and verification coordinates to one exact contract."""
        return _hash(json.dumps(['pure-result.v1', self.interpretation, self.context,
                                self.verifier, self.max_input, self.max_result],
                               separators=(',', ':')).encode('ascii'))

    def key(self, source):
        """Bind the exact input to this semantic contract."""
        return _hash(bytes.fromhex(self.digest) + _bounded(source, self.max_input))


@dataclass(frozen=True)
class Consumer:
    """One advisory dependency at an exact observed machine revision."""
    namespace: str
    identity: int
    revision: int
    checkpoint: str
    key: str

    def __post_init__(self):
        """Reject invalid address and revision coordinates."""
        for value in (self.namespace, self.checkpoint, self.key):
            _digest(value)
        if type(self.identity) is not int or not 0 <= self.identity < 2**24:
            raise ValueError('invalid machine coordinate')
        if type(self.revision) is not int or not 1 <= self.revision < 2**63:
            raise ValueError('invalid revision')


class ResultBank:
    """Local durable result and dependency catalog; never a machine-state authority.

    One SQLite connection per worker. Every returned stored result is checked
    with the receiver's current verifier. Batch resolution checks once per
    distinct input, and does not merge consumer state or publish successors.
    """
    def __init__(self, path, *, create=False):
        """Explicitly create or reopen without silently losing a missing bank."""
        self.db = sqlite3.connect(Path(path).resolve().as_uri() + ('?mode=rwc' if create else '?mode=rw'),
                                  uri=True, timeout=30)
        try:
            self.db.execute('PRAGMA synchronous=FULL')
            if create:
                with self.db:
                    self.db.execute('CREATE TABLE IF NOT EXISTS result (key TEXT PRIMARY KEY, contract TEXT NOT NULL, source BLOB NOT NULL, output BLOB NOT NULL, output_digest TEXT NOT NULL) WITHOUT ROWID')
                    self.db.execute('CREATE TABLE IF NOT EXISTS consumer (namespace TEXT NOT NULL, identity INTEGER NOT NULL, revision INTEGER NOT NULL, checkpoint TEXT NOT NULL, key TEXT NOT NULL, PRIMARY KEY(namespace,identity)) WITHOUT ROWID')
                    self.db.execute('CREATE INDEX IF NOT EXISTS reverse_dependency ON consumer(key,namespace,identity)')
            self.db.execute('SELECT key FROM result LIMIT 0')
            self.db.execute('SELECT key FROM consumer LIMIT 0')
        except Exception:
            self.db.close()
            raise
        self.produced = 0
        self.checked = 0

    def _check(self, contract, source, output, verify):
        """Independently verify exact result bytes under the receiver-selected contract."""
        _bounded(output, contract.max_result)
        self.checked += 1
        if verify(source, output) is not True:
            raise ValueError('pure result verification refused')
        return output

    def lookup(self, contract, source, verify):
        """Return a reverified retained value, or None; never produce on a miss."""
        if not isinstance(contract, PureContract):
            raise TypeError('invalid pure contract')
        key = contract.key(source)
        row = self.db.execute('SELECT contract,source,output,output_digest FROM result WHERE key=?', (key,)).fetchone()
        if row is None:
            return None
        if row[:2] != (contract.digest, source) or type(row[2]) is not bytes or _hash(row[2]) != row[3]:
            raise ValueError('stored result identity differs')
        return self._check(contract, source, row[2], verify)

    def resolve(self, contract, source, produce, verify):
        """Recover a verified result or form and durably admit a new one.

        Concurrent producers can duplicate work, but conflicting immutable
        publication is refused. No producer is trusted merely by its digest.
        """
        retained = self.lookup(contract, source, verify)
        if retained is not None:
            return retained
        key = contract.key(source)
        self.produced += 1
        output = self._check(contract, source, produce(source), verify)
        row = (contract.digest, source, output, _hash(output))
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO result VALUES (?,?,?,?,?)', (key, *row))
            if self.db.execute('SELECT contract,source,output,output_digest FROM result WHERE key=?',(key,)).fetchone() != row:
                raise ValueError('immutable result conflict')
        return output

    def resolve_batch(self, contract, sources, produce, verify):
        """Share one verified pure result per exact input in a bounded batch."""
        if len(sources) > 65536:
            raise ValueError('batch exceeds configured extent')
        resolved = {}
        for source in sources:
            _bounded(source, contract.max_input)
            if source not in resolved:
                resolved[source] = self.resolve(contract, source, produce, verify)
        return tuple(resolved[source] for source in sources)

    def observe_consumers(self, consumers):
        """Atomically replace advisory dependency coordinates; refuse regression/conflict."""
        consumers = tuple(consumers)
        if len(consumers) > 65536 or any(not isinstance(c, Consumer) for c in consumers):
            raise ValueError('invalid consumer batch')
        if len({(c.namespace,c.identity) for c in consumers}) != len(consumers):
            raise ValueError('duplicate machine coordinate')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            for c in consumers:
                prior = self.db.execute('SELECT revision,checkpoint,key FROM consumer WHERE namespace=? AND identity=?',(c.namespace,c.identity)).fetchone()
                row = (c.revision,c.checkpoint,c.key)
                if prior is not None and (c.revision < prior[0] or (c.revision == prior[0] and row != prior)):
                    raise ValueError('stale or conflicting consumer coordinate')
                self.db.execute('INSERT INTO consumer VALUES (?,?,?,?,?) ON CONFLICT(namespace,identity) DO UPDATE SET revision=excluded.revision,checkpoint=excluded.checkpoint,key=excluded.key', (c.namespace,c.identity,*row))

    def affected(self, key, namespace):
        """Return exactly the indexed consumer coordinates for one dependency."""
        _digest(key); _digest(namespace)
        return tuple(Consumer(namespace,i,r,c,key) for i,r,c in self.db.execute(
            'SELECT identity,revision,checkpoint FROM consumer WHERE key=? AND namespace=? ORDER BY identity',(key,namespace)))

    def close(self):
        """Release the local connection."""
        self.db.close()
