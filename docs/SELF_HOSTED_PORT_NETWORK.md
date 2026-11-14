# SHN-001 — An E-CPU network inside a one-interpreter, one/two-port chip

**Status:** bounded executable architecture experiment. This is **not** a measured silicon implementation, an embedded firmware image, a physical network-on-chip, or distributed physical execution.

## Question

Can E-CPU instantiate internally communicating observer-hosts even if the entire realization consists of *one* interpreter and at most **one or two physical external I/O ports**, without relying on a remote network or duplicating the physical execution engine?

The existing [Communication Host Model](COMMUNICATION_HOST_MODEL.md) defines a host by its observation/interaction relation, not by a machine boundary. An active port or queue can qualify as an observer-host; a passive wire does not automatically become an executor. The existing `OwnedNetworkFabric` supplies internal namespaces, virtual interfaces, point-to-point links, bounded queues, journals, and restorable topology. The existing `law_certifier.lcg_navigate` supplies a non-iterative state-coordinate lookup for a declared recurrence.

## Bounded realization

```text
  physical exterior: [ one or two ports, deliberately unused ]
  =================================================================
                           ONE CHIP / ONE INTERPRETER
  +------------------------- E-CPU ------------------------------+
  |                                                              |
  | dispatcher.tx  -- internal queue --> navigator.in            |
  |                                          [virtual host A]     |
  |                        navigator.out -- internal queue --+   |
  |                                                         v   |
  |                                                   projector.in
  |                                                   [virtual host B]
  |                                                         |    |
  | dispatcher.rx <-- internal queue ---- projector.out ----+   |
  |                                                              |
  | physical external I/O bytes = 0; all 3 host transitions      |
  | are run sequentially by the SAME interpreter                 |
  +--------------------------------------------------------------+
```

The host contracts are:

- **Dispatcher:** accepts one bounded query `(job_id, coordinate)` and observes the final reply.
- **Navigator:** reads a message, computes the LCG state at the specified coordinate using `mailcpu.law_certifier.lcg_navigate(5,1,65536,7,t)`, and sends the result to the next virtual interface. This is an *active* observer-host.
- **Projector:** reads that intermediate state, applies `y=(3x+11) mod 65536`, and sends a result to the dispatcher. This is also an active observer-host.

The virtual links do not compute. **The interpreter runs all virtual-host transitions**, using existing E-CPU FIFO semantics. Each accepted hop consumes an interpreter quantum and bytes of bounded internal storage. No physical port is attached to the internal OwnedNetworkFabric.

## The semantic observation and the physical realization

The request addresses the observer's result at coordinate `t`:

\[
 x_0=7, \quad x_{t+1}=5x_t+1\pmod {65536},\quad
 y_t = 3x_t+11\pmod{65536}.
\]

The `navigator` does **not** materialize `x_1, x_2, ..., x_{t-1}`. It invokes an existing E-CPU logarithmic closed-form navigator. The second observer-host applies a separate deterministic projection. The data traverses three software queues and yields two content-addressed, **unsigned** observation receipts. At large `t`, the number of virtual-host dispatches remains three. The arithmetic used to calculate the state still consumes real processor time and energy.

In particular, this experiment tests **logical host multiplicity** and **state-coordinate navigation**. It does not prove multiplication of physical processors, in-wire arithmetic, hardware port programmability, acceleration, or throughput benefits.

## Exact falsifiable predictions

1. The same coordinate and work description produce the same result with either one or two *declared external* physical ports. All external I/O counters remain zero.
2. A virtual `navigator` and `projector` exchange actual canonical byte frames over the existing `OwnedNetworkFabric`; they are not merely labels in a diagram.
3. For small coordinates, the result must agree exactly with a separately written **iterative** recurrence oracle.
4. A very large coordinate such as `10**15 + 137` must be reachable without enumerating its preceding states. This tests an existing mathematical law, not arbitrary state spaces.
5. Checkpoints taken after submission and between each host dispatch reconstruct the pending byte frame, topology, receipt sequence, and final result; changed packet bytes, receipts, physical-port claims, and resource accounts fail closed.
6. Queue saturation and MTU violation preserve the prior queue state and reject the send. Logical fanout does not grant infinite transport resources.
7. The result must explicitly report **one** underlying interpreter, **three** logical observer-hosts, **six** internal interfaces, **three** internal links, and **zero** transmitted bytes on the one/two physical external ports.

These predicates do **not** imply isolation: all virtual hosts share one crash domain, one memory resource, and one physical execution engine. The content digests bind observations to this program's declared operations; they do not authenticate independent authorities.

## Reproduce

From E-CPU repository root:

```bash
python -m pip install -e '.[dev]'
python -m pytest tests/test_self_hosted_port_network.py -v
python - <<'PY'
import json
from mailcpu.self_hosted_port_network import SelfHostedPortNetwork
for ports in (1, 2):
    chip = SelfHostedPortNetwork(ports)
    chip.submit('self-hosted-lookup', 10**15 + 137)
    print(json.dumps(chip.run(), sort_keys=True))
PY
```

The dedicated `self-hosted-port-network.yml` GitHub Actions workflow runs these checks with Python 3.11 and 3.13 alongside the existing OwnedNetworkFabric and navigation regressions.

## What would actually falsify the stronger hypothesis?

- If the only available *physical* components were passive pins and a non-operational interpreter, then no active transition occurs. Nothing in a description creates energy, memory cells, or logic that physically acts on the description.
- If bounded queue storage, scheduling, or interpreter time were exhausted, the virtual network would stall or refuse. More logical observer-hosts **do not** imply more simultaneous execution capacity.
- If the requested state lacks a supported navigation law, this experiment's `lcg_navigate` shortcut does not generalize. Other state-spaces may require explicit iteration, search, or externally furnished evidence.
- A port-host's observation contract qualifies it as a logical E-CPU host. It does not imply that the pin or passive signal line itself runs code.

## Subsequent exploration

**SHN-002** could host *nested* `HeadlessOS` contexts behind active virtual-port interfaces, plus a one- or two-physical-link time-division multiplexing model that accounts for the bytes and occupancy of each physical link. Test whether the composed observations survive loss of one virtual host, a queue-livelock case, or an interpreter restart. Only then attempt a real one-/two-port embedded implementation and measure on-chip memory, energy, and timing. The existing native TCR-003 tensor operator could become an admitted port-host handler in a later experiment, but it is not needed to establish the basic self-hosting proposition.
