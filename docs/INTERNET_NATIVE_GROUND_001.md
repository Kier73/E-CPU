# INTERNET-001 — The existing Internet as an E-CPU observer-host state-space

**Research status (2026-11-16):** One **live, authorized GitHub Git-service state transition** and a subsequent read of the content-addressed observation; six local verifier tests passed. This is a protocol/service-level test of pre-existing Internet-native state. It does **not** establish passive-link arithmetic, physical fiber processing, general Internet deployment, or a remotely running E-CPU interpreter.

## Why this experiment belongs to E-CPU

This work returns to the original proposition in [The Internet Is the Computer](THE_INTERNET_IS_THE_COMPUTER.md), [Latent Path Capacity](LATENT_PATH_CAPACITY.md), [Communication Host Model](COMMUNICATION_HOST_MODEL.md), and [State-Space Navigation](STATE_SPACE_NAVIGATION.md):

- **Host = observer, path = architecture.** A candidate host is any information locus with a specific observable operation; a passive link may be a carrier and its physical propagation may form a separate measurable Ground.
- **Capacity precedes recognition.** TCP acknowledgements, DNS cache decisions, Git content addressing, reference updates, routing policies and buffering exist independently of E-CPU's installation. Each is a candidate typed relation, not permission to use arbitrary infrastructure or a universal instruction set.
- **Mathematical capacity is not stored history.** A Ground describes a set of admissible states and transitions. Intention constrains the required observation; a verified direct law can resolve a distant logical coordinate without materializing every earlier state.
- **Internet state is part of the state-space.** The relevant composed state includes receiver-local states, protocol cursors, queue contents, named network objects and service transitions, not just processors connected by a byte pipe.

This is the intended meaning of a **superposition of addressable possibilities**: multiple mathematically described states are possible under one finite description, and a bounded request selects an observation. It is *not* a claim of quantum physical superposition or cost-free collapse.

## Ground, intention, and actual Internet realization

Let \`G\` describe a source-defined computational relation, \`I\` specify the requested state/observation, and \`P\` be the chosen Internet communication/observer path. A valid path realization must preserve an explicitly declared observation equivalence:

\`D(Φ_P(E(x))) ~_(G,conditions) T_G(x)\`.

\`E\` is encoding, \`Φ_P\` is the actually observed path and host-state transformation, \`D\` is decoding, and \`T_G\` is the intended Ground relation. The comparison does *not* assign endpoint arithmetic to fiber, and must account for transport, conversion, verification and persistence costs. Physical time and logical time remain separate.

INTERNET-001 isolates a particularly clear pre-existing service relation:

1. GitHub already has a content-addressed Git object service. An authorized caller publishes bytes; the service returns their Git blob address.
2. GitHub already has tree/commit transition constructors and a versioned branch-reference service. The caller constructs a tree and a commit, then requests an update with an explicitly expected predecessor.
3. A separately invoked Internet read observes the service's ref, commit, tree and blob. A receiver-owned verifier checks the intended predecessor/new-head identity and independently hashes the returned bytes.

**No interpreter, worker or E-CPU code was installed at GitHub**. The remote Git service supplies existing storage, versioning and ref-state operations. HTTPS and the GitHub account/permission context are the used interfaces; the underlying routers and fiber are carriers, not claimed to have executed Git or model arithmetic.

### Live observation (source identities)

- Repository: \`Kier73/E-CPU\` (user-authorized research branch only).
- Development branch: \`research/internet-native-ground-001-20261116\`.
- Stable observation branch: \`research/internet-native-ground-001-anchor\`.
- Prior branch head: \`6fd416facdb2aefd6fc7d66a06b014e3d31b5a52\`.
- Created Git blob: \`46958c491ec504e2f8562ca37b8b152d441376f0\` (358 bytes).
- Independent original-content SHA-256: \`ece11d917a3c4bf1240e8e02a29b94ff2761fcdf8e37504bc9660d382b0f5c67\`.
- New Git tree: \`e930dc1a04a0c42e09e43437a0749b344a123efb\`.
- New commit and anchored ref: \`9a34c11147db7d8619b65b6058fa121ab9b1c43c\`.
- Object: \`reports/internet_native_ground/remote_state.json\`.

The connector reported success when the branch was updated from its expected old commit to the new one, and the service's subsequent **GET** reported the new ref/commit/tree/blob identity. An attempted stale update returned an opaque GitHub API error; **we cannot attribute that error specifically to lease mismatch**. The safe negative oracle is that a verifier supplied the stale expected head must refuse the now-observed newer head; this refusal is tested locally.

The anchor branch must remain at its expected exact commit for the hosted read-only verification to pass. Its content hash and commit ID are supplied by the observer's external policy rather than learned only from the destination service being audited.

### Independent observer

\`examples/verify_internet_git_ground.py\` uses four HTTPS GETs (ref, commit, recursive tree, blob) and validates:

- exact receiver-owned commit SHA and Git blob SHA-1;
- expected relative path, complete/untruncated tree, declared object type;
- independently reconstructed Git-object SHA-1 and original-content SHA-256;
- bounded response size and strict JSON duplicate-key rejection;
- refusal of stale heads, wrong source bytes, incomplete trees, absent objects and changed intent.

The code is *read-only*. Offline tests use injected responses without network and do not pretend to be internet measurements. A dedicated CI workflow attempts the read-only HTTPS check against the **actual public GitHub endpoint**; consult its exact run before counting that test as passed.

## What RCG-001 to RCG-007 contribute—and what remains different

Those experiments increased the ability to address, compress and navigate large model Grounds. Their mathematical proofs are useful to *decide the observation to request*. The Internet-native Ground is the **realizer and observable protocol state**, which may have no ability or permission to carry out the model's full arithmetic.

The next meaningful synthesis is to bind a **certified compact observer capability atlas** (RCG-006/007) to E-CPU's pre-existing \`ComputationalFabricDirectory\`, \`EvidencePathResolver\`, \`ObserverPathStage\`, \`TransitPathSessionBinding\`, and M1/M3 authority, while admitting external path-state operators that can be independently characterized. Do not create a second scheduler, Hypervisor, transport or persistence ledger.

A single composed logical computation may use: a named service's retention relation, a TLS path's peer authentication, a transport's ordering/ACK state, a receiver's locally authorized projection, and a compact algebraic navigator. What these components each do must remain attributable.

## Next falsifiable path-native experiment

1. **Observe multiple authorized Internet mechanisms**: Git refs/objects, controlled DNS resolver responses and caching, HTTP conditional/range responses, and an owned TCP service. Record exact input/output, clock domains and permission scope. Only observe publicly permitted or owner-controlled services. TCP sequence/ACK/window behavior is specified by RFC 9293; DNS serve-stale is explicitly permitted by RFC 8767, so do not infer an exact universal TTL countdown.
2. **Discover a typed path law** from calibration probes, with withheld inputs, drift/reconfiguration controls, and source-vs-medium-vs-receiver cost attribution. For a physical transfer law, require real instrumented-path measurements and bypass controls rather than a software FIR simulation.
3. **Carry a navigable mathematical intention over the path**, allowing existing Internet loci to contribute only operations they actually support. Reuse \`mailcpu.observer_path_evidence\` and the receiver's authority for typed claims.
4. **Prove observation equivalence**, compare cold admission against warm reuse, test changed service behavior, retry/replay and loss, and record all bytes, wall times, setup and validation costs. Only then promote a newly discovered route capability.

This is not a request to exploit third-party network equipment, route traffic through arbitrary open resolvers, or hijack network caches.

## Reproduction

Offline:

\`\`\`bash
python -m unittest discover -s tests -p 'test_internet_git_ground.py' -v
\`\`\`

Read-only Internet observation (requires HTTPS reachability):

\`\`\`bash
python examples/verify_internet_git_ground.py \
  --repo Kier73/E-CPU \
  --branch research/internet-native-ground-001-anchor \
  --expected-commit 9a34c11147db7d8619b65b6058fa121ab9b1c43c \
  --path reports/internet_native_ground/remote_state.json \
  --expected-blob-sha1 46958c491ec504e2f8562ca37b8b152d441376f0 \
  --expected-content-sha256 ece11d917a3c4bf1240e8e02a29b94ff2761fcdf8e37504bc9660d382b0f5c67
\`\`\`

## External standards

- [RFC 9293 — TCP](https://www.rfc-editor.org/rfc/rfc9293.html), actual protocol state machine, sequence and acknowledgement semantics.
- [RFC 8767 — DNS serve stale](https://www.rfc-editor.org/rfc/rfc8767.html), example of cache state and policy invalidating a naive TTL-as-clock assumption.
- [P4_16 specification](https://p4.org/wp-content/uploads/sites/53/p4-spec/docs/P4-16-v-1.2.3.html), explicitly programmable packet-processing loci; separate from passive links.
