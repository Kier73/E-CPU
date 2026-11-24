# FAB-008 — Observation-formed loopback truth Grounds

The local address is an executable coordinate: an empty IPv4 UDP datagram addressed to 127.18.0.x selects an ordinal result socket using Linux classic BPF. The UDP port chooses the current Ground incarnation. The application decodes only the actual selected socket, with destination/peer ancillary checks; no userspace table evaluation constructs the answer.

## Ground and realization

For a table of 2, 4, 8 or 16 values and output width w in {1,2}, define T = sum(v_i * 2^(wi)). The seven-instruction selector reads the final destination octet x, computes ((T >> (wx)) & (2^w-1)), and returns that result socket index. The separate 16-instruction kernel guard refuses wrong address prefix/opcode/coordinate and nonempty datagrams. Fixed group membership is required. A result of zero is a delivered empty packet on socket zero, not silence.

The known primitive NAND Ground (1,1,1,0) is installed first. The existing fabric supplies 72 gate observations (nine per input of a three-input full adder); the resulting table (0,1,1,2,1,2,2,3) is checked against independent bit-count arithmetic and compiled into T=0xe994. The new operator is realized on two different ephemeral ports, with sixteen exact re-observations and eight kernel refusal controls. Then eight such observations compose one byte addition with host-side bit wiring. No host-side arithmetic oracle forms the kernel responses.

## Local measurement

Linux controlled loopback run, 2026-11-24: 65,536/65,536 byte additions, 524,288 composition packets, 4.749027984 s measured for the composition sweep (excluding setup and formation). Zero application payload bytes. Ordered BBH record SHA-256: 5613dffac5ad5b3f9e4f9110bc158d78b73068bfaeeba267a8bcba2b97849c22. Another 600 observations from 80 generated tables passed, and an intentionally contradictory NAND table refused formation. Quick run also passed as unprivileged nobody. The earlier FAB-006/007 standalone tests each verified 393,216 address-native arithmetic/logic results using datagram-length and socket-path encodings respectively. FAB-008 implements the new finite packed truth-table mechanism. The earlier probes are retained in [examples/fab_127](../examples/fab_127), runnable independently as shown below.

Compared with the nine-NAND full adder, the formed operator reduces communication events per byte addition from 72 to 8 (9x fewer; no timing speedup asserted from event counts). The formation cost is 72 native gate observations plus installation and verification. A matched local benchmark of 260 byte additions (256 pairs (a,(73a+91)%256) plus four edge cases) measured 18,720 original NAND packets in 0.156503689 s versus 2,080 formed packets in 0.018263547 s: 8.57x wall-time improvement, excluding formation/setup. The corrected canonical-identity exhaustive run repeated the same output digest in 4.64906535 s; semantic Ground SHA-256 796056b96e74b76c994a0f5f5bc51067ff01391757b0de2ec397918cb6f48e8f. The demonstration is bounded table discovery, not a general circuit synthesizer or a complexity-class result.

## Native E-CPU integration

KernelTable.realizer_binding returns the existing receiver-local RealizerBinding with an oracle against the admitted table. The native AdaptiveBootstrap tests declare an observed local operation, verify each of its coordinates before offering it, and exercise policy refusal, successful execution, lease expiry, native report verification and rebind identity. Ground/task identity excludes ephemeral port; inventory/plan evidence includes the observed placement. This is same-kernel rebinding, not physical host independence, remote attestation, or automatic failover. No new Hypervisor or authority is introduced.

Run:
    python examples/fab_127/loopback_kernel_fabric.py --quick
    python examples/fab_127/loopback_route_fabric.py --quick
    python -m mailcpu.loopback_truth_fabric --quick
    python -m mailcpu.loopback_truth_fabric
    python -m pytest -q tests/test_loopback_truth_fabric.py

Only use an isolated, authorized Linux loopback environment; the socket group is serial and not designed for concurrent/untrusted local requests. SO_BINDTODEVICE binds to lo; no system routing or firewall changes. The actual kernel must support classic BPF and reuseport selection. Failed installation/observation raises, not a userspace fallback. Cross-platform pure compiler checks are separate from Linux native execution.

## To Do

Generalize intention-driven circuit lowering; synthesize a sufficient symbolic Ground instead of enumerating all inputs when justified; cache admitted observations through native Structural Memory; use receiver-authorized topology formation and verify path membership/epoch under recovery; benchmark autonomous kernel chaining and wider distributed realizations.
