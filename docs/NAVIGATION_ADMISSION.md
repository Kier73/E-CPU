# Hypervisor-Owned Navigation Admission

## Purpose

NavigationCoordinator derives a replayable path and emits a non-authoritative proposal. This document specifies the next boundary: HypervisorNavigationAdmissionCoordinator asks the running MailCPU hypervisor whether that path may be admitted for a particular process.

The control sequence is:

~~~text
intention
  -> contextual address resolution
  -> abstract and concrete navigation
  -> formal witness replay
  -> trusted live-context reconstruction
  -> PID-derived kernel capabilities
  -> hypervisor policy arbitration
  -> bounded, expiring CPU grant
  -> a later trusted execution adapter
~~~

Admission does not execute the path, mutate process state, reserve resources, or imply that a backend has accepted the path.

## Trusted context boundary

Admission requires an explicit callback:

~~~python
context_provider(pid, descriptor, address) -> ProcessContext
~~~

The provider is a trusted integration seam. It must reconstruct the current state, bindings, resolved dependencies, resource capacity, capability labels, search budgets, and temporal frame from the host's authoritative process and runtime state. It must not merely return a caller-supplied context or copy the context embedded in the proposal.

This seam is necessary because a generic ProcessDescriptor does not currently have a universal mapping to every native MailCPU process, service, transit worker, or backend state. If the provider cannot produce a typed context, admission refuses. If that context does not reproduce the complete coordination result through verify_navigation_coordination, admission refuses.

## Hypervisor and kernel integration

HeadlessOS.hypervisor_arbitrate_event builds the request through the existing _make_hypervisor_request path. The granted-rights projection comes from the actual VirtualKernel process table and its Capability values, not from a claim inside the navigation proposal. The request also carries the current virtual temporal epoch.

The method enters HypervisorArbitrationLoop.arbitrate without dispatching an effectful handler. The existing ClassifierHypervisor evaluates its exact rights gate, classifier and intent proposals, policy thresholds, and review outcome. Its decision is recorded in the same hash-chained journal used by the kernel.

The admission coordinator accepts only:

- ALLOW from the current hypervisor decision;
- the CPU execution domain;
- the actual process capability execute on the normalized resource;
- a currently replayable navigation result with a concrete witness;
- the supplied descriptor, address, and trusted live context matching the original plan.

A policy review, denial, non-CPU domain, invalid plan, unavailable context, or arbitration conflict produces a typed refusal and no grant.

## Grant scope

NavigationExecutionGrant binds:

- one kernel PID and semantic process identity;
- the exact descriptor and semantic-address digests;
- the complete context and coordination digests;
- the coordinator proposal, concrete witness, and final-state digests;
- the ordered transition IDs and maximum step count;
- one normalized resource path, required rights, and peak resource envelope;
- the hypervisor decision receipt and classifier revision;
- an issue tick and expiry tick from the deterministic scheduler.

The validity interval is half-open:

~~~text
issued_at_tick <= scheduler_tick < expires_at_tick
~~~

The maximum number of transitions equals the exact path length. A grant cannot be widened to a different descriptor, endpoint, path, PID, resource, or right without changing its digest and its journal-bound admission record.

The current grant is a local control-plane artifact. Its SHA-256 digest is an identity, not a signature. It is not a transferable bearer capability and is not independently authentic when copied outside the host. A local consumer must verify the grant against the hypervisor decision and admission receipts. Cross-host use additionally requires authenticated receipt transport and receiver-side authority reconstruction.

## Replay and receipts

The arbitration identity is (source, channel, sequence), with channel navigation.admission. An exact retransmission recovers the original decision projection from the existing checkpointed arbitration ledger without reevaluating the model or policy. The same identity with a different request fingerprint is refused as refused_arbitration.

A successful admission appends hypervisor.navigation.admit with the grant projection, grant digest, decision receipt, coordination digest, and replay observation. A refusal appends hypervisor.navigation.refuse. Both share the kernel/hypervisor journal chain.

An exact duplicate can reproduce the same grant identity while the scheduler tick and request fingerprint remain unchanged. A later tick changes the event identity's content and will conflict with reuse of the same sequence; callers must use a new sequence for a new admission attempt. Expired grants are never renewed implicitly.

## Deliberate execution boundary

This layer stops at admission. It does not yet consume grants or execute TransitionRule values against a backend. The next integration layer must:

1. verify the grant's local journal provenance and current PID/resource rights;
2. recheck expiry and that the live state still matches the grant's starting witness;
3. execute at most the bound transition sequence and maximum step count;
4. use the existing effect/replay ledger so the same admission cannot apply the transition path twice;
5. emit a final-state digest and execution receipt, or a typed partial/failure result without pretending that the target was reached.

This separation preserves the distinction among a model's intention, a mathematically reachable path, a hypervisor decision, and an executed state transition.
