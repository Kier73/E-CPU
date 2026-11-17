# DATA-GROUND-001 — Any observed data as a mathematical Ground

**State:** Implemented as a finite, executable interpretation adapter in
`mailcpu/data_ground.py`, with tests, a demonstration, and dedicated CI.
A passing full-repository or multi-platform result must be confirmed by
GitHub Actions; the code being committed is not by itself a test result.

## The question

Can the system mathematically address arbitrary information **before**
knowing the format, and then recognize richer structure through explicit,
checkable interpretations rather than guessing one universal meaning?

The foundation is unconditional for every **finite admitted byte window**:

\[
b=(b_0,b_1,\ldots,b_{n-1})\in(\mathbb Z/256\mathbb Z)^n.
\]

This is an exact mathematical representation, **not an assertion of
meaning**. Every such window has coordinate values, a length and a
content digest; even empty, malformed text, encrypted or unknown data
are representable. If a receiver wants coordinate `i`, it can directly
read `b_i` in constant time for a resident byte window. This is not an
O(1) claim for remote transfer, total hashing, data acquisition,
decoding, or a full file residing outside the observer.

The *second* operation is a selected, versioned partial interpretation
\(D_L:\mathcal B\rightharpoonup M_L\) using a particular lens
\(L\). The interpreter may admit a typed mathematical value or
**refuse** if the bytes do not satisfy the lens. The result never
licenses an unsupported inference about the source's intention.

### The important ambiguity

The identical bytes `b"123"` are valid under at least three
different interpretations:

| Selected lens | Exact mathematical value | What it does **not** imply |
|---|---|---|
| UTF-8 | string `"123"` | the source meant a number |
| JSON | integer `123\in\mathbb Z` | the source intended numerical computation |
| big-endian unsigned integer | `3224115\in\mathbb Z` | any application assigned that binary layout |

All three can be **structurally correct**, with different versioned
`TranslationContract` identities, while their semantic intent remains
unresolved. The user's request, producer schema, receiver policy and
authenticated provenance can provide the evidence required to select
the appropriate interpretation. Byte identity alone cannot.

### Explore candidates without silently selecting one

`DataGround.candidate_views(offset=..., length=...)` tests the finite
registered lens family against the **same exact observed bytes**. Its
result retains the source digest, coordinate range, candidate
mathematical domain, admitted translation-contract identity and
refusals. The field `interpretation_selected` is always `null`:
structural decodability is not evidence of source intent or
hypervisor authority. A model or observer can use this survey to
propose a relevant view, but a receiver must still select the lens
under the actual intention, Ground and evidence requirements.

This is a bounded survey of registered adapters, not an exhaustive
enumeration of all mathematical structures a byte string could express.
The opaque vector remains available even when every richer registered
decoder refuses the data.

## Existing E-CPU capabilities, now composed

This implementation deliberately **does not** create a competing
transport, content store, canonical codec, Ground authority, or semantic
translation authority.

- `mailcpu.computational_objects.ComputationalObjectStore` and
  `ComputationalObjectManifest` remain owners of content-addressed,
  page-verified immutable data. `DataGround.from_object_range`
  reads the exact requested range through `read_range`. A partial
  observation is labelled `page-verified-range`; the whole object's
  content digest is only considered verified on an actual full read.
  An inline window receives no fabricated page-store provenance.
- `mailcpu.semantic_translation.RepresentationRef`,
  `ObservationContract`, `TranslationContract`,
  `ResourceBound` and `compare_projected_observations` supply the
  **existing** typed contract and exact-case equivalence check.
  `DataGround.verify_interpretation` reconstructs the claim from the
  retained original bytes, not from a self-authored content digest.
- `mailcpu._codec` remains responsible for lossless canonical
  runtime-state value encoding. `DATA-GROUND-001` supplies specific
  mathematical *decoders* of externally encountered raw bytes, a
  different operation from marshalling a known MailCPU value.
- `mailcpu.vantage_transform` and the VGI Ground-identification
  research already study choosing useful views of a state-space.
  This adapter supplies a concrete verified observation object for
  later candidate discovery and active probe selection.

## Admitted mathematical lenses

| Lens | Domain / evidence | Round-trip criterion |
|---|---|---|
| `opaque` | finite vector over `Z/256Z`, exact ordered bytes | identical bytes |
| `uint-be` | nonnegative integer, explicit 1–16-byte big-endian width | exact width and bytes |
| `uint-le` | nonnegative integer, explicit 1–16-byte little-endian width | exact width and bytes |
| `utf8` | Unicode scalar sequence, strict UTF-8 decode | exact UTF-8 bytes |
| `json` | exact symbolic tree with disjoint null, Boolean, integer, rational, Unicode, list and string-map domains | mathematical AST unchanged under normalized re-encoding |
| `ipv4-datagram` | real IPv4 header fields, length and checksum, payload digest and reversible raw image | exact datagram bytes |

No lens is applied without a receiver-supplied `DataLens(kind,
offset, length)`. Invalid UTF-8, malformed IPv4, mismatching checksum,
invalid length, duplicate JSON keys, NaN/Infinity, unsupported formats,
excessive JSON nesting, excessive numeric expansion and unobserved
byte ranges are refused. Decoder results remain **typed structural
claims**, not proof of authenticated origin, network path, model intent,
or an undiscovered mathematical law.

### Exact data identity versus mathematical-value identity

A JSON source such as:

```json
{ "amount": 1.2500, "offset": -0.002 }
```

is interpreted symbolically as the ordered mapping
\(\"amount\"\mapsto5/4\), \
\(\"offset\"\mapsto-1/500\). The original whitespace and
number spelling are retained **only in the source byte Ground**.
Normalized JSON may encode different bytes while preserving the exact
mathematical AST. The native `ObservationComparison` checks that
*mathematical* equivalence for this particular case, and
`roundtrip_bytes_exact` separately says whether the original bytes
were recovered. This avoids claiming that semantically equal
representations are necessarily byte-for-byte identical.

For `opaque`, unsigned integers, UTF-8 and a valid IPv4 datagram,
the admitted round-trip proof is byte-exact instead.

### Genuine packet compatibility

The existing PATH-GROUND-004/005/006 work observes actual network
byte streams and kernel IPv4 TTL changes. This new adapter accepts an
IPv4 datagram's **exact recorded bytes** and verifies version, total
length and one's-complement header checksum before interpreting the
TTL, addresses, protocol, packet ID and payload digest. It does not
need the experimental router PRs in order to recognize these bytes.

A receiver may then compare the parsed TTL with the existing real
`AF_PACKET` observations or with
`mailcpu/live_router_capture.py` if those pending branches are
admitted. The distinction remains:

- seeing `ttl=32` in a valid packet does **not** prove a router
  decremented it;
- an observed ingress/egress relation supplies the transition
  evidence;
- a signed observer receipt supplies credential identity, not physical
  truth;
- receiver-owned admission determines whether any of this evidence
  may enter a Ground.

See
[PATH-GROUND-006 PR](https://github.com/Kier73/E-CPU/pull/178)
for the not-yet-merged acquisition-time sensor experiment.

## Finite observation and navigation costs

The current adapter admits at most 65,536 bytes per observed window.
This is a **per-observation budget**, not a claim that a model,
repository, Internet stream, or computational object is inherently that
small. Large objects remain in the existing page store; a request can
navigate to a qualified byte range and read just the intersecting
pages. Remote communication and page retrieval costs remain with
their actual owners.

The `coordinate(i)` operation is a resident-buffer O(1) lookup after
those bytes have been obtained. A full SHA-256 hash still reads all
selected bytes, and decoding or normalization consumes the work
required for those exact bytes. No unknown semantic law is conjured by
a byte-level representation.

## Usage

```python
from mailcpu.data_ground import DataGround, DataLens

source = DataGround(b"123")
text = source.interpret(DataLens("utf8"))
numeric = source.interpret(DataLens("json"))
binary_integer = source.interpret(DataLens("uint-be"))
survey = source.candidate_views()
assert survey["interpretation_selected"] is None
assert source.verify_interpretation(text)
assert source.verify_interpretation(numeric)
assert source.verify_interpretation(binary_integer)

# A native computational object can be read in one verified range,
# retaining the exact manifest and original content digest as context.
# observed = DataGround.from_object_range(store, manifest, offset, length)
```

A complete demonstration is available at
`python -m examples.data_ground_demo`, and the main regression suite
is `python -m pytest -q tests/test_data_ground.py`. The dedicated
workflow runs Linux and Windows, Python 3.11 and 3.13, and executes
that demonstration.

## Next frontier: learn which mathematical interpretation is sufficient

The next research direction is **not** an unrestricted heuristic that
declares any bit pattern to be language, a model, a TCP packet or a
proof. Instead, use E-CPU's observation sufficiency and VGI's
Ground-identification work:

1. Treat unknown data as a finite but exact byte-vector Ground.
2. Identify the *candidate* partial lenses consistent with a format
   declaration, external schema, authenticated source, measured
   invariants or selected active probe.
3. Preserve multiple candidates and their distinct evidence.
4. Select the observation required by the user's mathematical
   intention, with explicit budget and authorization.
5. Reject unsupported candidates and only admit a typed result after
   reconstructing the required evidence from original data.
6. Retain the exact provenance, observation equality, rejected
   alternatives and unresolved semantic ambiguity.

In the desired larger system, a model can **propose** relevant
interpretations while the E-CPU itself **determines** whether its
Ground, invariants and receiver authorization suffice. That is an
architectural path to general data comprehension without confusing
finite representation capacity with universal semantic knowledge.
