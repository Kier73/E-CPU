"""MGA-001/D: persistent affine starting points and native shared realization.

A bank is explicitly installed by the receiver at a logical locus. The
local bank is not evidence that an arbitrary remote host retains anything.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re

from .law_certifier import lcg_navigate
from .affine_verification_ground import AffineVerificationGround
from .affine_vocabulary import AffineVocabulary
from .affine_coalescent import CoalescentVocabulary
from .runtime_qualification import affine_expected
from .shared_result_bank import PureContract, ResultBank
from .shared_observation_ground import plan_shared, execute_shared
from .substrate_bootstrap import (
    AdaptiveBootstrap, BootstrapRefused, BootstrapTask, RealizerBinding,
    SubstrateObservation, canonical, digest, name, sha, verify_bootstrap_report,
)

KIND = "affine.checkpoint"
REQUEST = "affine.checkpoint.request"
OPERATION = "affine.checkpoint.advance"
SCHEMA = "mailcpu.mga001.affine-continuation.v1"
MAX_COORDINATE = (1 << 63) - 1


def _coordinate(t):
    if type(t) is not int or not 0 <= t <= MAX_COORDINATE:
        raise BootstrapRefused("invalid affine coordinate")
    return t


@dataclass(frozen=True)
class Orbit:
    a: int
    c: int
    m: int
    x0: int
    context: str

    def __post_init__(self):
        sha(self.context, "source context")
        if type(self.m) is not int or not 2 <= self.m <= 2**31-1:
            raise BootstrapRefused("invalid affine modulus")
        if any(type(v) is not int or not 0 <= v < self.m for v in (self.a, self.c, self.x0)):
            raise BootstrapRefused("invalid affine parameters")

    @property
    def ground(self):
        return digest([SCHEMA, self.a, self.c, self.m, self.x0, self.context])

    def value(self, t, x):
        _coordinate(t)
        if type(x) is not int or not 0 <= x < self.m:
            raise BootstrapRefused("invalid checkpoint state")
        return {"ground": self.ground, "coordinate": t, "value": f"{x:08x}"}

    def parse(self, data):
        if (type(data) is not dict or set(data) != {"ground", "coordinate", "value"}
                or data["ground"] != self.ground or type(data["value"]) is not str
                or re.fullmatch("[0-9a-f]{8}", data["value"]) is None):
            raise BootstrapRefused("checkpoint representation mismatch")
        t, x = _coordinate(data["coordinate"]), int(data["value"], 16)
        if self.value(t, x) != data:
            raise BootstrapRefused("checkpoint outside source domain")
        return t, x

    def expected(self, t):
        return self.value(t, affine_expected(self.a, self.c, self.m, self.x0, _coordinate(t)))


def _contract(orbit, locus, authority):
    name(locus, "retention locus")
    name(authority, "receiver authority")
    return PureContract(orbit.ground, digest([SCHEMA, locus, authority]),
                        digest("independent-affine-expected-v1"), 128, 1024)


def _expected(orbit, t, verification_ground):
    if verification_ground is None:
        return orbit.expected(t)
    if type(verification_ground) not in (AffineVerificationGround, AffineVocabulary, CoalescentVocabulary):
        raise BootstrapRefused("independently admitted verification Ground required")
    return verification_ground.expected(orbit, t)


def _verifier(orbit, verification_ground=None):
    def verify(raw, output):
        t = json.loads(raw)
        return (canonical(t) == raw and canonical(_expected(orbit, t, verification_ground)) == output)
    return verify


def retain(bank, orbit, locus, authority, checkpoint, *, verification_ground=None):
    """Admit exact coordinate, independently recheck even if already retained."""
    if not isinstance(bank, ResultBank):
        raise BootstrapRefused("receiver-installed result bank required")
    t, _ = orbit.parse(checkpoint)
    raw = canonical(checkpoint)
    if canonical(_expected(orbit, t, verification_ground)) != raw:
        raise BootstrapRefused("checkpoint contradicts original source")
    stored = bank.resolve(_contract(orbit, locus, authority), canonical(t),
                          lambda _: raw, _verifier(orbit, verification_ground))
    if stored != raw:
        raise BootstrapRefused("retained checkpoint differs")
    return json.loads(stored)


def lookup(bank, orbit, locus, authority, t, *, verification_ground=None):
    if not isinstance(bank, ResultBank):
        raise BootstrapRefused("receiver-installed result bank required")
    raw = bank.lookup(_contract(orbit, locus, authority), canonical(_coordinate(t)), _verifier(orbit, verification_ground))
    return None if raw is None else json.loads(raw)


def _request(orbit, checkpoint, target):
    t, x = orbit.parse(checkpoint)
    target = _coordinate(target)
    if target < t:
        raise BootstrapRefused("forward continuation only")
    return t, x, target - t


def binding(orbit, locus):
    """Native pure local continuation operator, with independent relative oracle."""
    def handle(raw):
        if type(raw) is not dict or set(raw) != {"checkpoint", "target"}:
            raise BootstrapRefused("invalid continuation request")
        _, x, dt = _request(orbit, raw["checkpoint"], raw["target"])
        return orbit.value(raw["target"], lcg_navigate(orbit.a, orbit.c, orbit.m, x, dt))

    def check(raw, output):
        _, x, dt = _request(orbit, raw["checkpoint"], raw["target"])
        return canonical(output) == canonical(orbit.value(
            raw["target"], affine_expected(orbit.a, orbit.c, orbit.m, x, dt)))

    return RealizerBinding(locus, OPERATION, handle, digest([SCHEMA, orbit.ground, locus]), check)


def _local_plan(runtime, orbit, locus, checkpoint, t, coordinate):
    # No carrier or substitute locus may satisfy the selected starting point.
    resource = next(r for r in runtime.inventory.resources if r.resource_id == locus)
    local = AdaptiveBootstrap(SubstrateObservation((resource,), ()), runtime.policy,
                              tuple(v for (host, _), v in runtime.realizers.items() if host == locus), ())
    task = BootstrapTask(digest([SCHEMA, locus, checkpoint, t]), orbit.ground,
                         locus, REQUEST, locus, KIND,
                         {"checkpoint": checkpoint, "target": t},
                         max_quanta=1000000, max_steps=1, max_bytes=1024,
                         require_oracle=True)
    plan = local.plan(task, coordinate=coordinate)
    if len(plan.steps) != 1 or plan.steps[0].operation != OPERATION:
        raise BootstrapRefused("required continuation operator unavailable")
    return local, task, plan


def continue_observation(runtime, orbit, banks, offers, target_coordinate, targets, *, coordinate, verification_ground=None):
    """Select and realize a new intention from existing verified starting points.

    Only explicit offered bank coordinates are searched. Rank the native plans
    by declared quanta, relative horizon bit length, tree edges and stable
    locus/time. The tree is the MGA-001/C shortest-hop tree, not a globally
    minimum-cost Steiner tree. No hypothetical route is executed.
    """
    if not isinstance(runtime, AdaptiveBootstrap) or not isinstance(orbit, Orbit):
        raise BootstrapRefused("native runtime and orbit required")
    t = _coordinate(target_coordinate)
    if not isinstance(targets, (list, tuple)) or not targets:
        raise BootstrapRefused("targets required")
    if not isinstance(offers, (tuple, list)) or not offers:
        raise BootstrapRefused("explicit retained coordinate offers required")
    if any(not isinstance(b, ResultBank) for b in banks.values()):
        raise BootstrapRefused("invalid installed bank")
    if len({id(b) for b in banks.values()}) != len(banks):
        raise BootstrapRefused("each locus requires a distinct installed bank")
    known = {r.resource_id for r in runtime.inventory.resources}
    if not set(targets) <= known:
        raise BootstrapRefused("unknown target")
    live = {r.resource_id for r in runtime.inventory.resources
            if r.observed_at <= coordinate <= r.expires_at}
    authority = runtime.policy.authority_id
    # Fixed-width state encoding makes the placeholder's byte extent exact.
    placeholder = orbit.value(t, 0)
    choices, diagnostics = [], []
    if any(not isinstance(o, (list, tuple)) or len(o) != 2 for o in offers):
        raise BootstrapRefused("invalid coordinate offer")
    offered = set()
    for locus, start in offers:
        name(locus, "offered locus")
        offered.add((locus, _coordinate(start)))
    for locus, start in sorted(offered):
        if locus not in live or locus not in banks or start > t:
            diagnostics.append([locus, start, "UNAVAILABLE"])
            continue
        checkpoint = lookup(banks[locus], orbit, locus, authority, start, verification_ground=verification_ground)
        if checkpoint is None:
            diagnostics.append([locus, start, "NOT_RETAINED"])
            continue
        try:
            local, task, local_plan = _local_plan(runtime, orbit, locus, checkpoint, t, coordinate)
            route = plan_shared(runtime, locus, targets, KIND, placeholder, orbit.ground,
                                coordinate=coordinate)
        except BootstrapRefused:
            diagnostics.append([locus, start, "NO_ADMITTED_CONTINUATION"])
            continue
        if route["status"] != "READY":
            diagnostics.append([locus, start, "BLOCKED_ROUTE", route["repairs"]])
            continue
        score = (local_plan.estimated_quanta + route["declared_quanta"],
                 (t-start).bit_length(), len(route["tree"]), locus, start)
        choices.append((score, checkpoint, local, task, local_plan, route))
        diagnostics.append([locus, start, "CANDIDATE", list(score)])
    if not choices:
        raise BootstrapRefused("no qualified retained starting point")
    score, checkpoint, local, task, local_plan, predicted = min(choices, key=lambda row: row[0])
    locus, start = score[3:]
    computed = local.execute(task, local_plan, coordinate=coordinate)
    verify_bootstrap_report(computed, task, local_plan)
    output = computed["output"]
    _, x, delta = _request(orbit, checkpoint, t)
    if canonical(output) != canonical(orbit.value(t, affine_expected(orbit.a, orbit.c, orbit.m, x, delta))):
        raise BootstrapRefused("independent continuation check failed")
    actual = plan_shared(runtime, locus, targets, KIND, output, orbit.ground, coordinate=coordinate)
    if (actual["status"] != "READY" or actual["tree"] != predicted["tree"]
            or actual["declared_quanta"] != predicted["declared_quanta"]):
        raise BootstrapRefused("actual route differs from byte-extent plan")
    dissemination = execute_shared(runtime, locus, targets, KIND, output, orbit.ground,
                                   actual, coordinate=coordinate)
    # Only actual realized loci (including intermediate vertices) may acquire
    # a checkpoint, and only if a receiver-installed bank exists there.
    edge_by_id = {e.channel_id: e for e in runtime.inventory.channels}
    delivered = {locus: output}
    for record in dissemination["reports"]:
        e = edge_by_id[record["channel"]]
        delivered[e.target] = record["report"]["output"]
    retained = []
    for host, value in sorted(delivered.items()):
        if host in banks:
            retain(banks[host], orbit, host, authority, value, verification_ground=verification_ground)
            retained.append(host)
    body = {"schema": SCHEMA, "ground": orbit.ground, "coordinate": t,
            "start": {"locus": locus, "coordinate": start, "delta": delta},
            "horizon_bits": delta.bit_length(), "cold_horizon_bits": t.bit_length(),
            "score": list(score), "candidates": diagnostics,
            "local_report": computed, "dissemination": dissemination,
            "retained_loci": retained}
    return {**body, "digest": digest(body)}
