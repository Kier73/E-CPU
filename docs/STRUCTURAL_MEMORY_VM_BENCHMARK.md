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

The Structural Memory case admits one modulo-256 integer-orbit byte-stream per page, pins each page through a `StructuralMemoryFileRef`, and reserves the same virtual interval against those content hashes. It then reads the same working set. First access passes through `StructuralMemoryPageBacking`, which resolves the pinned provider, validates the byte-range receipt and SHA-256 page identity, and only then materializes the page into VM memory.

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
| Structural registry bytes | Serialized admitted generators, certificates, and coordinate-level read receipts |
| Checkpoint bytes | Full `HeadlessOS.snapshot()` serialization after the working set has been touched |
| Restore time | Normal `HeadlessOS.from_snapshot()` reconstruction, including trusted registry rebinding |
| Post-restore fault | First read of a previously untouched page after restore |

The restore path deliberately reads one page that was not in the original working set. That confirms that an inert checkpoint reference can be rebound to the trusted local Structural Memory registry and still reconstruct the exact page bytes. The report includes the new resident-page delta and verifies the resulting read receipt.

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

The current byte-stream provider evaluates and journals coordinates individually. That evidence is intentionally included in the Structural Memory registry and checkpoint-size measurements. A large page or working set may therefore have substantial cold-fault and provenance costs even when its generator description is compact. The experiment does not assume that a short formula implies low read latency, low journal volume, or low checkpoint size.

This is a single-process, single-VM comparison using the admitted integer-orbit family. It is not an operating-system swap benchmark, an RSS reservation measurement, an adversarial multi-tenant isolation proof, or evidence of physical-host VM capacity. Host RSS is not used to derive savings because this first paired experiment focuses on exact guest mapping state and the provenance/state cost of reconstructing pages. Follow-up work can add host RSS and larger working-set scale sweeps once these state and evidence relationships are stable.
