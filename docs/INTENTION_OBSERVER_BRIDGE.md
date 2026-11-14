# IOS-002 — Receiver-verified native observer receipts for intention sufficiency

**Status:** bounded, receiver-side integration of IOS-001's finite exact planning with E-CPU's existing `ObserverContract`, `ObserverReceipt`, `RepresentationRef`, and typed `SchedulerReading`. This is **not** a network dispatcher, independent evidence authority, signature verifier, or general Ground compiler.

## Question

When an IOS-001 plan says `MEASURE parity`, how can its selected reading cross the **native E-CPU observer evidence boundary** without elevating an advertised sensor, a self-hashed receipt, or an old plan into authority?

`mailcpu/intention_observer_bridge.py` implements the following flow:

1. The receiver supplies the currently admitted finite model, public reading, capability catalogue, policy fingerprint, selected native observer contracts, typed subject identity, scheduler coordinate, and a **fresh receiver-chosen challenge digest**.
2. `issue_measurement_requests` repeats IOS-001's exact minimum-cost plan check. For each selected feature it binds the model, plan, current policy, public observation, feature, native observer contract, subject, scheduler, and challenge into a stable request digest. This is a proposal, **not permission to dispatch**.
3. A separately authorized sender/receiver path returns native `ObserverReceipt` values. Each must verify under its `ObserverContract`, have the exact feature operation and request digest, and report the same declared logical scheduler coordinate. No omitted, extra, or provider-substituted receipt is accepted.
4. A caller-supplied **trusted receiver verifier** must return exactly `True` on every `(request, contract, receipt)` triple. The caller owns authorization, peer authentication, anti-replay policy, actual source trust and any needed semantic checks. No permissive default exists for a `MEASURE` outcome.
5. Only then does the bridge extract the strict finite-JSON measurement projections and call the existing IOS-001 resolver. The returned report binds the native receipt identities and recomputed result. `verify_observer_resolution` independently re-executes the check.

The `READY` outcome requires no additional observer evidence; the existing public observation and Ground still must be independently admitted before constructing the plan. `REFUSE` issues no measurement requests.

## Formal identity and time relation

Each request identifies the tuple:

`(model, plan, receiver authority, public value, feature, native contract, subject, scheduler ID + tick, fresh challenge)`.

The native `ObserverReceipt.input_digest` must be exactly the request digest, its `operation_id` must equal the selected feature name, and its typed scheduler reading must equal the receiver-selected coordinate. Thus a receipt for a different plan, feature, model, policy, challenge or declared logical time cannot be silently substituted. Exact scheduler equality is deliberately conservative: different clock domains and multiple independently ticking hosts will require a separate causal/temporal equivalence contract. No shared physical wall clock or cross-host elapsed time is inferred.

The native contract must match the selected `MeasurementCapability` by provider ID, full native contract digest and feature projection ID; its interpretation Ground fingerprint and context digest must match the finite model, and its subject must equal the receiver's pinned `RepresentationRef`.

A report's hashes verify **content continuity**, not signatures, host honesty, physical measurement, hardware attestation, or a durable one-time request ledger. The receiver verifier MUST enforce those obligations with existing Hypervisor, authenticated transport, recovery lineage, and policy facilities. A caller-supplied verifier that blindly returns `True` is insecure and must never be used for real untrusted measurements. A fresh challenge rejects cross-request replay only if the receiver truly changes and verifies it. Persistent replay prevention after a crash is future integration work.

## Conformance scope

`tests/test_intention_observer_bridge.py` covers:

- Complete native-receipt `MEASURE -> RESOLVED_AFTER_MEASUREMENT` and independently reconstructed result.
- Rejection of changed challenge (stale replay), scheduler coordinate, Ground, provider contract, receiver policy, and unsolicited measurements.
- Explicit requirement for receiver-side admission, including strict `True` rather than truthy values.
- Tampered output detection, forged-measurement refusal when the receiver rejects it, and strict finite-JSON projection rules.
- No unnecessary query for `READY` and no request issued on `REFUSE`.

Run in the complete E-CPU checkout:

```sh
python -m pytest -q tests/test_intention_sufficiency.py tests/test_intention_observer_bridge.py
python scripts/verify_invariants.py
python scripts/verify_repo.py
```

An isolated developer harness with simplified observer type stand-ins can verify the finite logic and method flow, but **only full repository CI** exercises the actual native E-CPU types and package dependency graph. This experiment does not claim live mTLS, independent failure domains, a physical sensor, or Hypervisor-issued grants until separately demonstrated.

## Follow-on experiment

Wire receiver-verified measurement requests into a controlled local HostCatalogue/Hypervisor execution adapter; then carry receipts through authenticated computational-fabric peers and recovery lineage, with durable challenge use, explicit trust domain independence and measured cost vectors. Preserve the distinct authorities of Ground admission, plan sufficiency, execution permission, transport identity, and actual semantic correctness.
