"""Local durability, conflict and exact reconstruction tests for the catalog."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from mailcpu.snapshot_catalog import SnapshotCatalog
from mailcpu.snapshot_delta import form_snapshot_delta

BASE=b'{"memory":"'+b'a'*8192+b'"}'
BASE_DIGEST=sha256(BASE).hexdigest()
REF=b'local-test-reference'


def key(i):
    """Form synthetic manifest keys for storage tests."""
    return sha256(str(i).encode()).hexdigest()


def delta(i):
    """Form distinct exact representations from the same pinned base."""
    return form_snapshot_delta(BASE,BASE[:100]+str(i).encode()+BASE[101:])


def catalog(path):
    """Explicitly initialize the test catalog."""
    return SnapshotCatalog(path,base_digest=BASE_DIGEST,base_reference=REF)


def test_reopen_and_conflict(tmp_path):
    """Retain immutable rows and refuse changed base or conflicting keys."""
    path=tmp_path/'store.sqlite'; c=catalog(path); d=delta(1)
    c.record(key(1),d); c.record(key(1),d)
    assert SnapshotCatalog(path).get(key(1))==d
    assert c.get(key(2)) is None
    with pytest.raises(ValueError,match='conflict'): c.record(key(1),delta(2))
    with pytest.raises(ValueError,match='base differs'): c.record(key(3),replace(d,base_digest=key(9)))
    with pytest.raises(ValueError,match='base differs'):
        SnapshotCatalog(path,base_digest=BASE_DIGEST,base_reference=b'other')
    assert SnapshotCatalog(path).get(key(1)).reconstruct(BASE)==d.reconstruct(BASE)


def test_parallel_publish(tmp_path):
    """Concurrent writers retain independent observations and exact retries."""
    path=tmp_path/'store.sqlite'; c=catalog(path)
    def publish(i):
        """Publish from separately opened catalog objects."""
        other=SnapshotCatalog(path); other.record(key(i),delta(i)); other.record(key(i),delta(i))
    with ThreadPoolExecutor(max_workers=8) as workers:
        list(workers.map(publish,range(64)))
    for i in range(64): assert c.get(key(i))==delta(i)


def test_process_loss(tmp_path):
    """A committed row survives abrupt exit and a torn transaction rolls back."""
    path=tmp_path/'store.sqlite'; c=catalog(path)
    script='''import os,sqlite3,sys
from mailcpu.snapshot_catalog import SnapshotCatalog
from mailcpu.snapshot_delta import SnapshotDelta
c=SnapshotCatalog(sys.argv[1]); d=SnapshotDelta(c.base_digest,sys.argv[3],int(sys.argv[4]),bytes.fromhex(sys.argv[5]))
c.record(sys.argv[2],d)
db=sqlite3.connect(sys.argv[1]); db.execute('BEGIN IMMEDIATE'); db.execute('DELETE FROM delta WHERE manifest=?',(sys.argv[2],)); os._exit(19)
'''
    d=delta(7)
    result=subprocess.run([sys.executable,'-c',script,str(path),key(7),d.target_digest,str(d.target_size),d.patch.hex()],
                          cwd=Path(__file__).resolve().parents[1],check=False)
    assert result.returncode==19
    assert SnapshotCatalog(path).get(key(7))==d
    assert c.get(key(7)).reconstruct(BASE)==d.reconstruct(BASE)


def test_missing_and_corrupt(tmp_path):
    """Do not recreate a missing catalog or hide altered delta/base bytes."""
    path=tmp_path/'store.sqlite'; c=catalog(path); d=delta(1); c.record(key(1),d)
    with sqlite3.connect(path) as db: db.execute('UPDATE delta SET patch=? WHERE manifest=?',(b'[0,null]',key(1)))
    with pytest.raises(ValueError,match='target identity'): c.get(key(1)).reconstruct(BASE)
    with sqlite3.connect(path) as db: db.execute('UPDATE base SET reference=?',(b'corrupt',))
    with pytest.raises(ValueError,match='base changed'): c.get(key(1))
    path.unlink()
    with pytest.raises(sqlite3.OperationalError): SnapshotCatalog(path)
    assert not path.exists()
