"""Finite, intention-relative observation sufficiency for E-CPU Grounds.

A finite Ground projection is a *locally supplied model*, not proof that its
state set or sensor readings are true. Planning is advisory. Execution authority,
measurement authentication, and Ground admission remain with existing E-CPU
components. This module never runs or dispatches a remote sensor.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import itertools
import json
import re
from typing import Any, Mapping, Sequence


SCHEMA = "mailcpu.intention-sufficiency.v1"
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_SAFE_INT = (1 << 53) - 1  # Portable JSON integer domain, not arbitrary mathematical precision.
_MAX_STATES = 256
_MAX_CAPABILITIES = 12


class SufficiencyRefused(ValueError):
    """The bounded model, current evidence, or measurement request is invalid."""


def _name(value: Any, label: str) -> str:
    """Mathematics: the safe identifier predicate accepts exactly one bounded name alphabet."""
    if type(value) is not str or _NAME.fullmatch(value) is None:
        raise SufficiencyRefused(f"invalid {label}")
    return value


def _hash(value: Any, label: str) -> str:
    """Mathematics: the digest predicate requires a 256-bit lowercase hexadecimal identity."""
    if type(value) is not str or _HEX.fullmatch(value) is None:
        raise SufficiencyRefused(f"invalid {label} digest")
    return value


def _json_normalize(value: Any) -> Any:
    """Mathematics: Snapshot portable, exact JSON: no float, duplicate Python key, or unsafe int."""
    if value is None or type(value) is bool:
        return value
    if type(value) is int and -_SAFE_INT <= value <= _SAFE_INT:
        return value
    if type(value) is str:
        try:
            value.encode("utf-8")  # reject unpaired surrogates
        except UnicodeError as exc:
            raise SufficiencyRefused("invalid Unicode in value") from exc
        return value
    if type(value) in (list, tuple):
        return [_json_normalize(part) for part in value]
    if type(value) is dict:
        if any(type(k) is not str for k in value):
            raise SufficiencyRefused("JSON mapping keys must be strings")
        return {_json_normalize(k): _json_normalize(v) for k, v in value.items()}
    raise SufficiencyRefused("expected exact finite JSON (encode floats or huge ints as strings)")


def _bytes(value: Any) -> bytes:
    """Mathematics: canonicalize the exact JSON algebra into sorted-key UTF-8 bytes."""
    return json.dumps(_json_normalize(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _fingerprint(value: Any) -> str:
    """Mathematics: E-CPU's Python sorted-key JSON digest profile, *not* RFC 8785 JCS."""
    return hashlib.sha256(_bytes(value)).hexdigest()


def _decode(raw: bytes) -> Any:
    """Mathematics: invert canonical JSON encoding to its finite value."""
    return json.loads(raw)


@dataclass(frozen=True)
class FiniteState:
    """One public Ground-model row. Values are frozen at construction time."""

    state_id: str
    public_json: bytes
    target_json: bytes
    feature_json: tuple[tuple[str, bytes], ...]

    @classmethod
    def create(cls, state_id: str, public: Any, target: Any,
               features: Mapping[str, Any]) -> "FiniteState":
        """Mathematics: snapshot one finite-state row with canonical feature values."""
        _name(state_id, "state id")
        if type(features) is not dict:
            raise SufficiencyRefused("finite state features must be a mapping")
        if len(features) > _MAX_CAPABILITIES:
            raise SufficiencyRefused("finite state exceeds feature bound")
        pairs = tuple(sorted((_name(k, "feature"), _bytes(v)) for k, v in features.items()))
        return cls(state_id, _bytes(public), _bytes(target), pairs)

    def __post_init__(self) -> None:
        """Mathematics: enforce the declared finite-model or capability invariants."""
        _name(self.state_id, "state id")
        if type(self.public_json) is not bytes or type(self.target_json) is not bytes:
            raise SufficiencyRefused("finite state requires exact encoded JSON")
        if _bytes(_decode(self.public_json)) != self.public_json or _bytes(_decode(self.target_json)) != self.target_json:
            raise SufficiencyRefused("state JSON is not canonical")
        if not isinstance(self.feature_json, tuple):
            raise SufficiencyRefused("missing feature values")
        if len(self.feature_json) > _MAX_CAPABILITIES:
            raise SufficiencyRefused("too many feature values")
        prev = ""
        for key, value in self.feature_json:
            _name(key, "feature")
            if key <= prev or type(value) is not bytes or _bytes(_decode(value)) != value:
                raise SufficiencyRefused("invalid or unordered feature entry")
            prev = key

    @property
    def features(self) -> dict[str, bytes]:
        """Mathematics: project immutable ordered features into a detached lookup."""
        return dict(self.feature_json)

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize this finite contract into its versioned JSON projection."""
        return {
            "state_id": self.state_id, "public": _decode(self.public_json),
            "target": _decode(self.target_json),
            "features": {k: _decode(v) for k, v in self.feature_json},
        }


@dataclass(frozen=True)
class FiniteGround:
    """Exact finite observer/target table under pinned E-CPU semantic identities.

    Digests identify the Ground, two projection contracts, and the context; they
    do not independently validate the state table against a real environment.
    """

    ground_digest: str
    public_contract_digest: str
    intention_contract_digest: str
    context_digest: str
    states: tuple[FiniteState, ...]

    def __post_init__(self) -> None:
        """Mathematics: enforce the declared finite-model or capability invariants."""
        for k in ("ground_digest", "public_contract_digest", "intention_contract_digest", "context_digest"):
            _hash(getattr(self, k), k)
        if type(self.states) is not tuple or not 1 <= len(self.states) <= _MAX_STATES:
            raise SufficiencyRefused("finite Ground requires 1..256 states")
        if any(not isinstance(row, FiniteState) for row in self.states):
            raise SufficiencyRefused("Ground rows must be FiniteState")
        if tuple(sorted(self.states, key=lambda r: r.state_id)) != self.states:
            raise SufficiencyRefused("states must be sorted by unique state id")
        if len({r.state_id for r in self.states}) != len(self.states):
            raise SufficiencyRefused("duplicate state id")
        feature_set = tuple(k for k, _ in self.states[0].feature_json)
        if any(tuple(k for k, _ in row.feature_json) != feature_set for row in self.states):
            raise SufficiencyRefused("every state must define the same feature catalogue")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize this finite contract into its versioned JSON projection."""
        return {
            "schema": SCHEMA + ".ground", "ground_digest": self.ground_digest,
            "public_contract_digest": self.public_contract_digest,
            "intention_contract_digest": self.intention_contract_digest,
            "context_digest": self.context_digest,
            "states": [r.to_dict() for r in self.states],
        }

    @property
    def digest(self) -> str:
        """Mathematics: compute the content identity of this exact model."""
        return _fingerprint(self.to_dict())


@dataclass(frozen=True)
class MeasurementCapability:
    """Receiver-declared offer; only the receiver can authorize and bind it."""

    feature_id: str
    contract_digest: str
    provider_id: str
    cost_units: int  # symbolic: not an assertion of measured latency or energy

    def __post_init__(self) -> None:
        """Mathematics: enforce the declared finite-model or capability invariants."""
        _name(self.feature_id, "feature id")
        _hash(self.contract_digest, "measurement contract")
        _name(self.provider_id, "measurement provider")
        if type(self.cost_units) is not int or not 0 <= self.cost_units <= _SAFE_INT:
            raise SufficiencyRefused("cost_units must be a portable nonnegative integer")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize this finite contract into its versioned JSON projection."""
        return {"feature_id": self.feature_id, "contract_digest": self.contract_digest,
                "provider_id": self.provider_id, "cost_units": self.cost_units}


def _offers(model: FiniteGround, offers: Sequence[MeasurementCapability]) -> tuple[MeasurementCapability, ...]:
    """Mathematics: accept a bounded, unique, known receiver capability catalogue."""
    if type(offers) not in (list, tuple) or len(offers) > _MAX_CAPABILITIES:
        raise SufficiencyRefused("capability catalogue exceeds bound")
    if any(not isinstance(c, MeasurementCapability) for c in offers):
        raise SufficiencyRefused("invalid measurement capability")
    result = tuple(sorted(offers, key=lambda c: c.feature_id))
    names = tuple(c.feature_id for c in result)
    if len(set(names)) != len(names) or not set(names).issubset(model.states[0].features):
        raise SufficiencyRefused("duplicate or unknown feature in capability catalogue")
    return result


def _seal(body: dict[str, Any], field: str) -> dict[str, Any]:
    """Mathematics: derive a report identity from the complete report body."""
    result = dict(body)
    result[field] = _fingerprint(body)
    return result


def _witness(states: Sequence[FiniteState], chosen: tuple[str, ...]) -> tuple[bool, tuple[str, str] | None]:
    """Mathematics: find a pair in one observation fiber with different target values."""
    seen: dict[tuple[bytes, ...], FiniteState] = {}
    for row in states:
        key = tuple(row.features[name] for name in chosen)
        earlier = seen.get(key)
        if earlier is not None and earlier.target_json != row.target_json:
            return False, (earlier.state_id, row.state_id)
        seen.setdefault(key, row)
    return True, None


def plan_sufficiency(model: FiniteGround, public_value: Any,
                     offers: Sequence[MeasurementCapability],
                     authority_digest: str) -> dict[str, Any]:
    """Mathematics: Exact minimum-cost sufficient feature set on one observed fiber.

    Minimize (declared total cost, number of features, feature IDs). Nothing
    about the plan grants permission to invoke the selected providers.
    """
    if not isinstance(model, FiniteGround):
        raise SufficiencyRefused("expected FiniteGround")
    _hash(authority_digest, "receiver authority")
    catalogue = _offers(model, offers)
    observed = _bytes(public_value)
    candidates = tuple(row for row in model.states if row.public_json == observed)
    if not candidates:
        raise SufficiencyRefused("public observation is outside the admitted finite Ground")
    best: tuple[int, int, tuple[str, ...]] | None = None
    for count in range(len(catalogue) + 1):
        for subset in itertools.combinations(catalogue, count):
            ids = tuple(item.feature_id for item in subset)
            cost = sum(item.cost_units for item in subset)
            if cost > _SAFE_INT:
                continue  # No representable declared total under the wire profile.
            if best is not None and (cost, count, ids) >= best:
                continue
            valid, _ = _witness(candidates, ids)
            if valid:
                best = (cost, count, ids)
    if best is None:
        _, conflicting = _witness(candidates, tuple(item.feature_id for item in catalogue))
        assert conflicting is not None
        status, selected, cost, result = "REFUSE", (), 0, None
    else:
        cost, _, selected = best
        status = "READY" if not selected else "MEASURE"
        conflicting = None
        result = _decode(candidates[0].target_json) if status == "READY" else None
    return _seal({
        "schema": SCHEMA + ".plan", "model_digest": model.digest,
        "authority_digest": authority_digest,
        "public_digest": _fingerprint(public_value),
        "catalogue_digest": _fingerprint([x.to_dict() for x in catalogue]),
        "candidate_count": len(candidates), "status": status,
        "selected_features": list(selected), "declared_cost_units": cost,
        "ready_result": result,
        "counterexample_state_ids": list(conflicting) if conflicting is not None else None,
    }, "plan_digest")


def verify_sufficiency_plan(plan: Mapping[str, Any], model: FiniteGround,
                            public_value: Any, offers: Sequence[MeasurementCapability],
                            authority_digest: str) -> None:
    """Mathematics: Replan from independently supplied pinned model and current policy."""
    if type(plan) is not dict or plan != plan_sufficiency(model, public_value, offers, authority_digest):
        raise SufficiencyRefused("plan is stale, modified, or not minimum sufficient")


def resolve_sufficiency(model: FiniteGround, public_value: Any,
                        offers: Sequence[MeasurementCapability], authority_digest: str,
                        plan: Mapping[str, Any], measured: Mapping[str, Any],
                        receipt_digest: str | None = None) -> dict[str, Any]:
    """Mathematics: Resolve only from complete readings under a freshly checked plan.

    A receipt *digest* does not authenticate its issuer. The caller must admit
    the receiver-owned measurement receipt before invoking this function.
    """
    verify_sufficiency_plan(plan, model, public_value, offers, authority_digest)
    if plan["status"] == "REFUSE":
        raise SufficiencyRefused("intention cannot be determined with permitted observations")
    selected = tuple(plan["selected_features"])
    if type(measured) is not dict or set(measured) != set(selected):
        raise SufficiencyRefused("missing, extra, or forbidden measurement")
    if selected:
        _hash(receipt_digest, "measurement receipt")
    elif receipt_digest is not None:
        raise SufficiencyRefused("READY requires no measurement receipt")
    encoded = {name: _bytes(value) for name, value in measured.items()}
    candidates = tuple(row for row in model.states
                       if row.public_json == _bytes(public_value)
                       and all(row.features[name] == value for name, value in encoded.items()))
    if not candidates:
        raise SufficiencyRefused("measurement contradicts the admitted finite Ground")
    possible = {row.target_json for row in candidates}
    if len(possible) != 1:
        raise SufficiencyRefused("requested intention remains ambiguous")
    result = _decode(next(iter(possible)))
    return _seal({
        "schema": SCHEMA + ".resolution", "model_digest": model.digest,
        "plan_digest": plan["plan_digest"], "authority_digest": authority_digest,
        "measurement_digest": _fingerprint({k: _decode(v) for k, v in sorted(encoded.items())}),
        "receipt_digest": receipt_digest, "remaining_candidates": len(candidates),
        "status": "RESOLVED_WITHOUT_MEASUREMENT" if not selected else "RESOLVED_AFTER_MEASUREMENT",
        "result": result,
    }, "resolution_digest")


def verify_sufficiency_resolution(resolution: Mapping[str, Any], model: FiniteGround,
                                  public_value: Any, offers: Sequence[MeasurementCapability],
                                  authority_digest: str, plan: Mapping[str, Any],
                                  measured: Mapping[str, Any], receipt_digest: str | None = None) -> None:
    """Mathematics: Reconstruct the complete result without trusting the received report."""
    expected = resolve_sufficiency(model, public_value, offers, authority_digest,
                                   plan, measured, receipt_digest)
    if type(resolution) is not dict or resolution != expected:
        raise SufficiencyRefused("resolution differs from independently reconstructed answer")
