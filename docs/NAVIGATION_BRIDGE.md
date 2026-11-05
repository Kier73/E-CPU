# Concrete-to-Abstract Navigation Bridge

## Purpose

The bridge compiles a restricted, explicitly declared subset of a concrete
`ProcessDescriptor` into the integer-affine `AbstractProgram` used by
[FORMAL_NAVIGATION.md](FORMAL_NAVIGATION.md). It connects contextual process
identity and bindings to conservative state-space analysis without turning
abstract possibilities into concrete paths.

## Supported projection

The first compiler version supports:

- flat, single-key state paths;
- integer equality and order comparisons (`eq`, `ne`, `lt`, `le`,
  `gt`, `ge`);
- integer literals and `ContextRef` values resolved through the supplied
  `ProcessContext`;
- ordered `set` and `increment` updates, folded into affine assignments;
- conjunctions of supported process invariants and semantic-goal conditions.

Boolean values are not integers in this contract. Floating-point arithmetic,
nested paths, membership/presence predicates, append/copy/delete updates, and
other non-affine operations are refused with `NavigationCompilationError`.
The compiler refuses the whole request if any guard, invariant, update, or goal
falls outside the supported language. It does not silently drop unsupported
semantics.

Only integer-valued initial fields are projected. Other untouched fields may
remain in the concrete JSON state, but they must not be referenced or mutated
by the compiled transition, invariant, or goal descriptions. A referenced
field that exists initially must have an exact integer value; Boolean and
floating-point coordinates are refused because the abstract domain is integer
only. A referenced field absent from the initial state is represented as
unconstrained in the abstract domain, which can introduce false positives but
cannot exclude a concrete integer value.

## Meaning of the result

`AbstractNavigationCompiler.compile(descriptor, address, context)` returns a
`CompiledNavigation` containing:

- the source descriptor, semantic-address, context and start-state digests;
- a one-location affine transition system derived from the concrete process;
- the affine goal constraints.

`analyze_compiled_navigation` delegates to the existing interval abstract
interpreter. It returns only `may_be_reachable`, `proved_unreachable`, or
`inconclusive`. A `may_be_reachable` result is an over-approximation, not a
proof that a concrete state or path exists. A `proved_unreachable` result is
relative to the supported projection and the exact source descriptions.

The compiler deliberately does not apply resource-capacity filters,
dependency readiness, capabilities, scheduler admission, or temporal
deadlines. Omitting transition resource restrictions enlarges the abstract
state-space and is therefore conservative for logical unreachability, but
cannot establish operational readiness.

`verify_abstract_compilation` recompiles the source request and compares the
canonical compilation digest. This detects a compilation detached from its
descriptor, semantic address, context bindings, or start state. It does not
authenticate the source or authorize execution.

## Evidence boundaries

The compiler does not produce a concrete transition sequence, reserve
resources, invoke a backend, or create an execution receipt. The existing
`ContextualNavigator` remains responsible for an exact bounded path and
`verify_navigation_witness` for replaying that path. The hypervisor remains
authoritative for every effect.

A future bridge may add relational abstract domains, arrays and structured
memory, or a compiler from MailCPU instruction blocks. Each extension must
preserve the fail-closed rule: unsupported constructs must be rejected or
soundly over-approximated, never silently omitted.
