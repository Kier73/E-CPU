# SAB-011 — Persistent composite host formed from primitive capabilities

**Status:** bounded research integration. SAB-010 actively constructs computation from incomplete, locally controlled primitive operations. SAB-003 qualifies its observable behavior. SAB-004 composes that newly formed role with independently qualified framed-communication and retained-state roles, using SAB-001's typed planner and SAB-004's existing immutable checkpoint and commit-decision machinery. SAB-005 mutual-TLS endpoints can provide the relay and storage roles; no new permission or recovery authority is introduced.

## Question

Can one Ground-native mathematical intention survive formation into multiple *different* computation structures, re-placement from one structure to another, and the loss of execution and relay participants **without repeating the previously committed computation**?

SAB-011 treats the **semantic Ground** and **observed result** as stable while host/recipe/protocol evidence changes. There is no privileged CPU, interpreter, port, or transport in the semantic contract. The current methods are concrete, authorized implementations, not proofs of arbitrary-substrate deployment.

## Construction-to-composition integration

The code `mailcpu/composite_host_formation.py` is intentionally an adapter, not a competing scheduler:

1. **Construct.** `CapabilityConstructionCompiler` takes independently challenged primitive interfaces (`affine.compose` plus `affine.apply`) or separately admitted program-stage and activation interfaces. It forms a bounded navigator under `ConstructionPolicy`, with a separate `FormationPolicy` for installed source.
2. **Qualify.** `ConstructedComputationEndpoint` exposes only SAB-003's fixed `observe` and `affine_mod` operations. It recompiles/realizes the Ground under local construction authority for each arithmetic request, verifies the SAB-010 observation receipt, and returns a checked value; arbitrary remote source dispatch is refused. SAB-003's original `qualify` function gives finite-witness `computational_fragment` evidence.
3. **Compose.** `CompositeFormationController` combines the qualified constructed compute host with independently qualified `framed_ipc` and `retained_state` hosts and the original SAB-004 `PlacementAuthority`. It binds construction inventory/policy fingerprints to the placement plan and recompiles before execution.
4. **Retain and decide.** `AdaptivePlacement.execute` remains the sole state-commit implementation in this integration. It sends the framed computation result, stores and reads back each immutable checkpoint, and publishes a separate commit marker only after the required copies exist. SAB-011 adds a receipt connecting SAB-010 formation provenance to SAB-004's existing accepted-result receipt; it does not rewrite checkpoint formats.
5. **Resume without compute.** A newly constructed controller with only the original known storage roles can invoke `AdaptivePlacement.resume` through one surviving admitted storage host. That host must supply a compatible checkpoint **and its committed decision**. Neither compute nor relay executes during readback.

The experiment uses two different construction paths: a navigator formed from separately invoked software-modeled arithmetic ports and a newly installed Python interpreter seed. Distinct mechanism traces are not mistaken for distinct physical failure domains. A test deliberately removes the preferred port-formed computation host and re-plans onto the interpreter-formed host.

## Authenticated network test

A separate integration test launches independently addressable TLS listeners for relay, store-a, and store-b; every receiver has a separate certificate, fixed allowlist, and durable folder. The origin must present an approved certificate with exact expected DNS subject-alternative-name. The test qualifies those peers through SAB-003 over SAB-005's real mTLS endpoint; no remote source or Hypervisor capability is accepted from client arguments. The compute host is locally constructed from split arithmetic ports, **not** remotely installed via mTLS in this milestone. The test executes with two storage replicas, restarts the surviving storage listener while stopping the relay and other store, and reconstructs the accepted observation from a newly formed controller.

## Falsifiers and required refusals

- Conflicting Ground, intention, local authority or primitive inventory invalidates a plan or accepted checkpoint.
- Missing/expired role qualification and absent local operator grant do not become eligible through advertisement.
- Arbitrary source dispatch never reaches a dynamically evaluated program.
- A reused request nonce with a different payload is refused by the constructed local computation interface.
- A staged checkpoint without an accepted decision is not recovered as committed; an invalid or corrupt record is refused by SAB-004.
- A TLS peer with a wrong signed client SAN is refused. A storage-only listener refuses `affine_mod` even with a well-formed request.

## Verification scope

Local subprocess tests show process-separated IO and durable readback; the direct TLS tests, when completed, show verified mutual-TLS **process boundaries**, not independent machines. Python/JavaScript source formation happens on authorized preconfigured interpreter surfaces (SAB-009). The software-modeled gate is not a physical chip. Content digests are integrity witnesses, not digital signatures, and role qualification from bounded probes is not general attestation. SAB-004's two storage copies and decision marker are **not** a Byzantine quorum certificate, and the direct TLS client is **not** native multi-hop ComputationalFabricForwarding. No exact-once guarantee is claimed for arbitrary effects.

## Next integration gates

Connect formed computation roles to receiver-local native Virtual Layer/Hypervisor admission and standard `ComputationalFabricForwarding` instead of the caller-mediated direct TLS path. Anchor the accepted SAB-004 composite checkpoint in `RecoveryLineageCoordinator` with a real durable majority; test competing controllers, revoked grants during failover, changed certificate identity, route lease expiry, lost acknowledgements and independently restarted physical machines.

This work remains in active development. Source installation requires **explicit authorization from the receiving environment**: passive reception or public network reachability is not a deployment grant.
