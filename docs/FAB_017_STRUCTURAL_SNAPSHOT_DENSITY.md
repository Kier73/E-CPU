# FAB-017 — Exact structural snapshot retention

## Contract

Native canonical HeadlessOS snapshot bytes and their M3 checkpoint identity remain authoritative. A snapshot delta describes how to reconstruct those exact bytes using one pinned base and a typed JSON patch. Base and target SHA-256 plus exact target byte length are independently checked; formation verifies the reconstructed bytes against the supplied target. A representation is not a permission, native admission proof, or replacement for M3. The caller must obtain the expected target digest from trusted state metadata. Both snapshots are bounded at 4 MiB. The implementation does not change M1/M3 persistence or publish a new state root.

The patch algebra is: null = unchanged; [0,value] = exact replacement; [1,removed,changed] = object edits; [2,p,s,middle] = array span; [3,p,s,middle] = string span; [4,edits] = disjoint same-length string mutations at explicit offsets. The last operation preserves unchanged spans between distant writes, important for hex-encoded guest pages. Integer, Boolean, float, and signed-zero encodings are distinguished. Canonical decode refuses duplicate keys/noncanonical bytes; malformed ranges, overlapping mutations, wrong base/target identities and out-of-range sizes are refused. Formation selects a smaller encoding versus direct replacement at each changed node. It is one hop, not an unbounded delta chain; JSON parsing and full target materialization still occur, and formation is not claimed to be sublinear.

## Local results, 2026-11-24

Exact module blob 476a1ff3c4a89d15247e0d8d876ee74b4c48c87b. Twelve tests passed, including 200 seeded mutation cases, disjoint writes, wrong-base and tampering controls, and canonical numeric/type edge cases.

Synthetic workload: 1,024 canonical application-shaped snapshots, sharing 16 KiB pseudo-random artifact data and a 4 KiB initial memory page with independent small mutations, register/file/journal changes. All snapshots independently reconstructed byte-for-byte. This is deliberately shared synthetic data, not measured native HeadlessOS state.

| Representation | Bytes |
|---|---:|
| Raw snapshots | 42,118,996 |
| Independently zlib compressed | 24,635,991 |
| Distinct fixed 4 KiB padded pages | 10,375,168 |
| Base plus initial single-span structural deltas | 4,253,504 |
| Base plus refined disjoint-mutation deltas | 326,091 |
| Compressed base and individually compressed refined deltas | 255,929 |

Refined formation 4.852215 s, reconstruction 1.040698 s. The structural size includes one base and 72 bytes of metadata per delta (two binary hashes plus uint64 length); no extent table, manifests, replication or recovery journals. The first single-span representation copied unchanged data between the base machine's private mutation and another machine's mutation; disjoint replacement corrected that inefficiency. Actual native workloads may share less, and independent compression may win for some workloads. These timings exclude M1 and M3.

## Native density test

The separate hosted test builds 8 actual native HeadlessOS applications without an added common file, then 64 with a shared 16 KiB virtual file. Each native process opens a private file, maps memory and writes independently identifiable bytes. At tick 3 it has a live descriptor and private memory. The test retains original bytes through the native M1 object store, and separately stores one base and a packed bundle of delta records through the same API. It uses independent M1 range reads to recover records, reconstructs exact snapshots, restores real native operating environments and checks that their future execution is byte-identical to continuation from the unmodified original state. It verifies private output files, memory, descriptors and journals, and reports actual padded M1 page bytes, manifest sizes, extent table size and timing. The native test uses explicit HALT to avoid depending on the pending FAB-015 terminal-SYSCALL restore repair. Native measurement is pending hosted verification; direct repository checkout was unavailable locally.

## Next use

Measure actual native density before changing persistent state representation. Choose base scopes and representation using observed costs, preserve independent machine identity and trusted target hashes, and bind any reconstructable representation into the original M1/M3 admission and durable recovery protocol. Keep original snapshots until the alternate representation is verified across independent recovery paths. The benchmark bundle is an experiment, not a production wire format or a durable index; no raw snapshot is discarded by this PR.
