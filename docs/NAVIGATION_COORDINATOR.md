# Unified Navigation Coordination

## Purpose

`NavigationCoordinator` composes the evidence-producing stages introduced by
contextual navigation, formal navigation, and the concrete-to-abstract bridge.
It returns a digest-bound admission proposal only when an exact concrete path
has been derived and every requested gate has passed.

The coordinator is intentionally not an executor, scheduler, policy engine, or
capability issuer. It does not call a backend, mutate process state, reserve
resources, or authorize an effect.

## Coordination sequence

For one `(ProcessDescriptor, SemanticAddress, ProcessContext)` request:

1. Compile the supported integer-affine projection and run conservative
   abstract reachability. Unsupported constructs are retained as an explicit
   compilation diagnostic; they do not erase or replace concrete navigation.
2. Evaluate the optional causal dependency DAG against the supplied vector
   clock stamps. Every declared event must be observed and each graph edge must
   be strictly `BEFORE`.
3. If a pair of finite transition systems is supplied, compute strong
   label-preserving bisimulation. Equivalence is a mandatory gate only when
   `require_representation_equivalence=True`.
4. Run the exact bounded `ContextualNavigator` and independent readiness
   contract evaluation.
5. Produce an `ExecutionAdmissionRequest` only when a concrete path is found,
   readiness succeeds, all supplied causal prerequisites are ready, and every
   explicitly required representation comparison passes.

The abstract and concrete analyses are deliberately both run. Abstract
`proved_unreachable` alongside a concrete witness is reported as
`abstract_contradiction`, never silently accepted. Abstract
`may_be_reachable` is not a concrete witness. Abstract `inconclusive` does
not invalidate a separately verified concrete path.

## Dispositions

| Disposition | Meaning |
|---|---|
| `ready` | A concrete path and witness exist; readiness and all requested gates pass; an admission proposal is present. |
| `already_satisfied` | The current state already matches the goal; no execution proposal is emitted. |
| `causal_blocked` | At least one requested event is absent or a dependency edge is not strictly BEFORE. |
| `representation_mismatch` | Representation equivalence was required but the supplied systems are not bisimilar. |
| `not_ready` | Concrete navigation found a path, but the readiness contract has blockers. |
| `abstract_unreachable` | Abstract analysis and concrete navigation both fail to find a route, with the abstraction proving the goal excluded. |
| `abstract_contradiction` | Abstract analysis proves unreachable while concrete navigation returns a witness; this is a model/compiler soundness alarm. |
| `resource_blocked` | The concrete route requires resources not present in the context. |
| `budget_exhausted` | The concrete search hit its explicit expansion/depth bound. |
| `unreachable` | Concrete search exhausted its bounded state-space without finding the goal; abstract analysis may still retain a false-positive possibility. |

## Digest binding and replay

The coordinator's context digest covers more than the legacy resolution digest:
current state, bindings, resolved dependencies, resource capacity,
capabilities, search budgets, and the complete typed temporal frame.

The admission proposal binds:
- descriptor, semantic address, complete context and starting-state digests;
- concrete witness and final-state digests;
- readiness evidence;
- transition IDs and the peak resource envelope;
- any abstract compilation/result digest and analysis-budget/widening configuration digest;
- any causal graph and observed-stamp digest;
- any bisimulation evidence digest and whether equivalence was mandatory.

`verify_navigation_coordination` recomputes the analyses and compares the
complete result and proposal digests. It also independently replays the
concrete navigation witness and recompiles the abstract projection when that
projection is supported.

## Evidence and authority boundaries

An `ExecutionAdmissionRequest` is explicitly non-authoritative. It is a
structured proposal for a future hypervisor adapter, not a capability, grant,
signature, reservation, or execution receipt. A receiving hypervisor must
revalidate the descriptor identity, current state, resource capacity, local
capabilities, causal evidence provenance, policy and any applicable deadlines
at admission time. Context digest equality alone does not authenticate a
reporter or prevent stale-state races.

A supplied bisimulation pair compares only those two caller-supplied finite
systems and their JSON observations. The coordinator does not automatically
compile a `ProcessDescriptor` into an LTS or assert that either supplied
system faithfully represents it. Callers must establish that correspondence
before treating the comparison as an implementation-equivalence guarantee.

The coordinator does not automatically construct causal receipts. It evaluates
the graph against supplied `CausalStamp` values; authentication, durable
receipt transport, cross-host actor identity and replay protection remain
responsibilities of the surrounding communication system.

## Tests

The suite checks successful plan creation and independent replay, context
digest coverage, readiness refusal, missing and concurrent causal events,
strict vector-clock precedence, mandatory and advisory bisimulation, explicit
abstract-compilation unavailability, abstract/concrete unreachability,
already-satisfied targets, resource refusal, bounded-search exhaustion, and
the integer-bridge fail-closed regression.
