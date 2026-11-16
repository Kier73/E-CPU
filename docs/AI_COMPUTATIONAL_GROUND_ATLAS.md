# AI Computational Ground Atlas — full-workflow translation (AGA-001)

**Status: source-inspected, machine-validated *catalogue* of Ground descriptions; not an automatic Ground admission and not proof of universal AI execution.**

**Purpose:** before writing another model emulator or family-specific engine, identify the E-CPU Ground, observation, transition and realization resources that already apply to every major modern AI computational structure. Build through **composition and navigation**, introducing a new primitive only after a demonstrated missing law or realization.

## The record and its source identity

**108 structural Ground descriptions** across **8 stages**, with **20 existing-scoped**, **19 research-scoped**, and **69 candidate mappings. These counts classify *related realization evidence*, not the number of admitted runnable AI Grounds.

- Canonical machine-readable source: [`mailcpu/ai_ground_atlas.v1.json`](../mailcpu/ai_ground_atlas.v1.json).
- Validator and query interface: [`mailcpu/ai_ground_atlas.py`](../mailcpu/ai_ground_atlas.py).
- Pinned source revisions: E-CPU main, IFS main, VGI main, VP main, plus explicitly separate stacked VP-002/003/004 *draft* commits. All anchors carry a commit identity rather than an implicit moving branch.
- Catalog content digest: `b7c3a70b77fe6963fc77181a2809c56dd7edbf433ea546a8e8c601894e340e44` (canonical UTF-8 JSON excluding its own digest). This checks integrity, not authenticity.

Every record states: **representation/state → transition relation → observer projection → navigation/realization strategy → dependencies → existing source anchors → verification obligation → status**. The catalog is open-world: no finite list can exhaust all architectures, representations or effective programs.

**Admission distinction:** all entries say `ground_admission: catalogued_only`. A native `RepresentationRef` can identify the catalogued Ground *description*, but it does not instantiate a `VirtualGroundRef`, admit a `StructuralMemorySpec`, bind an `OperatorSpec`, or grant a Hypervisor capability. The receiver retains these authorities. A referenced implementation may cover one mathematical subfamily without executing the full AI operator.

### Status and navigation taxonomy

| Status | Meaning |
| --- | --- |
| `mainline_scoped` | An inspected mainline E-CPU or VGI mechanism realizes a **bounded related relation**, not necessarily a whole AI operation |
| `research_scoped` | Concrete bounded experiment or draft VP implementation contributes evidence; publication/CI/scale beyond that scope is not asserted |
| `candidate` | Meaning and a plausible E-CPU composition are identified; an AI-specific realization is not yet demonstrated |

Navigation choices (`direct_law`, `inverse_navigation`, `composed_projection`, `symbolic_factorization`, `evidence_search`, `qualified_realization`, `state_continuation`, `explicit_evaluation`) describe **research or current pathways**, not automatic eligibility. In particular, a matrix multiply or Transformer decode cannot simply claim O(1) navigation because some *other* affine law does. Its own equivalence and complexity require proof.

## Translating AI into E-CPU operations

The Ground is not a model-specific host or an instruction-emulation schedule. The reusable E-CPU path is:

```text
source/event/intent (ComputationalObjectStore, ObservationTraceBuilder)
  -> typed meaning (RepresentationRef, computational Ground, ObserverContract)
  -> Ground proposal / admitted family (StructuralMemoryRegistry, VGI proof obligations)
  -> prediction/description selection and navigation (ContextualOrbitNavigator, NavigationPlan)
  -> composition (ComposedVirtualGroundNavigator, NavigableComputationDAG)
  -> permitted numeric/causal realization (VirtualLayerRuntime + Hypervisor + qualified observer-host)
  -> independent projection verification (ObservationContract, numerical/reference witness)
  -> retained continuation (ComputationalSession, ComputationalObjectStore, recovery lineage)
```

**A missing transition must remain unresolved.** The existing `Observed Orbit Pipeline` currently admits specific scalar generators; a tensor/attention/optimizer relation does not become such a generator merely because a tensor manifest is content-addressed. The atlas points to where typed model or path adapters would attach to the *existing* authority/execution system.

### Representative workflows — one Ground language across unlike AI systems

**Language model inference / MoE (source to token):**

`ground.source → model.parameters → model.tensor → model.architecture → forward.qkv → forward.attention → forward.moe_route → forward.moe_expert → forward.logits → forward.sampling → forward.autoregressive → operate.session → operate.recovery`.

Actual dependency edges are in the JSON, not necessarily this linear presentation. Inference state and masked attention are unresolved if no valid source-weighted realizer is bound. Existing VP-003/004 draft sparse inference can be reused as bounded real numerical sublayer evidence, not misrepresented as a full Qwen3 forward pass.

**Model training / adaptation (evidence to updated parameters):**

`data.acquisition → data.dataset → data.tokenizer / data.visual_encoding → data.batch → model.architecture → forward.* → learn.objective → learn.autodiff → learn.gradient → learn.optimizer → learn.checkpoint → learn.evaluation`.

An optimizer step is a state transition over model weights, optimizer moments, RNG and data cursor, not an opaque “train()” procedure. A closed-form direct jump to final trained parameters is **not** asserted. Evidence-driven law discovery and direct semantic compilation from IFS remain separate experimental strategies.

**Multimodal / diffusion:**

`data.visual_encoding + data.audio_encoding + data.video_encoding → forward.multimodal_fusion → forward.diffusion / forward.flow → model.latent → ground.observer`.

Positions, temporal alignment, dtype, and solver accuracy belong to the Ground and may determine which observations can be produced directly or must be evaluated.

**Retrieval-augmented model and autonomous agent:**

`retrieve.chunk → retrieve.vector → retrieve.rerank → retrieve.context → agent.planning → agent.tool → ground.authority → ground.evidence → agent.memory`.

The tool-call Ground is an *effectful* external relation; model-generated text cannot authorize an effect, and a transport acknowledgment is not an independently observed tool outcome.

**Unfamiliar future architecture:** recognize its typed representations and mathematical operator relations first, search for composable admitted Grounds and verified translations, then qualify a new observer-host/path if required. Only introduce a new operator/ground family when no existing admitted composition preserves the observation. Never mark an unknown relation as executed to force closure.

## Full inventory by workflow stage

| Workflow stage | Structures |
| --- | ---: |
| interpretation — Meaning, observation, authority and Ground admission | 10 |
| data — Data, preprocessing and sensory representation | 13 |
| model — Model architecture and parameter representation | 15 |
| inference — Forward numerical and sequence transitions | 24 |
| learning — Optimization, updates and training state | 17 |
| retrieval — Retrieval and knowledge-assisted computation | 4 |
| agency — Agentic computation and external effects | 9 |
| operations — Service, distribution, recovery and evaluation | 16 |

Each row below is a **source-anchored Ground descriptor**, not an execution result. The full transition/observation and verification language is in the JSON.

| Stage | Virtual Ground identifier | Computational structure | Evidence scope |
| --- | --- | --- | --- |
| interpretation | `ground.source` | Provenance and byte identity | `mainline_scoped` |
| interpretation | `ground.semantics` | Typed computational meaning | `mainline_scoped` |
| interpretation | `ground.observer` | Observer and observation contract | `mainline_scoped` |
| interpretation | `ground.intention` | Intention and target predicate | `mainline_scoped` |
| interpretation | `ground.transition` | Admitted transition law and invariants | `mainline_scoped` |
| interpretation | `ground.composition` | Composed Virtual Ground | `mainline_scoped` |
| interpretation | `ground.authority` | Receiver-controlled capability | `mainline_scoped` |
| interpretation | `ground.realization` | Substrate-independent Ground realization | `mainline_scoped` |
| interpretation | `ground.evidence` | Evidence status and proof obligations | `mainline_scoped` |
| interpretation | `ground.lineage` | Committed state and recovery lineage | `mainline_scoped` |
| data | `data.acquisition` | Data and event acquisition | `mainline_scoped` |
| data | `data.dataset` | Dataset membership and partition | `candidate` |
| data | `data.schema` | Data typing and schema validation | `mainline_scoped` |
| data | `data.normalization` | Preprocessing and normalization | `candidate` |
| data | `data.tokenizer` | Text tokenization and vocabulary | `candidate` |
| data | `data.visual_encoding` | Image patch and visual tokenization | `candidate` |
| data | `data.audio_encoding` | Acoustic feature and audio tokenization | `candidate` |
| data | `data.video_encoding` | Video and temporal multimodal frames | `candidate` |
| data | `data.augmentation` | Data augmentation and corruption | `candidate` |
| data | `data.batch` | Training/inference batch selection | `candidate` |
| data | `data.privacy` | Private, regulated and licensed data constraints | `mainline_scoped` |
| data | `data.synthetic` | Procedural and synthetic data formation | `research_scoped` |
| data | `data.labels` | Human, model and programmatic labels | `candidate` |
| model | `model.architecture` | Neural computation topology | `research_scoped` |
| model | `model.tensor` | Typed tensor geometry | `research_scoped` |
| model | `model.parameters` | Model parameter identity | `research_scoped` |
| model | `model.quantization` | Quantized representation and dequantization | `candidate` |
| model | `model.precision` | Floating-point and numerical behavior | `research_scoped` |
| model | `model.embedding` | Embedding table and feature projection | `candidate` |
| model | `model.position` | Position and relative coordinate encoding | `research_scoped` |
| model | `model.adapter` | Low-rank adapters and model deltas | `candidate` |
| model | `model.sparsity` | Sparse connectivity and parameter selection | `research_scoped` |
| model | `model.latent` | Latent space and generative representation | `candidate` |
| model | `model.compile` | Semantic-to-network construction | `research_scoped` |
| model | `model.convolution` | Convolutional and spatial architectures | `candidate` |
| model | `model.graph_network` | Graph neural network topology | `candidate` |
| model | `model.probabilistic` | Probabilistic graphical model | `candidate` |
| model | `model.weight_tying` | Weight sharing and parameter aliases | `candidate` |
| inference | `forward.matmul` | Linear/tensor contraction | `research_scoped` |
| inference | `forward.activation` | Pointwise nonlinearities | `research_scoped` |
| inference | `forward.normalization` | RMSNorm/LayerNorm and scaling | `candidate` |
| inference | `forward.qkv` | Attention Q/K/V projections | `research_scoped` |
| inference | `forward.attention` | Causal/bidirectional attention | `candidate` |
| inference | `forward.rope` | Rotary positional transform | `research_scoped` |
| inference | `forward.residual` | Residual composition | `research_scoped` |
| inference | `forward.moe_route` | Sparse mixture-of-experts routing | `research_scoped` |
| inference | `forward.moe_expert` | Selected expert neural realization | `research_scoped` |
| inference | `forward.encoder` | Encoder bidirectional representation | `candidate` |
| inference | `forward.multimodal_fusion` | Cross-attention and modality fusion | `candidate` |
| inference | `forward.logits` | Vocabulary or label projection | `candidate` |
| inference | `forward.sampling` | Token selection and decoding policy | `research_scoped` |
| inference | `forward.autoregressive` | Autoregressive inference orbit | `candidate` |
| inference | `forward.kv_cache` | Attention key-value memory | `candidate` |
| inference | `forward.diffusion` | Iterative diffusion / flow generation | `candidate` |
| inference | `forward.state_space` | Recurrent / state-space model transitions | `candidate` |
| inference | `forward.speculative` | Speculative decoding and proposal verification | `candidate` |
| inference | `forward.convolution` | Convolution and transposed-convolution operator | `candidate` |
| inference | `forward.pooling` | Pooling and spatial reductions | `candidate` |
| inference | `forward.graph_message` | Graph message passing and aggregation | `candidate` |
| inference | `forward.probability` | Probabilistic inference and marginalization | `candidate` |
| inference | `forward.flow` | Continuous flows and vector-field integration | `candidate` |
| inference | `forward.classifier` | Class prediction and structured output | `candidate` |
| learning | `learn.objective` | Loss/energy objective | `candidate` |
| learning | `learn.autodiff` | Automatic differentiation graph | `candidate` |
| learning | `learn.gradient` | Gradient evaluation and accumulation | `candidate` |
| learning | `learn.optimizer` | Optimizer parameter update | `candidate` |
| learning | `learn.schedule` | Learning-rate and phase scheduling | `mainline_scoped` |
| learning | `learn.randomness` | RNG and stochastic experiment state | `candidate` |
| learning | `learn.distributed` | Gradient collective and sharded training | `candidate` |
| learning | `learn.checkpoint` | Training checkpoint and optimizer continuity | `candidate` |
| learning | `learn.adapter` | Parameter-efficient adaptation | `candidate` |
| learning | `learn.preference` | Preference/RL policy optimization | `candidate` |
| learning | `learn.distillation` | Teacher/student representation transfer | `candidate` |
| learning | `learn.evaluation` | Held-out validation and experiment selection | `candidate` |
| learning | `learn.federated` | Federated model update and authority | `candidate` |
| learning | `learn.contrastive` | Contrastive and metric learning | `candidate` |
| learning | `learn.regularization` | Regularization and constrained optimization | `candidate` |
| learning | `learn.activation_recompute` | Activation rematerialization and memory scheduling | `candidate` |
| learning | `learn.search` | Hyperparameter and architecture search | `candidate` |
| retrieval | `retrieve.chunk` | Chunking and document-ground representation | `candidate` |
| retrieval | `retrieve.vector` | Vector or hybrid retrieval index | `candidate` |
| retrieval | `retrieve.rerank` | Grounded reranking and relevance | `candidate` |
| retrieval | `retrieve.context` | Retrieval-augmented context assembly | `candidate` |
| agency | `agent.policy` | Agent policy and action selection | `candidate` |
| agency | `agent.planning` | Task decomposition and dependency planning | `candidate` |
| agency | `agent.tool` | External tool effects and acts | `candidate` |
| agency | `agent.memory` | Agent episodic/semantic memory | `candidate` |
| agency | `agent.environment` | Environment and interaction Ground | `candidate` |
| agency | `agent.self_critique` | Self-evaluation and grounded correction | `candidate` |
| agency | `agent.human_handoff` | Approval, handoff and escalation | `candidate` |
| agency | `agent.tree_search` | Tree search and constrained exploration | `candidate` |
| agency | `agent.world_model` | Learned world model and planning | `candidate` |
| operations | `operate.session` | Queryable model and processor session | `research_scoped` |
| operations | `operate.batching` | Dynamic batching and queue management | `candidate` |
| operations | `operate.placement` | Expert/tensor placement and qualification | `research_scoped` |
| operations | `operate.fabric` | Authenticated communication and causal ordering | `mainline_scoped` |
| operations | `operate.path_compute` | Path-native transformation and qualification | `mainline_scoped` |
| operations | `operate.recovery` | Hard-failure restoration and fencing | `mainline_scoped` |
| operations | `operate.kv_paging` | Remote/stateful inference pages | `candidate` |
| operations | `operate.verify_numeric` | Independent numerical comparison | `research_scoped` |
| operations | `operate.verify_semantic` | Cross-Ground observational equivalence | `mainline_scoped` |
| operations | `operate.verify_provenance` | Model source and result authentication | `mainline_scoped` |
| operations | `operate.metrics` | Quality, latency, energy and resource evidence | `candidate` |
| operations | `operate.policy` | Safety, resource and privacy policy | `mainline_scoped` |
| operations | `operate.lifecycle` | Evaluation, monitoring and Ground refinement | `candidate` |
| operations | `operate.version_compat` | Model and tokenizer version compatibility | `candidate` |
| operations | `operate.eval_safety` | Safety evaluation and output moderation | `candidate` |
| operations | `operate.measure` | Model-system profiling and independent measurements | `candidate` |

## Query and validate the recorded Ground descriptions

```shell
python -m mailcpu.ai_ground_atlas validate
python -m mailcpu.ai_ground_atlas list --stage inference
python -m mailcpu.ai_ground_atlas show forward.moe_expert
python -m mailcpu.ai_ground_atlas closure operate.recovery
python -m unittest discover -s tests -p "test_ai_ground_atlas.py" -v
```

`show` returns the complete Ground descriptor plus its existing E-CPU `RepresentationRef` content identity; `closure` shows its transitive dependencies. Both are observational inspection actions; neither executes the described operation. The source catalogue is packaged as MailCPU package data so it remains readable after `pip install .`.

## Anti-emulation decision policy

1. **Start from intention and observation**: do not simulate an unneeded full processor or model state to answer a narrower query.
2. **Look for native laws and reused invariants first**: direct/inverse or symbolic navigation is eligible only when proven for the exact Ground, context, and observation.
3. **Keep the structure lazy**: use addresses and content identities for model weights, sparse experts, tensors, intermediate state and dependency fronts; request only the needed pages and operators.
4. **Use E-CPU composition**: `ComposedVirtualGroundNavigator`, `NavigableComputationDAG`, `VirtualLayerRuntime`, authenticated fabric and existing recovery-lineage authorities form the runtime. The atlas adds *no* second interpreter, storage system, scheduler or Hypervisor.
5. **Distinguish structural evidence from numerical or stateful execution**: a typed graph, a source hash, an expert-selection plan, or a simulated path is not completed model inference.
6. **Do not treat conventional realization as the destination**: CPU/GPU/reference inference can test equivalence and bridge missing components while researching qualified communication-path and directly navigated alternatives.
7. **Preserve unknown/partial cases**: a novel operation, external data not available, insufficient training information, missing permission, or unprovable direct jump requires a precise refusal or a scoped fallback—not a fictitious proof.

## Conformance gate to promote one catalog entry into an admitted runnable Ground

- Pin exact source, typed state and mathematical relation, including numerical precision and effect mode.
- Construct/identify a native E-CPU Ground reference and receiver-owned authority; maintain source and observation identities.
- Bind an existing supported navigator or realizer/`VirtualLayerRuntime` operator (or demonstrate a genuinely new qualified relation).
- Supply independent witnesses: exact proof when possible; numerical oracle, error certificate, or probabilistic coverage otherwise.
- Verify composition across predecessors, causal boundaries, replay, stale-revision rejection and recoverability for stateful operations.
- Record measured cost and the actual execution locus; a route or checksum is not evidence that passive transit performed neural arithmetic.
- Update the entry status **only after** the relevant scoped tests establish it, without converting the catalogue itself into an admission authority.

### Immediate build path (no redundant architecture)

Keep the existing VP-004 Ground-neural integration as a numerical experiment. Reuse E-CPU `ObservedOrbitPipeline` and `ComputationalExecutionAdmissionCoordinator` to select and authorize it; demonstrate query and verify under the same observer identity. Extend with one complete source-weighted Transformer layer and retained KV/session state **only after** the catalogue identifies the exact unresolved transitions. A universal interface may emerge from the existing contracts; do not assume it must be invented.

**Definition of success:** a virtual processor can observe a previously unseen well-described AI computation through available admitted Grounds, verify the requested result, and preserve the computational identity as realizers change. This is an experimental target; the atlas itself is the inventory for that research, not the completed proof.
