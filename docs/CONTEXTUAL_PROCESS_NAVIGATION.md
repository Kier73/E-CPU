# Contextual Process Navigation

## Purpose

Contextual Process Navigation gives a process a stable logical identity and a
reconstructable state-space without requiring every possible state to remain
materialized. A request identifies a process version and a target condition.
The resolver combines that description with current context and derives a
bounded path to the target.

The governing principle is:

> Preserve the identity and laws of a computation. Let context determine which
> part of its state-space is rendered. Materialize only what must become active.

This specification extends the symbolic-capacity model in
[STATE_SPACE_NAVIGATION.md](STATE_SPACE_NAVIGATION.md). It defines the first
runtime slice; it does not claim arbitrary symbolic theorem proving or
unbounded state-space traversal.

## 1. The three inputs

A process descriptor is

\[
D=(p,v,S_0,T,I,R),
\]

where:

- \(p,v\) identify a stable process and its logic version;
- \(S_0\) is an optional declared initial state;
- \(T\) is a finite set of guarded transition rules;
- \(I\) is a conjunction of state invariants;
- \(R\) is an independent readiness contract.

A semantic address is

\[
A=(p,v,G),
\]

where \(G\) is the desired state predicate. The address names *what must be
resolved*, not a host, socket, memory address, or already-running process.

A process context is

\[
C=(S_c,B_c,D_c,M_c,K_c,\Theta_c,\beta),
\]

where:

- \(S_c\) is an optional current materialized state;
- \(B_c\) is a finite mapping of contextual bindings;
- \(D_c\) is the set of dependency identifiers already resolved by the caller;
- \(M_c\) is available resource capacity;
- \(K_c\) is the set of capability labels available to the readiness check;
- \(\Theta_c\) is an optional typed `TemporalFrame`;
- \(\beta\) contains explicit expansion and depth limits.

The current state takes precedence over \(S_0\). If neither is available,
navigation refuses rather than inventing a starting point.

## 2. Declarative state language

The initial implementation uses finite JSON objects as states. Object-key paths
are tuples such as `("registers", "r0")`. It does not execute Python callbacks,
evaluate strings as code, or load executable code from an address.

`StateCondition` provides the closed predicate vocabulary:

| Operator | Meaning |
|---|---|
| `present`, `absent` | Whether a path exists |
| `eq`, `ne` | Typed equality or inequality |
| `lt`, `le`, `gt`, `ge` | Numeric or lexicographic string comparison |
| `in` | Membership in a finite list |

A `StatePattern` is a conjunction of conditions. The empty conjunction is true.

`ContextRef("target")` is a typed reference to a value supplied by the
`ProcessContext.bindings` mapping. This lets one process description resolve
different targets under different contexts. Its serialized form is the
reserved tagged object `{"$context":"target"}`. Missing bindings fail closed.

Transition updates are sequential and declarative:

- `set`: replace or create a leaf under an existing object parent;
- `increment`: add a finite numeric operand to an existing numeric leaf;
- `append`: append a JSON value to an existing list;
- `copy`: copy a value from another state path;
- `delete`: remove an existing leaf.

A `TransitionRule` has a stable identifier, a guard, ordered updates, and
per-transition resource-capacity requirements. A `ProcessDescriptor` sorts
rules by identifier, rejects duplicate IDs, and computes a canonical SHA-256
digest over its versioned description.

The descriptor is a closed description only relative to this declared
predicate and update language. It does not denote arbitrary Python behaviour,
all imaginable mathematical transformations, or every real-valued state.

## 3. Contextual rendering and navigation

The resolver is the function

\[
\mathcal{R}(D,A,C)\rightarrow N.
\]

It performs deterministic breadth-first search from the current or initial
state. At each candidate:

1. the transition guard must match the candidate state and context bindings;
2. each update is applied to a detached state value;
3. every declared process invariant must hold on the successor;
4. the transition's resource requirements must fit the context capacity;
5. the resulting state is checked against the semantic address goal.

Rules are visited in sorted identifier order. Therefore the first successful
path has the minimum number of transition edges; equal-length alternatives
have a stable identifier-based tie-break. This is a shortest-transition-count
policy, not a claim of globally minimum energy, wall time, monetary cost, or
resource consumption.

The context supplies two finite search limits:

- `max_expansions` bounds the number of states expanded (default 10,000);
- `max_depth` bounds the number of transitions in a candidate path (default 256).

Search stops with a typed status rather than returning an incomplete path as
success:

| Status | Meaning |
|---|---|
| `found` | A path to the goal was derived |
| `already_satisfied` | The starting state already satisfies the goal |
| `unreachable` | The explored bounded graph contains no valid path |
| `resource_blocked` | At least one enabled transition was excluded by resource capacity and no path was found |
| `budget_exhausted` | Expansion or depth limits prevented a complete conclusion |

A result's `resource_envelope` records the maximum per-transition capacity
requirement encountered on the selected path. These values are simultaneous
capacity requirements, **not cumulative resource consumption**.

## 4. Derivation witness and execution boundary

A successful `NavigationResult` contains:

- a sequence of transition identifiers;
- a derived final-state projection;
- the descriptor, semantic-address, context, start-state, and final-state
  digests in a `NavigationWitness`;
- the explored-state count and resource envelope.

`verify_navigation_witness` independently replays the transition identifiers
against the same descriptor and context, rechecks guards and invariants, and
compares the resulting endpoint and goal. This establishes that the returned
path is a valid derivation under the supplied model.

It does **not** establish that a process executed the path, that a remote
endpoint received it, or that any external side effect occurred. Digests
provide content integrity, not sender authentication or authority. A predicted
or derived state must not be recorded as a committed execution state.

The navigator never mutates `ProcessContext.current_state` and never invokes
an external handler. A later executor must separately admit and perform the
selected operations through the existing hypervisor and capability boundary.

## 5. Readiness is not scheduling

`ReadinessContract` evaluates independent prerequisites:

\[
\operatorname{Ready}(p)=
P_{\mathrm{state}}\land P_{\mathrm{dependencies}}\land
P_{\mathrm{resources}}\land P_{\mathrm{capabilities}}\land
P_{\mathrm{temporal}}.
\]

Its `ReadinessResult` returns all unmet conditions as stable blocker codes.
Dependencies are caller-supplied resolved identifiers; resource capacity is
not reserved; capability labels in this context are a logical precheck, not
an authorization grant. The hypervisor remains authoritative at every effect
boundary.

Temporal requirements ask only whether the optional `TemporalFrame` contains
the selected typed domains. They do not convert clock values, establish
deadlines, compare remote clocks, or consume time. Navigation and readiness
can therefore be evaluated without a clock. The temporal fabric remains a
separate source of execution budgets and event/causal coordinates.

## 6. Example

```python
from mailcpu.navigation import (
    ConditionOperator, ContextRef, ContextualNavigator, ProcessContext,
    ProcessDescriptor, SemanticAddress, StateCondition, StatePattern,
    StateUpdate, TransitionRule, UpdateOperation, verify_navigation_witness,
)

logic = ProcessDescriptor(
    "counter",
    "1",
    transitions=(
        TransitionRule(
            "increment",
            guard=StatePattern((
                StateCondition(("count",), ConditionOperator.LT, ContextRef("target")),
            )),
            updates=(StateUpdate(("count",), UpdateOperation.INCREMENT, 1),),
        ),
    ),
    initial_state={"count": 0},
)
request = SemanticAddress(
    "counter",
    "1",
    StatePattern((StateCondition(("count",), ConditionOperator.EQ, ContextRef("target")),)),
)
context = ProcessContext("counter", bindings={"target": 4})
result = ContextualNavigator().navigate(logic, request, context)

assert result.status.value == "found"
assert result.to_dict()["final_state"] == {"count": 4}
assert verify_navigation_witness(logic, request, context, result)
```

The descriptor is unchanged when the target changes from 4 to another bound
value. Context renders a different request over the same transition law.

## 7. Current limits and next stages

This first build deliberately uses finite JSON states and explicit breadth-first
search. The next formal extensions should be added behind the same contracts,
not smuggled into the current resolver:

1. symbolic terms and constraint solving for state families not explicitly
   enumerated by BFS;
2. abstraction and reachability bounds for large or infinite domains;
3. equivalence/bisimulation witnesses for alternate process representations;
4. dependency receipts bound to authenticated actor identities;
5. resource-aware multiobjective path ranking and consumptive budgets;
6. Petri-net/dataflow readiness for concurrent prerequisites;
7. calibrated predictors whose outputs remain advisory until validated.

The current runtime does not implement those extensions. In particular, it
does not materialize all possible states, prove completeness of a caller's
process descriptor, or implement semantic network routing. It establishes the
first executable contract for resolving *a described process under context*.
