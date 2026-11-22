# INTENT-001 — Forming an observer-relative processor from a finite law

**Current capability.** Given a declared finite deterministic source law, requested observation fields and an action word, E-CPU constructs the minimal future-observation quotient, derives a typed interpreter operation, selects a receiver-admitted host/path through SAB-001, executes the generated interpreter and compares the result against the original source. A different intention can form a different processor and route from the same source.

- Source: [`mailcpu/intention_formed_fabric.py`](../mailcpu/intention_formed_fabric.py), especially `FiniteObserverLaw`, `form_observer_machine`, `verify_formed_machine` and `realize_formed_intention`.
- Native admission and execution: [`mailcpu/substrate_bootstrap.py`](../mailcpu/substrate_bootstrap.py), `AdaptiveBootstrap` and `verify_bootstrap_report`.
- Executable evidence: [`tests/test_intention_formed_fabric.py`](../tests/test_intention_formed_fabric.py).

## 1. Formal implementation contract

The supplied source is a **total deterministic Moore machine**

\[
M=(X,A,\delta,O),\quad
\delta:X\times A\rightarrow X,\quad
O:X\rightarrow V_1\times\cdots\times V_r.
\]

`FiniteObserverLaw` stores the ordered names `states`, `actions`, `fields`, an integer-indexed total `transitions` matrix, and a typed `observations` matrix. Its constructor enforces:

| Parameter | Implemented domain |
|---|---|
| Source states \(n=|X|\) | \(1\le n\le64\) |
| Actions \(|A|\) | \(1\le |A|\le8\) |
| Observer fields \(r\) | \(1\le r\le8\) |
| Field values | `str`, `int`, `bool`, or `None`, encoded canonically |
| Action word \(w\) | \(w\in A^*\), \(|w|\le128\) at replay/execution |

An intention selects a nonempty, duplicate-free ordered subset \(F\) of the source's field names. Let \(O_F\) be that projection and \(\delta^*(x,w)\) be the source state after applying action word \(w\). The observational equivalence used to **form the machine** is

\[
x\sim_F y
\iff
\forall w\in A^*:\;
O_F\bigl(\delta^*(x,w)\bigr)
=
O_F\bigl(\delta^*(y,w)\bigr).
\]

The generated state space is the quotient \(Q_F=X/{\sim_F}\). The executable machine contains exactly these operations:

\[
\hat\delta([x],a)=[\delta(x,a)],
\qquad
\hat O([x])=O_F(x),
\]

and for every source state \(x\) and finite action word \(w\),

\[
\boxed{\hat O\bigl(\hat\delta^*([x],w)\bigr)
=O_F\bigl(\delta^*(x,w)\bigr).}
\]

The generated register size is \(b_F=\lceil\log_2|Q_F|\rceil\), implemented by `(len(groups) - 1).bit_length()`. Operator selection is exact:

\[
\operatorname{op}(F)=
\begin{cases}
\texttt{form.execute.compact.v1},&b_F\le1,\\
\texttt{form.execute.general.v1},&b_F>1.
\end{cases}
\]

`register_bits` measures the abstract state encoding, not physical allocated RAM.

## 2. Formation algorithm and independent audit

**Formation — `form_observer_machine(source, fields)`:**

1. Reject missing, duplicated or undeclared observer fields.
2. Partition the source states by their canonically encoded current \(O_F\) values.
3. For every state, form its action-successor class signature \(\bigl(q(\delta(x,a))\bigr)_{a\in A}\).
4. Split each class by signature; sort the resulting groups by their first source index; repeat until stable (at most \(n-1\) strict refinements).
5. Emit the ordered groups, source-state-to-group map, projected outputs, quotient transitions, source fingerprint and requested fields.
6. Independently call `verify_formed_machine` before returning the machine.

**Independent minimality audit — `verify_formed_machine(source, machine)`:**

Initialize pairwise distinguishability without using the producer's groups:

\[
D_0(x,y)=[O_F(x)\ne O_F(y)].
\]

Propagate distinguishability through the original source transitions:

\[
D_{k+1}(x,y)=D_k(x,y)\lor
\bigvee_{a\in A}D_k\bigl(\delta(x,a),\delta(y,a)\bigr).
\]

At the fixed point \(D_*\), every claimed grouping must satisfy

\[
\boxed{q_F(x)\ne q_F(y)\iff D_*(x,y).}
\]

The verifier also checks the source digest, source/quotient table dimensions, group coverage, every projected output and every action successor. In particular, merely rehashing an unnecessarily split, semantically incorrect or source-mismatched machine cannot make it pass this audit.

**Identity invariant.** Both `FiniteObserverLaw.fingerprint` and `FormedObserverMachine.fingerprint` use SHA-256 over canonical JSON-like data, preserving exact ordered source and quotient identities. Neither machine digest includes selected host IDs, carrier bindings or route cost:

\[
\operatorname{fingerprint}(M,F)
\text{ is independent of eligible host/path placement.}
\]

The identity is thus stable under *re-formation from the same ordered source and intention*, while `BootstrapPlan.fingerprint` can differ when available placements change.

## 3. Current Python syntax

**Processor formation: runnable native API.** This is the eight-state source from the test fixture, with parity or identity as the requested projection.

```python
from mailcpu.intention_formed_fabric import (
    FiniteObserverLaw, form_observer_machine, verify_formed_machine,
)

source = FiniteObserverLaw(
    states=tuple(f"s{i}" for i in range(8)),
    actions=("forward", "backward"),
    fields=("parity", "identity"),
    transitions=tuple(((i + 1) % 8, (i - 1) % 8) for i in range(8)),
    observations=tuple((i % 2, i) for i in range(8)),
)
word = ["forward", "forward", "backward"]

parity = form_observer_machine(source, ("parity",))
identity = form_observer_machine(source, ("identity",))
assert verify_formed_machine(source, parity)
assert len(parity.groups) == 2 and parity.register_bits == 1
assert parity.operation == "form.execute.compact.v1"
assert len(identity.groups) == 8 and identity.register_bits == 3
assert identity.operation == "form.execute.general.v1"
assert parity.apply({"initial_state": "s3", "word": word})["observation"] == {"parity": 0}
assert identity.apply({"initial_state": "s3", "word": word})["observation"] == {"identity": 4}
```

**Native execution: current call signature.** Here `inventory`, `policy` and `carriers` are constructed with actual `SubstrateObservation`, `BootstrapPolicy` and `CarrierBinding` values by the receiver. The complete working fixture is `environment()` / `run()` in [`tests/test_intention_formed_fabric.py`](../tests/test_intention_formed_fabric.py).

```python
from mailcpu.intention_formed_fabric import realize_formed_intention

realization = realize_formed_intention(
    source, ("parity",), "s3", tuple(word),
    inventory, policy, carriers,
    admitted_interpreters=("compact-a", "compact-b", "general"),
    admitted_observers=("witness",),
    ingress="origin", observer="witness", coordinate=5,
)
assert realization.machine.fingerprint == parity.fingerprint
assert realization.report["output"]["observation"] == {"parity": 0}
```

Host names above are fixture-local, explicitly receiver-admitted locus IDs, not remote endpoints automatically discovered by an API. `form.execute.*` is a generated operation identifier whose handler is locally bound for these IDs.

## 4. Actual execution order: generated processor → admitted path → observation

```text
FiniteObserverLaw + selected fields + initial state + action word
    -> form_observer_machine -> verify_formed_machine
    -> source.replay (independent expected observation)
    -> BootstrapTask(require_oracle=True, ground_digest=machine.fingerprint)
    -> receiver-owned RealizerBinding entries:
         generated quotient handler + source-replay oracle
         observation projection + independent source-replay oracle
    -> AdaptiveBootstrap(inventory, policy, bindings, carriers)
    -> runtime.plan(task, coordinate) [typed offers, leases, allowed resources/edges]
    -> runtime.execute(task, plan, coordinate) [revalidation, carrier and handler]
    -> verify_bootstrap_report(report, task, plan)
    -> exact comparison: report.output vs original-source expected observation
    -> FormedRealization(machine, task, plan, report)
```

The source table is replayed by `FiniteObserverLaw.replay`; the generated quotient is executed by `FormedObserverMachine.apply`. Their separate paths permit comparing the compressed machine with the original law. `AdaptiveBootstrap` owns route choice, receiver permissions, typed delivery and step receipts; INTENT-001 adds no alternate scheduler or authority journal.

A route/host failure can change the placement plan while preserving the exact `machine.fingerprint` and output, provided a different eligible receiver-bound host and path satisfy the existing policy.

## 5. Verified behavior and scope

| Property | Concrete evidence |
|---|---|
| Different intentions form different processors | `test_same_source_different_intention_forms_different_processor_and_path`: parity = 2 classes/1 bit, identity = 8 classes/3 bits, and distinct admitted interpreter loci |
| Re-form after losing the cheapest host | `test_reformation_on_loss_of_preferred_host_preserves_intention_identity`: unchanged machine/ground/output, changed plan and host |
| Exact source-vs-quotient behavior | `test_source_equivalence_for_all_small_intended_action_words`: all eight initial states, three projections, all two-action words of length 0–4 |
| Independent verification of minimality | `test_rehashed_oversplit_quotient_cannot_claim_minimality`; `test_rehashed_wrong_quotient_or_source_fails_exact_audit` |
| Receiver permission and delivery checks | `test_advertisement_is_not_an_execution_capability`, `test_revoked_receiver_authority_and_expired_observations_refuse`, `test_broken_transport_does_not_become_a_successful_result` |
| Generated multi-hop path in E-CPU's owned network | `test_intention_forms_processor_over_native_owned_multihop_fabric`: five owned namespaces, five simulated links, ten ports; routed native fabric frames and journal checked |
| Type and action-domain checking | `test_typed_observations_distinguish_boolean_from_integer`, `test_generated_machine_rejects_unmodeled_state_or_action` |

The **mathematical claim** is equality of future projected observations over the declared finite deterministic source. The **execution evidence** is receiver-owned Python interpretation, SAB-001 local carrier bindings and an owned-network simulator; source replay and generated execution are checked within one administrative trust domain. The bounded source, permitted action words, explicit bindings and actual transport observations establish precisely what this experiment covers.

Reproduce:

```sh
python -m pip install ".[dev]"
python -m pytest -q tests/test_intention_formed_fabric.py tests/test_substrate_bootstrap.py
```

The focused workflow targets Linux and Windows with Python 3.11 and 3.14. Its results should be consulted for the commit under review.

## 6. What translation exposes: next constructions

1. **Projection refinement and continuity.** Suppose intention \(F_2\) requests more distinctions than \(F_1\). A state-only map \(h:Q_{F_1}\to Q_{F_2}\) that preserves the original source projection can exist only if \(\sim_{F_1}\subseteq\sim_{F_2}\). When \(F_2\) splits a former class, the earlier quotient alone cannot select its refined source state. **Build:** an explicit refinement witness or retained source-state anchor; **test:** information-preserving re-interpretation versus ambiguous/refused refinement.
2. **Semantic identity versus encoding identity.** `source.fingerprint` binds ordered state names and rows. Two isomorphic Moore sources with different state names/order can have different digests even when their requested future observations agree. **Build:** a separate canonical quotient-isomorphism certificate, retaining the exact source digest as provenance; **test:** permute source labels and compare canonical semantic identities without collapsing distinct observations.
3. **Verifier complexity.** The implementation's distinguishability verifier permits at most \(n^2\) passes over \(O(n^2|A|)\) pair/action checks, a conservative \(O(n^4|A|)\) upper bound. **Build:** profile this bounded cost and compare a worklist/backward-transition fixed point against the independent existing oracle; **test:** equal acceptance/refusal across generated finite sources.
4. **Source-law discovery.** Connect IOS/INTERNET path observations and VGI Ground qualification to infer candidate \(\delta\), retain unknown transitions explicitly, and only form an admitted quotient on a suitably qualified domain.
5. **Distributed realization.** Bind generated handlers through authenticated E-CPU ingress and independently controlled hosts; measure byte/energy/time cost, host failover, receipt validity and separate administrative witness claims. Compose local observation Grounds through VLD consistency and IPS-002 route synthesis.

The research direction is **intention → observer equivalence → formed processor → receiver-admitted host/path → independently checked result**, with each translation tied to an implemented object or an explicit next experiment.

For the editorial procedure used here, see [Implementation-first documentation](IMPLEMENTATION_FIRST_DOCUMENTATION.md).
