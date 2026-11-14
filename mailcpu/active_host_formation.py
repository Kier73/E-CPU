"""SAB-009 — actively form an E-CPU observer on an authorized receiving substrate.

A receiver with a locally pinned interpreter and an authorized writable directory
begins *without* a Ground operator. E-CPU compiles a small trusted seed, stages
it, activates it, checks live observations, and subsequently reopens it after
process restart. This is code installation, not security sandboxing or arbitrary
remote program dispatch. Passive data reception is not execution authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Mapping, Protocol

from .ground_native_realization import (
    AffineGround, GroundIntention, RealizationPolicy, RealizationReceipt,
    RealizationRefused, _receipt, independent_observation,
)
from .runtime_qualification import canonical, digest

FORMATION_SCHEMA = "mailcpu.sab009.active-host-formation.v1"
REQUEST_KIND = "mailcpu.sab009.observation-request.v1"
REPLY_KIND = "mailcpu.sab009.observation.v1"
ENGINES = frozenset({"python", "javascript"})
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}\Z")
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]{0,18})\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")


class FormationRefused(RealizationRefused):
    """Refuse installation, activation, tampering or observation without local permission."""


def _identifier(value: Any, what: str) -> str:
    if type(value) is not str or _NAME.fullmatch(value) is None:
        raise FormationRefused(f"invalid {what}")
    return value


def _digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bounded_coordinate(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 10**18:
        raise FormationRefused("invalid coordinate")
    return value


def _wire_request(ground: AffineGround, coordinate: int, nonce: str) -> dict[str, str]:
    _bounded_coordinate(coordinate)
    if type(nonce) is not str or re.fullmatch(r"[a-f0-9]{32}", nonce) is None:
        raise FormationRefused("invalid observation challenge")
    return {"kind": REQUEST_KIND, "ground": ground.fingerprint,
            "coordinate": str(coordinate), "nonce": nonce}


def _valid_reply(reply: Mapping[str, Any], request: Mapping[str, Any], ground: AffineGround) -> int:
    if (not isinstance(reply, Mapping)
            or set(reply) != {"coordinate", "ground", "kind", "nonce", "value", "version"}
            or reply.get("kind") != REPLY_KIND
            or reply.get("coordinate") != request["coordinate"]
            or reply.get("ground") != ground.fingerprint
            or reply.get("nonce") != request["nonce"]
            or reply.get("version") != 1
            or type(reply.get("value")) is not str
            or _DECIMAL.fullmatch(reply["value"]) is None):
        raise FormationRefused("formed observer replied outside the admitted protocol")
    value = int(reply["value"])
    if value >= ground.modulus:
        raise FormationRefused("formed observer returned a value outside the Ground")
    return value


@dataclass(frozen=True)
class FormationPolicy:
    """Receiver-owned authorization to *change* explicitly named substrate resources."""

    allowed: frozenset[tuple[str, str]]
    expires_at: int
    max_seed_bytes: int = 8192
    max_frame_bytes: int = 2048
    max_process_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, frozenset) or not self.allowed:
            raise FormationRefused("formation requires exact local grants")
        for name, engine in self.allowed:
            _identifier(name, "surface identity")
            if engine not in ENGINES:
                raise FormationRefused("formation requires a supported local code engine")
        _bounded_coordinate(self.expires_at)
        if (type(self.max_seed_bytes) is not int or not 512 <= self.max_seed_bytes <= 65536
                or type(self.max_frame_bytes) is not int or not 128 <= self.max_frame_bytes <= 8192
                or type(self.max_process_seconds) not in {int, float}
                or not 0 < self.max_process_seconds <= 30):
            raise FormationRefused("formation resource bounds invalid")

    def permits(self, surface_id: str, engine: str, coordinate: int) -> None:
        if (surface_id, engine) not in self.allowed or coordinate > self.expires_at:
            raise FormationRefused("no current permission to form or operate on this surface")

    @property
    def fingerprint(self) -> str:
        return digest({"schema": FORMATION_SCHEMA + ".policy", "allowed": sorted(map(list, self.allowed)),
                       "expires_at": self.expires_at, "max_seed_bytes": self.max_seed_bytes,
                       "max_frame_bytes": self.max_frame_bytes,
                       "max_process_seconds": self.max_process_seconds})


@dataclass(frozen=True)
class SeedManifest:
    """Content-bound installed code and Ground identity, independent of execution host PID."""

    surface_id: str
    engine: str
    ground: str
    source_sha256: str
    source_bytes: int
    formation_policy: str

    def __post_init__(self) -> None:
        _identifier(self.surface_id, "manifest surface")
        if self.engine not in ENGINES:
            raise FormationRefused("invalid manifest code engine")
        for data in (self.ground, self.source_sha256, self.formation_policy):
            if type(data) is not str or _SHA.fullmatch(data) is None:
                raise FormationRefused("manifest identity digest malformed")
        if type(self.source_bytes) is not int or not 1 <= self.source_bytes <= 65536:
            raise FormationRefused("invalid seed size")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": FORMATION_SCHEMA + ".manifest", "surface_id": self.surface_id,
                "engine": self.engine, "ground": self.ground, "source_sha256": self.source_sha256,
                "source_bytes": self.source_bytes, "formation_policy": self.formation_policy}

    @property
    def fingerprint(self) -> str:
        return digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SeedManifest":
        if not isinstance(value, Mapping) or set(value) != {
                "schema", "surface_id", "engine", "ground", "source_sha256",
                "source_bytes", "formation_policy"} or value.get("schema") != FORMATION_SCHEMA + ".manifest":
            raise FormationRefused("stored seed manifest schema rejected")
        return cls(value["surface_id"], value["engine"], value["ground"],
                   value["source_sha256"], value["source_bytes"], value["formation_policy"])


# The programs below are trusted implementations *supplied by E-CPU*. They do not
# accept external executable source or invoke a command provided in a request.
_PYTHON_SEED = '''"""SAB-009 locally installed Python realization seed."""
import json, re, sys
KIND = "mailcpu.sab009.observation-request.v1"
REPLY = "mailcpu.sab009.observation.v1"
GROUND = "__GROUND__"
A, C, M, X = __A__, __C__, __M__, __X__
def run(req):
    if (type(req) is not dict or set(req) != {"kind", "ground", "coordinate", "nonce"}
        or req["kind"] != KIND or req["ground"] != GROUND
        or type(req["coordinate"]) is not str or re.fullmatch(r"(?:0|[1-9][0-9]{0,18})", req["coordinate"]) is None
        or int(req["coordinate"]) > 10**18
        or type(req["nonce"]) is not str or re.fullmatch(r"[a-f0-9]{32}", req["nonce"]) is None):
        raise ValueError("invalid request")
    t = int(req["coordinate"])
    p, q, a, c = 1, 0, A, C
    while t:
        if t & 1:
            p, q = (p*a) % M, (q*a+c) % M
        c, a = (a*c+c) % M, (a*a) % M
        t >>= 1
    return {"kind": REPLY, "coordinate": req["coordinate"], "ground": GROUND,
            "nonce": req["nonce"], "value": str((p*X+q) % M), "version": 1}
def main():
    raw = sys.stdin.buffer.readline(2049)
    if not raw.endswith(b"\\n") or len(raw) > 2048 or sys.stdin.buffer.read(1):
        return 2
    try:
        out = run(json.loads(raw))
    except (ValueError, TypeError, KeyError):
        return 2
    sys.stdout.buffer.write(json.dumps(out, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()+b"\\n")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
'''

_JS_SEED = '''"use strict";
// SAB-009 locally installed JavaScript realization seed (integer-exact BigInt).
const fs = require("fs");
const KIND = "mailcpu.sab009.observation-request.v1";
const REPLY = "mailcpu.sab009.observation.v1";
const GROUND = "__GROUND__";
const A = BigInt("__A__"), C = BigInt("__C__"), M = BigInt("__M__"), X = BigInt("__X__");
function run(req) {
  if (req === null || typeof req !== "object" || Array.isArray(req) ||
      Object.keys(req).sort().join(",") !== "coordinate,ground,kind,nonce" ||
      req.kind !== KIND || req.ground !== GROUND ||
      typeof req.coordinate !== "string" || !/^(?:0|[1-9][0-9]{0,18})$/.test(req.coordinate) ||
      BigInt(req.coordinate) > 1000000000000000000n ||
      typeof req.nonce !== "string" || !/^[a-f0-9]{32}$/.test(req.nonce)) {
    throw new Error("invalid request");
  }
  let t = BigInt(req.coordinate);
  let p = 1n, q = 0n, a = A, c = C;
  while (t > 0n) {
    if ((t & 1n) !== 0n) {
      p = (p*a) % M;
      q = (q*a+c) % M;
    }
    c = (a*c+c) % M;
    a = (a*a) % M;
    t >>= 1n;
  }
  return {coordinate:req.coordinate, ground:GROUND, kind:REPLY,
          nonce:req.nonce, value:String((p*X+q)%M), version:1};
}
try {
  const raw = fs.readFileSync(0, "utf8");
  if (Buffer.byteLength(raw, "utf8") > 2048 || !raw.endsWith("\\n") || raw.slice(0,-1).includes("\\n")) throw Error("framing");
  const result = run(JSON.parse(raw));
  process.stdout.write(JSON.stringify(result)+"\\n");
} catch (_error) { process.exitCode = 2; }
'''


def compile_seed(ground: AffineGround, engine: str) -> bytes:
    """Generate fixed E-CPU source, not executable text provided by the caller."""
    if not isinstance(ground, AffineGround) or engine not in ENGINES:
        raise FormationRefused("unsupported Ground or interpreter")
    program = _PYTHON_SEED if engine == "python" else _JS_SEED
    constants = {"__GROUND__": ground.fingerprint, "__A__": str(ground.a),
                 "__C__": str(ground.c), "__M__": str(ground.modulus),
                 "__X__": str(ground.seed)}
    for old, new in constants.items():
        program = program.replace(old, new)
    return program.encode("utf-8")


class ReceivingSurface(Protocol):
    """Local adapter for an authorized code-and-data environment."""

    surface_id: str
    engine: str

    def stage(self, manifest: SeedManifest, source: bytes) -> None:
        ...

    def activate(self, manifest: SeedManifest, request: Mapping[str, Any],
                 *, timeout: float, max_bytes: int) -> Mapping[str, Any]:
        ...


class LocalInterpreterSurface:
    """Authorized empty directory plus pinned executable: a real installation surface.

    This adapter assumes its directory and executable are trusted configuration.
    It is NOT an OS sandbox. Only the controlled seed generator supplies code.
    """

    def __init__(self, surface_id: str, engine: str, directory: str | Path,
                 executable: str) -> None:
        self.surface_id = _identifier(surface_id, "surface identity")
        if engine not in ENGINES:
            raise FormationRefused("unknown code engine")
        if type(executable) is not str or not os.path.isabs(executable):
            raise FormationRefused("interpreter must be a receiver-local absolute executable path")
        self.engine = engine
        self.directory = Path(directory)
        if not self.directory.is_dir() or self.directory.is_symlink():
            raise FormationRefused("receiving surface requires a pre-authorized real directory")
        self.executable = executable

    @property
    def _source_path(self) -> Path:
        return self.directory / ("ecpu-seed.py" if self.engine == "python" else "ecpu-seed.js")

    @property
    def _manifest_path(self) -> Path:
        return self.directory / "ecpu-seed-manifest.json"

    @staticmethod
    def _atomic(path: Path, data: bytes) -> None:
        fd, temp = tempfile.mkstemp(prefix=".ecpu-stage-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp, path)
            try:
                folder = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(folder)
                finally:
                    os.close(folder)
            except OSError:
                pass
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def _verify_installed(self, manifest: SeedManifest) -> None:
        try:
            stored_manifest = SeedManifest.from_dict(json.loads(self._manifest_path.read_bytes()))
            source = self._source_path.read_bytes()
        except (OSError, ValueError, UnicodeError, TypeError) as exc:
            raise FormationRefused("installed seed missing or invalid") from exc
        if (stored_manifest != manifest or len(source) != manifest.source_bytes
                or _digest_bytes(source) != manifest.source_sha256):
            raise FormationRefused("installed source or manifest differs from admitted bytes")

    def stage(self, manifest: SeedManifest, source: bytes) -> None:
        if manifest.surface_id != self.surface_id or manifest.engine != self.engine:
            raise FormationRefused("seed is addressed to another receiving surface")
        if len(source) != manifest.source_bytes or _digest_bytes(source) != manifest.source_sha256:
            raise FormationRefused("seed source digest mismatches the formation manifest")
        if self._manifest_path.exists() or self._source_path.exists():
            self._verify_installed(manifest)
            return  # immutable idempotent install; no silent reprogramming
        self._atomic(self._source_path, source)
        self._atomic(self._manifest_path, canonical(manifest.to_dict()))
        self._verify_installed(manifest)

    def activate(self, manifest: SeedManifest, request: Mapping[str, Any],
                 *, timeout: float, max_bytes: int) -> Mapping[str, Any]:
        self._verify_installed(manifest)
        raw = canonical(dict(request)) + b"\n"
        if len(raw) > max_bytes or max_bytes > 8192:
            raise FormationRefused("activation frame exceeds locally admitted budget")
        argv = ([self.executable, "-I", str(self._source_path)] if self.engine == "python"
                else [self.executable, str(self._source_path)])
        try:
            r = subprocess.run(argv, input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               check=False, timeout=timeout, cwd=self.directory)
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise FormationRefused("installed observer could not run") from exc
        if r.returncode or r.stderr or len(r.stdout) > max_bytes or not r.stdout.endswith(b"\n"):
            raise FormationRefused("installed observer returned an invalid frame")
        try:
            reply = json.loads(r.stdout)
            if type(reply) is not dict or canonical(reply) + b"\n" != r.stdout:
                raise FormationRefused("installed observer response is noncanonical")
            return reply
        except (ValueError, UnicodeError, TypeError) as exc:
            raise FormationRefused("installed observer response was malformed") from exc


@dataclass(frozen=True)
class FormedGroundRealizer:
    """Operational E-CPU observer created by installation into a previously blank surface."""

    surface: ReceivingSurface
    manifest: SeedManifest
    formation_policy: FormationPolicy

    @property
    def locus(self) -> str:
        return self.surface.surface_id

    @property
    def method(self) -> str:
        return "formed." + self.surface.engine

    def observe(self, intention: GroundIntention,
                policy: RealizationPolicy) -> RealizationReceipt:
        if not isinstance(intention, GroundIntention):
            raise FormationRefused("formed observer needs a typed intention")
        policy.permits(self.locus, self.method, intention.coordinate)
        self.formation_policy.permits(self.locus, self.surface.engine, intention.coordinate)
        if (self.manifest.ground != intention.ground.fingerprint
                or self.manifest.formation_policy != self.formation_policy.fingerprint):
            raise FormationRefused("installed code does not bind the admitted Ground or formation grant")
        nonce = digest({"formation": self.manifest.fingerprint,
                        "intention": intention.fingerprint, "stage": "observe"})[:32]
        req = _wire_request(intention.ground, intention.coordinate, nonce)
        reply = self.surface.activate(self.manifest, req,
                                      timeout=self.formation_policy.max_process_seconds,
                                      max_bytes=self.formation_policy.max_frame_bytes)
        value = _valid_reply(reply, req, intention.ground)
        if value != independent_observation(intention):
            raise FormationRefused("installed interpreter contradicts the Ground oracle")
        events = [{"kind": "seed_activated", "surface": self.locus,
                   "engine": self.surface.engine, "manifest": self.manifest.fingerprint},
                  {"kind": "ground_observed", "request": digest(req),
                   "response": digest(dict(reply)), "coordinate": intention.coordinate}]
        evidence = {"formation_kind": FORMATION_SCHEMA, "manifest": self.manifest.to_dict(),
                    "source_sha256": self.manifest.source_sha256,
                    "formation_policy": self.formation_policy.fingerprint,
                    "observation_request": digest(req), "observation_response": digest(dict(reply)),
                    "runtime_installed_by_receiver": True, "hardware_attested": False}
        return _receipt(intention, policy, locus=self.locus, method=self.method,
                        value=value, events=events, evidence=evidence)


def actively_form(surface: ReceivingSurface, ground: AffineGround,
                  policy: FormationPolicy, *, coordinate: int) -> FormedGroundRealizer:
    """Actively install, challenge, and admit a new observer—not merely discover it.

    Ground and source must both be approved before installation. The receiver
    then proves several concrete coordinates through the fresh executable.
    These are finite tests, not a universal proof of arbitrary computations.
    """
    if not isinstance(ground, AffineGround) or not isinstance(policy, FormationPolicy):
        raise FormationRefused("formation requires an admitted Ground and local formation policy")
    _bounded_coordinate(coordinate)
    surface_id = _identifier(surface.surface_id, "surface identity")
    engine = surface.engine
    policy.permits(surface_id, engine, coordinate)
    code = compile_seed(ground, engine)
    if len(code) > policy.max_seed_bytes:
        raise FormationRefused("compiled seed exceeds receiving surface budget")
    manifest = SeedManifest(surface_id, engine, ground.fingerprint,
                            _digest_bytes(code), len(code), policy.fingerprint)
    surface.stage(manifest, code)
    # Challenge the new active implementation across distant coordinates.
    for i, t in enumerate((0, 19, 10**12 + 913)):
        if t > policy.expires_at:
            continue
        nonce = digest({"installation": manifest.fingerprint, "probe": i})[:32]
        req = _wire_request(ground, t, nonce)
        response = surface.activate(manifest, req, timeout=policy.max_process_seconds,
                                    max_bytes=policy.max_frame_bytes)
        got = _valid_reply(response, req, ground)
        expected = independent_observation(GroundIntention("sab009-formation-probe", ground, t))
        if got != expected:
            raise FormationRefused("newly formed host failed independent Ground challenge")
    return FormedGroundRealizer(surface, manifest, policy)