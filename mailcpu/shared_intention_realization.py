"""ITR-003: source-checked shared intention families on receiver-admitted E-CPU.

CIG-019 establishes one common proof and multi-output decoder. A receiver
retains the admitted canonical bytes and realizes only the requested output
dependencies. Source witnesses qualify mathematical observations, not
physical measurements. SAB-001 remains the live host/path authority.
"""
from __future__ import annotations

import json
from time import perf_counter_ns
from typing import Sequence

from .inverse_nonlinear_realization import (
    NonlinearIntention, NonlinearCapacity, NonlinearRealizationRefused,
    SourceObservation, ReceiverSourceSectionMemory, qualify_observation,
    DIRECT_OPERATION, OBSERVE_OPERATION,
)
from .substrate_bootstrap import (
    AdaptiveBootstrap, BootstrapTask, BootstrapRefused, RealizerBinding,
    digest, verify_bootstrap_report,
)

SCHEMA = "mailcpu.itr003.shared-intention.v1"
BUDGET = {"max_pairs": 500000, "max_steps": 200000, "max_width": 32}
MAX_PROOF_BYTES = 8 * 1024 * 1024


def _raw(value):
    """Canonical detached JSON, used for receiver-owned proof storage."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def evaluate_slice(circuit, code: int, width: int, indices: Sequence[int]):
    """Evaluate only transitive ancestors of selected, admitted outputs.

    References in CIG-019 are signed; +/-1 are constants and 2..width+1
    are inputs. Traverse backwards, then evaluate in topological order.
    The circuit must already have been admitted by the independent verifier.
    """
    if (type(code) is not int or type(width) is not int or width < 0
            or not 0 <= code < 1 << width):
        raise NonlinearRealizationRefused("invalid observation coordinate")
    gates = circuit["gates"]
    outputs = circuit["outputs"]
    ids = tuple(indices)
    if (not ids or len(set(ids)) != len(ids)
            or any(type(i) is not int or not 0 <= i < len(outputs)
                   or outputs[i] is None for i in ids)):
        raise NonlinearRealizationRefused("requested output is unresolved or invalid")
    first = width + 2
    live = set()
    todo = [abs(outputs[i]) for i in ids]
    while todo:
        ref = todo.pop()
        if ref < first or ref in live:
            continue
        if ref >= first + len(gates):
            raise NonlinearRealizationRefused("circuit reference outside admitted graph")
        live.add(ref)
        _, a, b = gates[ref - first]
        todo.extend((abs(a), abs(b)))
    values = {}
    def read(ref):
        """Read a signed input, constant or previously evaluated gate."""
        v = abs(ref)
        if v == 1:
            bit = 1
        elif v < first:
            bit = (code >> (v - 2)) & 1
        else:
            bit = values[v]
        return bit if ref > 0 else 1-bit
    for ref in sorted(live):
        op, a, b = gates[ref-first]
        if op not in ("and", "or"):
            raise NonlinearRealizationRefused("unadmitted Boolean operation")
        values[ref] = read(a) & read(b) if op == "and" else read(a) | read(b)
    return [read(outputs[i]) for i in ids], len(live)


class SharedIntentionSession:
    """One source/ordered goal catalogue, independently admitted in this process.

    No external cache hit is accepted as proof. A new session with a saved
    receipt replays the original CIG-019 proof. Per-query placement always
    rechecks current local SAB inventory, leases and policy.
    """
    def __init__(self, variables, source, observations, targets, *, receipt=None,
                 max_pairs=500000, max_steps=200000, max_width=32):
        """Construct or independently re-admit a bounded shared certificate."""
        from shared_proof import synthesize_shared
        from verify_shared_proof import verify
        from verify_global_sufficiency import contract
        t0 = perf_counter_ns()
        targets = tuple(targets)
        if not 1 <= len(targets) <= 128:
            raise NonlinearRealizationRefused("bounded nonempty target catalogue required")
        self._base = NonlinearIntention(variables, tuple(source), tuple(observations),
                                        tuple(targets[0]))
        self._targets = tuple(contract(variables, [], [], f)[2] for f in targets)
        if len(set(self._targets)) != len(self._targets):
            raise NonlinearRealizationRefused("duplicate targets")
        budget = dict(max_pairs=max_pairs, max_steps=max_steps, max_width=max_width)
        if any(type(v) is not int or not 1 <= v <= BUDGET[k] for k,v in budget.items()):
            raise NonlinearRealizationRefused("receiver proof budget exceeded")
        self._contract = (variables, self._base.source, self._base.observations,
                          self._targets)
        self._budget = budget
        t1 = perf_counter_ns()
        if receipt is None:
            candidate = synthesize_shared(*self._contract, **budget)
        else:
            candidate = receipt
        t2 = perf_counter_ns()
        raw = _raw(candidate)
        if len(raw) > MAX_PROOF_BYTES:
            raise NonlinearRealizationRefused("shared proof exceeds byte budget")
        admitted = json.loads(raw)
        if not verify(*self._contract, admitted, **budget):
            raise NonlinearRealizationRefused("shared proof unresolved or failed independent replay")
        self._bytes = raw
        self._circuit = admitted["circuit"]
        self._statuses = tuple(g["status"] for g in admitted["goals"])
        self._proof = digest(admitted)
        self._ground = digest({"schema": SCHEMA, "contract": self._contract,
                               "proof": self._proof})
        self._sections = ReceiverSourceSectionMemory()
        t3 = perf_counter_ns()
        self._admission_ns = {"contract": t1-t0, "proof_discovery": t2-t1,
                              "independent_admission": t3-t2}

    @property
    def ground_digest(self):
        """Semantic identity is independent of any execution host."""
        return self._ground

    @property
    def proof_digest(self):
        """Identity of the independently admitted proof bytes."""
        return self._proof

    @property
    def admission_ns(self):
        """Measured cold or re-admission phases; detached copy."""
        return dict(self._admission_ns)

    def receipt(self):
        """Export a detached proof; recipients must independently replay it."""
        return json.loads(self._bytes)

    def realize(self, observed, indices, capacity: NonlinearCapacity):
        """Realize the requested projection with original-source witness audit."""
        from verify_global_sufficiency import value
        t0 = perf_counter_ns()
        indices = tuple(indices)
        if (not indices or any(type(i) is not int or not 0 <= i < len(self._targets)
                               for i in indices) or len(set(indices)) != len(indices)):
            raise NonlinearRealizationRefused("invalid target selection")
        if any(self._statuses[i] != "SUFFICIENT" for i in indices):
            raise NonlinearRealizationRefused("selected intention is not source-proved sufficient")
        code = qualify_observation(self._base, observed)
        expected = [value(self._targets[i], observed.model) for i in indices]
        t1 = perf_counter_ns()
        request = {"code": str(code), "targets": list(indices), "ground": self._ground}
        goal = digest({"ground": self._ground, "targets": indices})
        task = BootstrapTask("shared-proof-observation", goal, capacity.ingress,
                             "proof.code.v1", capacity.observer, "proof.observed.v1",
                             request, require_oracle=True)
        def decode(inp):
            """Execute only the verified dependency cone, not the source model."""
            if inp != request:
                raise BootstrapRefused("shared intention input substituted")
            result, work = evaluate_slice(self._circuit, int(inp["code"]),
                                           len(self._base.observations), indices)
            return {"values": result, "proof": self._proof, "evaluated_gates": work}
        def check_decode(inp, out):
            """Compare independent source truth; gate count is diagnostic."""
            return (inp == request and type(out) is dict
                    and set(out) == {"values", "proof", "evaluated_gates"}
                    and out["values"] == expected and out["proof"] == self._proof
                    and all(type(v) is int for v in out["values"])
                    and type(out["evaluated_gates"]) is int
                    and 0 <= out["evaluated_gates"] <= len(self._circuit["gates"]))
        def observe(prior):
            """Preserve the admitted result through the observation stage."""
            return prior
        def check_observe(prior, out):
            """Recheck projection against original source and proof identity."""
            return out == prior and check_decode(request, out)
        bindings = [RealizerBinding(h, DIRECT_OPERATION, decode,
                     digest({"host": h, "ground": self._ground, "op": DIRECT_OPERATION}),
                     check_decode) for h in sorted(set(capacity.interpreters))]
        bindings += [RealizerBinding(h, OBSERVE_OPERATION, observe,
                      digest({"host": h, "ground": self._ground, "op": OBSERVE_OPERATION}),
                      check_observe) for h in sorted(set(capacity.observers))]
        runtime = AdaptiveBootstrap(capacity.inventory, capacity.policy, bindings,
                                    capacity.carriers)
        plan = runtime.plan(task, coordinate=capacity.coordinate)
        t2 = perf_counter_ns()
        report = runtime.execute(task, plan, coordinate=capacity.coordinate)
        verify_bootstrap_report(report, task, plan)
        if not check_decode(request, report["output"]):
            raise NonlinearRealizationRefused("shared realization failed source oracle")
        t3 = perf_counter_ns()
        return {"ground": self._ground, "goal": goal, "proof": self._proof,
                "code": str(code), "targets": list(indices),
                "values": list(report["output"]["values"]),
                "evaluated_gates": report["output"]["evaluated_gates"],
                "total_gates": len(self._circuit["gates"]),
                "plan_digest": plan.fingerprint,
                "report_digest": report["report_digest"],
                "hosts": [s.locus for s in plan.steps if s.kind == "realize"],
                "spans_ns": {"source_qualification": t1-t0,
                             "route_discovery": t2-t1, "execution_and_check": t3-t2}}

    def realize_code(self, code, indices, capacity: NonlinearCapacity):
        """Use CIG-021's checked total-image section, not a supplied hidden state."""
        from source_section import section_witness
        t0 = perf_counter_ns()
        if type(code) is not int or not 0 <= code < 1 << len(self._base.observations):
            raise NonlinearRealizationRefused("invalid observation coordinate")
        section, built = self._sections.get_or_construct(self._base)
        witness = SourceObservation(section_witness(
            self._base.variables, self._base.observations, section, code))
        if qualify_observation(self._base, witness) != code:
            raise NonlinearRealizationRefused("section does not realize requested code")
        t1 = perf_counter_ns()
        result = self.realize(witness, indices, capacity)
        result["spans_ns"]["source_section"] = t1-t0
        result["section_constructed"] = built
        return result
