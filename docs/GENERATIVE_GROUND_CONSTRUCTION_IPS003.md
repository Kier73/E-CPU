# IPS-003 — Generative Ground Construction from a Needed Behavior

**Status:** bounded mathematical synthesis and executable local active-port demonstration. Not arbitrary software synthesis, remote physical host qualification, automatic creation of an E-CPU route, or evidence that passive transport performs arithmetic.

## Hypothesis

Can the required behavior of a virtual system determine its implementation *before* an executable instance exists, and can that implementation be independently checked using E-CPU's existing machinery?

The starting point is an imposed behavior, not a time-series predictor. We **declare the affine family** over Z/mZ, giving the exact desired observations at inputs 0 and 1:

    f(0) = u, f(1) = v
    => f(x) = ((v-u)*x + u) mod m

The affine-family assumption is essential: two values do not determine an arbitrary nonlinear function. Additional specified challenge points are checked for contradictions rather than treated as measurements.

The receiver supplies a fixed finite palette of mathematical transformations P_i(x) = a_i*x + c_i modulo m, each with a positive symbolic cost. The compiler derives the least-cost sequence of those transformations that realizes the required behavior. The transformation state transition is

    (a,c) ---P_i---> (a_i*a, a_i*c+c_i) mod m

This is shortest-path search in a bounded affine transformation monoid, **not a time-step simulation** and not arbitrary remote execution.

## Existing E-CPU components used

- IPS-002 ProposedRelation: retain the missing source/target relation and its Ground, context and verification obligation. No E-CPU EvidencePathEdge is synthesized from a wish.
- ComputationNode / NavigableComputationDAG: compile the derived primitive word into a content-addressed DAG and commit each predecessor-dependent result.
- SAB-008 TwoPortArithmeticGate: perform real bounded arithmetic frames in the existing active-port **software simulation**.
- SAB-008 AffineGround / GroundIntention / PortGroundRealizer: evaluate the *complete* derived law as an independent algorithm for the same exact mathematical Ground.
- SAB-008 RealizationPolicy / realize_under_contract / verify_receipt: enforce an existing local policy and verify mathematical observation identity.

No replacement Hypervisor, runtime, persistent ledger or observer authority is installed. The receipt carries the native DAG checkpoint, bounded gate frames, the SAB-008 Ground receipt and output. Verification reconstructs each DAG result independently of the original claimed snapshot, checks exact port-frame input and output digests, exhaustively checks the full finite domain, and invokes SAB-008 receipt verification. A correctly rehashed but numerically wrong native DAG is a negative control.

Both algorithms run within the same Python environment; this is independent *mathematical* verification, **not independent physical attestation**. A modeled active gate is not a passive Internet wire.

## Falsifiable test

Describe an intended function over Z/17Z:

    f(0) = 4 ; f(1) = 11  =>  f(x) = 7*x + 4 mod 17

Available transformations:

    P1(x) = 3*x + 2
    P2(x) = 8*x + 5
    P3(x) = x + 1

The inverse compiler must discover P1 followed by P2 without receiving that ordering:

    P2(P1(x)) = 8*(3*x+2)+5 = 7*x+4 mod 17.

At queried input x=9, the desired output is 16. The newly constructed DAG must execute and verify that observation. The test also checks all 17 possible inputs independently.

## Exact claim scope and negative controls

- contradictory_description: supplied desired points disagree with the declared affine family.
- budget_exhausted: word-depth or search-state budget exhausted; this is *not* proof of impossibility.
- not_derivable_in_supplied_palette: the entire reachable finite monoid was exhausted with no matching composition, relative only to this supplied primitive palette.
- Type, modulus, palette identity or local permission mismatch refuses.
- Altered output, changed primitive, invalidated intention, forged gate frame, and mathematically wrong but correctly rehashed native DAG are rejected by replay.

The result never silently upgrades IPS-002's ProposedRelation to a verified native evidence edge, never grants Hypervisor permission, and never claims remote network bandwidth or delivery.

## Reproduction

    python -m pytest -q tests/test_generative_ground_construction.py tests/test_ground_native_realization.py tests/test_navigable_computation.py

The dedicated workflow covers Linux and Windows with Python 3.11/3.13. Focused tests include 40 independent randomized small-word enumerations and native DAG/port integration.

## Next frontier

Extend the generated relation through E-CPU's VirtualLayerRuntime and Hypervisor admission, with typed predecessor output feeding a dependent DAG stage. Then prove the constructed relation can be qualified on actual authenticated peers and survives independent recovery. Generalize from affine arithmetic to new typed Ground families only when precise equivalence and authorization contracts are available; the present affine experiment is a concrete example, not a universal synthesis theorem.

Related research: IPS-001, IPS-002, SAB-008, GGE-001 and the Navigable Computation DAG documents in this repository.
