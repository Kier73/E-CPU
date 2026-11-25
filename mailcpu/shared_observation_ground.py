"""MGA-001/C: receiver-bound single-label dissemination and constructive cut repair.

A copyable canonical value is not a tensor conversion or a reserved bandwidth.
Use SAB-001's native inventory, grants, carrier drivers and receipt verifier.
"""
from __future__ import annotations

import heapq
import json

from .substrate_bootstrap import (
    AdaptiveBootstrap, BootstrapRefused, BootstrapTask, SubstrateObservation,
    canonical, digest, name, natural, sha, verify_bootstrap_report,
)

SCHEMA = "mailcpu.mga001.shared-observation.v1"


def _inputs(runtime, source, targets, kind, value, ground, coordinate):
    if not isinstance(runtime, AdaptiveBootstrap):
        raise BootstrapRefused("native bootstrap required")
    name(source, "source")
    name(kind, "representation")
    sha(ground, "Ground")
    natural(coordinate, "coordinate")
    if not isinstance(targets, (tuple, list)) or not targets:
        raise BootstrapRefused("nonempty target sequence required")
    for target in targets:
        name(target, "target")
    if len(set(targets)) != len(targets):
        raise BootstrapRefused("duplicate target")
    targets = tuple(sorted(targets))
    known = {r.resource_id for r in runtime.inventory.resources}
    live = {r.resource_id for r in runtime.inventory.resources
            if r.observed_at <= coordinate <= r.expires_at}
    if source not in live or not set(targets) <= known:
        raise BootstrapRefused("source unavailable or unknown target")
    data = canonical(value)
    if len(data) > 1048576:
        raise BootstrapRefused("payload outside native task envelope")
    eligible = {}
    for edge in runtime.inventory.channels:
        if (edge.source in live and edge.target in live
                and edge.observed_at <= coordinate <= edge.expires_at
                and kind in edge.carries and len(data) <= edge.max_payload_bytes
                and edge.channel_id in runtime.carriers):
            eligible[edge.channel_id] = edge
    return targets, eligible, data


def _shortest(source, edges, allowed):
    """Lexicographic cost: additional grants, hops, deterministic path."""
    outgoing = {}
    for key, edge in sorted(edges.items()):
        outgoing.setdefault(edge.source, []).append((key, edge.target))
    best = {}
    queue = [(0, 0, (), source)]
    while queue:
        cost, hops, path, node = heapq.heappop(queue)
        if node in best:
            continue
        best[node] = (cost, hops, path)
        for key, target in outgoing.get(node, ()):
            if target not in best:
                heapq.heappush(queue, (cost + int(key not in allowed),
                                      hops + 1, path + (key,), target))
    return best


def plan_shared(runtime, source, targets, kind, value, ground, *, coordinate):
    """A closed reachable cut, advisory grant repairs, or a shared execution tree."""
    targets, edges, data = _inputs(runtime, source, targets, kind, value, ground, coordinate)
    allowed = runtime.policy.allowed_channels
    best = _shortest(source, edges, allowed)
    reached = sorted(node for node, score in best.items() if score[0] == 0)
    reached_set = set(reached)
    missing = [t for t in targets if t not in reached_set]
    repairs = []
    for t in missing:
        if t not in best:
            repairs.append({"target": t, "status": "NO_OFFERED_PATH"})
        else:
            count, _, path = best[t]
            repairs.append({"target": t, "status": "PROPOSED_GRANTS",
                            "count": count, "path": list(path),
                            "grants": [e for e in path if e not in allowed]})
    tree = []
    seen = set()
    if not missing:
        for t in targets:
            for key in best[t][2]:
                if key not in seen:
                    seen.add(key)
                    tree.append(key)
    body = {
        "schema": SCHEMA, "inventory": runtime.inventory.fingerprint,
        "policy": runtime.policy.fingerprint, "coordinate": coordinate,
        "source": source, "targets": list(targets), "representation": kind,
        "ground": ground, "value_digest": digest(json.loads(data)),
        "bindings": {k: runtime.carriers[k].implementation_digest for k in sorted(edges)},
        "status": "BLOCKED" if missing else "READY", "reachable": reached,
        "missing": missing,
        "boundary_grants": sorted(k for k, e in edges.items()
                                  if e.source in reached_set and e.target not in reached_set),
        "repairs": repairs, "tree": tree,
        "separate_path_hops": sum(best[t][1] for t in targets) if not missing else None,
        "declared_quanta": sum(edges[k].estimated_quanta for k in tree),
    }
    return {**body, "digest": digest(body)}


def verify_shared_plan(runtime, source, targets, kind, value, ground, plan, *, coordinate):
    """Reconstruct identities; independently prove minimum grant counts by relaxation."""
    expected = plan_shared(runtime, source, targets, kind, value, ground, coordinate=coordinate)
    if canonical(plan) != canonical(expected):
        raise BootstrapRefused("stale or modified shared-observation plan")
    targets, edges, _ = _inputs(runtime, source, targets, kind, value, ground, coordinate)
    allowed = runtime.policy.allowed_channels
    distance = {source: 0}
    # Independent Bellman-Ford recurrence on the finite offered directed graph.
    for _ in range(len(runtime.inventory.resources) - 1):
        previous = dict(distance)
        for key, edge in edges.items():
            if edge.source in previous:
                candidate = previous[edge.source] + int(key not in allowed)
                if candidate < distance.get(edge.target, float("inf")):
                    distance[edge.target] = candidate
        if distance == previous:
            break
    reached = {x for x, d in distance.items() if d == 0}
    if reached != set(plan["reachable"]):
        raise BootstrapRefused("reachable cut inconsistent")
    for item in plan["repairs"]:
        target = item["target"]
        if item["status"] == "NO_OFFERED_PATH":
            if target in distance:
                raise BootstrapRefused("missed offered path")
            continue
        node = source
        grants = []
        for key in item["path"]:
            edge = edges[key]
            if edge.source != node:
                raise BootstrapRefused("broken repair path")
            node = edge.target
            if key not in allowed:
                grants.append(key)
        if (node != target or grants != item["grants"]
                or len(grants) != distance.get(target) or len(grants) != item["count"]):
            raise BootstrapRefused("repair is not minimum")
    known = {source}
    for key in plan["tree"]:
        e = edges[key]
        if key not in allowed or e.source not in known or e.target in known:
            raise BootstrapRefused("invalid shared execution tree")
        known.add(e.target)
    if plan["status"] == "READY" and not set(targets) <= known:
        raise BootstrapRefused("tree misses target")
    return True


def execute_shared(runtime, source, targets, kind, value, ground, plan, *, coordinate):
    """Perform each tree edge once with native SAB-001 planning and receipt checking.

    All observations are evaluated at the caller's declared snapshot coordinate.
    Failure stops later sends; already executed carriers are not rolled back.
    """
    verify_shared_plan(runtime, source, targets, kind, value, ground, plan, coordinate=coordinate)
    if plan["status"] != "READY":
        raise BootstrapRefused("shared observation blocked; no grant was applied")
    edges = {e.channel_id: e for e in runtime.inventory.channels}
    values = {source: json.loads(canonical(value))}
    reports = []
    for key in plan["tree"]:
        edge = edges[key]
        # Restrict the inventory to the selected edge, but retain the actual
        # receiver policy and actual carrier driver; no synthesized authority.
        local = AdaptiveBootstrap(
            SubstrateObservation(runtime.inventory.resources, (edge,)),
            runtime.policy, (), (runtime.carriers[key],))
        task = BootstrapTask(
            digest([plan["digest"], key]), ground, edge.source, kind,
            edge.target, kind, values[edge.source],
            max_quanta=edge.estimated_quanta, max_steps=1, max_bytes=1048576)
        selected = local.plan(task, coordinate=coordinate)
        if len(selected.steps) != 1 or selected.steps[0].operation != key:
            raise BootstrapRefused("selected carrier not realized")
        report = local.execute(task, selected, coordinate=coordinate)
        verify_bootstrap_report(report, task, selected)
        if canonical(report["output"]) != canonical(value):
            raise BootstrapRefused("shared observation changed")
        values[edge.target] = report["output"]
        reports.append({"channel": key, "report": report})
    result = {"schema": SCHEMA + ".receipt", "plan": plan["digest"],
              "observations": {t: values[t] for t in plan["targets"]},
              "transmissions": len(reports), "reports": reports}
    return {**result, "digest": digest(result)}
