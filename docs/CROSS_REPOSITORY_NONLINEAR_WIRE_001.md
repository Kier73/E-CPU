# WIRE-001 — Portable nonlinear computational structure between repositories

**Research state:** An executable, receiver-source-pinned interoperability experiment between Navigable-Compute **NCR-007** and E-CPU **INTENT-001**. It uses an actual GitHub-hosted repository retrieval during CI and the existing E-CPU `OwnedNetworkFabric` routed-frame simulator. It does **not** install an E-CPU daemon into an external service, claim physical Internet-path arithmetic, remote Hypervisor authority, independent Internet machines or arbitrary program synthesis.

## Usage question

If an already existing GitHub repository has articulated a valid nonlinear computational structure, can another observer use that **mathematical description as a communication payload**, reconstruct an observer-sufficient interpreter without being told its registers or routing topology, and independently verify that it preserves the source's future-observation meaning?

The experimental answer is yes, under a small source-checked envelope, with independent mathematical qualifications and concrete execution receipts.

## Capability reconnaissance — inspected live public repositories

| Repository | Existing capability | Role in a possible communication computer |
| --- | --- | --- |
| [E-CPU INTENT-001](../mailcpu/intention_formed_fabric.py) | Derives minimal future-observer Moore state classes and selects admitted typed host/path relations through SAB-001 | Receiving interpreter formation and native path execution |
| [E-CPU INTERNET-001/002](INTERNET_NATIVE_GROUND_001.md) | Git content-addressed objects, refs and graph/state operations as already deployed Internet service relations | Source retention, source identity and version/commit navigation; not a generic arithmetic host |
| [E-CPU INTERNET-009](INTERNET_OBSERVED_GROUND_REVISION_009.md) | Native source-qualified observation revises a finite Ground and chooses the next sufficient question | Dynamic qualification and feedback (not integrated into this first packet experiment) |
| [Navigable-Compute NCR-007](https://github.com/Kier73/Navigable-Compute/blob/main/docs/NCR-007.md) | Invariant-generated nonlinear GF(2) polynomial laws, exact observer Koopman feature-space navigation, independently audited portable wire format | **Foreign mathematical source and structural computational program**; no need to hard-code its resulting transition table in E-CPU |
| [VL-I TIME-010](https://github.com/Kier73/VL-I/blob/main/docs/TIME_010_NATIVE_RATIONAL_EXECUTION.md) | Actual source-discovered rational law executed through native E-CPU Hypervisor and quorum-fenced pure-result publication | Authenticated/executed next-stage semantic operator and ownership pattern |
| [In-Formation-Space SFI-004](https://github.com/Kier73/In-Formation-Space/blob/main/experiments/pnp-ground-navigation/SFI-004.md) | Source-verified interpreter construction memory across strengthened SAT CNF; old model counts never inherited without fresh proof | Reuse generated machine architecture without pinning an old answer |
| [Virtual-Layer-Dynamics sheaf](https://github.com/Kier73/Virtual-Layer-Dynamics/blob/main/src/vld/navigation/sheaf.py) | Exact observer-consistency global sections and obstructions | Test whether local cross-host Grounds compose into one globally consistent description |
| [Virtual-Ground-Interpreter](https://github.com/Kier73/Virtual-Ground-Interpreter) | Admitted versus missing Ground, partial witness and source-specific provenance checks | Qualify unfamiliar observations without converting existence of a packet into permission |

These are existing, independently scoped public capabilities, **not yet one universally interoperable network**. WIRE-001 actually connects the first and fourth rows while retaining the native carrier, source identity and receiver authority distinctions. No new transport library, consensus authority or general solver is introduced.

## Two actual communication paths, separately attributed

```text
Kier73/Navigable-Compute (exact pinned Git commit)
          |
          |  HTTPS Git repository-object delivery by GitHub's service
          v
Receiver runner imports NCR's original law generator + separate verifier
          |
          |  Construct source-invariant nonlinear operators and a verified
          |  observer Koopman Ground, then encode exact canonical wire packet
          v
E-CPU OwnedNetworkFabric (owned local multi-hop routed frame; packet bytes)
          |
          |  Actual native send_routed / receive and checked receiver pin
          v
NCR original wire decoder + independent algebraic proof recheck
          |
          |  Bounded faithful finite source view: at most 2**6 source states
          v
E-CPU INTENT-001 (requested observation fields, not a fixed interpreter)
          |
          |  Construct a minimal future-observer quotient + operation class
          v
SAB-001 native authorized resource and carrier graph
          |
          |  Actual routed request and result frames + locally checked handler
          v
E-CPU generated interpreter -> final observation and receipts
```

The first **real Internet communication** delivers a reviewed and pinned open-source mathematical implementation, not an external runtime authorized to execute E-CPU work. The second is E-CPU's **local owned-network simulation** with real simulated routed frame and journal state. The source packet does not grant an operation permission. On actual remote hosts, mTLS/Hypervisor admission would remain necessary.

### Why the mathematical result is nontrivial

Let a nonlinear source (X=\mathbb F_2^n) have exact transitions (T_a), and let (O_F) be the projection of its declared observer polynomials needed for a particular intention. NCR-007 constructs a source-qualified Koopman-feature representation (q:X\to \mathbb F_2^r), verified with exact ANF polynomial identities. E-CPU independently constructs a finite future-observer quotient (\pi_F:X\to X/\sim_F) using transition-refinement.

For the **same complete source observer projection**, the two independently constructed machines must agree on the *equivalence relation*, even when the internal feature vector and abstract register counts differ:

```text
  q(x) = q(y)    iff    π_F(x) = π_F(y)
                iff    O_F(T_w(x)) = O_F(T_w(y)) for every action word w.
```

This is an exact semantic cross-check, not an expected equality of representations. The NCR ground's dimension measures an invariant **linear feature space**; E-CPU's register count measures the log of the number of distinguishable **reachable finite source classes**. Equal intended meaning does not imply equal cost or internal coordinates.

The experiment imports a nonlinear four-bit, two-action law generated from the upstream **rank, causal topology, invariance and coefficient-orbit grammar**. It does **not** supply the transition table to NCR's constructor. E-CPU independently enumerates all 16 source states only to form its own small finite Moore interpreter after mathematical source qualification. Pairwise equivalence of all **256 ordered state pairs** is checked against NCR's independent lifted feature projection.

The observer then changes the requested view. One observer field requires a compact two-state processor, while another field requires a more expressive generated processor and a different admitted host. The completed E-CPU request/result path uses the original SAB-001 `AdaptiveBootstrap` and `OwnedNetworkFabric` operations; final values are checked against the upstream source's original operators.

A **distant logical-time observation** (more than (10^{40}) source repetitions) is present in the packet, verified by NCR's independent `verify_nonlinear_result` arithmetic, not by replaying all intermediate source steps or falsely claiming the E-CPU transport performed those repetitions.

## Security/provenance boundaries

1. **Receiver-pinned source:** CI explicitly checks out [Navigable-Compute commit `559a1a813012d13ed37c04e2a117467e34ed3cb1`](https://github.com/Kier73/Navigable-Compute/commit/559a1a813012d13ed37c04e2a117467e34ed3cb1) before importing its verifier. The passed commit label in the E-CPU packet adapter is merely contextual metadata, **not a cryptographic proof that import used that exact code**; CI provides the binding.
2. **Receiver-pinned packet:** the receiver compares the exact SHA-256 of the transported canonical bytes with a known expected digest. The digest is integrity only, not publisher authentication. The NCR decoder independently verifies mathematical law-family, source-ground, and distant-result claims even when an adversary recomputes all accessible hashes.
3. **Admission:** the receiver's native `BootstrapPolicy` and explicitly trusted handler bindings must authorize each transformed and carried step. An external program's wire packet or `OperationOffer` cannot issue capabilities.
4. **Scope:** the finite adapter is bounded to source widths 2–6, at most eight source actions and eight observer outputs, and a maximum 65,535-byte packet. This enumeration does not inherit NCR's large-scale, 128-bit no-enumeration construction guarantee.
5. **Independent witnesses:** NCR's polynomial checker and E-CPU's finite quotient checker are different implementations of related mathematical semantics; both run on a single CI runner under the same administrative environment. They are not physically independent trust roots or an external proof kernel.

## Reproduce

```sh
python -m pip install ".[dev]"
git clone --filter=blob:none https://github.com/Kier73/Navigable-Compute.git ../ncr-pinned-source
git -C ../ncr-pinned-source checkout --detach 559a1a813012d13ed37c04e2a117467e34ed3cb1
python -m pip install -e ../ncr-pinned-source
python -m pytest -q tests/test_cross_repository_nonlinear_ground.py tests/test_intention_formed_fabric.py tests/test_substrate_bootstrap.py
```

Focused CI exercises Linux/Windows and Python 3.11/3.14. Negative controls refuse modified packet bytes, altered mathematical source with a recalculated digest, unsupported source pins and a correctly checked mathematical packet when receiver-local execution permission is absent.

## Next use, not a parallel infrastructure rewrite

The next candidate bridges are (i) the SFI-004 verified compiled SAT Ground as an observer-operation capability, (ii) VL-I's TIME-010 native Hypervisor operator rather than local Python only, and (iii) VLD's exact multi-observer consistency operator for composing *multiple* foreign Grounds. These must be joined through typed source, adapter, authority and observation receipts. Physical Internet-host proofs and independent authorities remain open.

The proposed broader direction is: **a computational description may travel as mathematical structure through a communication relation, and the observer's intention can then choose and realize an appropriate processor without requiring a permanent instance of the originating system.**
