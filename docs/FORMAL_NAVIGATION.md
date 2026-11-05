# Formal Navigation: Symbolic Bounds, Equivalence, and Causal Dependencies

## Purpose

Contextual Process Navigation derives concrete paths through a finite declarative
transition algebra. This extension adds three formal methods for questions that
should not require enumerating every concrete state:

1. interval abstract interpretation over integer affine expressions;
2. strong bisimulation between finite labelled representations;
3. causal dependency DAGs checked using vector-clock partial order.

These are complementary analyses, not a universal solver. Each has a distinct
result contract and evidence boundary.

## 1. Integer affine terms

A symbolic linear expression has the form

\[
e(\mathbf{x})=c+\sum_{i=1}^{n}a_i x_i,
\qquad a_i,c\in\mathbb{Z}.
\]

`LinearExpression` stores a canonical, sorted coefficient vector. It supports
addition, subtraction, integer scaling, exact evaluation over a complete
valuation, and interval evaluation over abstract bounds.

`IntInterval([l,u])` denotes all integers from \(l\) through \(u\), inclusive.
A `None` lower endpoint denotes \(-\infty\); a `None` upper endpoint denotes
\(+\infty\). The interval is an enclosure, not a probability distribution.

A `LinearConstraint` expresses one relation between an affine expression and
zero:

\[
e(\mathbf{x})\in\{=,\ne,<,\le,>,\ge\}0.
\]

Its classifier returns one of:

- `entailed`: every integer valuation represented by the interval satisfies it;
- `refuted`: no represented valuation satisfies it;
- `unknown`: the interval abstraction cannot decide.

Unknown is deliberately retained as possible. It is never silently treated as
false.

## 2. Abstract interpretation

An `AbstractProgram` is a finite control graph. Each edge has a source and
target location, linear guards, and simultaneous affine assignments. The
initial state maps integer variables to intervals. Optional invariants are
linear constraints that must hold at every admitted location.

`AbstractReachabilityAnalyzer` performs a worklist fixed-point computation:

1. evaluate transition guards over the current interval state;
2. discard an edge only when a guard is definitely refuted;
3. evaluate all assignments against the same predecessor state;
4. discard a successor only when an invariant is definitely refuted;
5. join incoming abstract states at each control location;
6. widen expanding interval endpoints after a configured number of updates.

The interval operations are over-approximations. Correlations between variables
and disjoint alternatives may be lost. That loss can create false positives,
but it must not create a false proof of reachability.

The result is one of:

| Status | Meaning |
|---|---|
| `may_be_reachable` | An accepting abstract state remains compatible with the goal. |
| `proved_unreachable` | No accepting abstract state can satisfy the goal in the over-approximation. |
| `inconclusive` | The explicit transition-update budget was reached before a fixed point. |

`may_be_reachable` is not an existence proof for a concrete execution. The
result contains abstract bounds and goal dispositions, never a concrete path.
A concrete `NavigationWitness` must still come from the contextual navigator
or a future exact symbolic witness procedure.

The unreachability statement is relative to the finite transition graph,
affine integer semantics, and declared invariants supplied by the caller. It
does not certify that the caller's model describes every behavior of an
external process.

## 3. Representation equivalence by strong bisimulation

A `FiniteTransitionSystem` provides:
- a finite set of internal state identifiers;
- a JSON observation for each state;
- a finite set of labelled transitions;
- one initial state.

The internal identifiers may differ between representations. Observations
define the behavior visible to the comparison.

`compute_bisimulation(left, right)` computes the greatest strong bisimulation
relation. It starts with state pairs whose observations are equal, then
repeatedly removes pairs that fail either direction:

- **forth:** every labelled transition from the left state has a same-labelled
  transition from the right state to a related pair;
- **back:** every labelled transition from the right state has a same-labelled
  transition from the left state to a related pair.

The initial representations are equivalent only when their initial-state pair
survives the greatest-fixed-point computation.

This is a finite-state, strong, label-preserving equivalence check. It does not
establish equivalence for arbitrary infinite systems, weak/internal transitions,
timed equivalence, or effects omitted from the observation function. Choosing
the observation projection is part of the model and must be justified by the
caller.

`verify_bisimulation_relation` independently checks a supplied finite relation
against the forth/back obligations.

## 4. Causal dependency graphs

A `CausalDependencyGraph` describes event prerequisites as a directed acyclic
graph:

\[
G=(V,E),\qquad (a,b)\in E\Rightarrow a\prec b.
\]

The graph validates its event identities, edges, and acyclicity before use.
`evaluate()` then checks a mapping from event identifiers to `CausalStamp`
values produced by the existing temporal fabric.

Every declared event must be observed. For every edge \(a\rightarrow b\), the
vector-clock relation must be strictly `before`. Concurrent or reverse-ordered
stamps are blockers. Wall time, scheduler ticks, and monotonic timestamps are
not substituted for causal evidence.

The topological order is a deterministic structural order of the DAG. It is
not a measured schedule and does not allocate resources or authorize effects.
Causal stamps prove ordering relationships under the vector-clock identity
model; they do not authenticate the reporter. An authenticated telemetry
boundary remains necessary when stamps cross trust boundaries.

## 5. Combined use

The three methods answer different questions:

| Question | Mechanism | Positive result means |
|---|---|---|
| Could a family of states satisfy the target? | Abstract reachability | The over-approximation cannot rule it out. |
| Do two implementations preserve the same visible transition behavior? | Strong bisimulation | Their initial states are related by a verified finite bisimulation. |
| Are prerequisites causally ordered and present? | Causal dependency DAG | All required events are observed and each required edge is `BEFORE`. |

A safe coordination flow is:

1. use causal dependencies to determine whether inputs are ready;
2. use abstract reachability to eliminate impossible target regions;
3. compare candidate process representations by bisimulation;
4. use contextual navigation to derive a concrete path from the selected
   descriptor and context;
5. separately admit execution through the existing hypervisor and capabilities.

These analyses do not merge their evidence types. An abstract possibility is
not a path; a bisimulation relation is not a resource reservation; a causal
order is not authentication; a derived path is not an execution receipt.

## 6. Limits and next work

This build does not include general SMT/Presburger solving, polyhedral domains,
relational or disjunctive abstract domains, automatic abstraction refinement,
weak/timed bisimulation, graph-to-runtime dependency receipt transport, learned
prediction, or a process executor.

The interval domain can lose precision when variables are correlated. Strong
bisimulation is finite and only as meaningful as the selected observations.
Vector-clock size and actor identity lifecycle remain deployment concerns.

These limitations are explicit extension points. They should be improved by
adding new domains and proof procedures behind typed contracts, not by
weakening the evidence meaning of existing results.
