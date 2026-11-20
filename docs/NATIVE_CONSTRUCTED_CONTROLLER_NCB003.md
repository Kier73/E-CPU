# NCB-003 — Native admission of an intention-constructed coupled controller

**Status:** cross-repository proof-to-host research experiment. The producer is Navigable-Compute NCP-002 (PR #4, immutable merged commit \`e607fd80c00630f6b31e4c86b9b5ee8faebda410\`). The independently interpreting receiver is E-CPU. This does not make the mathematical Ground itself a credential, a real actuator or a stateful effect.

## Question

Can we start with **what system we want**, construct and verify the mathematical space of possible controllers, select a particular realizable controller coordinate, and then carry its exact requested action into E-CPU's existing *receiver-admitted* computational host fabric without inventing an action handler, host or authority from that mathematical certificate?

This is the next integration of the common research sequence:

    description → possibility relation → winning controller → selected instance
         → independent mathematical admission → live host resolution
         → native Hypervisor execution → verified observation → next coordinate

NCP-002 is particularly relevant because its construction already respects **joint resource capacities** and forbidden joint states. An isolated component may have an individually winning program that would conflict with another component's resources.

## Existing source and receiver contracts reused

**Navigable-Compute v0.5**, on its own branch, provides:

- \`GroundBrief\` with explicit finite state, goal, unsafe, initial and possible effect clauses.
- \`CoupledBrief\` with named resource capacities/claims and joint unsafe states.
- \`construct_coupled\` / \`navigate_coupled\` and \`CoupledGround.packet()\`.
- Its own \`coupled_verify.verify_coupled\` mathematical checker.

**E-CPU** retains authority:

- \`ComputationalAddress\` and \`ComputationalHostCatalogue\` carry exact content- and operator-contract-pinned workload metadata. They never grant capability.
- \`ComputationalAddressResolver\` resolves against the receiver's admitted System Ground, local live host, resource capacity and operator contract.
- \`ComputationalExecutionAdmissionCoordinator\` **re-resolves** that witness at execution time, validates the exact runtime binding and delegates to the original native \`VirtualLayerRuntime\` and \`Hypervisor\`.
- Each native \`OperatorSpec\` is registered on the receiver, has \`effect_mode="pure"\` and \`required_rights={"compute"}\`. The external NCP-002 description cannot register or execute a function.

Neither compiler's code is a substituted implementation of the other's authoritative pieces. The E-CPU module imports no NCP code.

## What the new bridge checks independently

\`mailcpu/constructed_controller_admission.py\` validates the **actual source packet** as E-CPU receives it. It does not trust the producer's verifier output or a stored digest:

1. Strict exact schema, bounded bytes, canonical NCP content SHA-256. No additional keys may introduce implicit authority.
2. Every original \`EffectCase\`: state interval, unique action name, relative/absolute outcome, disabled state, initial/goal/unsafe and unsafe joint-state tuple. Source semantics are reconstructed, not copied from an attacker-supplied output table.
3. Every \`SharedResource\`: legal factor/action identity, exact nonnegative capacity and unique claims. Recomputed joint actions exceeding capacity are disabled; goal factors remain terminal.
4. The complete bounded joint possibility relation and robust Bellman/AND-OR attractor, including **all** optimal options at each state and the precise worst-case rank. This second implementation does not import or invoke NCP-002's constructor/checker.
5. Exact mixed-radix controller coordinate, selected action table, global worst-case convergence and canonical whole-certificate digest. Numerical falsification is refused even with a recomputed hash.

This integration deliberately uses a **smaller admitted finite envelope**: 2–4 factors; up to 16 states per factor and 256 joint states; up to 128 joint action combinations; a 192-KiB packet ceiling. No assertion about universally efficient synthesis in coupled exponential spaces.

A checked controller's \`next_action(state)\` returns an inert instruction: exact packet, source, instance coordinate, current joint state, chosen local operations, safe possible successor states and descending rank. This mathematical instruction is **not authority**.

## Actual native pure operation execution

\`execute_constructed_action\` requires a receiver-provisioned \`NativeActionBinding\` for *every* selected nonterminal factor. It refuses missing or extra bindings, wrong action/factor, an unpinned controller digest, malformed workload inputs, and a host that cannot be found in the receiver's current native catalogue. All bindings are pre-resolved before any operation begins.

Each binding must carry a \`ComputationalAddress\` bound to the exact controller digest both as \`computational_ground_fingerprint\` and \`program_fingerprint\`. Its workload input must equal the exact controller digest, chosen action digest, factor, current local state and action name.

For every permitted action, the bridge invokes the *existing* \`ComputationalExecutionAdmissionCoordinator\`, which checks the live route again and calls the native Hypervisor. Missing \`compute\` capability, stale host, absent program pin or wrong runtime is refused without successfully publishing a step.

Only a native result of the exact expected type within the declared action outcomes can join the observed successor. The joint successor must also be in the independently computed coupled relation and strictly decrease the certified rank. A handler returning an unlisted state is refused even if the Hypervisor itself executed it. A successful \`QualifiedConstructedStep\` includes the exact action digest, next observed joint state and the real native route/admission/Hypervisor receipts.

**No unsafe non-atomic external effects are performed.** The connected handlers here are deterministic pure receiver-registered transitions. Native execution receipts do **not** authorize IPS-007/008 persistent writes: those still require a separately quorum-published Ground and receiver-owned effect barrier.

## Concrete cross-repository test

The dedicated GitHub Actions workflow uses two separate checkouts:

- E-CPU under test.
- **Pinned merged Navigable-Compute commit**, installed as a separate package, used only by the test producer—not by the E-CPU checker.

The external NCP-002 producer describes two 3-state controllers, one shared "advance" actuator, and derives a rank-optimal four-step joint controller (the independent, unconstrained design would require only two steps). E-CPU recomputes the entire mathematical certificate from the original clauses.

The native E-CPU test registers **two logical receiver-owned operator host loci**, each with separately registered \`advance\` and \`hold\` pure operators. The same admitted native System Ground controls both. The bridge executes all four dependency steps through the ComputationalHostCatalogue/Resolver/ExecutionAdmissionCoordinator/Hypervisor, checks each observed next state, and reaches the terminal pair \`(0,0)\`.

Adversarial controls:

- omit one required action binding, or remove one native host locus: **refuse before work**;
- remove compute permission from local authorized process: native Hypervisor/refreshed resolution refuses and the handler does not run;
- let native handler output an unlisted state: computation may have run, but no qualified controller transition is accepted;
- change the mathematical rank, action table, resource capacity, source effect clauses or instance coordinate, even recomputing SHA-256: independent verifier refuses;
- navigate to an alternative mathematically valid controller: it has a distinct digest, so old receiver-owned program pins do not automatically authorize it.

### Reproduce

    python -m pip install -e '.[dev]'
    git clone https://github.com/Kier73/Navigable-Compute --branch main --single-branch ncp-peer
    python -m pip install -e ./ncp-peer
    python -m pytest -q tests/test_constructed_controller_admission.py
    python -m pytest -q tests/test_computational_execution.py tests/test_computational_resolver.py

For exact historical reproduction, check out the commit \`e607fd80c00630f6b31e4c86b9b5ee8faebda410\` in \`ncp-peer\` first. Dedicated CI pins this exact commit.

## Measurement and semantics

The checked result is evidence that an intention-derived, finite fully observable **pure** controller can be executed through E-CPU's *existing authority mechanism*. The two host loci share the CI runner and HeadlessOS; they are **logical actors, not two independent machines**.

The E-CPU verifier has different implementation from the NCP-002 verifier but the same mathematical source; agreement is evidence of consistency, **not** a formal proof or physical verification of arbitrary actuators. The constructed transition outcomes were explicitly stipulated by the original description. The receiver's locally registered operations produce concrete outputs that are tested against them; this does not establish those relations for unqualified future hardware or external networks.

## The next experiment

Move beyond this pure action bridge to an **effectful, resource-aware admission boundary**: bind NCP-002 \`SharedResource\` claims to actual receiver-owned capacity reservations and IPS-008's authenticated durable handoff barrier. Require an exact **quorum-bound resource admission** before physical state changes; prove that concurrent constructed controllers cannot violate shared capacity when rehomed during a write.

That step must explicitly avoid the race between mathematical plan acceptance and actual receiver-side resource reservation. The admission can be considered correct only when the resource controls the atomic check.
