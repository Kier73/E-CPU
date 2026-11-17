# INTERNET-008 — Intention-specific VGI attention over E-CPU's real partial frontier

**Development status:** newly implemented opt-in adapter and native test suite; hosted native E-CPU + pinned VGI integration checks required before claiming runtime verification. This extends [INTERNET-007](INTERNET_PARTIAL_FRONTIER_007.md) and stays stacked on its review branch. The adapter never reads arbitrary public sites or installs remote code.

## Question

A route may have several speculative completions, but **the number of possible routes is not the same as how informative a probe is**. Can VGI's real incomplete-Ground distinguishability computations and E-CPU's existing intention-sufficiency planner guide the first *permitted, reachable* Internet observation, without granting any of VGI's counterfactual scenarios the status of network evidence?

## Two independent mathematical questions, one existing operational boundary

1. **E-CPU `FiniteGround` + `plan_sufficiency`**: in one receiver-supplied finite hypothesis table, which features form a minimum-cost sufficient set that determines the intention's target? The table is a hypothesis, not established reality. A plan or digest never authorizes measurement.
2. **VGI `GroundTransitionSystem` + `score_partial_probe`**: at a selected observer and finite horizon, how many previously unresolved state pairs would each *counterfactual* probe outcome resolve? The verified VGI implementation distinguishes `equivalent`, `distinguishable`, and `unresolved`. `unresolved` is **not** false or absent. Without explicitly supplied exact scenario weights, no success probability or expected information gain is inferred.
3. **E-CPU `PartialFrontierQualifier` and `EvidencePathResolver`**: retains exclusive control over which **first** unknown relations are reachable through verified preceding segments, live HeadlessOS authority, current leases, offer bounds, resource ceilings, real observer handlers and independent case verification. VGI never inserts hypothetical edges or submits network requests.

The optional `mailcpu.internet_distinguishability_attention.DistinguishabilityFrontierQualifier` is receiver-installed; it invokes the same original multi-gap planner and hooks a scorer **only after native reachability filtering**. For this milestone, the attention hook is active when at least two hypothetical gaps are required; INTERNET-006's existing one-missing-gap objective remains unchanged.

### Deterministic, probability-free order

For every eligible first offer, rank in this order:

1. Membership of its feature in the receiver-supplied finite model's exact minimum-cost sufficient feature set for the target.
2. Number of **target-conflicting pairs** in the current public-observation fiber separated by that feature, computed exactly from `FiniteGround` rows.
3. Actual VGI `score_partial_probe` worst-case and best-case count of newly resolved predictive state pairs under declared scenarios.
4. INTERNET-007's count of bounded potential route completions.
5. Typed lexicographic estimated route cost and exact offer digest for deterministic ties.

The minimum-cost *feature set* may contain multiple measurements; one feature alone does not imply an intention is resolved. Predicted scenario outcomes are counterfactual, not source measurements. This order is a receiver-configured policy rather than a universal information-theoretic optimum. Scenario probabilities, if present in the VGI probe, are retained as model data but are deliberately **not** used for ranking.

## Controlled decision experiment

There are five unknown, receiver-curated relations, with two possible completions behind `dnsroot` and one behind `httpalt`:

```
           /-- gita ------\
start -- dnsroot           +--> goal
           \-- gitb ------/
start -- httpalt -- rfcend ------> goal
```

INTERNET-007's path-count heuristic selects `dnsroot`. In the supplied finite model, the `http` feature is sufficient to distinguish the target, while `dns` is not; VGI's counterfactual simulation also yields different finite-horizon distinctions. INTERNET-008 selects **`httpalt`**, even though it has lower structural route coverage and a higher estimated cost. After its receiver handler produces independently verifiable evidence, the *native* router may accept it. `rfcend` then becomes a one-gap continuation and must be qualified separately. Nothing assumes the second step succeeded in advance.

The source code does not set any network result's authority based on target separation, and does not silently update the finite hypothesis Ground based on a returned projection. A future evidence-to-model-revision workflow must prove exact decoding of a source response into a finite feature value, preserve the prior version, and re-plan. This pilot demonstrates **better intention-directed choice**, not autonomous learning of world truth.

## Scope and obligations

- **Two independent model identities**: VGI `system.fingerprint` plus E-CPU `FiniteGround.digest`, scenario descriptors, feature bindings and the intended Ground/context. Both are recorded in the advisory choice trace. Digest identity does not authenticate the model author.
- **No forged authority**: the attention hook sees only candidates accepted by the verified-prefix planner; its chosen offer digest is checked against that finite candidate set. The native process capability snapshot is used by E-CPU's actual resolver and may be revoked before dispatch.
- **No fabricated numerical expectation**: actual `score_partial_probe` returns only bounds unless weights were explicitly declared; this policy does not use expected gain to choose.
- **No false refutations**: timeout, overrun, changed content, or verifier refusal remain append-only failed attempts. They are not counterexamples to the mathematical target or to unseen Internet-path capacities.
- **No network access from VGI**: the optional package is pure attention analysis. Actual network work belongs solely to receiver-installed E-CPU handlers (e.g., the bounded RFC observation from INTERNET-007), and their own allowlists and budgets.
- **No universal proof**: the exact target-pair count holds only for the supplied finite model; VGI pair counts hold only over stated predictive states, channels, actions, scenarios and horizon.

## Verification

Pin VGI source to **`7a3c4a368d1d24044a6c06a317c26ef316513e6d`** (current inspected repository revision). CI explicitly checks out this exact revision rather than fetching a floating branch. In an E-CPU checkout with the stacked branches present:

```bash
export PYTHONPATH="$PWD/vgi-source/virtual_ground_interpreter${PYTHONPATH:+:$PYTHONPATH}"
python -m unittest discover -s tests -p 'test_internet_distinguishability_attention.py' -v
python -m unittest discover -s tests -p 'test_internet_partial_frontier.py' -v
python -m unittest discover -s tests -p 'test_internet_prospective_qualification.py' -v
python -m unittest discover -s tests -p 'test_internet_ground_routing.py' -v
```

`.github/workflows/internet-distinguishability-attention.yml` runs these native contracts on Python 3.11 and 3.13 and preserves the full previous routing suite. The workflow does not claim that hosted VMs are independent internet observer-hosts or that a hypothetical scenario has occurred on the public internet.

## Next research step

Use E-CPU's observation-path evidence gate and VGI's append-only model revision to update a finite hypothesis table **only from an independently admitted and decoded response**. Then repeat attention with the revised Ground and compare the resulting request count, target sufficiency and per-query network costs against structural-only exploration. Conditional paths through genuinely different remote services remain a separate authenticated experiment.
