# VGI as an E-CPU Virtual Layer computational domain

## Purpose

This integration hosts the independently versioned Virtual Ground Interpreter (VGI) as a node-local, pure Virtual Layer operator. E-CPU owns workload admission, hosted-system identity, receiver-local authority, execution journaling, and semantic replay. VGI owns its task language, instruction semantics, signal values, computational Ground, and machine checkpoint format.

The first operator is `vgi.signal8.execute@1`. It is a hosted reference computation, not a replacement for the E-CPU instruction algebra and not a physical signal processor.

## Two distinct Grounds

The integration deliberately carries two independently verified identities.

The **E-CPU system Ground** is the admitted host context:

```text
VirtualGroundRef(origin_digest, state_digest, coordinate, frontier_digest)
```

The **VGI computational Ground** defines the representation and laws under which the task executes. For the initial operator it is the VGI Signal8 Ground, whose fingerprint identifies the Z/8Z domain, four observer coordinates, instruction set, assumptions, and ambiguity policy.

A successful receipt contains both. The outer Virtual Layer effect also contains the E-CPU system Ground reference. Neither identity may stand in for the other.

## Operator contract

- ID/version: `vgi.signal8.execute@1`
- Substrate: `cpu`
- Input/output kind: JSON object / JSON object
- Required local right: `compute`
- Execution mode: deterministic and pure
- Input schema: `vgi.signal8.request.v1`
- Request fields: `schema`, `ground_fingerprint`, `task`, `initial_memory`, and `max_steps`

The typed task is a VGI `TaskSpec` expression tree. Initial memory is a map of declared task input addresses to the exact serialized signal-value fields: real, imaginary, observer, and conservative phase-error bound. The address set must equal the task's declared inputs. Semantic integers are not part of the execution payload.

The receiver resolves the operator and implementation locally. The workload contains task data and an operator reference, never executable Python code, a handler, or authority.

## Execution path

```text
VirtualLayerWorkload
  -> admitted E-CPU system identity and Ground check
  -> node-local operator contract/version resolution
  -> receiver-local hypervisor authorization
  -> VGI computational Ground fingerprint check
  -> TaskSpec validation and lowering to VGI Program IR
  -> bounded SignalStateMachine execution
  -> signal-valued output and trace capture
  -> VGI machine checkpoint and execution digest
  -> E-CPU effect receipt and semantic ledger
```

The adapter calls VGI's compiler and machine directly. It does not call `observe_symbol`; signal values remain phasor/observer/error-bound objects through the complete hosted execution. A caller may perform explicit terminal observation outside the operator if its application contract allows that.

The returned VGI receipt includes:

- E-CPU system Ground reference and VGI computational Ground identity/fingerprint;
- VGI version, task/program fingerprint, and instruction count;
- halted status, final program counter, signal-valued outputs, and instruction trace;
- a VGI machine snapshot with its own state digest;
- a canonical execution digest binding the receipt.

The outer Virtual Layer result adds the operator-contract digest, node, substrate, workload identity, system Ground, resource accounting, and canonical result digest.

## Persistence and replay

The VGI checkpoint is included in the pure operator result. The E-CPU hypervisor effect ledger records the committed result under the semantic operation identity. On an exact retry, E-CPU returns the recorded effect without re-entering the node-local VGI handler. The checkpoint can be restored by VGI only with the matching Program and computational Ground fingerprints.

This first slice proves local hosted execution and exact semantic replay through the E-CPU effect ledger. It does not yet claim hard-process restart of a VGI host, cross-process restoration of a VGI machine from an independent checkpoint bundle, or durable storage of VGI's checkpoint outside the existing effect/checkpoint boundaries. Those are explicit next gates.

## Installation

The adapter is part of E-CPU. VGI remains a separate repository and is installed through the pinned optional extra:

```sh
python -m pip install ".[vgi]"
```

The optional extra pins the VGI source commit used by this integration. Standard E-CPU installations do not need VGI.

## Verification and limits

The E-CPU tests exercise compile, execute, branch evidence, signal-valued results, dual-Ground identity, checkpoint restoration, and semantic retry suppression. CI installs the pinned VGI extra and runs VGI's own finite Ground verification before the E-CPU suite.

The current interpreter is bounded to its declared finite Signal8 Ground and typed task-expression language. It is not a natural-language planner, an unrestricted algorithm synthesizer, a universal computation claim, or a physical analog computer. The Python instruction dispatcher remains software. The E-GPU does not execute VGI signal values yet; a signal-native lane backend would require a separate typed backend contract and independent semantic oracle.

## Next gates

1. Exercise VGI checkpoint restoration after actual E-CPU requester/receiver process termination.
2. Define canonical floating-point/phasor reproducibility requirements across platforms before claiming cross-platform byte-identical result receipts.
3. Introduce VGI's typed backend protocol and instruction read/write contracts before exposing alternative Ground implementations.
4. Prototype a signal-native E-GPU method only after the hosted scalar VGI path is stable.
