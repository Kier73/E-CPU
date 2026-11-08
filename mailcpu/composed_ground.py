"""Compositional Virtual Ground projections over independently generated state components.

The module combines separately admitted Structural Memory generators into one
typed structured state view. Each component binds its own structural
representation, semantic field path, scalar encoding, law revision, and read
receipt. The aggregate is a Virtual Ground projection anchored to an exact
system Ground; it is not silently promoted to a HeadlessOS checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Mapping, Sequence

from .seed import SystemIdentity
from .semantic_translation import RepresentationRef, canonical_value_digest, structural_memory_spec_representation_ref
from .structural_memory import StructuralMemoryError, StructuralMemoryReadReceipt, StructuralMemoryRegistry
from .temporal import SchedulerReading
from .virtual_layer import VirtualGroundRef, VirtualStructuralMemoryRef
from .observer_orbit import (
    ContextualOrbitAddress,
    ObserverOrbitError,
    VirtualGroundProjection,
    contextual_orbit_context,
)


class ComposedGroundError(ValueError):
    """Mathematics: a composed state schema, component binding, or evidence projection is invalid."""


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_FORWARD_COMPLEXITY = {
    "int": "O(1)",
    "fgraph": "O(1)",
    "lcg": "O(log n)",
    "gf2": "O(log n) for fixed recurrence order",
}
_TEMPLATE_TYPE = "mailcpu.virtual-state-template"


def _identifier(value: Any, label: str) -> str:
    """Mathematics: constrain component and schema names to a stable bounded identifier alphabet."""
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ComposedGroundError(f"{label} must be a safe 1-128 character identifier")
    return value


def _canonical_json(value: Any, label: str) -> str:
    """Mathematics: encode finite JSON with sorted keys and compact separators."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ComposedGroundError(f"{label} must be finite canonical JSON") from exc


def _clone_json(value: Any, label: str) -> Any:
    """Mathematics: detach a JSON value by applying canonical encode/decode."""
    return json.loads(_canonical_json(value, label))


def _path(value: Sequence[str]) -> tuple[str, ...]:
    """Mathematics: normalize a non-empty sequence of JSON object-key coordinates."""
    if not isinstance(value, (tuple, list)) or not value:
        raise ComposedGroundError("field_path must be a non-empty sequence")
    path = tuple(value)
    if any(not isinstance(item, str) or not item for item in path):
        raise ComposedGroundError("field_path entries must be non-empty object keys")
    return path


def _template_ref(template: Mapping[str, Any]) -> RepresentationRef:
    """Mathematics: identify one exact virtual-state template independently of its generated component values."""
    return RepresentationRef.from_payload(_TEMPLATE_TYPE, 1, template)


def _read_path(state: Mapping[str, Any], field_path: tuple[str, ...]) -> Any:
    """Mathematics: resolve a nested object path without coercing its terminal value."""
    current: Any = state
    for part in field_path:
        if not isinstance(current, Mapping) or part not in current:
            raise ComposedGroundError(f"template does not contain field path {'.'.join(field_path)!r}")
        current = current[part]
    return current


def _write_path(state: dict[str, Any], field_path: tuple[str, ...], value: int) -> None:
    """Mathematics: replace one existing scalar leaf while preserving all unrelated template structure."""
    current: Any = state
    for part in field_path[:-1]:
        if not isinstance(current, dict) or part not in current or not isinstance(current[part], dict):
            raise ComposedGroundError(f"template parent path does not exist: {'.'.join(field_path)!r}")
        current = current[part]
    leaf = field_path[-1]
    if not isinstance(current, dict) or leaf not in current:
        raise ComposedGroundError(f"template leaf does not exist: {'.'.join(field_path)!r}")
    if isinstance(current[leaf], (dict, list)):
        raise ComposedGroundError(f"component field must be a scalar leaf: {'.'.join(field_path)!r}")
    current[leaf] = value


def _validate_scalar(value: Any, value_kind: str) -> None:
    """Mathematics: enforce the declared integer, byte, or bit subset of the scalar value domain."""
    if type(value) is not int:
        raise ComposedGroundError("Structural Memory component output must be a strict integer")
    if value_kind == "byte" and not 0 <= value <= 255:
        raise ComposedGroundError("byte component value must lie in [0, 255]")
    if value_kind == "bit" and value not in (0, 1):
        raise ComposedGroundError("bit component value must be 0 or 1")
    if value_kind not in {"integer", "byte", "bit"}:
        raise ComposedGroundError(f"unsupported component scalar kind {value_kind!r}")


def composed_component_context(
    system_identity: SystemIdentity,
    base_ground: VirtualGroundRef,
    computational_ground: RepresentationRef,
    state_schema: RepresentationRef,
    template: Mapping[str, Any],
    *,
    scheduler_id: str,
    component_id: str,
    field_path: Sequence[str],
    representation: RepresentationRef,
    value_kind: str = "integer",
    extensions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the exact Structural Memory context for one field in a composed state.

    Mathematics:
    Context = (system, base Ground, Computational Ground, scheduler,
    state schema, template digest, component identity, field path,
    component representation, scalar encoding, declared extensions).
    """
    _identifier(component_id, "component_id")
    normalized_path = _path(field_path)
    if not isinstance(state_schema, RepresentationRef) or not isinstance(representation, RepresentationRef):
        raise ComposedGroundError("state_schema and representation must be RepresentationRef values")
    if value_kind not in {"integer", "byte", "bit"}:
        raise ComposedGroundError(f"unsupported component scalar kind {value_kind!r}")
    if not isinstance(template, Mapping):
        raise ComposedGroundError("state template must be an object")
    _read_path(template, normalized_path)
    user_extensions = {} if extensions is None else _clone_json(dict(extensions), "component extensions")
    if not isinstance(user_extensions, dict):
        raise ComposedGroundError("component extensions must be an object")
    component_extension = {
        "role": "mailcpu.composed-state-component.v1",
        "state_schema": state_schema.to_dict(),
        "template_ref": _template_ref(template).to_dict(),
        "component_id": component_id,
        "field_path": list(normalized_path),
        "representation": representation.to_dict(),
        "value_kind": value_kind,
        "extensions": user_extensions,
    }
    return contextual_orbit_context(
        system_identity,
        base_ground,
        computational_ground,
        scheduler_id=scheduler_id,
        extensions=component_extension,
    )


@dataclass(frozen=True)
class ComposedComponentAddress:
    """One independently generated component and its structural field destination."""

    component_id: str
    field_path: tuple[str, ...]
    representation: RepresentationRef
    value_kind: str
    orbit_address: ContextualOrbitAddress

    def __post_init__(self) -> None:
        """Mathematics: bind a unique component identity to a typed representation and contextual orbit address."""
        _identifier(self.component_id, "component_id")
        object.__setattr__(self, "field_path", _path(self.field_path))
        if not isinstance(self.representation, RepresentationRef):
            raise ComposedGroundError("component representation must be a RepresentationRef")
        if not isinstance(self.orbit_address, ContextualOrbitAddress):
            raise ComposedGroundError("component orbit_address must be a ContextualOrbitAddress")
        if self.value_kind not in {"integer", "byte", "bit"}:
            raise ComposedGroundError("component value_kind must be integer, byte, or bit")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize component meaning, field location, encoding, and its pinned orbit address."""
        return {
            "component_id": self.component_id,
            "field_path": list(self.field_path),
            "representation": self.representation.to_dict(),
            "value_kind": self.value_kind,
            "orbit_address": self.orbit_address.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ComposedComponentAddress":
        """Mathematics: reconstruct and revalidate one exact composed component address."""
        expected = {"component_id", "field_path", "representation", "value_kind", "orbit_address"}
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ComposedGroundError("composed component address fields are invalid")
        return cls(
            component_id=payload["component_id"],
            field_path=tuple(payload["field_path"]),
            representation=RepresentationRef.from_dict(payload["representation"]),
            value_kind=payload["value_kind"],
            orbit_address=ContextualOrbitAddress.from_dict(payload["orbit_address"]),
        )


@dataclass(frozen=True)
class ComposedVirtualGroundAddress:
    """Common system/time address plus a set of independently generated state components."""

    system_identity: SystemIdentity
    base_ground: VirtualGroundRef
    computational_ground: RepresentationRef
    coordinate: SchedulerReading
    state_schema: RepresentationRef
    template_json: str
    components: tuple[ComposedComponentAddress, ...]
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Mathematics: require every component to share one system, base Ground, interpretation, scheduler coordinate, and template."""
        if not isinstance(self.system_identity, SystemIdentity):
            raise ComposedGroundError("system_identity must be a SystemIdentity")
        if not isinstance(self.base_ground, VirtualGroundRef):
            raise ComposedGroundError("base_ground must be a VirtualGroundRef")
        if not isinstance(self.computational_ground, RepresentationRef):
            raise ComposedGroundError("computational_ground must be a RepresentationRef")
        if not isinstance(self.coordinate, SchedulerReading):
            raise ComposedGroundError("coordinate must be a SchedulerReading")
        if not isinstance(self.state_schema, RepresentationRef):
            raise ComposedGroundError("state_schema must be a RepresentationRef")
        if self.coordinate.tick < self.base_ground.coordinate:
            raise ComposedGroundError("composed coordinate precedes the base Virtual Ground")
        try:
            template = json.loads(self.template_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ComposedGroundError("template_json is malformed") from exc
        if not isinstance(template, dict) or _canonical_json(template, "state template") != self.template_json:
            raise ComposedGroundError("template_json must be a canonical JSON object")
        if not isinstance(self.components, (tuple, list)) or not self.components:
            raise ComposedGroundError("composed Virtual Ground requires at least one component")
        components = tuple(self.components)
        if any(not isinstance(item, ComposedComponentAddress) for item in components):
            raise ComposedGroundError("components must contain ComposedComponentAddress values")
        components = tuple(sorted(components, key=lambda item: item.component_id))
        ids = [item.component_id for item in components]
        if len(set(ids)) != len(ids):
            raise ComposedGroundError("component identities must be unique")
        paths = [item.field_path for item in components]
        for index, left in enumerate(paths):
            for right in paths[index + 1:]:
                if left == right or left == right[:len(left)] or right == left[:len(right)]:
                    raise ComposedGroundError("component field paths must be disjoint and non-overlapping")
        if len({(item.type_id, item.schema_version, item.content_digest) for item in (self.state_schema,)}) != 1:
            raise ComposedGroundError("state schema identity is invalid")
        offset = self.coordinate.tick - self.base_ground.coordinate
        user_extensions = _clone_json(dict(self.extensions), "composed address extensions")
        if not isinstance(user_extensions, dict):
            raise ComposedGroundError("composed address extensions must be an object")
        for component in components:
            address = component.orbit_address
            if (
                address.system_identity != self.system_identity
                or address.base_ground != self.base_ground
                or address.computational_ground != self.computational_ground
                or address.coordinate != self.coordinate
                or address.orbit_offset != offset
                or address.structural_memory.coordinate != offset
            ):
                raise ComposedGroundError(f"component {component.component_id!r} does not share the composed system/time address")
            expected_context = composed_component_context(
                self.system_identity,
                self.base_ground,
                self.computational_ground,
                self.state_schema,
                template,
                scheduler_id=self.coordinate.scheduler_id,
                component_id=component.component_id,
                field_path=component.field_path,
                representation=component.representation,
                value_kind=component.value_kind,
                extensions=user_extensions,
            )
            if _clone_json(dict(address.structural_memory.context), "component memory context") != expected_context:
                raise ComposedGroundError(f"component {component.component_id!r} Structural Memory context is not bound to this composition")
            _read_path(template, component.field_path)
        object.__setattr__(self, "components", components)
        object.__setattr__(self, "extensions", user_extensions)

    @property
    def template(self) -> dict[str, Any]:
        """Mathematics: return a detached copy of the immutable JSON state template."""
        return json.loads(self.template_json)

    @property
    def template_ref(self) -> RepresentationRef:
        """Mathematics: compute the content-addressed identity of the exact state template."""
        return _template_ref(self.template)

    @property
    def orbit_offset(self) -> int:
        """Mathematics: compute the common scheduler coordinate relative to the pinned base Ground."""
        return self.coordinate.tick - self.base_ground.coordinate

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the full common address and every independently pinned component."""
        return {
            "schema": "mailcpu.composed-virtual-ground-address.v1",
            "system_identity": self.system_identity.snapshot(),
            "base_ground": self.base_ground.to_dict(),
            "computational_ground": self.computational_ground.to_dict(),
            "coordinate": self.coordinate.to_dict(),
            "state_schema": self.state_schema.to_dict(),
            "template_json": self.template_json,
            "components": [item.to_dict() for item in self.components],
            "extensions": _clone_json(self.extensions, "composed address extensions"),
            "orbit_offset": self.orbit_offset,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ComposedVirtualGroundAddress":
        """Mathematics: reconstruct the composed address only when its exact schema and relative coordinate agree."""
        expected = {
            "schema", "system_identity", "base_ground", "computational_ground",
            "coordinate", "state_schema", "template_json", "components", "extensions",
            "orbit_offset",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ComposedGroundError("composed Virtual Ground address fields are invalid")
        if payload["schema"] != "mailcpu.composed-virtual-ground-address.v1":
            raise ComposedGroundError("unsupported composed Virtual Ground address schema")
        coordinate = payload["coordinate"]
        if not isinstance(coordinate, Mapping) or set(coordinate) != {"scheduler_id", "tick"}:
            raise ComposedGroundError("composed scheduler coordinate fields are invalid")
        result = cls(
            system_identity=SystemIdentity.from_snapshot(payload["system_identity"]),
            base_ground=VirtualGroundRef.from_dict(payload["base_ground"]),
            computational_ground=RepresentationRef.from_dict(payload["computational_ground"]),
            coordinate=SchedulerReading(coordinate["scheduler_id"], coordinate["tick"]),
            state_schema=RepresentationRef.from_dict(payload["state_schema"]),
            template_json=payload["template_json"],
            components=tuple(ComposedComponentAddress.from_dict(item) for item in payload["components"]),
            extensions=payload["extensions"],
        )
        if payload["orbit_offset"] != result.orbit_offset:
            raise ComposedGroundError("stored composed orbit offset differs from its typed coordinates")
        return result

    @property
    def digest(self) -> str:
        """Mathematics: hash the complete canonical identity of the composed Virtual Ground request."""
        return canonical_value_digest(self.to_dict())


@dataclass(frozen=True)
class ComposedComponentProjection:
    """One component's generated scalar, semantic representation, and Structural Memory evidence."""

    address: ComposedComponentAddress
    projection: VirtualGroundProjection

    def __post_init__(self) -> None:
        """Mathematics: require the component value projection to match its exact address and semantic scope."""
        if not isinstance(self.address, ComposedComponentAddress):
            raise ComposedGroundError("component projection address is invalid")
        if not isinstance(self.projection, VirtualGroundProjection):
            raise ComposedGroundError("component projection must be a VirtualGroundProjection")
        orbit = self.address.orbit_address
        if (
            self.projection.system_identity != orbit.system_identity
            or self.projection.base_ground != orbit.base_ground
            or self.projection.computational_ground != orbit.computational_ground
            or self.projection.coordinate != orbit.coordinate
            or self.projection.orbit_offset != orbit.orbit_offset
            or self.projection.structural_memory != orbit.structural_memory
        ):
            raise ComposedGroundError("component projection does not match its pinned orbit address")
        _validate_scalar(self.projection.value, self.address.value_kind)

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize component semantics separately from its generated value and read receipt."""
        return {"address": self.address.to_dict(), "projection": self.projection.to_dict()}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ComposedComponentProjection":
        """Mathematics: reconstruct one component projection and revalidate its memory receipt."""
        if not isinstance(payload, Mapping) or set(payload) != {"address", "projection"}:
            raise ComposedGroundError("composed component projection fields are invalid")
        return cls(
            ComposedComponentAddress.from_dict(payload["address"]),
            VirtualGroundProjection.from_dict(payload["projection"]),
        )


@dataclass(frozen=True)
class ComposedVirtualGroundProjection:
    """Structured multi-component state projection under one exact base system Ground."""

    address_digest: str
    system_identity: SystemIdentity
    base_ground: VirtualGroundRef
    computational_ground: RepresentationRef
    coordinate: SchedulerReading
    state_schema: RepresentationRef
    template_json: str
    components: tuple[ComposedComponentProjection, ...]
    state_json: str
    state_digest: str

    def __post_init__(self) -> None:
        """Mathematics: verify component evidence, reconstruct the assembled state, and bind the resulting digest."""
        if not isinstance(self.address_digest, str) or len(self.address_digest) != 64:
            raise ComposedGroundError("address_digest must be a SHA-256 digest")
        if not isinstance(self.system_identity, SystemIdentity) or not isinstance(self.base_ground, VirtualGroundRef):
            raise ComposedGroundError("composed projection system identity or base Ground is invalid")
        if not isinstance(self.computational_ground, RepresentationRef) or not isinstance(self.state_schema, RepresentationRef):
            raise ComposedGroundError("composed projection interpretations are invalid")
        if not isinstance(self.coordinate, SchedulerReading):
            raise ComposedGroundError("composed projection coordinate is invalid")
        try:
            template = json.loads(self.template_json)
            state = json.loads(self.state_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ComposedGroundError("composed projection JSON is malformed") from exc
        if not isinstance(template, dict) or _canonical_json(template, "projection template") != self.template_json:
            raise ComposedGroundError("projection template JSON is not canonical")
        if not isinstance(state, dict) or _canonical_json(state, "assembled state") != self.state_json:
            raise ComposedGroundError("assembled state JSON is not canonical")
        if canonical_value_digest(state) != self.state_digest:
            raise ComposedGroundError("assembled state digest does not match its content")
        if not isinstance(self.components, (tuple, list)) or not self.components:
            raise ComposedGroundError("composed projection requires component evidence")
        components = tuple(sorted(self.components, key=lambda item: item.address.component_id))
        if any(not isinstance(item, ComposedComponentProjection) for item in components):
            raise ComposedGroundError("composed components must contain typed projections")
        ids = [item.address.component_id for item in components]
        if len(set(ids)) != len(ids):
            raise ComposedGroundError("composed projection component identities must be unique")
        rebuilt = json.loads(self.template_json)
        for item in components:
            orbit = item.address.orbit_address
            if (
                item.projection.system_identity != self.system_identity
                or item.projection.base_ground != self.base_ground
                or item.projection.computational_ground != self.computational_ground
                or item.projection.coordinate != self.coordinate
            ):
                raise ComposedGroundError("component projection does not share the composed system/time identity")
            _validate_scalar(item.projection.value, item.address.value_kind)
            _write_path(rebuilt, item.address.field_path, item.projection.value)
        if _canonical_json(rebuilt, "rebuilt composed state") != self.state_json:
            raise ComposedGroundError("assembled state cannot be reproduced from the template and component projections")
        object.__setattr__(self, "components", components)

    @property
    def orbit_offset(self) -> int:
        """Mathematics: derive the projection's scheduler offset from the exact base Ground."""
        return self.coordinate.tick - self.base_ground.coordinate

    @property
    def state(self) -> dict[str, Any]:
        """Mathematics: return a detached materialization of the composed symbolic state projection."""
        return json.loads(self.state_json)

    def identity_payload(self) -> dict[str, Any]:
        """Mathematics: bind the assembled state to its base Ground, schema, time, and component projection identities."""
        return {
            "schema": "mailcpu.composed-virtual-ground-projection.v1",
            "scope": "composed-virtual-state-projection-not-headlessos-checkpoint",
            "address_digest": self.address_digest,
            "system_identity": self.system_identity.snapshot(),
            "base_ground": self.base_ground.to_dict(),
            "computational_ground": self.computational_ground.to_dict(),
            "coordinate": self.coordinate.to_dict(),
            "orbit_offset": self.orbit_offset,
            "state_schema": self.state_schema.to_dict(),
            "template_ref": _template_ref(json.loads(self.template_json)).to_dict(),
            "state_digest": self.state_digest,
            "components": [
                {
                    "component_id": item.address.component_id,
                    "field_path": list(item.address.field_path),
                    "representation": item.address.representation.to_dict(),
                    "value_kind": item.address.value_kind,
                    "projection_digest": item.projection.projection_digest,
                }
                for item in self.components
            ],
        }

    @property
    def projection_digest(self) -> str:
        """Mathematics: compute stable identity for the structured projection, excluding per-read receipt IDs."""
        return canonical_value_digest(self.identity_payload())

    @property
    def evidence_digest(self) -> str:
        """Mathematics: hash the component-specific Structural Memory receipts that substantiate this projection."""
        return canonical_value_digest([item.projection.read_receipt.to_dict() for item in self.components])

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the structured state, stable projection identity, and independent component receipts."""
        return {
            **self.identity_payload(),
            "template_json": self.template_json,
            "state_json": self.state_json,
            "projection_digest": self.projection_digest,
            "evidence_digest": self.evidence_digest,
            "component_projections": [item.to_dict() for item in self.components],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ComposedVirtualGroundProjection":
        """Mathematics: reconstruct a portable structured projection and verify every component read receipt."""
        expected = {
            "schema", "scope", "address_digest", "system_identity", "base_ground",
            "computational_ground", "coordinate", "orbit_offset", "state_schema",
            "template_ref", "state_digest", "components", "template_json", "state_json",
            "projection_digest", "evidence_digest", "component_projections",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected:
            raise ComposedGroundError("composed projection fields are invalid")
        if payload["schema"] != "mailcpu.composed-virtual-ground-projection.v1":
            raise ComposedGroundError("unsupported composed projection schema")
        if payload["scope"] != "composed-virtual-state-projection-not-headlessos-checkpoint":
            raise ComposedGroundError("unsupported composed projection scope")
        coordinate = payload["coordinate"]
        if not isinstance(coordinate, Mapping) or set(coordinate) != {"scheduler_id", "tick"}:
            raise ComposedGroundError("composed projection scheduler coordinate is invalid")
        projection = cls(
            address_digest=payload["address_digest"],
            system_identity=SystemIdentity.from_snapshot(payload["system_identity"]),
            base_ground=VirtualGroundRef.from_dict(payload["base_ground"]),
            computational_ground=RepresentationRef.from_dict(payload["computational_ground"]),
            coordinate=SchedulerReading(coordinate["scheduler_id"], coordinate["tick"]),
            state_schema=RepresentationRef.from_dict(payload["state_schema"]),
            template_json=payload["template_json"],
            components=tuple(ComposedComponentProjection.from_dict(item) for item in payload["component_projections"]),
            state_json=payload["state_json"],
            state_digest=payload["state_digest"],
        )
        expected_template_ref = _template_ref(json.loads(projection.template_json))
        if RepresentationRef.from_dict(payload["template_ref"]) != expected_template_ref:
            raise ComposedGroundError("projection template reference does not match template content")
        if payload["orbit_offset"] != projection.orbit_offset:
            raise ComposedGroundError("projection orbit offset differs from its coordinates")
        if payload["projection_digest"] != projection.projection_digest:
            raise ComposedGroundError("composed projection digest does not match its identity")
        if payload["evidence_digest"] != projection.evidence_digest:
            raise ComposedGroundError("composed projection evidence digest does not match its receipts")
        return projection


@dataclass(frozen=True)
class ComposedGroundNavigationResult:
    """Direct multi-component state generation result and per-component law profile."""

    projection: ComposedVirtualGroundProjection
    generator_profiles: tuple[tuple[str, str, str], ...]
    expanded_states: int = 0

    def __post_init__(self) -> None:
        """Mathematics: bind each component to one declared family and its supported forward complexity."""
        if not isinstance(self.projection, ComposedVirtualGroundProjection):
            raise ComposedGroundError("composed navigation projection is invalid")
        profiles = tuple(self.generator_profiles)
        expected_ids = {item.address.component_id for item in self.projection.components}
        if {item[0] for item in profiles} != expected_ids or len(profiles) != len(expected_ids):
            raise ComposedGroundError("generator profile set differs from the composed component set")
        if any(_FORWARD_COMPLEXITY.get(family) != complexity for _, family, complexity in profiles):
            raise ComposedGroundError("generator profile contains an unsupported complexity declaration")
        object.__setattr__(self, "generator_profiles", tuple(sorted(profiles)))
        if type(self.expanded_states) is not int or self.expanded_states != 0:
            raise ComposedGroundError("direct composed generation must not expand intermediate orbit states")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: serialize the composed projection and its component-specific algebraic profiles."""
        return {
            "schema": "mailcpu.composed-ground-navigation-result.v1",
            "projection": self.projection.to_dict(),
            "generator_profiles": [
                {"component_id": name, "family": family, "complexity_bound": bound}
                for name, family, bound in self.generator_profiles
            ],
            "expanded_states": self.expanded_states,
        }


class ComposedVirtualGroundNavigator:
    """Generate a structured multi-component state from receiver-admitted Structural Memory laws."""

    def __init__(self, registry: StructuralMemoryRegistry) -> None:
        """Mathematics: bind the compositor to one receiver-local admitted Structural Memory registry."""
        if not isinstance(registry, StructuralMemoryRegistry):
            raise ComposedGroundError("ComposedVirtualGroundNavigator requires a StructuralMemoryRegistry")
        self.registry = registry

    def locate(
        self,
        address: ComposedVirtualGroundAddress,
        *,
        expected_state_digest: str | None = None,
    ) -> ComposedGroundNavigationResult:
        """Evaluate every certified component at one shared coordinate and assemble the typed state projection.

        Mathematics:
        For component generators g_i and common relative coordinate t, compute
        v_i=g_i(t), then update only the declared field paths in template T:
        S_t = T[field_i <- v_i]. No intervening system states are materialized.
        """
        if not isinstance(address, ComposedVirtualGroundAddress):
            raise ComposedGroundError("locate requires a ComposedVirtualGroundAddress")
        state = address.template
        component_projections: list[ComposedComponentProjection] = []
        profiles: list[tuple[str, str, str]] = []

        for component in address.components:
            memory_ref = component.orbit_address.structural_memory
            try:
                version = self.registry.version_for_revision(memory_ref.memory_id, memory_ref.revision)
            except StructuralMemoryError as exc:
                raise ComposedGroundError(
                    f"component {component.component_id!r} Structural Memory revision is not admitted"
                ) from exc
            if (
                version.spec.digest != memory_ref.spec_digest
                or version.certificate.digest != memory_ref.certificate_digest
            ):
                raise ComposedGroundError(f"component {component.component_id!r} Structural Memory identity differs")
            transition = structural_memory_spec_representation_ref(version.spec)
            try:
                receipt = self.registry.read_revision(
                    memory_ref.memory_id,
                    memory_ref.revision,
                    memory_ref.coordinate,
                    context=json.loads(_canonical_json(dict(memory_ref.context), "component memory context")),
                )
            except StructuralMemoryError as exc:
                raise ComposedGroundError(
                    f"component {component.component_id!r} guarded read refused its coordinate or context"
                ) from exc
            _validate_scalar(receipt.value, component.value_kind)
            scalar = VirtualGroundProjection(
                system_identity=address.system_identity,
                base_ground=address.base_ground,
                computational_ground=address.computational_ground,
                transition=transition,
                coordinate=address.coordinate,
                orbit_offset=address.orbit_offset,
                structural_memory=memory_ref,
                value=receipt.value,
                value_digest=receipt.value_digest,
                read_receipt=receipt,
            )
            component_projection = ComposedComponentProjection(component, scalar)
            component_projections.append(component_projection)
            _write_path(state, component.field_path, receipt.value)
            family = version.spec.family
            complexity = _FORWARD_COMPLEXITY.get(family)
            if complexity is None:
                raise ComposedGroundError(f"component {component.component_id!r} uses unsupported family {family!r}")
            profiles.append((component.component_id, family, complexity))

        state_json = _canonical_json(state, "composed state")
        state_digest = canonical_value_digest(state)
        if expected_state_digest is not None and expected_state_digest != state_digest:
            raise ComposedGroundError("generated composed state differs from expected_state_digest")
        projection = ComposedVirtualGroundProjection(
            address_digest=address.digest,
            system_identity=address.system_identity,
            base_ground=address.base_ground,
            computational_ground=address.computational_ground,
            coordinate=address.coordinate,
            state_schema=address.state_schema,
            template_json=address.template_json,
            components=tuple(component_projections),
            state_json=state_json,
            state_digest=state_digest,
        )
        return ComposedGroundNavigationResult(
            projection=projection,
            generator_profiles=tuple(profiles),
            expanded_states=0,
        )
