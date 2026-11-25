# MSF-001 — Multi-source computational fabric usage

## Intention

Run the real E-CPU computational-directory and native Virtual Layer/Hypervisor execution path on **four independently pinned public Git source fabrics**. Then carry compact result receipts over a real `OwnedNetworkFabric` *in-process network* with separate source namespaces and a shared receiver namespace, and execute a final native join. Only Git metadata, never the file/blob contents, enters the local Ground.

The sources are `Kier73/E-CPU`, `Kier73/Virtual-Ground-Interpreter`, `Kier73/In-Formation-Space`, and `Kier73/VL-I`. Exact source commit, tree, anchor blob SHA, anchor size and a bounded set of same-namespace file entries form the source-specific Ground. This uses the pre-existing GitHub commit/tree object service as an external **observation path**, not as an E-CPU mTLS peer or an executing remote CPU.

## Executable composition

```text
4 independent source repositories @ fixed commits
                 |
         GitHub Git commit/tree service (bounded HTTPS GETs)
                 |
     receiver verifies commit -> tree -> anchor + sampled entries
                 |
   4 source-specific content-addressed mathematical Grounds
                 |
  ComputationalFabricAuthority + ComputationalFabricDirectory
  advertises ONLY 4 receiver-local source processors + 1 join processor
                 |
    ComputationalFabricResolver route proposals (local peer)
                 |
    ComputationalAddressResolver + native Hypervisor admission
                 |
      4 source reductions (sum of selected file lengths)
                 |
  OwnedNetworkFabric: 4 distinct namespaces, multi-edge routed frames
                 |
     verify each received Ground and source result locally
                 |
        native Hypervisor join of received observations
                 |
          exact independent sum oracle + bounded report
```

For external source `i`, the selected finite relation is

\[
G_i=(repo_i,commit_i,tree_i,anchor_i,entries_i),\quad
h_i=SHA256(J(G_i)),\quad
f_i(G_i)=\sum_{e\in entries_i} size(e).
\]

The final native reduction realizes `sum_i f_i(G_i)` and compares with a separate direct oracle. `J` is canonical sorted JSON. A directory route witness selects a possible local host but does not authorize it. Each native execution goes through `ComputationalAddressResolver` and `ComputationalExecutionAdmissionCoordinator` with the receiver's own live PID, operator contract, System Ground and capability.

The source paths remain external; no raw Python code is fetched or evaluated. The branch/ref cannot change the pinned Git commit. A report records each external Source Ground fingerprint, the active E-CPU directory digest, selected local host, non-authoritative route digest, native execution verdict, routed frame count, total payload bytes and final joined value.

## Reproduce

```sh
python -m pytest -q tests/test_multi_source_fabric_usage.py
python examples/multi_source_fabric_usage.py --live --output /tmp/msf001-report.json
```

`--live` opts into eight bounded GitHub HTTPS GETs for the four source commits and corresponding trees. There are **no downloads of repository files, source code, model weights or Git blobs**. The workflow `source-fabric-usage.yml` runs the focused tests and the live observation on a public GitHub Actions runner with `contents: read` and uploads the resulting report.

## Verified scope and next experiments

- The remote Git object service is used for independently pinned source structural observations. GitHub's content-addressed Git tree identity is checked against the caller-selected commit, and the exact anchor blob and size are independently checked in the returned tree.
- E-CPU's real computational-directory API and local Virtual Layer/Hypervisor authorize and execute five native operations in one receiver process; source-specific Ground fingerprints prevent accidental cross-source host selection.
- `OwnedNetworkFabric` supplies distinct local namespaces and genuine route/queue transitions in the E-CPU simulator. The route does **not** claim physical separation, a live mTLS WAN peer or Internet-path numerical processing.
- The exact live CI report is the evidence for successful public HTTPS observations. Local unit tests supply offline adversarial data only and cannot be counted as public-network verification.

**To Do:** elevate multiple receiver-owned gateways onto distinct actual TLS peers, exchange their snapshots using `ComputationalFabricPeerClient`/`Server`, and send the same source-pinned workload over actual authenticated forwarding paths. Measure per-provider RTT and byte counts, destination host reassignment, intermediate failure/recovery, lease expiry and replay under a fixed source Ground. Couple source Ground translation through `EvidencePathResolver` when sources expose incompatible representations. A source site still has no remote authority until such authority is separately installed and verified.

## Implementation

- [`examples/multi_source_fabric_usage.py`](../examples/multi_source_fabric_usage.py)
- [`tests/test_multi_source_fabric_usage.py`](../tests/test_multi_source_fabric_usage.py)
- [`mailcpu/computational_fabric.py`](../mailcpu/computational_fabric.py)
- [`mailcpu/owned_network.py`](../mailcpu/owned_network.py)
- [`mailcpu/computational_execution.py`](../mailcpu/computational_execution.py)
- [WIRE-001](CROSS_REPOSITORY_NONLINEAR_WIRE_001.md) and [Computational Fabric](COMPUTATIONAL_FABRIC.md)
