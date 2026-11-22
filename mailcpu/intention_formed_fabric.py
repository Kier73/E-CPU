"""INTENT-001: form a minimal finite observer processor and admit its substrate path.

This is a bounded finite deterministic source-law experiment. Mathematical
realizability, local authority, and actual execution remain separate. Offered
host capacity never supplies executable code or receiver permission. Its
generated handlers execute *locally* through SAB-001; no remote installation
or physical Internet execution is claimed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .substrate_bootstrap import (
    AdaptiveBootstrap, BootstrapPlan, BootstrapPolicy, BootstrapRefused,
    BootstrapTask, CarrierBinding, RealizerBinding, SubstrateObservation,
    canonical, digest, name, verify_bootstrap_report,
)

_SCHEMA = "mailcpu.intention-formed-fabric.v1"
_COMPACT = "form.execute.compact.v1"
_GENERAL = "form.execute.general.v1"
_OBSERVE = "form.observe.v1"


@dataclass(frozen=True)
class FiniteObserverLaw:
    """Exact finite Moore source: state/action relations and state observations."""

    states: tuple[str, ...]
    actions: tuple[str, ...]
    fields: tuple[str, ...]
    transitions: tuple[tuple[int, ...], ...]
    observations: tuple[tuple[str | int | bool | None, ...], ...]

    def __post_init__(self) -> None:
        """Mathematics: certify a total deterministic finite source relation."""
        if not 1 <= len(self.states) <= 64 or not 1 <= len(self.actions) <= 8 or not 1 <= len(self.fields) <= 8:
            raise BootstrapRefused("finite observer-law dimension outside bounds")
        for tag, values in (("source state", self.states), ("action", self.actions), ("field", self.fields)):
            if any(type(x) is not str for x in values) or len(set(values)) != len(values):
                raise BootstrapRefused(f"duplicate or invalid {tag}")
            for x in values:
                name(x, tag)
        if len(self.transitions) != len(self.states) or len(self.observations) != len(self.states):
            raise BootstrapRefused("source law has incomplete state table")
        for row, observation in zip(self.transitions, self.observations):
            if len(row) != len(self.actions) or any(type(x) is not int or not 0 <= x < len(self.states) for x in row):
                raise BootstrapRefused("source transition is not total and state-indexed")
            if len(observation) != len(self.fields) or any(type(x) not in (str, int, bool, type(None)) for x in observation):
                raise BootstrapRefused("source observer fields must be finite scalar values")
            if len(canonical(observation)) > 1024:
                raise BootstrapRefused("source observation exceeds finite bound")

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: content-address the exact source without an executor identity."""
        return {"schema": "mailcpu.finite-observer-source.v1",
                "states": list(self.states), "actions": list(self.actions),
                "fields": list(self.fields),
                "transitions": [list(row) for row in self.transitions],
                "observations": [list(row) for row in self.observations]}

    @property
    def fingerprint(self) -> str:
        """Mathematics: preserve the exact source-law identity across host changes."""
        return digest(self.to_dict())

    def replay(self, initial: str, word: Sequence[str], fields: Sequence[str]) -> dict[str, Any]:
        """Mathematics: directly execute the original source table as a separate oracle."""
        if initial not in self.states or len(word) > 128 or any(a not in self.actions for a in word):
            raise BootstrapRefused("source coordinate or action word is not admitted")
        if not fields or len(set(fields)) != len(fields) or any(f not in self.fields for f in fields):
            raise BootstrapRefused("requested observer projection is not source-declared")
        state = self.states.index(initial)
        for action in word:
            state = self.transitions[state][self.actions.index(action)]
        return {field: self.observations[state][self.fields.index(field)] for field in fields}


@dataclass(frozen=True)
class FormedObserverMachine:
    """Minimal future-observation quotient and generated transition microarchitecture."""

    source_digest: str
    fields: tuple[str, ...]
    actions: tuple[str, ...]
    states: tuple[str, ...]
    groups: tuple[tuple[int, ...], ...]
    state_groups: tuple[int, ...]
    outputs: tuple[tuple[Any, ...], ...]
    transitions: tuple[tuple[int, ...], ...]

    @property
    def register_bits(self) -> int:
        """Mathematics: ceil(log2(number of observer-distinguishable state classes))."""
        return (len(self.groups) - 1).bit_length()

    @property
    def operation(self) -> str:
        """Select a typed interpreter capacity from the generated machine size."""
        return _COMPACT if self.register_bits <= 1 else _GENERAL

    def to_dict(self) -> dict[str, Any]:
        """Mathematics: bind source, intention, quotient and generated instructions."""
        return {"schema": _SCHEMA, "source_digest": self.source_digest,
                "fields": list(self.fields), "actions": list(self.actions),
                "states": list(self.states), "groups": [list(x) for x in self.groups],
                "state_groups": list(self.state_groups),
                "outputs": [list(x) for x in self.outputs],
                "transitions": [list(x) for x in self.transitions],
                "register_bits": self.register_bits, "operation": self.operation}

    @property
    def fingerprint(self) -> str:
        """Mathematics: identify the generated processor independently of placement."""
        return digest(self.to_dict())

    def apply(self, value: Mapping[str, Any]) -> dict[str, Any]:
        """Execute the generated quotient transitions, not the original source replay."""
        if not isinstance(value, Mapping) or set(value) != {"initial_state", "word"}:
            raise BootstrapRefused("formed interpreter requires exact typed input")
        initial, word = value["initial_state"], value["word"]
        if type(initial) is not str or initial not in self.states or type(word) is not list or len(word) > 128:
            raise BootstrapRefused("invalid formed interpreter coordinate")
        state = self.state_groups[self.states.index(initial)]
        for action in word:
            if type(action) is not str or action not in self.actions:
                raise BootstrapRefused("unknown generated instruction")
            state = self.transitions[state][self.actions.index(action)]
        return {"initial_state": initial, "word": list(word),
                "observation": dict(zip(self.fields, self.outputs[state])),
                "quotient_state": state, "machine_digest": self.fingerprint}


def form_observer_machine(source: FiniteObserverLaw, fields: Sequence[str]) -> FormedObserverMachine:
    """Mathematics: refine observer-equivalence until every action respects the quotient.

    Start with states indistinguishable under the requested projection, then
    split a class whenever one action leads to distinguishable successor
    classes. Stabilization yields the smallest deterministic Moore quotient
    preserving every future requested observation word (finite source).
    """
    if not isinstance(source, FiniteObserverLaw):
        raise BootstrapRefused("a declared finite source law is required")
    selected = tuple(fields)
    if not selected or len(set(selected)) != len(selected) or any(type(f) is not str or f not in source.fields for f in selected):
        raise BootstrapRefused("intention requests undeclared or duplicate observations")
    positions = tuple(source.fields.index(f) for f in selected)
    by_output: dict[bytes, list[int]] = {}
    for i, row in enumerate(source.observations):
        by_output.setdefault(canonical(tuple(row[p] for p in positions)), []).append(i)
    groups = tuple(sorted((tuple(x) for x in by_output.values()), key=lambda x: x[0]))
    for _ in range(len(source.states)):
        indices = [0] * len(source.states)
        for idx, group in enumerate(groups):
            for state in group:
                indices[state] = idx
        next_groups: list[tuple[int, ...]] = []
        for group in groups:
            signatures: dict[tuple[int, ...], list[int]] = {}
            for state in group:
                signature = tuple(indices[dst] for dst in source.transitions[state])
                signatures.setdefault(signature, []).append(state)
            next_groups.extend(tuple(members) for members in signatures.values())
        refined = tuple(sorted(next_groups, key=lambda x: x[0]))
        if refined == groups:
            break
        groups = refined
    else:
        raise BootstrapRefused("finite observer partition did not stabilize")
    indices = [0] * len(source.states)
    for idx, group in enumerate(groups):
        for state in group:
            indices[state] = idx
    machine = FormedObserverMachine(
        source.fingerprint, selected, source.actions, source.states,
        groups, tuple(indices),
        tuple(tuple(source.observations[group[0]][p] for p in positions) for group in groups),
        tuple(tuple(indices[dst] for dst in source.transitions[group[0]]) for group in groups),
    )
    verify_formed_machine(source, machine)
    return machine


def verify_formed_machine(source: FiniteObserverLaw, machine: FormedObserverMachine) -> bool:
    """Mathematics: check exact quotient semantics and rederive the canonical minimum."""
    if not isinstance(machine, FormedObserverMachine) or machine.source_digest != source.fingerprint or \
       machine.actions != source.actions or machine.states != source.states:
        raise BootstrapRefused("formed machine is not bound to this source law")
    selected = machine.fields
    if not selected or len(set(selected)) != len(selected) or any(f not in source.fields for f in selected):
        raise BootstrapRefused("invalid machine observer projection")
    n = len(source.states)
    if sorted(x for group in machine.groups for x in group) != list(range(n)) or \
       len(machine.state_groups) != n or len(machine.outputs) != len(machine.groups) or \
       len(machine.transitions) != len(machine.groups):
        raise BootstrapRefused("formed machine partitions or dimensions are invalid")
    for index, group in enumerate(machine.groups):
        if not group or len(machine.transitions[index]) != len(source.actions):
            raise BootstrapRefused("incomplete generated operation table")
        for state in group:
            if machine.state_groups[state] != index or \
               tuple(source.observations[state][source.fields.index(f)] for f in selected) != machine.outputs[index] or \
               tuple(machine.state_groups[dst] for dst in source.transitions[state]) != machine.transitions[index]:
                raise BootstrapRefused("generated machine is not source-equivalent")
    # Independently derive pairwise distinguishability from the original
    # observations, WITHOUT consulting the generated partition. Distinct
    # classes are minimal iff every cross-class pair has some finite action
    # word that separates its source observations. Fixed-point propagation
    # is exact on a finite deterministic transition system.
    distinguished = [[any(source.observations[i][source.fields.index(f)] !=
                          source.observations[j][source.fields.index(f)] for f in selected)
                      for j in range(n)] for i in range(n)]
    for _ in range(n * n):
        changed = False
        for i in range(n):
            for j in range(i + 1, n):
                if not distinguished[i][j] and any(
                    distinguished[source.transitions[i][a]][source.transitions[j][a]]
                    for a in range(len(source.actions))
                ):
                    distinguished[i][j] = distinguished[j][i] = True
                    changed = True
        if not changed:
            break
    for i in range(n):
        for j in range(i + 1, n):
            if (machine.state_groups[i] != machine.state_groups[j]) != distinguished[i][j]:
                raise BootstrapRefused("formed quotient not observationally minimal")
    return True


@dataclass(frozen=True)
class FormedRealization:
    """One source-qualified formed machine plus native SAB-001 actual execution evidence."""

    machine: FormedObserverMachine
    task: BootstrapTask
    plan: BootstrapPlan
    report: dict[str, Any]


def realize_formed_intention(
    source: FiniteObserverLaw, fields: Sequence[str], initial_state: str,
    word: Sequence[str], inventory: SubstrateObservation, policy: BootstrapPolicy,
    carriers: Sequence[CarrierBinding], *,
    admitted_interpreters: Sequence[str], admitted_observers: Sequence[str],
    ingress: str, observer: str, coordinate: int,
) -> FormedRealization:
    """Form a processor from intended observations, then use locally admitted host/path capacity.

    The executable adapter is installed only for explicitly receiver-admitted
    locus IDs; advertisements and host hints cannot grant it authority.
    Carrier deliveries and observer execution are SAB-001 local simulation.
    """
    machine = form_observer_machine(source, fields)
    request = {"initial_state": initial_state, "word": list(word)}
    expected = source.replay(initial_state, request["word"], machine.fields)
    task = BootstrapTask(
        "formed-observation", machine.fingerprint, ingress, "form.request.v1",
        observer, "form.observed.v1", request, require_oracle=True,
    )
    def interpret(value: Any) -> dict[str, Any]:
        """Mathematics: execute the newly generated quotient instructions."""
        return machine.apply(value)

    def check_interpret(previous: Any, result: Any) -> bool:
        """Mathematics: independently re-execute the original source relation."""
        try:
            expected_result = source.replay(previous["initial_state"], previous["word"], machine.fields)
            return type(result) is dict and result == machine.apply(previous) and \
                   result["observation"] == expected_result
        except (KeyError, TypeError, ValueError, IndexError):
            return False

    def observe(value: Any) -> dict[str, Any]:
        """Project the qualified result into the exact requested observation."""
        return {"observation": value["observation"], "machine_digest": value["machine_digest"]}

    def check_observe(previous: Any, result: Any) -> bool:
        """Mathematics: compare observed data with source replay, not host assertions."""
        try:
            return type(result) is dict and result == {
                "observation": source.replay(previous["initial_state"], previous["word"], machine.fields),
                "machine_digest": machine.fingerprint,
            }
        except (KeyError, TypeError, ValueError, IndexError):
            return False

    bindings: list[RealizerBinding] = []
    for host in sorted(set(admitted_interpreters)):
        name(host, "admitted interpreter locus")
        bindings.append(RealizerBinding(host, machine.operation, interpret,
                         digest({"adapter": _SCHEMA, "host": host, "machine": machine.fingerprint}),
                         check_interpret))
    for host in sorted(set(admitted_observers)):
        name(host, "admitted observer locus")
        bindings.append(RealizerBinding(host, _OBSERVE, observe,
                         digest({"adapter": _SCHEMA, "witness": host, "machine": machine.fingerprint}),
                         check_observe))
    runtime = AdaptiveBootstrap(inventory, policy, bindings, carriers)
    plan = runtime.plan(task, coordinate=coordinate)
    report = runtime.execute(task, plan, coordinate=coordinate)
    verify_bootstrap_report(report, task, plan)
    if report["output"] != {"observation": expected, "machine_digest": machine.fingerprint}:
        raise BootstrapRefused("final observation differs from independently replayed source")
    return FormedRealization(machine, task, plan, report)
