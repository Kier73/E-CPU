# SAB-008 — Ground-native realization, substrate-neutral observer contract

**Status:** research implementation. The semantic Ground and requested observation are invariant across realizers, not a particular Python runtime, process, port, or network topology.

## Question

Can one mathematical intention be interpreted and verified through a constrained active port, an independent code-and-data interpreter, and a mutually authenticated relay plus receiver-native Hypervisor, without elevating any of those into the definition of an E-CPU host?

An intention is I=(G,id,t,O), where G is the bounded affine Ground x_(n+1)=(a*x_n+c) mod m and O requests x(t). Its fingerprint binds the Ground, request identity, coordinate and observer projection; physical placement is separate.

The observation equality O_G,I(r1)=O_G,I(r2)=O_G,I(r3) is admitted **only after checking** exact semantic identity, current local permission, receiver or locally bound capability, independent result oracle, and distinct realization evidence. Matching values without these bindings are insufficient.

## Experimental realizers

| Realizer | Primitive | Verification boundary |
|---|---|---|
| Software-modeled two-port active gate | Bounded compose/apply frames; O(log t) arithmetic transitions | A logical port model, not a measured physical chip |
| Independently launched interpreter | Fixed SAB-003 affine_mod opcode and empirical role qualification | Distinct OS process; no arbitrary untrusted source execution |
| Authenticated direct-peer composition | SAB-005 mTLS relay preserving exact bytes, followed by a separate remote receiver-native Hypervisor computation | Two pinned TLS identities and process lifetimes, not native ComputationalFabricForwarding |

The federated case is caller-orchestrated direct-peer composition; native multi-hop Fabric forwarding and recovery lineage remain separate integration work. A passive optical link, public DNS endpoint, or observed latency is not automatically an execution host or storage authority.

## Authority and evidence

The caller's exact (locus,method) permission is distinct from receiver-local Hypervisor authority. Fresh active capability qualification is used by interpreter and federated implementations. The resulting observation receipts bind the Ground and intention, policy fingerprint, coordinate, observer, method, locus, trace digest, and evidence digest. They report a checked finite observation, **not** an authenticated physical attestation, a universal proof, or exactly-once arbitrary side effects. SHA-256 gives content integrity, not remote identity.

The bounded software oracle uses two affine binary-navigation evaluators to check the requested coordinate. It does not enumerate all preceding states and does not claim that all possible Grounds are computable.

## Information-theoretic superposition analogy

A Ground describes a symbolic state-space, and partial evidence may leave several candidate states compatible with observations. This is informational uncertainty, not a claim of physical quantum superposition. Active observations can change the subject; passive reads need not. Physical energy and informational mechanisms still realize every observed transition.

## Tests

The dedicated SAB-008 CI checks Python 3.11 and 3.13: semantic identity across realizers, large-coordinate logarithmic port trace, fresh-interpreter behavioral qualification, refusal on malformed frames, incorrect modulus, Boolean integers, altered Ground/request/evidence, duplicate results without independent realizations, expired permissions, bad TLS server SAN, and revoked caller authority. On full E-CPU, the mTLS integration runs without skip and demands Hypervisor-authorized computation. Earlier SAB-005, SAB-004 and SAB-003 tests run as separate regressions.

**Local sandbox:** 16 tests passed, 3 native-TLS cases skipped because the full E-CPU runtime was unavailable. Independent native CI is a separate unverified gate.

## Next gate

Replace simulated ports with measured physical primitives; embed the new contract in E-CPU's native Computational Fabric forwarding and quorum lineage; test two real hosts with independently powered resources, and promote only verified observations and locally admitted transformations. This work is in active development.
## Open realizer vocabulary

The semantic contract deliberately **does not enumerate valid substrate types**. A GroundRealizer exposes a method identity, an operational locus and a typed observe operation. Local policy may permit any bounded method name, including one not anticipated by this prototype. An unknown label alone produces no computation: only a locally bound realizer capable of satisfying the Ground may operate. The generic realize_under_contract entrypoint checks policy before invoking a realizer and independently revalidates the receipt afterward. Port, interpreter and federated implementations are examples, never the complete set of possible native hosts.
