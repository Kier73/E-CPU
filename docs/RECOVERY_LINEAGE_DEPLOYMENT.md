# Recovery-lineage multi-host deployment topology

## Purpose

PRs #42–#44 established durable recovery-lineage authorities in independent processes, mutual-TLS identity checks, reconnect to an existing journal, strict-quorum behavior through a TCP stream blackhole, and catch-up after a member rejoins.

The next boundary is placement across independent machines and failure domains. This document defines a machine-checkable deployment description for that topology. It does not claim that physical hosts have been provisioned or that network reachability has been exercised from this repository environment.

## Topology model

A schema-v1 topology contains:

- One exact fixed-membership snapshot, including system identity, incarnation, owner, owner term, genesis digest, and strict-majority quorum.
- Exactly one topology member for every member ID in that snapshot.
- One owner and at least two non-owner authorities.
- A unique host ID, declared failure-domain label, and TLS DNS identity for every member.
- A distinct endpoint host and port for every remote authority.
- An absolute, node-local journal path and distinct certificate, private-key, and peer trust-bundle paths for each member.

The owner is not exposed as an authority-service endpoint in this topology. It runs the coordinator locally. Each non-owner authority runs the existing mutual-TLS service on its own host.

The example at examples/recovery-lineage-topology.json uses documentation-only IP addresses (192.0.2.0/24) and the reserved .test DNS suffix. Replace these with provisioned host addresses and certificate SANs before deployment. Its paths and membership digest are illustrative.

## Validate and derive membership

Install the package on the deployment-control host, then validate the topology:

~~~sh
mailcpu-recovery-topology \
  --topology examples/recovery-lineage-topology.json \
  --write-membership /etc/mailcpu/membership.json
~~~

The command exits zero only if the topology is structurally valid. It prints a redacted summary containing the canonical topology digest, fixed-membership digest, member count, strict quorum, declared failure-domain count, and authority endpoints.

The optional membership output is the normalized SeedCommitMembership snapshot consumed by each existing authority service through its --membership argument. Distribute an identical copy to every authority and the owner. Do not independently edit the membership on individual machines.

Python callers can construct or restore the same validated object:

~~~python
import json
from pathlib import Path

from mailcpu import RecoveryLineageDeployment

payload = json.loads(
    Path("examples/recovery-lineage-topology.json").read_text(encoding="utf-8")
)
deployment = RecoveryLineageDeployment.from_snapshot(payload)
print(deployment.digest)
~~~

## Three-host placement

The intended deployment is:

| Logical member | Process placement | Persistent state | Transport identity |
|---|---|---|---|
| A (owner) | Host A | A's local recovery journal | owner certificate with owner DNS SAN |
| B (authority) | Host B | B's local journal | B server certificate with B DNS SAN |
| C (authority) | Host C | C's local journal | C server certificate with C DNS SAN |

All three hosts must be independently provisioned. The operator must place them in distinct failure domains appropriate to the environment (for example, separate availability zones and separate machines). A distinct DNS name or IP alone is not evidence of separate physical infrastructure.

On host B, use the topology's B values to run the already-existing service:

~~~sh
mailcpu-recovery-authority \
  --membership /etc/mailcpu/membership.json \
  --member-id B \
  --journal /var/lib/mailcpu/recovery/B.jsonl \
  --host 0.0.0.0 \
  --port 7443 \
  --certificate /etc/mailcpu/tls/authority-b.pem \
  --private-key /etc/mailcpu/tls/authority-b.key \
  --client-ca /etc/mailcpu/tls/owner-ca.pem \
  --expected-owner-dns owner-a.mailcpu.test
~~~

Host C runs the same command with member ID C, C's journal/certificate/private key, and the configured C endpoint. Both services remain under an external supervisor (systemd, Kubernetes, or an equivalent host manager). Exactly one live process may own each member journal.

The owner runs its local RecoveryLineageAuthority over A's journal. It creates one RecoveryLineagePeerClient for B and one for C using each configured endpoint host, port, and TLS DNS name, then supplies those peers to DistributedRecoveryLineageCoordinator. The owner-side SSL context must load its client certificate and trust the authority CA; each authority service must trust the owner CA and require the expected owner DNS SAN. These are the same mutual-TLS rules already described in RECOVERY_LINEAGE_SERVICE.md.

Network policy must allow the owner-to-authority TCP paths on the configured ports. Keep private keys on their respective hosts; the topology file contains paths only, never key material.

## What the validator establishes

The implementation and tests establish that:

1. The deployment snapshot has exactly the schema-v1 field set and round-trips to a canonical digest.
2. The configured member IDs cover the fixed membership exactly, including exactly one owner role.
3. There are at least three members, each with a distinct declared host ID, failure-domain label, and TLS DNS identity.
4. Remote authority endpoints do not alias the same normalized IP/DNS host.
5. Every member declares absolute node-local journal/TLS paths, and those four resource paths are distinct within that member.
6. The CLI can emit the normalized fixed-membership snapshot without printing private-key paths.

The test suite exercises these constraints in tests/test_recovery_deployment.py. X-26 in INVARIANTS.md registers the contract.

## Proof boundary and next experiment

This is configuration validation, not deployment attestation. It does not:

- provision virtual machines, containers, cloud accounts, DNS, firewall rules, certificates, or storage;
- resolve DNS names or establish TCP connections;
- inspect certificate SANs, certificate expiry/revocation, or private-key permissions;
- prove that two declared hosts are actually separate machines, racks, zones, regions, power domains, or cloud accounts;
- prove fsync behavior under storage-controller failure or physical power loss;
- test real WAN routing, asymmetric partitions, latency distributions, packet loss, or network failover;
- change fixed membership or transfer owner authority.

The sample addresses are deliberately non-routable documentation values. A successful validator run against the sample is only a schema and invariant test.

The next empirical step is to provision A, B, and C on three separately administered hosts, use real certificates and DNS SANs, start the two remote authority services under their supervisors, and run the existing recovery/partition protocol from the owner. Capture host identity, zone, storage, certificate, and network-path evidence alongside the quorum receipts. Only then should the repository describe the physical multi-host property as demonstrated.

Owner-term transition and membership changes remain separate protocol work. They require explicit joint-consensus or equivalent quorum-intersection proof, durable transition records, stale-owner fencing, and crash-cut tests; this topology validator does not elect or replace an owner.
