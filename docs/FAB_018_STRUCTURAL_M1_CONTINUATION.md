# FAB-018 — Structural M1 realization under native M3

## Identity and representation

FAB-017 defines a bounded, exact one-hop snapshot delta. FAB-018 places this behind the original M1 object-store interface, instead of changing M3's checkpoint or introducing another state authority. A raw canonical JSON object S has native manifest M(S), including its complete SHA-256, ordered padded page hashes, geometry, media type and canonical manifest identity. Given a pinned raw base B, the alternate representation is D(B,S), which reconstructs S exactly. Admission requires M(reconstruct(B,D)) = M(S), including every ordered page hash. No alternate representation can change the native M3 checkpoint or advance its revision by itself.

`StructuralObjectStore` subclasses `ComputationalObjectStore`. A digest-only backing invokes the original M1 manifest formation code without retaining target raw pages; this internal descriptor formation is not an admission claim. Before returning that descriptor, the adapter publishes the alternate record through `SnapshotCatalog` (SQLite local transaction, synchronous FULL). The catalog key is the native manifest digest. The catalog pins one raw M1 base manifest; rows retain target digest, exact target length and typed structural patch. An existing identical row is an exact retry, while different bytes for the same manifest key are refused. Opening without an explicit base never creates an absent catalog. The base is read from native backing at reconstruction time, so a lost base is not hidden by a process-local cache.

The native M3 store still uses its original put_bytes, verify, read_bytes and exact predecessor CAS. A represented object is fully reconstructed and independently described before verification or a range read succeeds. An absent record permits the original native raw lookup; a present corrupt record refuses rather than silently falling back. A missing raw object and missing representation cannot create empty replacement state. Stream puts, non-JSON, noncanonical JSON, objects outside the 4 MiB structural domain and descriptions failing the size heuristic retain the normal M1 raw path. The heuristic charges the encoded delta and a 128-byte record allowance; it is not a calibrated storage/latency optimizer.

Publication order: native raw base available -> durable alternate row -> native M1 verification -> original M3 checkpoint persistence and quorum CAS. A crash between row publication and M3 admission may leave an unreachable row, not a new committed machine revision. No garbage collection or production raw-copy deletion is authorized. This local representation catalog must be backed up or replicated with the pinned base before it can supply independent-host durability. Existing M3 exported checkpoint/proof remains unchanged and requires the destination to have either original pages or the alternate representation provider. Direct PageBacking clients cannot read omitted target pages from that backing. Range reads materialize the complete alternate object; no sparse reconstruction or delta-chain navigation is claimed.

## Local verified evidence

Exact native M1 source recovered from GitHub: blob 68e354ba0141fb8daaf4dd4b1da369b8b389d6de. Exact new module blobs: snapshot_catalog.py b21e6ff4980fa38906f0316accaae26f6c617eae; structural_object_store.py c43c966dc88b84507811c2c5bfa393d974b6649d. FAB-017 snapshot_delta.py 476a1ff3c4a89d15247e0d8d876ee74b4c48c87b.

Nine local tests passed against the actual native M1 source and a test page backing: immutable catalog conflict and exact retry; parallel writes by eight threads; abrupt process exit after commit and before a later transaction commits; missing and corrupt base/row refusal; 32 distinct native objects with identical raw and structural manifests, native range reads, reopen and retry with no new retained raw pages; ordinary stream/noncanonical fallback; corrupt row refusal even if raw pages are available; forged per-page digest refusal. The process-loss test is local SQLite recovery, not a power-loss or independent-host trial.

The reproducible benchmark uses 1,024 synthetic canonical application-shaped objects from FAB-017. The backing counts exact native padded page bytes in memory. The catalog is an actual SQLite file after reopening, including its own metadata. All 1,024 native manifests are identical between the raw and alternate routes; all 1,024 independently verified and read after catalog reopen.

| Metric | Measured |
|---|---:|
| Logical object bytes | 42,118,996 |
| Native raw distinct page bytes | 10,375,168 |
| Alternate retained base pages | 45,056 |
| Catalog file bytes | 450,560 |
| Alternate base + catalog bytes | 495,616 |
| Identical manifest bytes, either route | 1,575,936 |
| Raw put time (in-memory backing) | 0.232969 s |
| Alternate put time (SQLite FULL, formation and verification) | 7.734938 s |
| Alternate verification plus read time | 3.880319 s |

The page-and-representation payload reduction is 20.93x. Charging the identical serialized manifest bytes to both sides changes the ratio to approximately 5.77x. Neither figure includes M3 lineage, filesystem allocation overhead, replication or other host overhead. The raw and structural write timings are not matched durability comparisons: native raw writes here are in-memory, while structural records use durable local transactions. Structural formation and repeated full reconstruction remain important costs to measure. The original 1,024-object experiment is synthetic, not native OS density.

## Native M3 and attention integration

The hosted test uses eight independently admitted actual HeadlessOS machines named fab127.<namespace>.<24-bit-id>, each at a live file-descriptor/memory cut. It first creates ordinary native M1/M3 states, then forms and verifies structural representations of the same state manifests in an isolated second page backing. It imports the unmodified M3 exports, removes only the disposable original raw-page test directory after verification, reopens catalog/base and native lineage, and checks exact native rejoin identity and private memory. The merged FAB-014 attention planner selects one ready application at a time from actual M3 observations; the controller reopens and revalidates the revision and digest before using the existing native M3 adapter. A fresh interpreter realizes each candidate; the native closed-state backend independently verifies it. An abrupt worker loss before publication, exact retry and corrupted structural row challenge unchanged quorum high-water. The final output file, common file and journal are verified. The test uses explicit HALT (independent of pending terminal-SYSCALL repair), original absolute scheduler ceiling 5 after tick 3, and local native RemotePageStore without remote peers. Candidate execution and reference realization are separate; workload attention vector is advisory, not total host metering.

Hosted integration is pending. Direct local checkout still fails DNS, but the exact standalone native M1 module was recovered and tested locally. FAB-018 is stacked on FAB-017; FAB-015 canonical address helper and FAB-016 machine-head index remain separate pending PRs. The test uses their compatible stable name form, not the unmerged index API.

## Next implementation

1. Measure real native M3 storage breakdown and reconstruction costs; select shared bases and representations by measured cost including manifest and lineage overhead.
2. Integrate FAB-016 current-head resolution and incremental readiness summaries with the merged allocator after native verification. Observe state via head and trusted M3; avoid reading complete state for every unselected machine.
3. Replicate catalog records and base objects over existing durable communication paths before acknowledging independent-host recoverability. Publish and recover representation availability with existing native authority, not a second machine lineage.
4. Bound repeated full-state reconstruction and retain independently verified reusable structural components. Preserve native exact manifest and state identity while optimizing the work of interpretation.
