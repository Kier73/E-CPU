# IOS-003 — authenticated selected-observation execution

**Status:** bounded native E-CPU mTLS / ReliableChannel experiment with receiver-owned provider admission and durable SQLite completion, not a general fabric scheduler, portable signature format, or full Hypervisor integration.

## Question and path

Can a receiver hold a finite intention-relative Ground and public observation, request only the smallest authorized feature set, and resolve the intention from a separate observer-host's responses without transferring the full hidden state?

```text
Receiver: finite Ground + IOS-001 plan
   │   exact IOS-002 request / scheduler / challenge
   ▼
Authenticated mTLS stream (SocketTransport + ReliableChannel)
   │
   ▼
Provider: native contract + installed callback + local admission
   │   validate peer, context, Ground, allowed feature domain
   │   persist request/receipt in SQLite transaction
   ▼
Reliable response: native ObserverReceipt only
   │
   ▼
Receiver: native IOS-002 receipt reconstruction and local authorization
   ▼
Intention result (without provider's hidden state)
```

`mailcpu.intention_measurement_fabric` provides `HostedMeasurement` (one receiver-installed pure observation and local policy), `MeasurementReceiptLedger` (durable idempotent completion), `MeasurementPeerServer` (peer-bound handler), and `MeasurementPeerClient` (verified TLS request/response and IOS-002 reconstruction).

The provider enforces its **own** permitted peer identities, exact observer contract and Ground/context binding, request freshness, feature result domain, and `admit(request, client_peer_id)` callback, before returning a feature-only projection. Merely advertising or requesting a capability does not authorize it. Mutual TLS validates both peer certificates and required DNS SANs. ReliableChannel performs sequencing, retries and transport duplicate suppression.

A SQLite transaction using WAL + synchronous FULL commits the completed response before ReliableChannel acknowledges the request. Retrying the same exact request after a reconnection returns the retained receipt. Reusing an existing challenge with changed request content refuses. This permits **pure observer** idempotent replay; it does not make arbitrary external side effects exactly once or durably checkpoint live channels.

## Reproduce

```sh
python -m pytest tests/test_intention_measurement_fabric.py -q
```

Tests exercise policy refusal before a read, schema and forbidden-feature rejection, stale challenge refusal, duplicate/collision recovery, and localhost mutual TLS with an independently running server thread and actual SocketTransport. TLS fixture requires `openssl`; non-TLS tests have no external dependencies.

## Verified scope and next experiment

- The private phase remains inside the provider's installed callback and is never included in the wire request/response. This is interface-level non-disclosure, **not** protection against a compromised provider, arbitrary side channels, or access to the machine's process memory.
- Observable projection hashes and on-disk ledger identity are *not* signatures. The live authenticated stream supplies peer attribution; the receiving party should not treat an exported receipt as independently authenticated without separate signature/attestation verification.
- A receiver-owned callback must still check real Hypervisor capability grants, current policy, peer lease, and state-specific measurement rights. This experiment deliberately does **not** manufacture such a grant.
- A localhost TLS test establishes distinct endpoints and certificate identities, not independent physical hosts, failure domains, or host processes.
- Measure real bytes, duration and cryptographic overhead separately from IOS-001's declared symbolic costs.
- Next: run two supervised processes/physical hosts with pinned Ground and authenticated hosted capabilities, integrate native Hypervisor/coordinator admission, and restore across independent crashes with third-host audit.

Related: [IOS-001](INTENTION_RELATIVE_OBSERVATION_SUFFICIENCY.md), [Observer contracts](OBSERVER_ORBIT_CONTRACT.md), [Computational fabric](COMPUTATIONAL_FABRIC.md), [Persistent recovery](RECOVERY_LINEAGE.md), and [GCI-003](https://github.com/Kier73/In-Formation-Space/tree/main/experiments/cross-ground-continuity/gci003).
