"""Controlled SAB-003 worker: one restricted JSON operation per fresh process.

This program is locally installed, not an untrusted-code sandbox. A completed
probe gives finite behavioral evidence; it does not confer Hypervisor authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
from typing import Any

KIND = "mailcpu.sab003.request.v1"
REPLY = "mailcpu.sab003.reply.v1"
KEY = re.compile(r"[a-f0-9]{32}\\Z")


def _canonical(value: Any) -> bytes:
    """Encode finite JSON in stable order."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value: Any) -> str:
    """Return a content checksum without claiming authentication."""
    return hashlib.sha256(_canonical(value)).hexdigest()


def _affine(a: int, c: int, mod: int, x0: int, coordinate: int) -> int:
    """Evaluate F^t by binary affine-map composition."""
    p, q, mul, add, t = 1, 0, a, c, coordinate
    while t:
        if t & 1:
            p, q = (mul * p) % mod, (mul * q + add) % mod
        add = (mul * add + add) % mod
        mul = (mul * mul) % mod
        t >>= 1
    return (p * x0 + q) % mod


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
    """Write one immutable record through a file-synced atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".sab003-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        try:
            d = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(d)
            finally:
                os.close(d)
        except OSError:
            pass
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def serve(message: Any, *, host_id: str, directory: Path, no_compute: bool = False,
          no_storage: bool = False, no_transfer: bool = False, volatile: bool = False,
          wrong_compute: bool = False, unsafe_dispatch: bool = False) -> dict[str, Any]:
    """Implement a closed, fixed-vocabulary host contract without loading code."""
    if not isinstance(message, dict) or set(message) != {"kind", "host", "nonce", "operation", "payload"}:
        raise ValueError("invalid request fields")
    if (message["kind"] != KIND or message["host"] != host_id or
            type(message["nonce"]) is not str or not 8 <= len(message["nonce"]) <= 64 or
            type(message["operation"]) is not str or not isinstance(message["payload"], dict)):
        raise ValueError("invalid request schema")
    op, data = message["operation"], message["payload"]
    reply: dict[str, Any] = {"kind": REPLY, "host": host_id, "nonce": message["nonce"],
                              "boot": secrets.token_hex(16), "ok": False,
                              "result": None, "error": "unsupported"}
    if op == "observe" and set(data) == {"word"} and type(data["word"]) is str:
        reply.update(ok=True, result={"word_digest": _digest(data["word"])}, error=None)
    elif op == "transfer" and not no_transfer and set(data) == {"bytes_hex"} and type(data["bytes_hex"]) is str:
        raw = bytes.fromhex(data["bytes_hex"])
        if len(raw) > 1024:
            raise ValueError("transfer too large")
        reply.update(ok=True, result={"bytes_hex": raw.hex()}, error=None)
    elif op == "affine_mod" and not no_compute and set(data) == {"a", "c", "mod", "x0", "coordinate"}:
        a, c, mod, x0, t = (data[key] for key in ("a", "c", "mod", "x0", "coordinate"))
        if (any(type(n) is not int for n in (a, c, mod, x0, t)) or
                not 2 <= mod <= 2**31 - 1 or
                not all(0 <= n < mod for n in (a, c, x0)) or not 0 <= t <= 10**18):
            raise ValueError("invalid affine parameters")
        value = _affine(a, c, mod, x0, t)
        reply.update(ok=True, result={"value": (value + 1) % mod if wrong_compute else value}, error=None)
    elif op in {"retain", "retrieve"} and not no_storage:
        if op == "retain":
            if set(data) != {"key", "value"}:
                raise ValueError("invalid retention write")
            key, value = data["key"], data["value"]
        else:
            if set(data) != {"key"}:
                raise ValueError("invalid retention read")
            key, value = data["key"], None
        if type(key) is not str or KEY.fullmatch(key) is None:
            raise ValueError("invalid storage key")
        path = directory / (key + ".json")
        if volatile and op == "retain":
            reply.update(ok=True, result={"key": key, "receipt": _digest(value)}, error=None)
        elif volatile and op == "retrieve":
            reply.update(ok=False, result=None, error="not_found")
        elif op == "retain":
            record = {"host": host_id, "key": key, "value": value}
            encoded = {"record": record, "digest": _digest(record)}
            if path.exists():
                if json.loads(path.read_bytes()) != encoded:
                    raise ValueError("immutable storage conflict")
            else:
                _write_atomic(path, encoded)
            reply.update(ok=True, result={"key": key, "receipt": _digest(value)}, error=None)
        elif not path.exists():
            reply.update(ok=False, result=None, error="not_found")
        else:
            encoded = json.loads(path.read_bytes())
            record = encoded.get("record")
            if (not isinstance(record, dict) or set(record) != {"host", "key", "value"} or
                    record["host"] != host_id or record["key"] != key or
                    encoded.get("digest") != _digest(record)):
                raise ValueError("corrupt retained record")
            reply.update(ok=True, result={"key": key, "value": record["value"]}, error=None)
    elif op == "execute_source" and unsafe_dispatch:
        # Bad fixture only: never execute the user-supplied text.
        reply.update(ok=True, result={"accepted": True}, error=None)
    return reply


def main(argv: list[str] | None = None) -> int:
    """Serve one bounded line-delimited JSON request, then terminate."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--directory", required=True)
    for flag in ("no-compute", "no-storage", "no-transfer", "volatile", "wrong-compute", "unsafe-dispatch"):
        parser.add_argument("--" + flag, action="store_true")
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.buffer.readline(8193)
        if len(raw) > 8192 or not raw.endswith(b"\n"):
            return 2
        result = serve(json.loads(raw), host_id=args.host, directory=Path(args.directory),
                       no_compute=args.no_compute, no_storage=args.no_storage,
                       no_transfer=args.no_transfer, volatile=args.volatile,
                       wrong_compute=args.wrong_compute, unsafe_dispatch=args.unsafe_dispatch)
        sys.stdout.write(json.dumps(result, sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n")
        return 0
    except (ValueError, OSError, TypeError, KeyError, json.JSONDecodeError):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
