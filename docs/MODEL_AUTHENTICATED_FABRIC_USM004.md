# USM-004 — An authenticated model host operating E-CPU

**Status:** implementation and test suite proposed; live hosted evidence must
come from the accompanying workflow, not this description.

USM-001 trained an advisory controller and invoked E-CPU Ground services.
USM-002 allowed a separate model process to issue typed E-CPU calls. USM-003
introduced artifact-mediated independent reconstruction in In-Formation-Space.
USM-004 adds a real **mutually authenticated MailCPU socket and ReliableChannel
communication path**, joining a model process to a receiver-owned Ground.

## Reusing E-CPU instead of emulating it

The model and the receiver run in separate operating-system processes. They
communicate over E-CPU's existing `SocketTransport`, `connect_mutual_tls`,
`accept_mutual_tls`, and `ReliableChannel`, not a separately invented
JSON-over-TCP protocol.

The bidirectional operation has these stages:

```text
Model OS process                           E-CPU receiver OS process
      |                                               |
      |    authenticated mTLS + MailCPU channels       |
      |<---------- stage/new prompt -------------------|
      |-- model asks observe ------------------------->|
      |<---------- bounded observed window ------------|
      |-- model evaluates a trained policy ------------|
      |-- propose or defer --------------------------->|
      |                     E-CPU evidence verification |
      |                     receiver admission policy  |
      |<------------ admitted Ground / refusal --------|
      |-- read(target coordinate) -------------------->|
      |                     revision-pinned navigation |
      |<------------- read receipt + value ------------|
      |<------------- final trace digest --------------|
```

Each directional message is a MailCPU reliable frame with a sequence number,
transport ACK, channel name and peer-scoped address. The receiver runs
`session.apply` in the reliable channel's commit callback before transport
ACK emission. This ordering is important but **does not by itself make
process-crash recovery durable**. That requires restoring session, journal
and channel checkpoints atomically, to be tested in the next stage.

The model worker has no reference to `StructuralMemoryRegistry` and cannot
choose the receiver's held-out observation samples, override receiver policy,
change the user's target coordinate, or promote a Ground with a probability
score. It receives only an explicit source window during the `observe` call.

The receiver accepts the model client's certificate only if its CA chain
verifies and its DNS subject alternative name matches `model-node`. The client
verifies the server's hostname `receiver-node` under its configured CA. These
identities are names in short-lived test certificates, not production trust
identities. The model's advertised name is not enough to authenticate it.

## Reproduction

```bash
python -m pytest -q tests/test_model_authenticated_fabric.py
```

This test constructs temporary TLS identities using the `openssl` CLI,
launches independent Python subprocesses, opens an actual loopback TCP
listener, authenticates both peers, and exchanges real MailCPU messages.
It covers:

- An affine observation stream admitted by E-CPU, with a real read at
  logical coordinate `1_000_000_000_137` and an independent source check.
- A deliberately high-confidence model requesting a nonlinear Ground, with
  E-CPU free to refuse.
- A model whose policy chooses to stop after observing.
- Two **unforced trained-model** operating sessions, with separate affine
  and nonlinear sources. The training result does not override receiver
  evidence and can produce a proposal or a deferral.
- A request made without host admission authority.
- A certificate issued by the same test CA but with the wrong client DNS SAN:
  authentication must stop before any Ground-service call.

## Scope of the evidence

This uses **two real OS processes and a real authenticated socket**, but both
processes run on the same physical runner. The network route is loopback.
It therefore does **not yet** demonstrate operation between physical hosts,
cross-network reachability, or robust session recovery. The worker's OS user
permissions are not sandboxed; separation is by process and software API.
The trusted certificate authority, model artifact and receiver admission
policy are provisioned by this test.

The data is an explicitly generated finite mathematical stream, not physical
sensor telemetry. E-CPU's witness-grounded status remains evidence-bounded
and is not an infinite-domain proof. The operation trace digest provides
content integrity, not a signature or external attestation. Peer
authentication comes from the TLS certificates.

## Path to USM-005

Persist the receiver's exact session, journal, StructuralMemoryRegistry
revision, and MailCPU reliable-channel state at a shared checkpoint cut.
Kill the receiver after effect commit but before an acknowledgement, restart
on a new mTLS socket, and have the model retry the same semantic intention.
An independent VGI/IFS observer should reconstruct one admitted Ground and
one accepted result despite the transport's at-least-once delivery.

The ultimate question is whether a model can preserve its active
computational intention while its operating environment changes from one
authenticated observer-host to another, without promoting unverifiable
claims into system truth.
