"""SAB-003: qualify bounded observation, processing, framed transport and retained state.

An endpoint is *not* a trusted processor merely because it is reachable or advertises
an opcode. Each role requires fixed behavior under a local probe policy. The result is
finite behavioral evidence, never hardware attestation or Hypervisor permission.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import subprocess
from typing import Any, Mapping, Protocol

REQUEST_KIND = "mailcpu.sab003.request.v1"
RESPONSE_KIND = "mailcpu.sab003.reply.v1"
REPORT_KIND = "mailcpu.sab003.qualification.v1"
ROLES = frozenset({"observer", "framed_ipc", "computational_fragment", "retained_state", "restricted_dispatch_observed"})
HEX32 = re.compile(r"[a-f0-9]{32}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
MAX_COORDINATE = 10**18


class QualificationRefused(ValueError):
    """An endpoint, probe, transcript, or claim violates the qualification contract."""


def canonical(value: Any) -> bytes:
    """Serialize finite JSON without coercion or non-finite numbers."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise QualificationRefused("value is not finite JSON") from exc


def digest(value: Any) -> str:
    """Identify canonical content; this is not proof of origin or identity."""
    return hashlib.sha256(canonical(value)).hexdigest()


def _name(value: Any, what: str) -> str:
    """Accept only bounded, unambiguous names."""
    if type(value) is not str or HOST.fullmatch(value) is None:
        raise QualificationRefused(f"invalid {what}")
    return value


def _integer(value: Any, what: str, minimum: int = 0, maximum: int = MAX_COORDINATE) -> int:
    """Accept bounded integer coordinates, rejecting booleans."""
    if type(value) is not int or not minimum <= value <= maximum:
        raise QualificationRefused(f"invalid {what}")
    return value


def affine_expected(a: int, c: int, modulus: int, x0: int, coordinate: int) -> int:
    """Verify an affine transition via binary affine-map composition."""
    p, q, mul, add, t = 1, 0, a, c, coordinate
    while t:
        if t & 1:
            p, q = (mul * p) % modulus, (mul * q + add) % modulus
        add, mul = (mul * add + add) % modulus, (mul * mul) % modulus
        t >>= 1
    return (p * x0 + q) % modulus


@dataclass(frozen=True)
class QualificationPolicy:
    """Receiver-local authorization for bounded tests against explicitly owned hosts."""

    allowed_hosts: frozenset[str]
    observer_id: str
    expires_at: int
    permitted_roles: frozenset[str] = ROLES
    max_calls: int = 8
    max_response_bytes: int = 4096

    def __post_init__(self) -> None:
        """Validate authorization before making even the first probe."""
        _name(self.observer_id, "observer")
        if not self.allowed_hosts or any(_name(x, "allowed host") != x for x in self.allowed_hosts):
            raise QualificationRefused("empty or invalid host permission")
        _integer(self.expires_at, "lease expiration")
        if not self.permitted_roles.issubset(ROLES) or "observer" not in self.permitted_roles:
            raise QualificationRefused("qualification requires a permitted observer role")
        _integer(self.max_calls, "call budget", 1, 32)
        _integer(self.max_response_bytes, "response byte budget", 256, 65536)

    @property
    def fingerprint(self) -> str:
        """Bind the local permission set, lease, observer, and resource bounds."""
        return digest({"hosts": sorted(self.allowed_hosts), "observer": self.observer_id,
                       "expires": self.expires_at, "roles": sorted(self.permitted_roles),
                       "max_calls": self.max_calls, "max_response_bytes": self.max_response_bytes})


class QualificationEndpoint(Protocol):
    """A locally installed, permitted, bounded request/response interface."""

    host_id: str
    separate_process_per_exchange: bool

    def exchange(self, request: Mapping[str, Any], *, max_bytes: int) -> Mapping[str, Any]:
        """Return one framed observation; this call grants no remote program authority."""
        ...


class SubprocessQualificationEndpoint:
    """Launch an explicitly supplied local program once per request, with no shell."""

    separate_process_per_exchange = True

    def __init__(self, host_id: str, command: tuple[str, ...], *, timeout: float = 3.0) -> None:
        """Bind the exact permitted command and a strict wall-time ceiling."""
        self.host_id = _name(host_id, "endpoint host")
        if not command or any(type(part) is not str or not part for part in command):
            raise QualificationRefused("command must be an explicit non-empty argv tuple")
        if isinstance(timeout, bool) or not isinstance(timeout, (float, int)) or not 0 < timeout <= 30:
            raise QualificationRefused("invalid local process timeout")
        self.command = tuple(command)
        self.timeout = float(timeout)

    def exchange(self, request: Mapping[str, Any], *, max_bytes: int) -> Mapping[str, Any]:
        """Execute one bounded JSON exchange, rejecting extra output and nonzero exit."""
        raw = canonical(dict(request)) + b"\n"
        if len(raw) > 8192:
            raise QualificationRefused("probe request exceeds fixed worker ABI")
        try:
            result = subprocess.run(self.command, input=raw, capture_output=True,
                                    timeout=self.timeout, check=False)
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise QualificationRefused("process observation unavailable") from exc
        if result.returncode != 0 or result.stderr or len(result.stdout) > max_bytes or not result.stdout.endswith(b"\n"):
            raise QualificationRefused("process returned an invalid or oversized frame")
        try:
            parsed = json.loads(result.stdout)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise QualificationRefused("process returned malformed JSON") from exc
        if not isinstance(parsed, dict) or len(canonical(parsed)) + 1 != len(result.stdout):
            raise QualificationRefused("process returned noncanonical or multiple frames")
        return parsed


def _request(host_id: str, operation: str, payload: Mapping[str, Any], seed: str, number: int) -> dict[str, Any]:
    """Construct one deterministic, unique, scope-separated correlation token."""
    nonce = digest({"seed": seed, "index": number, "host": host_id, "operation": operation})[:32]
    return {"kind": REQUEST_KIND, "host": host_id, "nonce": nonce,
            "operation": operation, "payload": dict(payload)}


def _check_response(request: Mapping[str, Any], response: Mapping[str, Any]) -> None:
    """Reject unframed results, malformed identifiers, and spoofed request echoes."""
    if (not isinstance(response, Mapping) or
            set(response) != {"kind", "host", "nonce", "boot", "ok", "result", "error"} or
            response.get("kind") != RESPONSE_KIND or response.get("host") != request["host"] or
            response.get("nonce") != request["nonce"] or
            type(response.get("boot")) is not str or HEX32.fullmatch(response["boot"]) is None or
            type(response.get("ok")) is not bool):
        raise QualificationRefused("response identity or schema failed")
    if response["ok"]:
        if response["error"] is not None or not isinstance(response["result"], dict):
            raise QualificationRefused("successful response has invalid payload")
    elif response["error"] not in {"unsupported", "not_found"} or response["result"] is not None:
        raise QualificationRefused("refusal response is malformed")
    canonical(dict(response))


def _evaluation(probes: list[dict[str, Any]], *, policy: QualificationPolicy,
                separate_process_per_exchange: bool, seed: str, host_id: str) -> tuple[tuple[str, ...], dict[str, str]]:
    """Reassess every sample from raw observations, not from claimed role flags."""
    roles: set[str] = set()
    statuses: dict[str, str] = {}
    calls = 0
    stage = 0
    all_groups = ["observer", "framed_ipc", "computational_fragment", "retained_state", "restricted_dispatch_observed"]
    expected_order = [role for role in all_groups if role in policy.permitted_roles
                      for _ in range({"observer": 1, "framed_ipc": 1, "computational_fragment": 3,
                                      "retained_state": 2, "restricted_dispatch_observed": 1}[role])]
    if len(probes) != len(expected_order) or any(
            not isinstance(item, dict) or item.get("role") != role
            for item, role in zip(probes, expected_order)):
        raise QualificationRefused("probe transcript order or coverage differs from local policy")
    for role in all_groups:
        if role not in policy.permitted_roles:
            continue
        stages = [x for x in probes if x["role"] == role]
        expected_count = {"observer": 1, "framed_ipc": 1, "computational_fragment": 3,
                          "retained_state": 2, "restricted_dispatch_observed": 1}[role]
        if len(stages) != expected_count:
            raise QualificationRefused("probe transcript omits a required test")
        supported: list[bool] = []
        for item in stages:
            if set(item) != {"role", "request", "response"} or not isinstance(item["request"], dict):
                raise QualificationRefused("probe record schema mismatch")
            req, resp = item["request"], item["response"]
            if set(req) != {"kind", "host", "nonce", "operation", "payload"} or not isinstance(req["payload"], dict):
                raise QualificationRefused("request record schema mismatch")
            if req["kind"] != REQUEST_KIND:
                raise QualificationRefused("request kind mismatch")
            _check_response(req, resp)
            calls += 1
            if calls > policy.max_calls:
                raise QualificationRefused("transcript exceeds local probe quota")
            if role == "observer":
                if req["operation"] != "observe" or req["payload"] != {"word": "sab003:observe:hello"}:
                    raise QualificationRefused("unexpected observation challenge")
                good = resp["ok"] and resp["result"] == {"word_digest": digest(req["payload"]["word"])}
            elif role == "framed_ipc":
                if req["operation"] != "transfer" or req["payload"] != {"bytes_hex": bytes(range(64)).hex()}:
                    raise QualificationRefused("unexpected transport challenge")
                good = resp["ok"] and resp["result"] == req["payload"]
            elif role == "computational_fragment":
                t = (2, 19, 10**12 + 913)[stage]
                if req["operation"] != "affine_mod" or req["payload"] != {"a": 5, "c": 7, "mod": 65521, "x0": 19, "coordinate": t}:
                    raise QualificationRefused("unexpected mathematical challenge")
                good = resp["ok"] and resp["result"] == {"value": affine_expected(5, 7, 65521, 19, t)}
            elif role == "retained_state":
                key = req["payload"].get("key")
                if type(key) is not str or HEX32.fullmatch(key) is None or key != digest({
                        "seed": seed, "host": host_id, "purpose": "retention"})[:32]:
                    raise QualificationRefused("retention address malformed")
                if stage == 0:
                    if req["operation"] != "retain" or set(req["payload"]) != {"key", "value"}:
                        raise QualificationRefused("retention write challenge malformed")
                    value = req["payload"]["value"]
                    if value != {"ground": "sab003", "payload": [2, 3, 5, 7]}:
                        raise QualificationRefused("retention value altered")
                    good = resp["ok"] and resp["result"] == {"key": key, "receipt": digest(value)}
                else:
                    previous = stages[0]
                    if req["operation"] != "retrieve" or req["payload"] != {"key": previous["request"]["payload"]["key"]}:
                        raise QualificationRefused("retention read target differs from committed write")
                    good = resp["ok"] and resp["result"] == {"key": key, "value": previous["request"]["payload"]["value"]}
                    if good and (not separate_process_per_exchange or
                                 resp["boot"] == previous["response"]["boot"]):
                        raise QualificationRefused("claim of post-restart persistence lacks separate process evidence")
            else:
                if req["operation"] != "execute_source" or req["payload"] != {"source": "no dynamic dispatch"}:
                    raise QualificationRefused("unexpected unsupported opcode challenge")
                good = not resp["ok"] and resp["error"] == "unsupported"
            if resp["ok"] and not good:
                raise QualificationRefused(f"{role} returned a contradictory success")
            supported.append(bool(good))
            stage = (stage + 1) % expected_count
        if all(supported):
            roles.add(role)
            statuses[role] = "verified_on_probes"
        elif role == "retained_state" and len(supported) == 2 and supported[0] and not supported[1]:
            statuses[role] = "not_recovered_after_restart"
        elif not any(supported):
            statuses[role] = "unavailable_or_refused"
        else:
            raise QualificationRefused(f"partial inconsistent {role} behavior")
    return tuple(sorted(roles)), statuses


@dataclass(frozen=True)
class QualificationReport:
    """Content-bound finite-evidence runtime profile, without a grant of authority."""

    payload: dict[str, Any]

    @property
    def fingerprint(self) -> str:
        """Expose the stable digest of the complete qualification artifact."""
        return str(self.payload["report_digest"])

    def to_resource(self, *, cost: int = 3) -> Any:
        """Advertise only probed transitions into SAB-001, never bind code or capabilities."""
        from .substrate_bootstrap import OperationOffer, ResourceObservation
        _integer(cost, "advertised cost", 1, 100000)
        roles = set(self.payload["verified_roles"])
        offers = ((OperationOffer("affine_mod", "affine_request", "affine_result", cost),)
                  if "computational_fragment" in roles else ())
        return ResourceObservation(self.payload["host"], "qualified-portable-environment",
                                   self.payload["coordinate"], self.payload["expires_at"],
                                   self.payload["observer"], self.fingerprint, offers)


def qualify(endpoint: QualificationEndpoint, policy: QualificationPolicy, *, coordinate: int,
            seed: str = "sab003-public-test-seed") -> QualificationReport:
    """Run permitted bounded active probes and assemble a separately recheckable profile."""
    _integer(coordinate, "qualification coordinate")
    if (endpoint.host_id not in policy.allowed_hosts or coordinate > policy.expires_at or
            type(seed) is not str or not 8 <= len(seed) <= 128):
        raise QualificationRefused("host, lease or challenge seed is not locally authorized")
    probes: list[dict[str, Any]] = []
    needed = sum(n for role, n in (("observer", 1), ("framed_ipc", 1),
                                  ("computational_fragment", 3), ("retained_state", 2),
                                  ("restricted_dispatch_observed", 1))
                 if role in policy.permitted_roles)
    if needed > policy.max_calls:
        raise QualificationRefused("probe quota cannot cover the required qualification schedule")

    def send(role: str, operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Enforce the exact caller-side request quota and observed response envelope."""
        if len(probes) >= policy.max_calls:
            raise QualificationRefused("probe quota exhausted")
        req = _request(endpoint.host_id, operation, payload, seed, len(probes))
        reply = endpoint.exchange(req, max_bytes=policy.max_response_bytes)
        _check_response(req, reply)
        if len(canonical(reply)) + 1 > policy.max_response_bytes:
            raise QualificationRefused("response exceeded local bound")
        probes.append({"role": role, "request": req, "response": json.loads(canonical(reply))})
        return dict(reply)

    if "observer" in policy.permitted_roles:
        send("observer", "observe", {"word": "sab003:observe:hello"})
    if "framed_ipc" in policy.permitted_roles:
        send("framed_ipc", "transfer", {"bytes_hex": bytes(range(64)).hex()})
    if "computational_fragment" in policy.permitted_roles:
        for t in (2, 19, 10**12 + 913):
            send("computational_fragment", "affine_mod", {"a": 5, "c": 7, "mod": 65521,
                                                          "x0": 19, "coordinate": t})
    if "retained_state" in policy.permitted_roles:
        key = digest({"seed": seed, "host": endpoint.host_id, "purpose": "retention"})[:32]
        value = {"ground": "sab003", "payload": [2, 3, 5, 7]}
        send("retained_state", "retain", {"key": key, "value": value})
        send("retained_state", "retrieve", {"key": key})
    if "restricted_dispatch_observed" in policy.permitted_roles:
        send("restricted_dispatch_observed", "execute_source", {"source": "no dynamic dispatch"})

    roles, statuses = _evaluation(probes, policy=policy, seed=seed, host_id=endpoint.host_id,
                                  separate_process_per_exchange=endpoint.separate_process_per_exchange)
    if "observer" not in roles:
        raise QualificationRefused("even the minimum host observation was not reproduced")
    payload = {"kind": REPORT_KIND, "host": endpoint.host_id, "observer": policy.observer_id,
               "coordinate": coordinate, "expires_at": policy.expires_at,
               "policy_digest": policy.fingerprint, "seed": seed,
               "separate_process_per_exchange": endpoint.separate_process_per_exchange,
               "verified_roles": list(roles), "statuses": statuses, "probes": probes,
               "evidence_grade": "finite_behavioral_witness_only",
               "full_ecpu_runtime_verified": False, "hardware_attested": False,
               "local_hypervisor_permission_granted": False}
    payload["report_digest"] = digest(payload)
    return QualificationReport(payload)


def verify_report(report: QualificationReport | Mapping[str, Any], policy: QualificationPolicy,
                  *, coordinate: int) -> bool:
    """Recheck every visible probe and the claims, without trusting advertised roles."""
    value = report.payload if isinstance(report, QualificationReport) else report
    if not isinstance(value, Mapping):
        raise QualificationRefused("qualification report must be an object")
    expected_fields = {"kind", "host", "observer", "coordinate", "expires_at", "policy_digest",
                       "seed", "separate_process_per_exchange", "verified_roles", "statuses", "probes",
                       "evidence_grade", "full_ecpu_runtime_verified", "hardware_attested",
                       "local_hypervisor_permission_granted", "report_digest"}
    if set(value) != expected_fields or value["kind"] != REPORT_KIND:
        raise QualificationRefused("qualification report schema mismatch")
    report_digest = value["report_digest"]
    if type(report_digest) is not str or HEX64.fullmatch(report_digest) is None:
        raise QualificationRefused("report digest field invalid")
    body = dict(value)
    body.pop("report_digest")
    if digest(body) != report_digest:
        raise QualificationRefused("qualification report digest mismatch")
    if (value["host"] not in policy.allowed_hosts or value["observer"] != policy.observer_id or
            value["policy_digest"] != policy.fingerprint or value["expires_at"] != policy.expires_at or
            value["coordinate"] != coordinate or coordinate > policy.expires_at or
            value["evidence_grade"] != "finite_behavioral_witness_only" or
            value["hardware_attested"] is not False or
            value["local_hypervisor_permission_granted"] is not False or
            value["full_ecpu_runtime_verified"] is not False or
            type(value["separate_process_per_exchange"]) is not bool):
        raise QualificationRefused("qualification policy, lease or evidence tier mismatch")
    probes = value["probes"]
    if type(probes) is not list or len(probes) > policy.max_calls:
        raise QualificationRefused("qualification probes malformed")
    seed = value["seed"]
    if type(seed) is not str or not 8 <= len(seed) <= 128:
        raise QualificationRefused("report challenge seed malformed")
    for index, record in enumerate(probes):
        if not isinstance(record, Mapping) or not isinstance(record.get("request"), Mapping):
            raise QualificationRefused("probe record is not typed")
        if record.get("request") != _request(value["host"], record.get("request", {}).get("operation"),
                                              record.get("request", {}).get("payload", {}), seed, index):
            raise QualificationRefused("probe correlation token or contents altered")
        if record.get("request", {}).get("host") != value["host"]:
            raise QualificationRefused("transcript refers to another host")
    roles, statuses = _evaluation(probes, policy=policy, seed=seed, host_id=value["host"],
                                  separate_process_per_exchange=value["separate_process_per_exchange"])
    if value["verified_roles"] != list(roles) or value["statuses"] != statuses or "observer" not in roles:
        raise QualificationRefused("claimed host profile contradicts its observations")
    return True