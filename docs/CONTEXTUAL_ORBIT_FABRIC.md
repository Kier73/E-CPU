# Contextual Orbit Navigation over the Computational Fabric

## Purpose

This specification composes the existing contextual state-space navigator with the Virtual Layer and authenticated Computational Fabric. A target-value query becomes a portable operation request. The destination host interprets that request against its own admitted Structural Memory revision, performs a mathematically supported inverse, verifies the candidate by forward evaluation, and returns the resulting Virtual Ground projection and evidence.

The operation moves the *query*, not the generator implementation, registry, or receiver authority. It does not serialize a VM image or copy the full state trajectory.

## Semantic request

`ContextualOrbitLocateValueRequest` binds:

- a `ContextualOrbitAddress`: SystemIdentity, base Virtual Ground, Computational Ground, scheduler domain, context extensions, and an exact Structural Memory revision;
- an `ObserverContract`: subject law, interpretation Ground, observation schema, revision, and context digest;
- a strict integer target value; and
- an operation identity for the observer receipt.

The address must be at the base coordinate (relative orbit offset zero). The Structural Memory reference is pinned to memory ID, revision, context, specification digest, certificate digest, and coordinate. The request digest commits this complete query. It carries no executable function and no authority token.

## Receiver authority and no-eager-read path

A routed workload uses Virtual Layer schema version 3 and an operator reference whose Structural Memory access mode is `navigate`. This mode is distinct from the default `read` mode used by ordinary symbolic operands.

After the receiver reconstructs the request and recomputes the workload/operator contract, its existing Hypervisor authorizes the exact operation resource. Only inside the admitted invoke path does the Virtual Layer:

1. require the receiver process's local `read` capability on `/structural-memory/read`;
2. resolve the exact historical Structural Memory revision in the receiver-local registry;
3. validate the pinned base coordinate, context, specification digest, and certificate digest; and
4. pass the untouched request to the receiver's trusted local handler.

The access mode is also declared by the receiver's registered `OperatorSpec` and is included in that operator contract's digest. The receiver refuses a workload whose `VirtualOperatorRef` mode differs from the local contract; a caller cannot switch an ordinary read-based operator into navigation mode by editing the request.

This authority check does **not** call `read_revision` and does not materialize the base coordinate. The trusted handler is bound to that receiver's `StructuralMemoryRegistry` and invokes the existing `ContextualOrbitNavigator.locate_value`. The navigator performs the supported inverse, forward-verifies the candidate under the admitted law and certified horizon, then reads the actual located coordinate and creates its `StructuralMemoryReadReceipt`, `VirtualGroundProjection`, and `ObserverReceipt`.

The local Computational Address resolver may independently validate the base address while selecting a receiver. That validation is also a guarded metadata/horizon check, not a value read. A relay does not need to possess the Structural Memory revision or its read capability.

## Inverse and descriptor bounds

The operation deliberately reuses the existing inverse methods and their refusal behavior. It does not add a scan, breadth-first search, BSGS fallback, or replay fallback:

| Structural Memory family | Inverse method | Operation behavior |
|---|---|---|
| `int` | Exact progression/modular inverse | Direct candidate, then certified forward verification |
| `lcg` | 2-adic bit lifting under full-period power-of-two conditions | Refuses when the required conditions do not hold |
| `gf2` | Bounded recurrence inversion | Receiver handler caps recurrence order |
| `fgraph` | Earliest-coordinate index over the stored finite orbit | Receiver handler caps index entries |

The receiver handler also caps the canonical parameter and context descriptor sizes. The default limits are 65,536 UTF-8 bytes for each descriptor, recurrence order 256, and 65,536 finite-graph index entries. These are operation-profile limits, not changes to what Structural Memory may store or what the standalone navigator can represent. A deployment can construct a handler with stricter limits. Exceeding a handler limit refuses the operation before inversion.

The Virtual Layer separately enforces its workload byte, energy, and virtual-tick budgets. Its current deterministic energy estimate is based on the declared operation contract and serialized workload/address; it is not a calibrated measurement of every arithmetic family. Implementations must not interpret that estimate as a wall-clock bound.

## Routing and result verification

The dispatcher constructs a normal `ComputationalAddress` for the declared operator and Computational Ground, resolves a compatible host and directed peer path, then sends the operation through the existing authenticated forwarding channel. The destination still resolves its local operator contract and uses its own process capabilities and Hypervisor policy.

The origin accepts the terminal effect only when it is bound to the exact workload, operator version, contract digest, input digest, and successful Hypervisor ALLOW result. It then independently validates the returned `OrbitValueResult` serialization and checks:

- target value and selected coordinate;
- SystemIdentity, base Virtual Ground, Computational Ground, transition subject, context, and absolute scheduler coordinate;
- exact memory ID, revision, specification digest, certificate digest, located coordinate, value, and value digest in the read receipt;
- observer identity, revision, contract, subject, interpretation, observation schema, operation ID, and located-address input digest; and
- observer evidence references to both the returned Structural Memory read receipt and Virtual Ground projection.

A routed receipt also binds the selected logical host, peer path, route witness, forwarding-receipt digest, operator-effect digest, and advertised implementation fingerprint.

## Failure behavior

The operation refuses when the base address is not at offset zero, observer context or interpretation does not match, the receiver lacks local Structural Memory read capability, the exact revision/specification/certificate is unavailable, the law does not have an admitted direct inverse, the target is unreachable, the candidate lies outside the certified horizon, any configured descriptor/index bound is exceeded, the route or operator contract is incompatible, or returned evidence fails origin-side validation.

There is no silent search fallback. A caller that needs general path search must issue a different explicitly bounded operation with its own cost and observation contract.

## Evidence and proof boundary

The multi-hop integration test exercises an authenticated A→B→C path. Peer B is a relay with no Structural Memory revision. Peer C holds the exact revision and local read capability. The journal assertion is that the receiver records one `structural_memory.read_revision` at the inverse-selected coordinate and no base-coordinate materialization; the relay records no Structural Memory read.

The digests bind canonical content and provenance. They are not digital signatures, independent proof of remote execution, trusted hardware attestation, or proof that the advertised host is a particular physical machine. The terminal Hypervisor effect and transport chain establish the current software execution path under the configured trust model.

The operation does not establish a speedup over native execution. Remote latency still includes serialization, route, queueing, receiver resolution, inverse work, forward verification, result validation, and return transport. The demonstrated property is *interpretive compression*: for supported laws, the receiver can locate and materialize the needed coordinate without materializing the intervening trajectory or reading the base coordinate merely for authorization.

## Implementation

- `mailcpu/orbit_fabric.py`: request, operator contract, receiver handler, dispatcher, and origin verification.
- `mailcpu/virtual_layer.py`: schema-v3 authority-only Structural Memory navigation access mode.
- `mailcpu/observer_orbit.py`: existing contextual inverse and forward-verification engine.
- `mailcpu/computational_fabric.py` and `mailcpu/computational_fabric_forwarding.py`: host selection, directed routing, and authenticated forwarding.
- `tests/test_computational_fabric.py::test_contextual_orbit_inverse_navigation_executes_on_receiver_over_multihop_fabric`: A→B→C integration and receiver-only read assertions.
