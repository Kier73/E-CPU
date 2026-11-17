"""Queryable, non-authoritative AI Computational Ground atlas.

This module indexes descriptions of computational structures and existing
E-CPU realization evidence. It does NOT admit a Ground, grant a capability,
register an operator, infer a universal law, or execute model computation.
Only existing MailCPU authority/realizer APIs can perform those actions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

SCHEMA = "mailcpu.ai-ground-atlas.v1"
DEFAULT_PATH = Path(__file__).with_name("ai_ground_atlas.v1.json")
_STATES = {"mainline_scoped", "research_scoped", "candidate"}
_EFFECTS = {"pure", "stateful", "effectful"}
_MODE = {
    "direct_law", "inverse_navigation", "composed_projection",
    "symbolic_factorization", "evidence_search", "qualified_realization",
    "state_continuation", "explicit_evaluation",
}
_ENTRY_KEYS = {
    "id", "name", "stage", "representation", "transition_relation",
    "observation_projection", "navigation", "dependencies", "source_anchors",
    "realization_status", "realization_scope", "verification_obligation",
    "effect_class", "ground_admission",
}
_TOP_KEYS = {
    "schema", "purpose", "admission_rule", "pin_policy", "open_world",
    "coverage_scope", "sources", "stages", "navigation_modes", "entries",
    "catalog_digest",
}
_ID = re.compile(r"[a-z][a-z0-9]*(?:[._][a-z0-9]+)+\Z")
_SOURCE_ALIAS = re.compile(r"[A-Z][A-Z0-9]*\Z")
_SAFE_PATH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")


class AtlasRefused(ValueError):
    """An atlas description is malformed, contradictory or not safely bound."""


def canonical(value: Any) -> bytes:
    """Canonical finite JSON bytes, with no NaN or unstable key ordering."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _require_text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise AtlasRefused(f"{label} requires nonempty bounded text")


def validate(document: Any) -> dict[str, Any]:
    """Verify catalog identity, source pins, Ground descriptions and DAG closure.

    Source references are inspectable, pinned hints—not certificates that the
    referenced implementation realizes the entire candidate Ground.
    """
    if not isinstance(document, dict) or set(document) != _TOP_KEYS:
        raise AtlasRefused("atlas has missing or unexpected top-level fields")
    if document["schema"] != SCHEMA or document["open_world"] is not True:
        raise AtlasRefused("unsupported schema or closed-world assertion")
    for key in ("purpose", "admission_rule", "pin_policy", "coverage_scope"):
        _require_text(document[key], key)
    if "catalogued_only" not in document["admission_rule"]:
        raise AtlasRefused("atlas must refuse implicit Ground admission")
    if not isinstance(document["stages"], dict) or not document["stages"]:
        raise AtlasRefused("stages must be a nonempty mapping")
    for stage, name in document["stages"].items():
        if not isinstance(stage, str) or not stage or not stage.isidentifier():
            raise AtlasRefused("malformed stage identifier")
        _require_text(name, f"stage {stage}")
    if document["navigation_modes"] != sorted(_MODE):
        raise AtlasRefused("navigation modes differ from declared protocol")
    sources = document["sources"]
    if not isinstance(sources, dict) or not sources:
        raise AtlasRefused("source registry must be nonempty")
    for alias, source in sources.items():
        if not isinstance(alias, str) or not _SOURCE_ALIAS.fullmatch(alias):
            raise AtlasRefused("bad source alias")
        if not isinstance(source, dict) or set(source) != {"repo", "ref"}:
            raise AtlasRefused(f"source {alias} must bind repo and commit ref")
        if not isinstance(source["repo"], str) or not source["repo"].startswith("Kier73/"):
            raise AtlasRefused("untrusted source repository")
        if not isinstance(source["ref"], str) or not _SHA.fullmatch(source["ref"]):
            raise AtlasRefused("source revision must be an exact commit SHA")
    if not isinstance(document["entries"], list) or not document["entries"]:
        raise AtlasRefused("Ground entries must be nonempty")
    by_id: dict[str, dict[str, Any]] = {}
    observed_stages = set()
    for value in document["entries"]:
        if not isinstance(value, dict) or set(value) != _ENTRY_KEYS:
            raise AtlasRefused("Ground entry has unknown/missing fields")
        identifier = value["id"]
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            raise AtlasRefused(f"invalid Ground identifier {identifier!r}")
        if identifier in by_id:
            raise AtlasRefused(f"duplicate Ground identifier: {identifier}")
        by_id[identifier] = value
        if value["stage"] not in document["stages"]:
            raise AtlasRefused(f"unknown stage at {identifier}")
        observed_stages.add(value["stage"])
        for key in ("name", "representation", "transition_relation", "observation_projection",
                    "realization_scope", "verification_obligation"):
            _require_text(value[key], f"{identifier}.{key}")
        if value["navigation"] not in _MODE:
            raise AtlasRefused(f"unknown navigation strategy at {identifier}")
        if value["effect_class"] not in _EFFECTS:
            raise AtlasRefused(f"unknown effect classification at {identifier}")
        if value["realization_status"] not in _STATES:
            raise AtlasRefused(f"unknown realization status at {identifier}")
        if value["ground_admission"] != "catalogued_only":
            raise AtlasRefused(f"catalog may not assert admitted Ground at {identifier}")
        deps = value["dependencies"]
        if not isinstance(deps, list) or len(deps) != len(set(deps)) or not all(
            isinstance(dep, str) and _ID.fullmatch(dep) for dep in deps
        ):
            raise AtlasRefused(f"invalid dependencies at {identifier}")
        if identifier in deps:
            raise AtlasRefused(f"self-dependent Ground at {identifier}")
        anchors = value["source_anchors"]
        if not isinstance(anchors, list) or not anchors or len(set(anchors)) != len(anchors):
            raise AtlasRefused(f"missing/repeated source anchors at {identifier}")
        aliases = []
        for anchor in anchors:
            if not isinstance(anchor, str) or ":" not in anchor:
                raise AtlasRefused(f"malformed source anchor at {identifier}")
            alias, path = anchor.split(":", 1)
            if alias not in sources or not path or not _SAFE_PATH.fullmatch(path) or \
               ".." in path.split("/") or path.startswith("/"):
                raise AtlasRefused(f"unsafe/unknown source anchor at {identifier}")
            aliases.append(alias)
        status = value["realization_status"]
        if status == "mainline_scoped" and not any(a in {"ECPU", "VGI", "VP1"} for a in aliases):
            raise AtlasRefused(f"mainline-scoped entry without a mainline anchor: {identifier}")
        if status == "research_scoped" and not any(a in {"IFS", "VP2", "VP3", "VP4"} for a in aliases):
            raise AtlasRefused(f"research-scoped entry without a research anchor: {identifier}")
    if observed_stages != set(document["stages"]):
        raise AtlasRefused("catalog does not cover every declared stage")
    # Separate the representation graph from the order in which entries appear.
    marks: dict[str, int] = {}
    def visit(key: str) -> None:
        if key not in by_id:
            raise AtlasRefused(f"unresolved Ground dependency {key}")
        if marks.get(key, 0) == 1:
            raise AtlasRefused(f"cyclic Ground dependencies at {key}")
        if marks.get(key, 0) == 2:
            return
        marks[key] = 1
        for dependency in by_id[key]["dependencies"]:
            visit(dependency)
        marks[key] = 2
    for key in by_id:
        visit(key)
    expected_digest = digest({k: v for k, v in document.items() if k != "catalog_digest"})
    if document["catalog_digest"] != expected_digest:
        raise AtlasRefused("Ground atlas digest disagrees with canonical content")
    return document


def load(path: Path | None = None) -> dict[str, Any]:
    """Load with refusal on duplicate JSON keys and invalid UTF-8."""
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise AtlasRefused(f"duplicate JSON key {key}")
            obj[key] = value
        return obj
    src = DEFAULT_PATH if path is None else Path(path)
    return validate(json.loads(src.read_text(encoding="utf-8"), object_pairs_hook=pairs))


def find(catalog: Mapping[str, Any], identifier: str) -> dict[str, Any]:
    for record in catalog["entries"]:
        if record["id"] == identifier:
            return record
    raise AtlasRefused(f"unrecognized computational structure: {identifier}")


def dependency_closure(catalog: Mapping[str, Any], identifier: str) -> list[str]:
    index = {x["id"]: x for x in catalog["entries"]}
    if identifier not in index:
        raise AtlasRefused(f"unrecognized computational structure: {identifier}")
    result = []
    seen: set[str] = set()
    def add(item: str):
        if item in seen:
            return
        seen.add(item)
        for dep in index[item]["dependencies"]:
            add(dep)
        result.append(item)
    add(identifier)
    return result


def representation_ref(catalog: Mapping[str, Any], identifier: str) -> Any:
    """Give a Ground *description* a native E-CPU content-addressed identity.

    RepresentationRef != StructuralMemory admission, system seed, or authority.
    No concrete model parameters are fabricated by this operation.
    """
    from .semantic_translation import RepresentationRef
    value = find(catalog, identifier)
    cited = sorted({a.split(":", 1)[0] for a in value["source_anchors"]})
    return RepresentationRef.from_payload("mailcpu.ai-ground-description", 1, {
        "schema": SCHEMA,
        "entry": value,
        "source_revisions": {a: catalog["sources"][a] for a in cited},
    })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect source-anchored AI Ground descriptions; no execution or admission")
    parser.add_argument("action", choices=("validate", "list", "show", "closure"))
    parser.add_argument("ground", nargs="?", help="Ground ID for show/closure")
    parser.add_argument("--catalog", type=Path, help="Use an explicit catalog file")
    parser.add_argument("--stage", help="Filter list by workflow stage")
    args = parser.parse_args(argv)
    try:
        atlas = load(args.catalog)
        if args.action == "validate":
            output: Any = {"schema": atlas["schema"], "count": len(atlas["entries"]),
                           "catalog_digest": atlas["catalog_digest"], "all_entries_catalogued_only": True}
        elif args.action == "list":
            if args.stage and args.stage not in atlas["stages"]:
                raise AtlasRefused(f"unrecognized stage: {args.stage}")
            output = [{"id": x["id"], "stage": x["stage"], "name": x["name"],
                       "realization_status": x["realization_status"]}
                      for x in atlas["entries"] if not args.stage or x["stage"] == args.stage]
        elif args.action == "show":
            if not args.ground:
                raise AtlasRefused("show requires a Ground ID")
            output = {"ground": find(atlas, args.ground),
                      "representation_ref": representation_ref(atlas, args.ground).to_dict()}
        else:
            if not args.ground:
                raise AtlasRefused("closure requires a Ground ID")
            output = {"ground": args.ground, "dependency_closure": dependency_closure(atlas, args.ground)}
        print(json.dumps(output, sort_keys=True, indent=2))
        return 0
    except (AtlasRefused, OSError, ValueError) as error:
        parser.exit(2, f"AI Ground atlas refusal: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
