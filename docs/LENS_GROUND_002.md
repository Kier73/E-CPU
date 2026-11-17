# LENS-002 — Native authenticated cross-host realization of lens Grounds

**Status:** dependent experimental integration on LENS-001; network and receiver
tests must pass before claiming verified mTLS operation. This extension reuses
SAB-005's pinned mTLS listener, SAB-008's receiver-native Hypervisor pattern,
Structural Memory proposal/certificate replay, and the existing E-CPU law engine.

## Question

Can the **same** mathematical intention `(spec_digest, certificate_digest,
coordinate)` be realized by two separately authenticated observer-hosts,
without distributing the entire preceding orbit history or trusting a remote
advertisement as authorization?

A LENS-001 Ground is `x(t) = P^-1(F(t))`, with `F` a 64-bit affine
recurrence and `P` one or two whitelisted reversible word frames.

## Implemented request route

```text
origin: recover lens -> StructuralMemory proposal and finite witnesses
  |
  | client allow-set: exact spec digest (no wildcard)
  v
LensNativeDispatcher: exact request/proposal + independent affine oracle
  |
  | SAB-005 MutualTLSQualificationEndpoint (CA + pinned receiver DNS SAN)
  v
PinnedTLSServer: installed receiver opcode + exact local --allow-lens-ground
  |
  v
federated_native_worker (new process each request):
  validate proposal serialization and full certificate/witness replay
  require the receiver-configured spec digest allow-set
  verify coordinate within [0, 10^18] and Structural Memory prefix horizon
  construct locally admitted System Ground and pure Virtual Layer operator
  execute through receiver HeadlessOS Hypervisor with local compute capability
  independently compare output to Structural Navigator's admitted law
  persist native audit by (host,nonce) with immutable replay consistency
  |
  | one canonical response (value + spec/certificate + Hypervisor audit hash)
  v
origin: recheck mTLS response echo + exact Ground + independent binary
affine composition + inverse frames + certificate/witness replay
```

The response's `hypervisor_receipt_digest` identifies receiver-side audit
evidence but is **not** a remote hardware attestation or a cryptographic
signature. The actual transport identity comes from mTLS; the remote process
configuration controls execution authority. Rechecking a digest does not
grant permission to use a Ground.

## Roles and safeguards

- `mailcpu/lens_native_fabric.py`: client `LensNativeDispatcher`, exact
  `LensNativeReceipt`, and independently rerunnable value/receipt checks.
- `mailcpu/federated_placement.py`: one opt-in installed
  `lens64.navigate` operation; explicit `--allow-lens-ground <spec SHA-256>`
  receiver policy. No remote source code is installed.
- `mailcpu/federated_native_worker.py`: receiver-local certificate replay,
  Structural Navigator horizon check, Hypervisor operator dispatch, and
  durable native audit. Existing `affine_mod` path remains intact.
- `tests/test_ground_native_realization.py`: live mTLS fixture now includes
  a second mathematical receiver identity; one lens proposal is queried
  across both and both audit directories are examined. Incorrect TLS
  server identity, wrong local Ground permit and tampered results are refused.

The client transmits the **finite witness set and certificate**, not a full
state tape. Its bounded request frame caps portable proposal size at 8192
bytes; larger evidence sets require a future content-addressed transfer
protocol rather than relaxing this security-critical frame.

## Reproduction

```sh
python -m pytest -q tests/test_lens_ground.py
python -m pytest -q tests/test_ground_native_realization.py
python scripts/verify_repo.py
```

The mTLS fixture creates ephemeral client/server certificates and starts
receiver processes on loopback. Separate identities/processes are exercised;
this is a controlled network test, not a geographically distributed or
hardware-independent benchmark.

## What to measure next

1. Run repeated host restart and fresh-receiver recovery under the same
   pinned Ground; check immutable request replay and audit continuity.
2. Separate the fit/selection witness set from an untouched independently
   selected oracle; prove conjugacy identities where possible.
3. Route the portable Ground through native multi-hop Computational Fabric
   forwarding and quorum-fenced continuity (SAB-007) rather than two
   independent direct mTLS requests.
4. Extend the whitelisted Ground language to signed/revision-aware
   transforms, CRT-time additive components, GF(2) word laws, and ladder
   generators, retaining truthful refusal for unsupported cases.
