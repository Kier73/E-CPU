# SAB-010 — Capability-to-construction compiler

**Status:** bounded active-formation research. One exact affine Ground is implemented through two construction recipes. The compiler uses receiver-installed primitive bindings and explicit permissions; it does not assume a CPU, named operating system, Internet endpoint, hardware attestation, or general-purpose interpreter is inherently E-CPU-native.

## Foremost objective

E-CPU's initial bootstrap should not merely choose an already existing computational service. Given a receiving environment, it should be able to **form an appropriate observer-host** from whatever useful, admitted primitive transitions the environment exposes. A surface may begin as a pair of active ports, a code-and-data receiver, a storage-only component, or a composition of these. Reception alone is not proof of execution.

The semantic Ground remains independent of the selected recipe:

\[
I=(G,\theta,t),\qquad
\mathsf{Construct}(I,\mathcal P,K)\rightarrow(H,E),\qquad
\mathsf{Verify}(G,I,E)=\mathsf{true}
\]

Here \(\mathcal P\) is a finite set of observed, locally bound primitive operations; \(K\) is receiver-owned construction permission; \(H\) is a newly assembled Ground realizer; and \(E\) is bounded evidence of the observation. The resulting computation belongs to \(G\) and \(I\), not a particular resource implementation.

## Two executable synthesis recipes

**1. Primitive-algebra synthesis:** given separately qualified `affine.compose` and `affine.apply` operations, synthesize a binary affine-map composition navigator. They can be on **different logical port loci**, neither possessing a full E-CPU navigation routine. At coordinate \(t\), the construction requires at most \(\lfloor\log_2 t\rfloor + 1 + \operatorname{popcount}(t)\) compositions and one application. Every composition result is independently checked against the exact finite modular algebra, then the final observation is independently compared with the Ground oracle. The port implementation in the mandatory test is **software-modeled**, not measured hardware.

**2. Interpreter formation:** given `program.stage` and `program.activate` bindings for the same receiving surface/engine, construct a composite receiving interface and delegate to SAB-009. E-CPU installs a locally generated seed, verifies installed bytes, challenges it at several coordinates, and returns a Ground-native observation. The two primitive interfaces can be bound by separately owned adapter instances. They must be able to access the **same installed artifact**; merely sharing an identifier does not satisfy the execution test. Both Python and JavaScript/Node receivers are covered in tests. No remotely supplied or caller-authored executable source is accepted.

Both recipes produce SAB-008 `RealizationReceipt` records identifying the mathematical Ground and intention independently of the selected construction. The controller re-compiles the exact recipe immediately before form/observe, refusing stale primitive inventories or revoked grants. A storage-only receiver, an activation-only receiver, or a single compose port cannot become an arithmetic executor by name alone.

## Trust, role and evidence hierarchy

- **Primitive evidence:** `observe_gate` actively challenges the callable gate. `bind_receiving_surface` only identifies a receiver-owned *candidate interface*; it makes no assertion that any installed seed will execute correctly. SAB-009 performs that latter verification when the seed is formed.
- **Receiver authority:** `ConstructionPolicy` admits only exact `(locus,primitive)` grants and bounded cost, event and frame budgets; SAB-009 additionally requires its own `FormationPolicy` for modifying the receiving surface. Neither is inferred from a capability advertisement.
- **Semantic verification:** each stage follows an explicit operation algebra; the final `RealizationReceipt` is independently checked against the original Ground and intention. Identical scalar outputs with different intentions are not interchangeable receipts.
- **Portability:** a newly formed navigator need not run through the MailCPU instruction machine. The adapters and their physically observed transitions may differ, while the Ground-native meaning remains stable.
- **Continuity:** the SAB-009 formed seed can reopen from exact immutable bytes after a fresh controller and subprocess restart. Port-model invocations preserve audit traces but do not demonstrate independent durable port state.

## Reproducible result

For \(x_{n+1}=(5x_n+7)\bmod65521\), \(x_0=19\), a request for coordinate \(10^{12}+913\) yields **46,511** through either recipe. The mandatory two-port synthesis uses **59 semantic primitive operations** (58 compositions plus one application) on separate logical loci. This is not a claim that 59 total physical instructions or network exchanges were consumed. Declared `estimated_quanta` are planner weights, not hardware measurements.

`python -m unittest discover -s tests -p 'test_capability_construction.py' -v` runs the adversarial tests. The dedicated workflow tests Python 3.11/3.13, Node 22, and the prior SAB-008/009 contracts.

## Current scope and next development gates

- This prototype supports a **closed four-primitive vocabulary** and one Ground family; it is not yet a general-language compiler for arbitrary unfamiliar substrates. New primitive algebras require explicit contracts and verifiers.
- A primitive digest verifies the recorded test content, not a remote host's honesty or hardware identity. The gate challenge is finite; every produced transition is therefore also checked against its algebra.
- The test ports and interpreter processes run under one test machine; they are **not** independent physical failure domains.
- Code installation is explicitly local and permissioned, not a sandbox or remote deployment protocol. A receiver and its interpreter must be owner-controlled. No public-facing resource scanning or unauthorized runtime installation is performed.
- The recipe compiler has no general distributed transaction log, quorum lineage, rehoming proof, transport protocol, network discovery or arbitrary stateful operator semantics. Integrating those requires E-CPU's existing fabric and recovery mechanisms, preserving receiver-owned authority.

**Next frontier:** synthesize richer roles from real, remotely authenticated primitive observations; preserve verified algebra when the primitive set changes; and form persistent composite hosts with independently recoverable storage, communication and execution components. Verify each upgrade rather than assuming that a new substrate can support it.