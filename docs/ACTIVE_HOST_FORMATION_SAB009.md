# SAB-009 — Active formation of Ground-native observer-hosts

**Status:** research prototype. The receiving substrate begins with a locally approved code interpreter and writable data location, **not** with an E-CPU operator already installed. The controller actively stages a bounded E-CPU seed, invokes it, and checks its observations. This is *formation*, not merely passive classification or routing. Two real host code engines are exercised; a third receiver that stores bytes but cannot interpret them is deliberately refused as a computational host.

## Why the distinction matters

The substrate-neutral Ground in SAB-008 is an invariant of *meaning*, not a restriction to passive observation. A host may initially lack a computational operator, but an authorized receiving system may support **construction of that operator**. E-CPU can then compose, create, replace, and restart host loci through substrate-specific realization recipes. The substrate's primitive ability to receive, retain, or interpret is an enabling condition; a host does not need to advertise a completed E-CPU runtime before E-CPU forms one on it.

The operational distinction is:

1. **Receive:** bytes or signals reach a locus; this does not by itself confer execution.
2. **Retain:** the locus persists a bounded description or program; this may be useful as a memory fragment even if it cannot execute it.
3. **Interpret:** the substrate has an actual admitted transition mechanism that can give a staged description operational meaning.
4. **Form:** E-CPU supplies a trusted, Ground-compatible seed through an authorized local installation binding.
5. **Challenge:** the new observer must demonstrate the intended state-space law at multiple coordinates.
6. **Admit:** the controller independently checks the result and returns an SAB-008 `RealizationReceipt`. Authority stays local.
7. **Recover:** installation content identity is preserved across process restart; conflicting unapproved reprogramming is refused.

The formed host is a small E-CPU **observer/transition fragment**, not an automatically installed full E-CPU virtual machine. Generalized installation of memory, network, Hypervisor and scheduling components remains open research.

## Formal contract

For an admitted Ground \(G\), a substrate \(S\), and a local permission policy \(K\), formation is a typed transformation:

\[
F(G,S,K) \rightarrow (S', M, E)
\]

where \(S'\) is the substrate after installed structure has been formed, \(M\) is an immutable, content-identified implementation manifest, and \(E\) is finite challenge evidence. A claim of correct observation is admitted only when the installed code is still bound to \(M\), the active request remains within \(K\), and the independent Ground observation agrees. Matching values without the same Ground, intention, source identity, and granted method are insufficient.

The *semantic* intention is independent of method and substrate. `FormedGroundRealizer` implements SAB-008's `GroundRealizer` protocol and produces ordinary SAB-008 receipt records. The method and installation manifest are evidence of realization, not elements of the Ground itself.

## Concrete experiments

- **Blank Python surface:** a controller generates a small self-contained affine interpreter seed and installs it in a pre-authorized, initially empty directory. Each observation launches a fresh `python -I` process. The installed program does not import `mailcpu` or receive executable source in its request.
- **Blank JavaScript surface:** the same Ground is compiled to a distinct self-contained JavaScript seed, installed in an initially empty directory, then executed using a locally configured Node interpreter. All coordinates and modular operations are represented using `BigInt`, avoiding loss of precision above JavaScript's Number-safe integer interval.
- **Storage-only surface:** accepts the seed bytes, but cannot activate them. Formation refuses to describe it as an execution host. A future compositional profile could use its retained bytes as a memory or carrier contribution.

For the bounded test Ground \(x_{t+1}=(5x_t+7)\bmod 65521\), \(x_0=19\), the observation at \(t=10^{12}+913\) is **46,511** on both installed code engines. Their source artifact digests differ while the Ground, intention and observation agree. At \(t=10^{18}\), the JavaScript implementation uses exact integer arithmetic, subject to the local installation grant.

## Authority and verification

`FormationPolicy` allows only exact `(surface_id, engine)` pairs, expires at a declared logical coordinate, and bounds source bytes, frames and subprocess wall time. The code generator is a receiver-controlled fixed template; requests carry only canonical Ground identity, a decimal coordinate and a challenge nonce. The installed source is hashed and rechecked immediately before activation. A re-created local adapter can reopen the same source/manifest; a conflicting seed or changed manifest is refused, not silently installed.

**Important limitations:**

- SHA-256 of a seed is an integrity check, **not** signature, remote identity, remote hardware attestation, or proof of the interpreter's honesty.
- Both code engines run as ordinary local OS child processes. `-I` is import isolation, **not** a security sandbox. The directories and executables must be controlled by their owners. This prototype must not run user-supplied or network-supplied code.
- This test does **not** send code over the Internet or scan strangers' hosts. Installation is explicitly local and permissioned; extending it to other machines requires separate authenticated deployment channels and receiver-owned policy.
- Finite arithmetic probes do not prove universal program correctness. They show particular implemented methods agree with the independently specified Ground under the test schedule.
- A passive conductor, storage device, DNS request, or generic byte sink cannot execute arbitrary E-CPU structure merely by receiving information. Additional real transition primitives or an interpreting observer are required.
- Recovery is immutable file content and fresh-process reexecution, not quorum-anchored recovery, atomic distributed update, or arbitrary side-effect exactly-once delivery.
- A general full-runtime bootloader must additionally form scheduling, capability governance, communication, durable state, evidence provenance, and mutually consistent recovery lineage.

## Tests

`tests/test_active_host_formation.py` covers empty-before/full-after formation; two-engine semantic equivalence; exact distant-coordinate arithmetic; reconstruction after restart; undeclared/expired authority; seed-size refusal; content tampering; conflicting updates; inability of storage-only receivers to execute; method mismatch; Ground mismatch; immutable idempotent installation; malformed policies; deterministic source construction.

The dedicated GitHub Actions workflow installs Python 3.11/3.13 and Node.js 22. It runs the new tests against the full E-CPU package and then runs SAB-008 Ground-native regression tests. A local run on Python 3.13 and Node 22 passed **16/16 tests in two verified batches**; that is not a claim about GitHub CI or physical deployment.

## Next frontier

Move from fixed two code-generation recipes toward a **capability-to-construction compiler**: observe which operations an authorized substrate can actually receive, hold, interpret, and export; synthesize and stage an implementation plan for the requested E-CPU role; verify that installation and rollback are safe; and compose formed fragments into a higher-order virtual host. Transport and authority still belong to the receiver. The goal is active substrate shaping, not merely dispatching to existing endpoints.