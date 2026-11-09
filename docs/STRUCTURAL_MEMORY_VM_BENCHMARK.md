# Paired VM benchmark: resident pages versus Structural Memory

## Purpose

This experiment measures a narrow memory-tier question:

> For the same MailCPU virtual address space and the same touched working set, what changes when untouched pages remain as revision-pinned Structural Memory reservations rather than materialized resident mappings?

It is paired with the independent VM-fleet benchmark but reports a different quantity. The VM-fleet benchmark measures how many independent OS/VM instances pass a declared resident-page budget. This experiment measures one VM's resident-versus-reserved page state, fault and access costs, evidence metadata, and checkpoint behavior.

## Controlled profile

Each case constructs one `HeadlessOS`, one `MailCPUVirtualMachine`, one scheduler, one kernel, and one process memory image. Both cases use:
- identical page size and virtual page count;
- identical deterministic byte contents;
- the same number of initially touched working-set pages;
- the same resident-page ceiling and process memory quota; and
- the same checkpoint/restore path.

The materialized case reserves the full virtual interval and writes every page, forcing each page into a resident mapping.

The Structural Memory case admits one modulo-256 integer-orbit byte-stream per page, pins each page through a `StructuralMemoryFileRef`, and reserves the same virtual interval against those content hashes. It then reads the same working set. First access passes through `StructuralMemoryPageBacking`, which resolves the pinned provider, validates the range receipt and SHA-256 page identity, and only then materializes the page into VM memory. The provider returns the ordered per-byte receipt IDs, but the registry commits them to the shared journal as one range receipt that binds the admitted revision, exact context, coordinate interval, ordered generated-value digest, and ordered receipt-ID digest. Restore re-evaluates the range and verifies both commitments.

## Measurements

The report keeps these quantities separate:

| Measurement | Meaning |
|---|---|
| Virtual bytes | Total address-space coverage: mapped plus reserved pages |
| Resident bytes | Pages currently materialized in `VirtualMemory.mapped_pages()` |
| Reserved bytes | Virtual pages not yet materialized, including their optional backing identities |
| Cold page access | First read of each working-set page; includes the fault and any Structural Memory evaluation |
| Hot access | Repeated reads after the page is mapped |
| Backing descriptor bytes | Serialized page-reference and local-page descriptor state |
| Structural registry bytes | Serialized admitted generators and certificates; range-read commitments are in the shared kernel journal |
| Range events | Durable range-level journal records |
| Coordinate commitments | Number of per-coordinate value receipt identities committed by those range events |
| Checkpoint bytes | Full `HeadlessOS.snapshot()` serialization after the working set has been touched |
| Restore time | Normal `HeadlessOS.from_snapshot()` reconstruction, including trusted registry rebinding |
| Post-restore fault | First read of a previously untouched page after restore |

The restore path deliberately reads one page that was not in the original working set. That confirms that an inert checkpoint reference can be rebound to the trusted local Structural Memory registry and still reconstruct the exact page bytes. The report includes the new resident-page delta and verifies the resulting read receipt.

The host-side `StructuralMemoryPageBacking` cache is a separate tier from guest residency. It retains at most four recently reconstructed structural pages (plus their receipts) using LRU eviction. Once a page has been verified and copied into this cache, the provider's redundant coordinate/value cache is discarded; a later host-cache miss regenerates the same pinned range and validates the same receipt identities. Locally persisted COW pages live in the content-addressed local store and do not consume a second page-cache entry. The report measures retained host page bytes, receipt-coordinate count, and provider coordinate-cache entries separately from guest resident bytes.

## Run

From the repository root:

~~~bash
python -m pytest -q tests/test_structural_memory_vm_benchmark.py
python scripts/benchmark_structural_memory_vm.py \
  --page-size 4096 \
  --virtual-pages 4 \
  --working-set-pages 2 \
  --hot-repetitions 5 \
  --pretty \
  --output structural-memory-vm-comparison.json
~~~

The CI scheduler/state workflow runs the smoke tests and the default 4 KiB-page profile, then uploads the JSON report as `structural-memory-vm-comparison`.

## Interpretation and limits

A reserved page is not a resident page, but neither is it free storage. A Structural Memory reference carries a revision-pinned generator identity and certificate; resolving it requires local authority, generator evaluation, receipt validation, content hashing, and VM materialization. Once faulted, its bytes are resident just like any other mapped page. Copy-on-write or reclaim operations may also convert a generated page into locally backed private content.

### First 4 KiB measurement (CI)

The first paired CI run used four virtual pages and touched two pages in each case. Both VMs represented the same 16 KiB address space and returned identical page bytes.

| Measurement | Materialized | Structural Memory |
|---|---:|---:|
| Resident pages after cold working-set access | 4 | 2 |
| Resident guest bytes | 16 KiB | 8 KiB |
| Reserved pages after cold working-set access | 0 | 2 |
| Reserved guest bytes | 0 | 8 KiB |
| Mean cold page access | 5.3 µs | 29.7 ms |
| Mean hot access | 3.5 µs | 2.7 µs |
| Full checkpoint size | 65,763 B | 86,539 B |
| Checkpoint restore | 1.03 ms | 47.0 ms |
| Durable range-read journal events | 0 | 2 |
| Per-coordinate receipt IDs committed by the range events | 0 | 8,192 |

The resident-page reduction is 50%, but the untouched pages are not free: the Structural Memory case carries four admitted descriptions/certificates, page references, and range evidence. At this four-page size the complete checkpoint is about 20.8 KiB larger than the materialized case. The optimization's major gain is avoiding the previous 8,192 individual journal/cache entries: before range commitments the same profile produced a 41.3 MB checkpoint and took about 5.03 s to restore. Range commitments reduced those to 86.5 KiB and 0.58 s. A second optimization constructs the deterministic point-receipt IDs without allocating a complete point-receipt object for every byte; it preserves exact ID equivalence, reduces cold page access from 293.9 ms to 29.7 ms, and reduces restore from 581 ms to 47 ms.

Cold generation remains expensive—roughly 29.7 ms per page versus 5.3 µs for an already-materialized page. This profile therefore demonstrates a compact, replay-verifiable representation and an exact 50% guest resident-page reduction, not a general-purpose swap replacement or an overall faster memory tier. A realistic system would need workload-aware choice of materialization versus regeneration, larger amortization windows, and further optimization while retaining the same receipt and hash checks.

This is a single-process, single-VM comparison using the admitted integer-orbit family. It is not an operating-system swap benchmark, an RSS reservation measurement, an adversarial multi-tenant isolation proof, or evidence of physical-host VM capacity. Host RSS is not used to derive savings because this paired experiment focuses on exact guest mapping state and the provenance/state cost of reconstructing pages. Larger working-set and fleet-scale tests remain future work.
