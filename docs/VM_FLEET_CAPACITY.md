# Independent VM Fleet Capacity Benchmark

## Purpose

This benchmark answers a narrower, reproducible question before making a general VM-density claim:

> How many independent MailCPU virtual machines can execute a known workload, preserve their own OS/kernel/scheduler/memory state, and return a verified result under a declared guest-memory profile?

A benchmark VM is one independently constructed HeadlessOS and its composed MailCPUVirtualMachine. Each instance has its own scheduler, kernel, event journal, process table, and virtual address spaces. This is intentionally different from spawning many processes inside one HeadlessOS; those processes share one VM.

## Workload

Each VM receives one contiguous integer interval. Its MailCPU program computes the sum of that interval using ordinary SET, ADD, and HALT instructions. The orchestrator dispatches one scheduler instruction to each runnable VM per round, then reduces the verified partial sums.

The global expected result for N VMs and W units per VM is:

\[
\sum_{k=0}^{NW-1} k = \frac{NW(NW-1)}{2}.
\]

The benchmark refuses to count a VM as successful unless its task halted, its instruction count is exact, its partial result matches its assigned interval, its journal verifies, and the fleet has distinct scheduler and kernel instances.

## Resource profile

Every VM gets:
- one MailCPU guest process;
- a fixed 4 KiB page geometry;
- a fully written guest working set of at least two pages;
- an equal per-VM resident-page ceiling;
- its own full HeadlessOS snapshot, measured after execution.

An optional max-total-resident-pages value acts as an explicit fleet admission budget. It is enforced by the benchmark orchestrator before creating VMs. It is not a new global quota inside MailCPU. The per-VM ceiling is also passed into the existing VM resident-page admission mechanism.

The output records guest resident bytes, process RSS where available, full OS snapshot bytes, construction time, execution time, snapshot time, instruction throughput, and per-VM scheduler-quantum latency.

## Run

From the repository root:

~~~bash
python scripts/benchmark_vm_fleet.py \
  --vm-counts 1,2,4,8,16 \
  --work-units 256 \
  --working-set-pages 2 \
  --max-total-resident-pages 64 \
  --pretty \
  --output vm-fleet-capacity.json
~~~

The guest page-budget ceiling in this example is 32 VMs at two resident pages each. To establish the maximum under that declared guest-page budget, include 32 in --vm-counts. A result that only tests up to 8 VMs is an observed lower bound, not an exact maximum.

The benchmark report includes:
- requested and admitted VM counts at every scale point;
- explicit refusal counts when the fleet page budget is exhausted;
- independent scheduler/kernel counts;
- total and per-worker retired instructions;
- worker and aggregate correctness evidence;
- guest resident pages and bytes;
- full OS snapshot size;
- process RSS and available-memory observations on Linux;
- timing and throughput measurements.

## Interpretation and limits

This is a same-process VM fleet experiment. It validates independent VM objects and an actual algorithm partition/reduction path under a controlled local scheduler. It does not yet measure remote host placement, network transport, authenticated fabric forwarding, fault-domain independence, foreign CPU instruction execution, a Linux guest, or arbitrary programs.

The guest-page budget gives an exact capacity only for that declared logical-page constraint and chosen working-set profile. The physical host maximum remains workload-, runtime-, and machine-dependent. RSS is an observed process measurement, not a reservation; available-memory readings are snapshots, not a guarantee. To claim a physical host maximum, run a scale-up experiment on a named machine, record its memory/CPU/runtime configuration, enforce a host-level stop budget, repeat cold and warm trials, and include failure/recovery tests.

Structural Memory remains a separate memory tier. A future paired experiment should compare materialized resident pages with cold symbolic reservations and demand-faulted working sets. It must report reserved bytes, resident bytes, backing descriptor size, cold fault cost, hot access cost, and recovery cost separately. A symbolic reservation must not be counted as resident-memory savings after its page has been faulted into RAM.

## Verification

The smoke tests verify:
1. three independent VM/OS instances execute disjoint work and reduce to the correct global result;
2. a guest-page fleet budget refuses excess VM admission;
3. a sampled scale range is not mislabeled as an absolute physical host maximum; and
4. invalid resource profiles are refused.

The CI workflow runs the measurement separately from the full test-suite gate and uploads its JSON report even when another gate fails. This preserves useful capacity evidence while the broader verification baseline is being repaired.
