# General Computational Hosting

## Status

M2 establishes an initial local computational hosting contract over the M0/M1 computational-object foundation. It admits a multi-file artifact as one immutable composite identity, binds a local backend implementation and profile separately from that artifact, and executes typed operations through a trusted local adapter.

The implementation is backend-neutral. A model runtime, emulator, virtual CPU, numerical engine, or another computational domain can implement the adapter contract without adding its dependencies to the core package.

This is not a universal byte interpreter. The artifact still requires a domain-specific Ground and a trusted adapter that understands its representation.

## 1. Identities that must not collapse

M2 distinguishes four operation-facing identities:

1. **Artifact identity** — which exact collection of component bytes and representation metadata was admitted.
2. **Backend identity** — which explicitly declared implementation, runtime versions, device profile, configuration, and resource bounds interpret the artifact.
3. **Operation identity** — which logical request, operation, input, workload, and logical-time coordinate are being evaluated.
4. **Result identity** — which canonical output was produced by that operation under that artifact and backend.

The host adds a fifth identity: the receiver-local logical host and its operational authority context.

A model is one artifact kind. The hosting contract does not assume neural-network semantics, tensor layouts, text input, a particular framework, or one device class.

## 2. Composite artifact identity

M1 identifies one byte object. A real computational artifact may consist of many files: parameters, configuration, schemas, executable pieces, lookup tables, processing stages, or other domain-specific components.

For component \(k\):

\[
A_k=(p_k,\mu_k,n_k,h_k,r_k)
\]

where:

- \(p_k\) is its normalized relative POSIX path;
- \(\mu_k\) is its media type;
- \(n_k\) is its logical byte length;
- \(h_k=\operatorname{SHA256}(b_k)\) is its content identity;
- \(r_k\) is an optional complete M1 byte-object manifest that locates its ordered pages.

The composite descriptor is:

\[
M_A=\operatorname{Canonical}
\left(
\begin{array}{l}
\text{kind},\text{schema},\text{artifact\_id},\text{artifact\_kind},\\
\sum_k n_k,\{A_k\}_{p_k\ \mathrm{sorted}},\text{metadata}
\end{array}
\right)
\]

\[
I_A=\operatorname{SHA256}(M_A)
\]

Any byte, component path, media type, nested M1 storage descriptor, or declared metadata change produces a distinct manifest identity.

The nested M1 descriptor is optional. With an existing ComputationalObjectStore supplied during admission, every component is also paged through that store and its complete page manifest is bound into the composite artifact. Without a store, the manifest still identifies the component bytes locally, but does not itself provide remote page locations.

### 2.1 Admission rules

The directory admission function:

- requires a real, non-symlink directory;
- admits regular files only and rejects symlinks;
- uses normalized relative POSIX paths and rejects traversal;
- sorts component descriptors lexicographically;
- streams SHA-256 over file bytes;
- enforces total-size and file-count bounds;
- optionally publishes each component through the existing M1 object store;
- refuses publication if the M1 descriptor does not match the local file identity.

Exclusions are explicit relative path prefixes supplied by the caller. The normalized, non-redundant prefix set is stored in the artifact manifest and therefore participates in its digest. The core does not silently discard files based on a particular framework's cache or naming conventions. Verification and local host loading reuse the bound exclusion set; a caller cannot silently change it during verification.

The directory verifier recomputes component digests and sizes. Strict inventory checking is enabled by default: an unmanifested extra file makes the directory differ from the admitted artifact. When requested, it can also resolve and verify every nested M1 page manifest.

This is content integrity under the SHA-256 assumption, not origin authentication. A composite digest does not sign the artifact or prove who supplied it.

## 3. Backend identity is independent of artifact identity

A backend profile declares:

\[
B=(I_B,I_{\mathrm{impl}},h_{\mathrm{impl}},D,\mathcal{S},V,C,L_{\mathrm{in}},L_{\mathrm{out}},\delta,E)
\]

where:

- \(I_B\) is the backend identifier;
- \(I_{\mathrm{impl}}\) is the implementation identifier;
- \(h_{\mathrm{impl}}\) is an explicitly supplied implementation digest;
- \(D\) is the declared device/profile label;
- \(\mathcal{S}\) is the set of supported E-CPU substrates;
- \(V\) is the declared runtime-version map;
- \(C\) is finite JSON configuration;
- \(L_{\mathrm{in}}\) and \(L_{\mathrm{out}}\) are the input and output byte ceilings.
- \(\delta\) is the explicit deterministic-execution declaration;
- \(E\) is the declared effect mode (pure, idempotent, or transactional).

The profile fingerprint is:

\[
F_B=\operatorname{SHA256}(\operatorname{Canonical}(B))
\]

A single immutable artifact can therefore be interpreted by multiple backends while retaining a common \(I_A\) and distinct \(F_B\) values.

The deterministic declaration and effect mode are required profile fields with no permissive defaults; both are included in the backend fingerprint.

The implementation digest is explicit rather than guessed from a class name. The profile fingerprint binds the declared facts, but is not a signature or a hardware attestation. Device/runtime declarations must not be presented as proof that a particular physical accelerator, driver, or precision mode actually executed the operation. An adapter that performs fallback or runtime substitution must expose that fact in its own declared or observed profile rather than silently treating requested and actual execution loci as identical.

## 4. Local adapter and host lifecycle

The backend-specific code implements the small trusted ComputationalBackendAdapter protocol:

- load(manifest, artifact_root, profile);
- execute(request);
- unload().

The core does not import model, compiler, emulator, or accelerator frameworks. These remain optional and local to the adapter.

LocalComputationalHost binds:

\[
H_{\mathrm{local}}=(I_H,I_A,F_B,S,T,K,L)
\]

It lazily loads on first execution. Before initialization, it re-verifies the local artifact against its composite manifest with strict file inventory. Adapter initialization must succeed before the host transitions to LOADED. Unload returns it to UNLOADED.

The host serializes adapter lifecycle and request execution under a local lock. This is a safe initial lifecycle contract, not a throughput or concurrency scheduler. A later extension may introduce bounded concurrent sessions when a backend declares its state and concurrency semantics.

The local verification occurs immediately before adapter initialization; it is not an immutable filesystem snapshot or a defense against another privileged local process changing files between verification and backend reads. Deployments must provision the admitted artifact root as controlled, non-writable input for untrusted actors. Backends that require stronger isolation should load from an independently protected or content-addressed materialization.

The adapter is trusted local implementation code. No request can supply Python code or replace the adapter implementation.

## 5. Typed operation and temporal context

A local request binds:

\[
r=(q,I_A,op,x,w,t)
\]

where \(q\) is request identity, \(I_A\) is the admitted artifact manifest, \(op\) is the operation label, \(x\) is finite JSON input, \(w\) is workload identity, and \(t\) is the workload's logical-time coordinate.

The input identity is:

\[
h_x=\operatorname{SHA256}
\left(
\operatorname{Canonical}(op,x,w,t)
\right)
\]

The artifact digest is bound separately in the receipt. Logical time is passed from the existing VirtualLayerWorkload; the host does not invent a new global clock.

The core initially uses a bounded finite-JSON request/response envelope. Large weights, tensors, memory images, executable sections, or other binary data should remain in M1 byte objects and be referenced by typed identifiers, not copied into ordinary Virtual Layer JSON workloads. Domain-specific adapters are responsible for validating layouts and translating typed references into local backend inputs.

## 6. Result receipt, measurement, and commit

For output \(y\), the core computes:

\[
h_y=\operatorname{SHA256}(\operatorname{Canonical}(y))
\]

The deterministic host receipt binds:

\[
Q=\operatorname{Canonical}
\left(
I_H,I_A,F_B,q,w,t,h_x,h_y,|y|,\text{EXECUTED}
\right)
\]

\[
h_Q=\operatorname{SHA256}(Q)
\]

The receipt checks its canonical digest on construction and decoding. The execution object also checks that its canonical output bytes match the output digest and byte count in the receipt.

### 6.1 Why duration is not inside the deterministic receipt

The local host reports elapsed execution duration from the process-local monotonic performance counter as a separate observation.

That measurement is intentionally excluded from \(Q\). Two identical requests producing identical output under the same artifact/backend profile should retain the same receipt identity even if one execution takes longer. Including elapsed duration in a pure operator's committed result would make replayed operations differ solely due to timing noise.

A monotonic duration is local to the observing process and boot/restore segment. It must not be subtracted across hosts to invent global latency or causal order. Logical time remains the workload's existing E-CPU coordinate.

### 6.2 Executed is not committed

The host receipt status is EXECUTED, not COMMITTED.

Its digest provides deterministic result integrity and linkage. It is not a digital signature, a durable ledger entry, or a proof of origin. The enclosing Virtual Layer/Hypervisor operation remains responsible for receiver-local capability reconstruction, policy arbitration, semantic replay identity, effect commitment, publication, and acknowledgement. Only that existing commit boundary can establish the committed effect.

The host must not independently claim that a state transition is durably committed merely because its adapter returned a value.

The local host does not persist request identifiers or deduplicate direct local retries. When used through the existing Virtual Layer/Hypervisor path, replay protection comes from the enclosing semantic operation identity and Hypervisor ledger. Direct callers remain responsible for their own retry and side-effect policy; a deterministic receipt alone does not provide exactly-once execution.

## 7. Virtual Layer and Transit composition

The generic host operator factory adapts a LocalComputationalHost into a versioned OperatorSpec. The portable workload contains an operation label, finite input, and optional request identifier; the implementation stays at the receiving node.

The Virtual Layer adapter is available only when the backend profile explicitly declares deterministic execution and pure effects. The current Virtual Layer runtime accepts replay-safe pure operators; it does not make nondeterministic or external side effects safe by wrapping them in a receipt. A local backend may still be called directly under its own domain contract, but this M2 Transit adapter refuses profiles that cannot satisfy the current replay boundary. Execution metrics remain outside the deterministic receipt.

TransitComputationalHost binds that operator to a receiver HeadlessOS-compatible authority and exposes the existing Virtual Layer operation/resource identity. It can be used as the backend for the existing TransitComputeWorker; the worker and Hypervisor remain responsible for authorization and commit. The remote side names the operator and supplies typed data, never executable adapter code or authority.

This composes with the existing:

- OperatorRegistry and VirtualLayerRuntime;
- Hypervisor capability reconstruction and effect/replay ledger;
- HypervisorOperationChannel and reliable request/result channels;
- TransitBackendRouter where multiple operation backends share one worker;
- ComputationalObjectStore and existing page backings for large artifact bytes.

No new clock, page store, address envelope, TCP framing protocol, or authority system is introduced.

## 8. Implemented and unimplemented boundaries

M2 implements:

- a generic multi-file computational artifact manifest;
- path, byte, inventory, metadata, and optional M1 page-manifest verification;
- explicit backend implementation/profile fingerprinting;
- a local load/execute/unload adapter contract;
- bounded finite-JSON requests and results;
- deterministic result receipts distinct from local performance observations;
- a generic Virtual Layer operator and Transit receiver adapter.

M2 does not yet implement:

- automatic discovery/cataloguing of artifacts on arbitrary hosts;
- hardware attestation or signed origin identity for backend fingerprints;
- domain-specific numerical equivalence or accuracy tests;
- tensor shape/dtype/layout conversion or collective operations;
- persistent mutable execution sessions, key/value cache state, or checkpoint migration;
- model/VM partition scheduling or multi-host collective execution;
- arbitrary executable-byte loading or a universal interpreter;
- general external-side-effect transactions beyond the existing Hypervisor commit contracts.

The next obligation is persistent computational state: session identity, versioned mutable state, checkpoint manifests, atomic continuation, and recovery across host changes. Replicated and partitioned hosting should then reuse those same artifact/backend/state contracts rather than introducing parallel object systems.
