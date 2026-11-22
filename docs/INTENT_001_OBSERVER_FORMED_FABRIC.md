# INTENT-001 — The intention forms the processor and observer-host topology

**Research status:** bounded, executable finite deterministic observer-law experiment integrated with E-CPU's native SAB-001 substrate bootstrap. This does **not** claim an Internet-wide E-CPU deployment, automatic remote code installation, general-purpose machine discovery, indefinite execution, formal proof of arbitrary software equivalence, or computation in passive carriers.

## Inversion preserved in the README

E-CPU need not start with a permanent E-CPU processor or daemon. An observer can describe what must become observable, derive the distinctions and transformations necessary to realize it, identify already-capable computational loci and their communication relations, then execute and verify the formed architecture under receiver-owned permission. The **intention-relative semantic machine** may survive a change of physical arrangement without preserving a process.

The pipeline tested here:

```text
Source-law observation + requested output fields + action-word intention
                           |
                           v
            Finite future-observer quotient
                           |
                           v
    Generated registers, state transitions, observer readout
                           |
                           v
         Required compact/general interpreter operation
                           |
             +-------------+---------------+
             |                             |
    Source-declared host offers    Native SAB-001 receiver policy
             |                             |
             +---------intersection--------+
                           |
                           v
     Native typed carrier + generated local interpreter + observer
                           |
                           v
            Actual SAB-001 step receipts and output
                           |
                           v
   Independent original-source replay and report consistency check
```

## Exact mathematical contract

The finite source is a total deterministic Moore machine:

```text
M = (X, A, delta: X × A → X, O: X → V)
```

The intention chooses observer fields `F` (a projection of `O`). Two source states are equivalent when **every future action-word** yields identical projected observations:

```text
x ~_F y  iff  for every w in A*: O_F(delta*(x,w)) = O_F(delta*(y,w)).
```

The compiler starts with classes equal under `O_F` and repeatedly splits them when their successor classes differ under an action. Once stable, each class has a well-defined output and successor transition for every action. For a finite source with `n` states, the partition stabilizes after at most `n-1` strict refinements.

This is classical deterministic automaton minimization, tested here as an **observer-intention-derived computational architecture** rather than a fixed processor. It is not universal program synthesis. It is finite, source-declared and bounded to 64 states, eight actions, eight scalar observer fields and action words of length at most 128.

The generated machine contains the exact ordered source digest, the intention's fields, quotient groups, state-to-group interpretation, derived transition table and output decoder. Its register count is `ceil(log2(number of classes))`, an abstract information-state size, not measured RAM. The generated interpreter operation is `form.execute.compact.v1` for at most one register bit, otherwise `form.execute.general.v1`.

**Minimality is checked separately.** Beyond validating every source transition and observation against the claimed quotient, the verifier independently computes pairwise distinguishability from the original source with a fixed-point propagation that does *not* trust the producer's claimed groups. A rehashed but unnecessarily split machine fails, as does a wrong transition or a Ground bound to a changed source.

## Native E-CPU composition

The implementation imports **the original** `SubstrateObservation`, `OperationOffer`, `BootstrapPolicy`, `AdaptiveBootstrap`, `CarrierBinding`, `RealizerBinding`, `BootstrapTask`, and `verify_bootstrap_report`. It does not create a parallel routing service, checkpoint authority, Hypervisor or consensus layer.

The caller supplies an inventory and receiver-owned policy, plus **explicitly admitted interpreter and observer locus IDs** and locally controlled carrier bindings. The module forms the processor first and only then binds its finite software interpreter to those explicitly admitted loci. An untrusted offer is never an executable handler and does not grant rights. SAB-001 plans a least-declared-cost typed path, checks leases and carriers, revalidates before execution, executes the actual locally bound generated handler, and emits step receipts.

The generated handler uses the quotient. A separate local oracle replays the **original uncompressed source table** for the exact input and action word. The final witness performs another source-replay check. Receipt reconstruction additionally checks digest-chain consistency. These are software-observer checks within one trust domain, **not** cryptographic remote attestations or independently administered witnesses. A dishonest receiver could fabricate both executions.

The observer capacity is **latent** until the intention selects a specific projection and generated program. The source is supplied explicitly; the system does not yet discover unknown source laws from public Internet traffic.

## Falsifiable test

A single eight-state source supplies two possible observations: `parity` or `identity`. The source transition law is unchanged:

- `parity` intention forms two future-stable states, one abstract register bit, the `form.execute.compact.v1` operator, and the path through an admitted compact interpreter;
- `identity` intention forms eight states, three register bits, the `form.execute.general.v1` operator, and a *different host* and communication path;
- Remove the cheapest compact host, leaving another admitted compact host: the same parity Ground and output are recomputed over a different native SAB-001 path. No old process or session resurrection is required.
- A remote advertised compact operation with no receiver-admitted local handler is refused; so are missing permissions, expired resources, forged source/quotient structure, altered transport and unsupported problem descriptions.

The test suite checks generated versus original source results for **every initial state and every action word of length 0–4** for three observation projections. This is a finite exhaustive regression over those word lengths. The fixed-point proof covers unbounded finite action-word lengths under the *declared* source law, not external physical-world behavior.

## Reproduce

```sh
python -m pip install ".[dev]"
python -m pytest -q tests/test_intention_formed_fabric.py tests/test_substrate_bootstrap.py
```

A focused Linux/Windows × Python 3.11/3.14 Actions matrix checks both the new experiment and existing SAB-001. It is independent of the repository-wide general verification gate.

## Next research frontier

1. **Source acquisition rather than supplied model:** connect native IOS/INTERNET observation tools and VGI Grounds to infer/qualify an unknown environment transition grammar and preserve `unknown` when evidence is insufficient.
2. **Non-finite processor formation:** import independently checked PFI-001/NCR quotient and SFI-002/003 heterogeneous program-Ground claims. The current Moore partition is deliberately finite; it must not be mistaken for a SAT or general-program solver.
3. **Physical observer-host realization:** qualify an existing owned service/port through E-CPU's actual authenticated fabric and Hypervisor; measure bytes, energy, source validation, interpreter formation, and physical delivery. The present runtime is a **receiver-owned Python interpretation and carrier simulation**.
4. **Intention succession:** show what changes when requested observations expose previously erased distinctions. Preserve continuity only with an exact quotient map or a new source-state anchor, as proven in VL-I PFI-001.
5. **Composition beyond single machine:** use VLD's sheaf consistency tests to discover globally compatible observer-local Grounds, and let IPS-002 synthesize missing qualified communication relations rather than merely choosing among already offered typed paths.

The aspiration is not "keep E-CPU alive on the Internet" but **make a mathematical intention sufficient to articulate, form, and verify the computational organization its realization requires**.
