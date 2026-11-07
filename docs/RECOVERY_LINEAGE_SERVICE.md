# Recovery-lineage authority service

## Role and deployment shape

**RecoveryLineageAuthorityService** is the long-lived server process for one non-owner authority. It accepts only the fixed owner's mutually authenticated TLS identity, serves one reliable recovery-lineage stream at a time, and returns to the listener when that stream disappears. The journal path is independent of the stream lifecycle: reconnecting constructs a fresh participant over the same journal, so an interrupted owner connection does not create a new authority identity or reset the member's durable vote/decision history.

The service does not spawn or supervise its own OS process. Run one service instance per non-owner member under an external process supervisor or orchestrator, such as systemd, Kubernetes, or an equivalent host manager. Place each member on its own machine or failure domain and mount only that member's protected persistent journal storage.

~~~text
             owner process A
      owner journal + coordinator
         /                 \
   mTLS stream           mTLS stream
      /                       \
service B                   service C
journal B                   journal C
managed by B's              managed by C's
host supervisor             host supervisor
~~~

## Identity binding

Provision a CA-trusted certificate for each fixed membership identity. The owner client certificate must contain the owner DNS SAN configured on every authority service. Each authority certificate must contain its own DNS SAN, which the owner supplies as server_hostname when connecting. The service validates the owner's client certificate and exact expected DNS SAN; the owner validates the authority certificate chain and DNS SAN. Member IDs remain protocol identities, while DNS SANs are explicitly provisioned transport identities.

Do not infer the DNS name from a member ID or accept a peer certificate solely because it chains to the trusted CA. Keep the membership snapshot, member-to-DNS mapping, certificates, and owner term under deployment control.

## Starting one authority member

Install the package and provision a server certificate/private key plus a CA bundle used to verify the owner client certificate. Then run:

~~~sh
mailcpu-recovery-authority \
  --membership /etc/mailcpu/membership.json \
  --member-id B \
  --journal /var/lib/mailcpu/recovery/B.jsonl \
  --host 0.0.0.0 \
  --port 7443 \
  --certificate /etc/mailcpu/tls/member-b.pem \
  --private-key /etc/mailcpu/tls/member-b.key \
  --client-ca /etc/mailcpu/tls/authority-ca.pem \
  --expected-owner-dns owner-a.internal
~~~

A representative systemd policy is:

~~~ini
[Unit]
Description=MailCPU recovery-lineage authority B
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/opt/mailcpu/venv/bin/mailcpu-recovery-authority --membership /etc/mailcpu/membership.json --member-id B --journal /var/lib/mailcpu/recovery/B.jsonl --host 0.0.0.0 --port 7443 --certificate /etc/mailcpu/tls/member-b.pem --private-key /etc/mailcpu/tls/member-b.key --client-ca /etc/mailcpu/tls/authority-ca.pem --expected-owner-dns owner-a.internal
Restart=on-failure
RestartSec=1
User=mailcpu
Group=mailcpu
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/mailcpu/recovery
~~~

The process supervisor restarts the service after process failure. The authority service itself handles stream loss and invalid TLS attempts without exiting. Protect the journal from concurrent writers: one active service process must own a member journal at a time. Use a durable filesystem with documented fsync guarantees, restricted file permissions, backups, and operational monitoring.

## Connecting from the owner

The owner uses an SSL client context with CA validation, hostname checking, and its own client certificate:

~~~python
import ssl

from mailcpu import (
    DistributedRecoveryLineageCoordinator,
    RecoveryLineageAuthority,
    RecoveryLineagePeerClient,
)

owner_context = ssl.create_default_context(
    ssl.Purpose.SERVER_AUTH,
    cafile="/etc/mailcpu/tls/authority-ca.pem",
)
owner_context.load_cert_chain(
    "/etc/mailcpu/tls/owner-a.pem",
    "/etc/mailcpu/tls/owner-a.key",
)

owner = RecoveryLineageAuthority(
    membership, "A", "/var/lib/mailcpu/recovery/A.jsonl"
)
peer_b = RecoveryLineagePeerClient.connect_mutual_tls(
    membership,
    "B",
    "member-b.internal",
    7443,
    owner_context,
    server_hostname="member-b.internal",
)
peer_c = RecoveryLineagePeerClient.connect_mutual_tls(
    membership,
    "C",
    "member-c.internal",
    7443,
    owner_context,
    server_hostname="member-c.internal",
)
coordinator = DistributedRecoveryLineageCoordinator(
    membership,
    {"A": owner, "B": peer_b, "C": peer_c},
)
proof = coordinator.seal(manifest)
~~~

When a peer stream fails, close that peer client and create a new RecoveryLineagePeerClient.connect_mutual_tls(...) against the same configured member endpoint. The service accepts the replacement connection and reconstructs the participant over its existing journal. A deployment supervisor or owner-side connection manager should apply bounded retry/backoff and expose peer liveness; it must not create a new membership or journal when reconnecting.

## Failure experiments

The tests in tests/test_recovery_lineage_service.py cover:

1. Both remote streams are severed. The owner alone cannot form a prepare quorum and refuses to advance. The still-running B/C services accept fresh TLS connections, recover their journals, and seal the original generation.
2. A client expects member C's DNS SAN but connects to B. TLS verification fails; B remains alive and accepts a subsequent correctly authenticated owner connection.
3. The owner process is hard-killed immediately after its PREPARE record is fsynced. A replacement owner process reopens the same journal, obtains the exact original vote, and completes the generation with B/C.
4. B and C cannot form an admissible certificate without the fixed owner A's vote. The protocol does not self-elect a replacement owner.

The service also preserves the prior PR #42 tests for process death after remote PREPARE, after remote COMMIT, and after quorum completion.

## Operational limits and proof boundary

The tests use independent local processes, ephemeral test certificates, loopback TCP, and deliberate stream closure. They establish certificate-chain and DNS-SAN authentication, reconnection to an existing member journal, quorum refusal below threshold, and exact same-owner restart recovery. They do not establish separate physical-host fault domains, firewall-level partition behavior, arbitrary packet-loss/latency tolerance, certificate revocation or live rotation, storage power-loss guarantees, Byzantine tolerance, or automatic leader election.

Membership and owner term remain fixed. A replacement owner cannot simply claim the owner identity with a different term; changing ownership requires a separate safe membership/term-transition protocol. Until that exists, owner failure is fail-closed: remote members do not elect themselves, and the same owner identity/term must recover its durable journal.
