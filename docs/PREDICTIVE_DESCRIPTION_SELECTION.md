# Predictive Description Selection over Composed Virtual Grounds

## 1. Purpose and boundary

This layer tests which admitted description best predicts an independently observed multi-component state. It builds on the composed Virtual Ground representation and direct law navigation introduced earlier.

The selector is deliberately offline and advisory. It does not:
- propose or admit Structural Memory revisions;
- rewrite a generator, observer contract, hypervisor policy, or fabric route;
- treat a candidate's own generated values as ground truth;
- turn a composed projection into a complete HeadlessOS checkpoint; or
- silently switch to breadth-first search, orbit enumeration, or SystemSeed replay when direct navigation refuses.

The experiment has two coupled descriptions:

- **Structural information:** component identities, field paths, representation references, encodings, pinned Structural Memory specs/certificates, and exact state bytes.
- **Interpreted structure:** the common system identity, base Virtual Ground, Computational Ground, state schema, scheduler domain, and the semantics assigned to each component.

A candidate is a fixed ComposedVirtualGroundAddress whose component laws already exist as admitted Structural Memory revisions.

## 2. Independent observation contract

A PredictiveGroundObservation contains the canonical observed state, absolute scheduler tick, ObserverContract, and ObserverReceipt. The receipt is verified against the exact contract and must carry a typed scheduler reading for the same tick.

For this experiment:
- ObserverContract.subject must equal the composed state's state_schema reference.
- ObserverContract.interpretation must equal the composed computational_ground reference.
- ObserverContract.context_digest must equal predictive_experiment_digest(address).
- The receipt projection must be the exact canonical state supplied as the observation.
- The receipt scheduler identity and tick must agree with the experiment address and sample.

The experiment digest binds system incarnation, base Virtual Ground, Computational Ground, scheduler identity, schema, template, component identities, field paths, representations, encodings, and declared extensions. It intentionally excludes candidate-specific Structural Memory revisions so multiple descriptions can be evaluated against the same observation stream.

An observer receipt is a content/provenance binding, not a digital signature or independent physical attestation. The caller must obtain receipts from the observer authority it trusts. A digest cannot make an untrusted observer trustworthy.

## 3. Chronological evaluation

The evaluator accepts two cutoffs and separates observations by scheduler tick:

\[
D=\{s_t:t\leq d\},\quad
V=\{s_t:d<t\leq v\},\quad
T=\{s_t:t>v\}.
\]

- **Development** is reported as a diagnostic partition. It does not fit candidate parameters.
- **Validation** selects the candidate and constructs the Pareto frontier.
- **Test** is a later held-out partition reported after ranking; it does not affect the recommendation.

Candidate laws are fixed and admitted before this function runs. In this first version, there is no gradient update, parameter search, synthetic data generation, or automatic law admission. Development observations are diagnostics, not training inputs to this evaluator. Structural Memory certificate witness coordinates are not exposed by the certificate summary, so the experiment owner must keep validation/test observations separate from any samples used to construct or admit the candidate laws.

The evaluator requires at least one development and one validation observation. A test partition may be empty, but the report then makes no out-of-window test claim. Scheduler ticks must be unique and the observed state must contain every declared component field with the declared scalar encoding.

## 4. Prediction and residual metrics

Each candidate is rebound to the observed absolute scheduler tick while retaining its exact base Ground, context, Structural Memory revision, spec digest, and certificate digest. ComposedVirtualGroundNavigator.locate evaluates every component directly at that common coordinate.

The evaluator records:

| Measure | Meaning |
|---|---|
| Coverage | Fraction of observations for which every component generator returned a guarded value. |
| Component accuracy | Correct predicted component values divided by values successfully predicted. |
| Predictive yield | Correct component values divided by all component values expected across the partition. This combines coverage and accuracy. |
| Full-state match rate | Fraction of samples where the assembled composed projection exactly equals the observed state. |
| Residual leaves | Unequal state leaves between the composed projection and the observation on covered samples. |
| Unmodeled changed leaves | Observation/template changes outside the candidate's declared component paths. |
| Distinct component states | Number of unique observed, predicted, and exactly matched component-value tuples in the sample partition. |
| Component-state-space coverage | Matched distinct observed tuples divided by all distinct observed tuples. This is coverage of the sampled support, not an enumeration or estimate of the globally reachable state space. |
| Navigation evidence digest | Digest of each sample's target coordinate, composed projection/state identity, component read-receipt digest, or guarded refusal. |
| Navigation evidence digest | Hash of each sample's target coordinate, composed projection/state identity, component read-evidence digest, or guarded refusal. |

Coverage and conditional accuracy are separate by design. A candidate that predicts very accurately only for a small fraction of the observed coordinates cannot hide its refusal rate inside a high accuracy score. Predictive yield makes that trade-off explicit.

The composed projection currently writes scalar component values into nested JSON object paths. Other changing fields remain visible as residual or unmodeled changes; they are not silently assumed to be predicted.

## 5. Description and navigation cost

The report charges each candidate in three distinct ways:

1. **Description bytes:** UTF-8 bytes in the canonical description containing the shared experiment identity, every component layout/representation, complete Structural Memory spec, and certificate.
2. **Verification witness units:** the sum of admitted certificate witness_count values. This is a count of witness cases represented by the certificates, not a measured CPU duration.
3. **Navigation work units:** a deterministic algorithmic proxy derived from the admitted family and queried coordinate:
   - integer progression: one unit;
   - finite graph: O(N) canonical orbit materialization plus O(1) indexed access. The current registry reconstructs the stored orbit parameters for each new coordinate, so the proxy charges N units per read;
   - LCG: queried coordinate bit length;
   - GF(2): recurrence-order cubed times the queried coordinate bit length.

These units compare the known algebraic cost profiles. They are not measured instruction counts, elapsed time, energy, or asymptotic proofs for an entire OS. Physical execution measurements, when supplied separately, remain separate fields.

## 6. Selection rule

The selector constructs a Pareto frontier from validation results. A candidate dominates another only when it is no worse in all of the following and strictly better in at least one:

- predictive yield, sampled component-state-space coverage, sample coverage, component accuracy, and full-state match rate (maximize);
- description bytes, mean navigation work units, and verification witness units (minimize).

The frontier is ordered deterministically by predictive yield, matched distinct component-state coverage, sample coverage, component accuracy, full-state match rate, mean navigation work, description size, witness units, then candidate ID. This is a transparent prediction-first tie-break, not a hidden weighted score. The full frontier remains in the report so a later policy can apply an explicit resource preference without discarding the measured trade-off.

The selected ID is a recommendation only. Admission, execution, and checkpoint authority remain with their existing owners.

## 7. Hypervisor and compute-fabric connection

PredictiveExecutionEvidence.from_hypervisor_result accepts only a typed HypervisorExecutionResult whose local action is ALLOW, whose effect is a Virtual Layer operator result, and whose executed flag is true. It retains:
- decision receipt and operation identity;
- the complete canonical HypervisorExecutionResult payload, with its digest rechecked against every retained identity field, effect estimate, replay flag, placement label, and extracted handler measurement;
- declared estimated Virtual Layer energy and virtual ticks;
- node and substrate labels; and
- explicitly reported numeric handler measurements, such as elapsed milliseconds or transferred bytes.

The distinction matters: estimated_energy and estimated_virtual_ticks come from the operator contract and runtime preflight. A measured handler_total_ms is an elapsed measurement. Neither should be mislabeled as the other.

An optional ComputationalFabricRouteWitness contributes its typed network, host, and total route-cost vectors. When the hypervisor effect names a node, the adapter requires it to match the route witness target node. The witness validates the additive relation total = network + host, but its authoritative property is false. The selector therefore preserves the route witness digest and costs as planning context, not as proof of execution, an observed latency, or a prediction label. Likewise, the typed hypervisor result and its digest are not a digital signature: callers must source the result from the trusted host hypervisor/effect ledger rather than accept a caller-constructed object as attestation.

The current ranking does not blend these operational measurements into the prediction objective. Instead, the report counts all returned Hypervisor result samples and replay receipts separately, but includes only non-replayed effects in estimated energy/tick sums, measured handler metrics, and route-cost totals so an idempotent retransmission is not charged as a second execution. They are reported separately so future experiments can compare the model's predictive utility with the cost of obtaining and using its observations without conflating host placement with model correctness.

## 8. Anti-enumeration and failure semantics

For every sample and candidate, the evaluator requests one direct composed projection at the target coordinate. expanded_states must remain zero. A guarded refusal is counted as unavailable coverage; it does not trigger a hidden fallback to:
- ContextualNavigator graph search;
- finite-orbit enumeration;
- a generated transition trace; or
- exact SystemSeed replay.

If a general path is not algebraically navigable, a separately verified path index or explicitly budgeted path-discovery experiment can be evaluated in a later extension. This selector does not pretend arbitrary non-injective transitions have a general inverse.

## 9. Research direction

The immediate experiment is to compare alternative admitted generator bases over the same observed multi-component trajectory, then inspect where residual changes concentrate. Those residuals identify which state variables need new interpretations or component generators.

A next stage could compile register vectors, pages, memory regions, or process-state bundles as higher-level generators rather than expanding every byte into an independent scalar component. Another stage could construct candidate descriptions from observer evidence, but only with separate admission witnesses and chronologically held-out evaluation.

The long-term question—whether a virtual description can become more effective at producing and navigating information than the system it describes—remains a testable research objective, not a result assumed by this implementation.

\[
\boxed{\text{Observe independently; predict compositionally; compare on held-out time; select by evidence and cost.}}
\]
