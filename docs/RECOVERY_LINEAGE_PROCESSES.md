# Distributed recovery-lineage authorities

## Process topology

The recovery-lineage protocol can run with one owner/coordinator process and
one remote process per non-owner authority member. The owner process also owns
its own durable authority journal. For a three-member membership:

```text
                 owner process A
          coordinator + authority journal A
                 /             \
                /               \
      reliable TCP             reliable TCP
              /                   \
 authority process B         authority process C
 journal B                   journal C
```

Each remote process opens exactly one `DurableSeedCommitLedger` through
`RecoveryLineageProcessParticipant`. Its journal path is local to that
process's storage domain. A process restart reopens that same journal and
reconstructs the participant ledger from its hash-chained durable records.
`RecoveryLineageAuthorityService` now provides the long-lived server loop:
it accepts one mutually authenticated owner stream, serves the participant,
and returns to the listener after disconnect so a fresh owner stream can
rebind to the same member journal.

The owner uses `RecoveryLineagePeerClient` to bind each remote member to a
`SocketTransport` plus two `ReliableChannel` instances. The requests and
responses use the existing seed-quorum channel identities:

- `seed.commit.quorum.request`
- `seed.commit.quorum.response`

The recovery protocol defines its own typed message kinds on those channels.
It does not reuse seed-mutation requests or transition artifacts; checkpoint
lineage has its own smaller request algebra.

## Message algebra

| Request | Durable participant action | Response |
|---|---|---|
| Recovery prepare | Validate fixed membership and fsync the single-valued slot vote | Typed `SeedPrepareVote` |
| Recovery commit | Validate the strict-majority certificate and fsync the decision | Typed `SeedCommitDecision` |
| Recovery inspect | Read the local committed high-water and requested slot's proposal, certificate, decision, and journal validity | Read-only state projection |

The receiver performs the ledger action inside
`ReliableChannel.receive(commit=...)`. The participant therefore only
consumes and acknowledges a request after the corresponding durable ledger
operation has completed. PREPARE and COMMIT replies are sent only after their
respective fsync operations return.

Each request and response is bound to the configured owner/member endpoint,
request ID, protocol phase, membership digest, proposal digest, and exact
record identity. A response arriving over another peer connection or for
another request/phase is rejected.

## Owner coordinator

`DistributedRecoveryLineageCoordinator` extends the existing recovery-lineage
algorithm. It accepts:

- one local `RecoveryLineageAuthority` for the configured owner;
- one `RecoveryLineagePeerClient` for every other configured member.

The inherited `seal`, `latest_proof`, `high_water`, and
`verify_checkpoint_bundle` operations retain their strict-majority and
owner-vote rules. Remote transport failures are treated as unavailable
members; they do not become votes or decisions. The coordinator returns a seal
proof only after a strict majority of participants have durably committed.

The owner process is also an authority participant. Its vote and decision are
written to its own local journal, not synthesized by the network coordinator.

## Restart and fault-injection protocol

The participant exposes a test fault hook at two precise points:

- `after_prepare_fsync`: after the local PREPARE record and vote are durable,
  before the vote response is published and before the request is acknowledged;
- `after_commit_fsync`: after the local COMMIT record and decision are
  durable, before the decision response is published and before the request
  is acknowledged.

The integration tests launch actual Python child interpreters for B and C.
They terminate B after each named fsync boundary, preserve its journal, launch
a replacement interpreter under the same member identity, and attach a fresh
TCP transport. The retry then demonstrates:

1. A PREPARE retry returns the exact original vote receipt.
2. A COMMIT retry returns the exact original durable decision and certificate.
3. The owner reuses the original prepare certificate after a partial commit;
   it does not create a different voter projection.
4. After a complete quorum seal, both remote processes can be hard-killed and
   restarted. A newly constructed owner coordinator reads a quorum of matching
   generation/root pairs from the reopened journals before admitting the
   stored recovery bundle.

## Usage sketch

The owner process opens its own journal and connects to each remote authority:

```python
from mailcpu import (
    DistributedRecoveryLineageCoordinator,
    RecoveryLineageAuthority,
    RecoveryLineagePeerClient,
)

owner = RecoveryLineageAuthority(membership, "A", authority_directory / "A.jsonl")
peer_b = RecoveryLineagePeerClient.connect(membership, "B", "127.0.0.1", port_b)
peer_c = RecoveryLineagePeerClient.connect(membership, "C", "127.0.0.1", port_c)

coordinator = DistributedRecoveryLineageCoordinator(
    membership,
    {"A": owner, "B": peer_b, "C": peer_c},
)
proof = coordinator.seal(manifest)
```

Each remote process can either construct `RecoveryLineageProcessParticipant`
directly over an accepted stream, or run `RecoveryLineageAuthorityService` with
a server SSL context, expected owner DNS SAN, and persistent journal path.
The `mailcpu-recovery-authority` command exposes this service for deployment.
An external supervisor owns process launch/restart, machine placement, journal
provisioning, certificate distribution/rotation, and endpoint configuration.
The service itself handles connection loss and accepts a new TLS stream without
replacing the member's journal.

## Failure semantics and proof boundary

A remote process that disappears before its vote is durable is unavailable.
A process that disappears after PREPARE fsync can recover its exact vote from
the journal. A process that disappears after COMMIT fsync can recover its
exact decision and certificate. A partial commit is not a read high-water
until the owner can observe a strict majority of matching committed states.

After post-quorum process loss, recovery reopens the persistent member
journals and queries each process again. The owner does not treat its own
previous result object as proof that the remote processes still hold the
committed state.

This implementation runs the owner authority/coordinator in one process and
each non-owner member in a separate service process. Mutual TLS now verifies
certificate chains and the configured DNS SAN for each side; the service can
accept fresh authenticated streams while retaining its journal. The tests
establish process-level separation and stream recovery, not physical-host
isolation. Production deployment still requires separate machines or fault
domains, protected durable storage, an external process supervisor, certificate
lifecycle controls, and an explicit membership/owner-term lifecycle. It is not
Byzantine consensus, automatic owner election, or a power-loss qualification.
See `RECOVERY_LINEAGE_SERVICE.md` for the TLS service and deployment contract.
