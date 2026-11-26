# BOOT-001B — Network-retained continuation

BOOT-001A stores its native intention DAG in M3. B removes the shared
checkpoint and M1 page directory from the disposable worker, using a
scoped immutable storage receiver over the existing framed mutual-TLS
transport. The original session store accepts an optional record backing;
its ordinary local storage remains the default. The receiver durably
writes pages and records before acknowledging readback. The original
M3 store reads back the record before quorum seal, validates canonical
checkpoint bytes, scope and lineage on recovery, and verifies M1 pages.
There is no mutable latest pointer at the storage receiver.

The retained record is addressed by the native generation and recovery
manifest digest; pages are addressed by their SHA-256. The current
quorum remains the only source of the accepted root. An unavailable
provider is a recovery failure, not permission to construct a new genesis.
The existing owner journal and fixed membership remain necessary.

## Test

    python -m pytest -q tests/test_bootstrap_retention.py

The integration starts real loopback mTLS authority services and a
separate storage-service process. Fresh workers use empty checkpoint
directories and resolve all pages and records over the network. The
owner is killed after acceptance, storage is killed and restarted,
recovery while storage is offline refuses, and the replacement worker
finishes the same DAG. The fixture source responses are controlled.
Storage uses a single receiver-owned disk; the test still retains the
local fixed owner journal, certificate/configuration files and rejoin
address. It is not independent WAN or independent storage failure-domain
evidence. The fixture reuses B's test certificate for storage; separate
service identities are required for deployment. The receiver is a
bounded, explicitly invoked experimental service, not a public daemon
or self-provisioning system. Hosted verification is pending.

## Next

A separately administered owner service and independent retained
providers are needed for full host-independent ownership and availability.
Use separate provisioned identities and actual owned network endpoints.
Integrate VL-K as a pure admitted operation and verify its result
independently before the next native commit.
