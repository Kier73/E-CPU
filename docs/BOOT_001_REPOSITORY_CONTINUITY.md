# BOOT-001A — Repository intention into M3 continuity

## Native composition

The owner explicitly initializes a new M3 lineage from an admitted
INTERNET-007 repository manifest. The artifact digest is the canonical
manifest digest. M3 revision 1 contains INTERNET-007 revision 0; each
successful quantum advances exactly one DAG node and one M3 revision.
This is a distinct experiment, not a migration or reset of the existing
Git state branch.

`mailcpu.bootstrap_001.initialize` creates genesis and returns the original
`SessionRejoinAddress`. `recover` checks immutable scope and obtains the
native M3 high-water. `step` requires the observed checkpoint digest,
reconstructs the original DAG, calls the existing typed read-only operator,
validates its native semantic result and commits through original
`ComputationalSessionStore.commit_state` CAS and recovery authority.
Terminal re-entry performs no source reads or writes. The local caller
chooses the authorized store and read-only observation binding. The
address is not a capability.

## Test

    python -m pytest -q tests/test_bootstrap_001.py

The test launches two existing remote authority service processes under
distinct mTLS identities and invokes fresh owner interpreters across
real loopback TCP. It retains one shared filesystem for M1 pages and
checkpoint records. Source Git/HTTP responses are controlled fixtures,
not a live Internet observation. One hard exit occurs after a source
read before commit, another after commit before acknowledgment.
A subsequent interpreter must recover the exact accepted checkpoint,
reject stale continuation, finish the remaining four operations and
observe terminal no-op. The native authority services remain alive
across owner deaths.

This is the first closure cut, not evidence of geographically separate
hosts, independent disk failure domains, live GitHub observation,
VL-K realization or uninterrupted execution. Hosted qualification is
pending until the exact workflow passes.

## Next cut

Replace the shared filesystem with independently retained M1 objects
and checkpoint records; configure actual owned remote authority endpoints
using the existing deployment and mTLS mechanisms. Bind a source-pinned
VL-K pure operation through existing E-CPU receiver admission and verify
its result before commit. A separate explicitly configured authorized
supervisor may wake a successor; no open-ended dispatch or unapproved
provider provisioning. Track wake delay, transport bytes, physical
execution, quorum recovery, and duplicate accepted effects separately.
