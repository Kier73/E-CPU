# HSS-002 — The external model remains where it is

**Thesis:** the data-bearing source is a *coordinate* of the Virtual Layer,
not a set of bytes to copy into its runtime. Source information can be
interpreted as an executable relation without relocating that source.

## Operational sequence

    intent                        external observation host
      │                                      │
      │                        [source model, repository, page]
      │                                      │
      ├── observes source STRUCTURE ◄── source metadata / browser projection
      │     pinned revision, paths, configuration, extent
      │
      ├── forms one Virtual Layer source Ground
      │     Ground = (source, revision, observed structure, evidence)
      │
      ├── compiles intended observation into a virtual processor
      │     P = (ground_head, intention, virtual position, interpretation law)
      │
      ├── evaluates the requested structural relation
      │     e.g. locate file, resolve extent, navigate logical layer position
      │
      └── retains a three-frame CONTROL stream and structural result
            never the tensor/shard/model payload

The original external model stays at its original location. No part of its
weight payload is transferred, cached, ingested into M1, or reconstructed
on E-CPU.

Implementation:
- [external_virtual_structure.py](../mailcpu/external_virtual_structure.py)
- [observe_hosted_surface.py](../scripts/observe_hosted_surface.py)
- [test_external_surface_streams.py](../tests/test_external_surface_streams.py)
- [CI](../.github/workflows/hosted-external-surfaces.yml)

This is not a model-specific DeepSeek/Qwen importer. The model's
\`model_type\` is retained as a description and never used to pick a
hardcoded neural interpreter. Any externally declared architecture enters
the same structural address field.

## Source identity and virtual execution

Given a public model page:

    https://huggingface.co/{owner}/{model}/tree/main

The receiver observes only the host's **metadata API**, specifically
a revision record and a bounded, paginated file tree. It does **not**
request /resolve, /blob, HTTP weight ranges or checkpoint artifacts.
Only the metadata description itself crosses the communication path.

A hosted source is an immutable record:

    S = {
      repository,
      40-hex revision,
      sorted path -> (declared byte extent, optional source LFS SHA256),
      declared architectural configuration,
      SHA256 of each upstream metadata observation
    }

    source_head = SHA256(canonical(S))

The complete source payload size may be enormous. Its sum is recorded
as a symbolic property but does not determine the amount of data
moved into the VL.

For a requested intention I, the built-in structural interpreter is:

    R = Resolve(S, I)
    P = (source_head, I, R, control_frames)
    position_head = SHA256(canonical(P))

Available laws:

    source.catalogue     -> number of remote files, total external size, types
    source.file          -> a source-pinned virtual file address
    source.extent        -> any valid coordinate [offset, offset+length)
    source.architecture  -> exactly observed configuration fields
    source.layer         -> bounded logical index from source-declared count

The coordinates are information: an arbitrary external source byte extent
can be named without transferring even one byte from it.

A position uses three hash-linked **control frames**:

    genesis = SHA256(canonical({source_head, control_domain}))
    F0 = {source identity, genesis}
    F1 = {intention, predecessor = H(F0)}
    F2 = {result digest, predecessor = H(F1)}

    position_head = SHA256(canonical(
      source_head, intention, result, frames, scope
    ))

These are semantic operations on the source description, not fragments
of the underlying file.

### Interpretation cost

The immutable file index is constructed only once per observed revision,
and cached in a receiver-owned map. Its Ground hash is also cached.
A known-file virtual coordinate lookup is therefore expected O(1)
on average for path lookup, with result formation cost dependent on the
*intention description*, not on source file byte length.

A catalogue scan depends on the number of *described entries*, not the
declared sizes of those entries. Network observation of source metadata
is separately accounted for, not hidden in the warm virtual-read cost.

## A read is a run, with an exact sufficiency condition

The relevant mathematical test is whether an observation of source
structure contains all information needed to determine the requested
behavior.

Let A(M) be the admitted structural observation of an external model M,
and F_I(M) the property requested by intention I. An interpreter can
reliably realize F_I from that observation alone precisely when:

    A(M1) = A(M2)  =>  F_I(M1) = F_I(M2)

for all source instances permitted by the interpretation contract.

For file size, address, layer count and structural properties, that
condition is satisfied by the observed metadata.

For trained logits, activations or model-specific reasoning behavior,
an address alone generally cannot determine the result. Many models
with identical tensor layouts have different coefficients. Such a
neural intention requires a *different evidence law*, for example:

- An observer host at the original data locus evaluates the required
  operation and emits a receiver-verified semantic receipt; or
- A previously admitted exact sufficient-statistic / trained Ground
  is interpreted, with source binding and sufficient behavioral proof.

**Neither option requires relocating the source model into E-CPU.**
Both require actual grounded information appropriate to the intention.
A structural metadata observation is never falsely promoted into
a verified arbitrary model inference.

This preserves the distinction between the *immense data-bearing
source space* and the *small information-bearing computational Ground*
that the VL can realize by navigation.

## Headless browsing as an observer host

A browser may be useful when a public website exposes structure only
through its rendered UI. The browser runs at an observation host and
projects *addresses, descriptions or verified visible attributes* into
the Virtual Layer. The VL does not ingest arbitrary scripts, page assets,
model checkpoints or page source as a new execution substrate.

The first adapter \`project_browser_addresses\` accepts a bounded list
of projected link addresses and constructs a source-relative Ground.
It makes no browser launch claim: live browser capture requires a
separately admitted observer capability. When a source provides a
structured metadata interface, it is simpler and more efficient to
observe that interface directly.

## Verification and stress experiment

The test fixture describes 48 very large model shards plus metadata,
a configuration, tokenizer and inference-source file. It exercises:

1. A pinned source identity from only three small metadata reads
   (revision + two paginated file-tree observations).
2. An arbitrary 10^27-byte file extent, addressed at byte 10^25,
   with zero model payload transfers.
3. One identical interpreter for DeepSeek, Qwen, Llama, Mamba,
   diffusion, audio and novel model types.
4. Portable structural Ground, frame and result reconstruction in
   an independently started Python worker process.
5. Refusal of forged source revisions, contradictory pagination,
   absent files, invalid extents, fabricated neural operators
   and modified control-frame chains.
6. Cold metadata observation time versus repeated warm VL
   interpretation time.
7. A live external DeepSeek metadata-observation run with
   a retained JSON source identity and measured control cost.

Reproduce the live experiment:

    python scripts/observe_hosted_surface.py \
      --url https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/tree/main \
      --rounds 2000 --out artifacts/deepseek-virtual-structure.json

The report explicitly records:
- \`declared_external_bytes\`: source-host's model data domain,
- \`metadata_observation_bytes\`: small received descriptions,
- \`model_payload_bytes_transferred = 0\`,
- \`model_payload_partial_ranges_acquired = 0\`,
- \`structural_interpretation_mean_ns\`: speed of interpretation
  after the Ground is established.

## To Do — source-local neural interpretation

The intended next construction is **a typed operator interface living at
the source locus**, registered as an E-CPU observer-host:

    intention + source coordinate + causal input
      -> source-local interpretation / qualified model computation
      -> compact structural or numerical Ground receipt
      -> receiver verifies and navigates the next state

This is where exact remote numerical model behavior, externally hosted
static weights and continuous VL-I state-space navigation converge.
The computational identity remains attached to the receiver's
source/intention/evidence relation, rather than the machine or file
that happens to carry a model representation.

The research priority is the interpretation law and its verification,
not data delivery throughput or the size of the model's weight file.
