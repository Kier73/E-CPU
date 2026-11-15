# CAPACITY-002 — In-transit network-state capacity and exact neural realization

## Research question

Can E-CPU identify and navigate computational capacity **already present in the combined states of observer-hosts and in-transit communication paths**, even when the loci know nothing of E-CPU? Can the recognized relation also be expressed **directly in an existing E-CPU neural transition representation** without redefining the mathematical Ground or execution authority?

This experiment follows [Capacity Precedes Recognition](LATENT_PATH_CAPACITY.md) (E-CPU CAPACITY-001, pending integration review) and the merged [The Internet Is the Computer](THE_INTERNET_IS_THE_COMPUTER.md). It does **not** depend on CAPACITY-001's code or on physical-fiber apparatus. It uses E-CPU's current `mailcpu.law_certifier` and `mailcpu.transition_space` interfaces.

## The mathematical object is the whole network state

For `n` observer roles in an owned, finite, directed ring, let `H_i` be a one-bit observer-local state and `Q_i` a one-bit in-transit slot on the outgoing edge. Then:

```
S = (H_0,...,H_(n-1), Q_0,...,Q_(n-1)),   |S| = 2^(2n)
```

A currently unknown observer operation `f_i` accepts `(H_i,Q_(i-1))` and returns `(H_i',Q_i')`. All sites update **synchronously**. The installed E-CPU code never enters these sites: only a trusted local probe function can ask each site for its bounded input/output observation. `Q_i` is a real mathematical state variable of the path model; it is not merely a network latency annotation, host-local scratch register or an endpoint address.

There are four possible two-bit inputs to each `f_i`. A receiver observes each row twice, checks exact Boolean outputs and context, and reconstructs `F : S -> S` from the **declared directed wiring and complete local maps**. It thereby avoids enumerating every global state during *discovery*:

```
n = 4:   distinct local observations = 4*n = 16
         repeated local probe calls = 8*n = 32
         possible global states    = 2^(2*n) = 256
```

This smaller sample count is justified by the **explicit compositional factorization**, not by fitting an arbitrary global map from 16 examples. If a hidden operation also depends on an unmodeled input, time, remote queue or environmental state, the certificate's premise fails. A repeated probe catches some, not all, such deviations. Runtime guard/lease and independent environmental evidence remain separate obligations.

## Two foreign realizations of one Ground

Four local sites have a preexisting relation `f(h,incoming) = (h XOR incoming, h)`. A second set of four sites implements the same relation through a distinct function body and identity. These are *software-defined opaque test loci* that do not import or execute E-CPU. E-CPU observes their bounded responses and reconstructs the same exact network map:

```
H_i' = H_i XOR Q_(i-1)
Q_i' = H_i
```

These two path observations produce one mathematical Ground digest and different path/host/snapshot evidence digests. A relation does not need to have previously heard of the E-CPU to have this capacity. Conversely, a checksum does not mean that a foreign host has admitted an execution request.

## Navigation by an already present E-CPU facility

The network map is a finite deterministic functional graph. For an initial state, E-CPU's existing `brent_cycle` discovers `(mu,lambda)` for the orbit. Its existing `Law(family='fgraph', verdict='GROUND')` then resolves a requested logical coordinate by indexing a finite preperiod/cycle, without traversing every preceding time step or invoking any original site during the jump.

From the fixture initial state `(1,0,1,1,0,1,0,0)`:

```
t = 10^30 + 11
S(t) = (1,0,0,0,0,1,0,0)
mu = 0; lambda = 12
```

An independent hand-coded synchronous ring oracle verifies **every one of the 256 global transitions** and the distant result through its own cycle indexing. This is mathematical equivalence of the declared snapshot, not a general claim about arbitrary networks or physical independent processors. Orbit preparation is finite and nonzero work; only the logical-time query avoids `10^30` iterations. The current prototype rebuilds this finite orbit for each query; future persistent structural memory could amortize it further.

## Neural representation inside the Ground

`build_neural_realization` does not introduce a new neural inference framework. It translates each **fully observed local two-input truth table** to a typed `FiniteTransitionProgram` using existing `BooleanInput`, `BooleanConstant`, `BooleanNot`, `BooleanAnd`, `BooleanXor`, and `BooleanSelect` nodes. It then calls **existing E-CPU** `compile_live_compositional_transition_program` to build a genuine finite Boolean ReLU model.

The compiler is not allowed to define the Ground. Before reporting it as an acceptable alternative realization, the adapter independently checks **all 256 global inputs**:

```
observed component composition == typed Boolean program == compiled ReLU prediction
```

Any mismatch or changed program identity is refused. This is an **exact, compiled neural realization**, not training a model and not giving an ML policy the power to authorize communication, place a host or declare truth. It is a useful basis for later interfacing trained models as optional advisers or for VGI to discover smaller state representations and higher-dimensional composed operators. The full native E-CPU compiler must pass repository CI; local tests use a test-only compatible numeric ReLU compiler.

## Verification and trust boundary

- **Local tests:** `29/29` focused, in Python 3.13 with a test-only `Law`/Brent fixture and a test-only independently evaluated numeric ReLU compiler; these fixtures are **not** pushed to E-CPU.
- **Native tests:** `.github/workflows/network-state-capacity.yml` exercises actual E-CPU imports and neural compiler on Python 3.11 and 3.13, alongside existing network path and neural/stateful regressions. Its results must be observed before claiming native integration.
- **Negative controls:** unauthorized probes; expired site; duplicate role/host; partial or malformed local observations; nondeterministic repeated probe; wrong path or modified receipt; wrong neural program digest; deliberately corrupted neural prediction; changed local law, snapshot or placement.
- **No claim:** uncontrolled public-network execution, physically independent machines, arbitrary unseen state closure, source authentication by hash, network stack computation by passive fiber, learned model performance or model-derived authority.

This is a **compositional structural-capacity result**: a path's state space may be an implicit computer *before* E-CPU encounters it; E-CPU can make a verified part of that state space addressable, then realize its transitions through available computational representations.

## Reproduce

From the E-CPU repo root after installing its normal test dependencies:

```bash
python -m pytest -q tests/test_network_state_capacity.py
python -m examples.run_network_state_capacity
python -m pytest -q tests/test_transition_space.py tests/test_stateful_transition.py tests/test_transit_path_modes.py tests/test_observer_path_evidence.py
```

The research question that follows naturally: can E-CPU *persist the compositional proof* and navigate many requests directly from reused structural memory, and can VGI discover an even smaller invariant representation of the combined network/queue state without brute-force global enumeration?