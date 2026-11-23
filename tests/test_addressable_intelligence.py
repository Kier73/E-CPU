"""AIG-001: live model behavior from retained original pretrained source-glances.

The two original retained SmolLM2 tensors are BF16 genuine source observations.
The fixed comparison is mathematically a 2-row readout of an original layer-0
Q projection, *not* tokenizer output or full transformer inference.
A new VLD neural FSM is formed from resulting exact evidence, and an original
VL-I conversation then runs under real E-CPU M2/M3 across worker processes.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import sys

import pytest

from mailcpu.addressable_intelligence import (
    CompiledModelIntention, compile_trained_model_intention,
    generate_neural_ground_from_trained_observations,
    original_full_four_row_projection,
)
from mailcpu.computational_host import LocalComputationalHost
from mailcpu.computational_objects import ComputationalObjectStore
from mailcpu.computational_session import ComputationalSessionStore
from mailcpu.computational_transition import ComputationalSessionTransitionAdapter
from mailcpu.intention_sufficiency import (
    FiniteState, FiniteGround, MeasurementCapability,
    plan_sufficiency, resolve_sufficiency, verify_sufficiency_resolution,
)
from mailcpu.recovery_lineage import RecoveryLineageAuthority, RecoveryLineageCoordinator
from mailcpu.seed_commit_quorum import SeedCommitMembership
from mailcpu.stream_os_session import OS_STATE_SCHEMA
from mailcpu.vli_neural_model import (
    VLIGenerativeModelAdapter, admit_vli_neural_runtime, vli_neural_profile,
)
from mailcpu.vli_neural_session import (
    VLINeuralModelSessionBackend, bootstrap_vli_neural_model,
    encode_vli_model_turn, read_vli_model_checkpoint,
    vli_model_session_contract, vli_model_session_fingerprint,
)
from mailcpu.vli_temporal_session import read_vli_temporal_checkpoint

pytest.importorskip("vli.generative_response")
pytest.importorskip("experiments.model_fabric.slice_ground")
from vli.generative_response import GeneratedModelGround, GenerativeConversation

SLICE = (
    Path(__file__).resolve().parents[1] / "original-vl64"
    / "experiments" / "model_fabric" / "datasets"
    / "2026-11-18-pretrained-bf16-slice-ground.json"
)
GENESIS = hashlib.sha256(b"mailcpu-recovery-lineage-genesis-v1").hexdigest()


def _source():
    """Admit original pretrained observations by independent historical pin."""
    raw = SLICE.read_bytes()
    source = json.loads(raw)
    return source, source["ground_digest"]


def _compiled():
    """Build one certified observation-specific interpreter from real BF16 rows."""
    source, head = _source()
    return compile_trained_model_intention(
        source, expected_source_head=head, row_a=0, row_b=1,
    )


def _samples(compiled):
    """Construct diverse unseen Q-projection vectors from a learned direction."""
    direction = [a / compiled.denominator for a in compiled.coefficients]
    return (
        direction,
        [-v for v in direction],
        [direction[i] * (1 if i % 3 else -0.3) for i in range(len(direction))],
        [direction[i] * (-1 if i % 5 else 0.1) for i in range(len(direction))],
    )


def test_actual_original_pretrained_observation_compiles_one_model_behavior() -> None:
    """Exact BF16 Q preference, 0 remote reads, less execution than dense 4-row."""
    source, head = _source()
    model = _compiled()
    assert source["model"] == "HuggingFaceTB/SmolLM2-135M"
    assert model.source_head == head
    assert model.model_observation_bytes == 5760
    assert model.relevant_source_bytes == 3456
    assert model.width == 576
    assert model.denominator > 0 and len(model.coefficients) == 576
    assert model.ground_digest != head
    assert model == CompiledModelIntention.restore(
        model.description, expected_head=model.ground_digest,
    )

    seen_early = 0
    for hidden in _samples(model):
        report = model.observe(hidden)
        reference = original_full_four_row_projection(source, hidden, expected_source_head=head)
        assert report["sign"] == (1 if reference[0] > reference[1]
                                  else -1 if reference[0] < reference[1] else 0)
        assert model.verify_observation(hidden, report)
        assert report["new_remote_weight_bytes"] == 0
        assert report["full_four_row_projection_performed"] is False
        assert 1 <= report["observed_coordinates"] <= 576
        if report["certified_early"]:
            seen_early += 1
            assert int(report["partial_dot_squared_integer"]) > int(
                report["remaining_bound_squared_integer"]
            )
    assert seen_early >= 1


def test_intention_readout_matches_dense_original_on_held_out_states() -> None:
    """No table of input vectors: novel states use exact trained direction law."""
    source, head = _source()
    model = _compiled()
    rng = random.Random(31826)
    matched = 0
    examined = []
    for i in range(48):
        hidden = [rng.uniform(-1.0, 1.0) for _ in range(model.width)]
        out = model.observe(hidden)
        ref = original_full_four_row_projection(source, hidden, expected_source_head=head)
        delta = ref[0] - ref[1]
        if abs(delta) < 1e-9:
            continue  # FP64 reference and exact real sign have different near-tie semantics
        assert out["sign"] == (1 if delta > 0 else -1)
        assert out["source_head"] == head
        examined.append(out["observed_coordinates"])
        matched += 1
    assert matched >= 45
    assert len(examined) == matched
    assert all(1 <= x <= model.width for x in examined)


def test_canonical_model_source_and_adversarial_observation_refusal() -> None:
    """A missing trained byte, forged source root or observed decision refuses."""
    source, head = _source()
    compiled = _compiled()
    changed = copy.deepcopy(source)
    changed["revision"] = "0" * 40
    with pytest.raises(ValueError, match="identity"):
        compile_trained_model_intention(changed, expected_source_head=head)
    changed = copy.deepcopy(source)
    changed["q_payload_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        compile_trained_model_intention(changed, expected_source_head=head)
    with pytest.raises(ValueError, match="identity"):
        compile_trained_model_intention(source, expected_source_head="0" * 64)
    with pytest.raises(ValueError, match="readout rows"):
        compile_trained_model_intention(source, expected_source_head=head, row_a=1, row_b=1)
    changed_model = dict(compiled.description)
    changed_model["coefficients"] = list(changed_model["coefficients"])
    changed_model["coefficients"][0] += 1
    with pytest.raises(ValueError, match="changed"):
        CompiledModelIntention.restore(changed_model, expected_head=compiled.ground_digest)
    observation = compiled.observe(_samples(compiled)[0])
    forged = dict(observation, sign=-observation["sign"])
    with pytest.raises(ValueError, match="reconstructed"):
        compiled.verify_observation(_samples(compiled)[0], forged)
    with pytest.raises(ValueError, match="finite"):
        compiled.observe([float("nan")] * 576)
    assert compiled.observe([0.0] * 576)["sign"] == 0


def test_ecpu_intention_sufficiency_selects_pretrained_readout_not_full_projection() -> None:
    """Original E-CPU planner reduces required model output to admitted pairwise read."""
    compiled = _compiled()
    source = compiled.source_head
    candidates = _samples(compiled)
    rows = tuple(
        FiniteState.create(
            str(i), "original-trained-hidden", compiled.observe(hidden)["sign"],
            {
                "trained_pair_preference": compiled.observe(hidden)["sign"],
                "full_four_row_projection": compiled.observe(hidden)["sign"],
            },
        ) for i, hidden in enumerate(candidates)
    )
    assert len({row.target_json for row in rows}) >= 2
    ground = FiniteGround(
        compiled.ground_digest, hashlib.sha256(b"input-hidden").hexdigest(),
        hashlib.sha256(b"pairwise-q-preference").hexdigest(),
        hashlib.sha256(b"observed-four-sample-environment").hexdigest(),
        rows,
    )
    offers = (
        MeasurementCapability(
            "trained_pair_preference", compiled.ground_digest,
            "exact-pinned-readout", 3,
        ),
        MeasurementCapability(
            "full_four_row_projection", compiled.source_head,
            "original-trained-dense", 5,
        ),
    )
    authority = hashlib.sha256(b"receiver-owned-intention-capability").hexdigest()
    plan = plan_sufficiency(ground, "original-trained-hidden", offers, authority)
    assert plan["status"] == "MEASURE"
    assert plan["selected_features"] == ["trained_pair_preference"]
    assert plan["declared_cost_units"] == 3
    for hidden in candidates:
        receipt = compiled.observe(hidden)
        reading = {"trained_pair_preference": receipt["sign"]}
        resolved = resolve_sufficiency(
            ground, "original-trained-hidden", offers, authority,
            plan, reading, receipt["observation_digest"],
        )
        assert resolved["result"] == receipt["sign"]
        verify_sufficiency_resolution(
            resolved, ground, "original-trained-hidden", offers,
            authority, plan, reading, receipt["observation_digest"],
        )


def test_original_vld_compiles_new_neural_model_from_real_trained_readout_observations() -> None:
    """No prior trained network is needed for an executable observed-state machine."""
    compiled = _compiled()
    observations = [(h, compiled.observe(h)) for h in _samples(compiled)]
    description, certificate = generate_neural_ground_from_trained_observations(
        compiled, observations,
    )
    ground = GeneratedModelGround(description)
    assert ground.verify()
    assert certificate["compiled_trained_behavior_head"] == compiled.ground_digest
    assert certificate["generated_neural_weights_digest"] == ground.weights_digest
    assert certificate["observed_cells_verified"] == 8
    assert certificate["pretrained_weight_download_bytes_after_compilation"] == 0
    assert certificate["generated_hidden_units"] == 8
    for i in range(4):
        here = "observed_" + str(i)
        later = "observed_" + str((i+1)%4)
        assert ground.generated(here, "inspect") == (
            here, (observations[i][1]["sign"]+1,
                   int(observations[i][1]["certified_early"])),
        )
        assert ground.generated(here, "advance") == (
            later, (observations[(i+1)%4][1]["sign"]+1,
                    int(observations[(i+1)%4][1]["certified_early"])),
        )
    copied = json.loads(description)
    copied["metadata"]["original_pretrained_ground_head"] = "f" * 64
    changed_source = json.dumps(copied, sort_keys=True, separators=(",", ":")).encode()
    changed_ground = GeneratedModelGround(changed_source)
    assert changed_ground.manifest["ground_digest"] != ground.manifest["ground_digest"]
    assert changed_ground.weights_digest == ground.weights_digest


class Backing:
    """Real E-CPU M1 4-KiB page contract for quorum session tests."""

    page_size = 4096

    def __init__(self):
        """Preserve native M1 contents across disposed worker processes."""
        self.pages = {}

    def put_page(self, value):
        """Admit exact immutable full M1 pages."""
        assert isinstance(value, bytes) and len(value) == 4096
        head = hashlib.sha256(value).hexdigest()
        assert self.pages.setdefault(head, value) == value
        return head

    def get_page(self, head):
        """Read one content-addressed native M1 page."""
        return self.pages[head]


def _host():
    """Original source-qualified VL-I/VLD neural model M2 interpreter."""
    manifest, dep, root = admit_vli_neural_runtime()
    return LocalComputationalHost(
        host_id="independent-addressable-model-reference",
        manifest=manifest, artifact_root=root, profile=vli_neural_profile(manifest, dep),
        adapter=VLIGenerativeModelAdapter(dep),
    )


def _store(root, backing, reference):
    """Reopen original A/B/C M3 journals with no new consensus implementation."""
    membership = SeedCommitMembership(
        "addressable-trained-model-observations", 1,
        ("A", "B", "C"), "A", 1, GENESIS,
    )
    members = {
        name: RecoveryLineageAuthority(
            membership, name, root / "authorities" / (name + ".jsonl"),
        ) for name in membership.member_ids
    }
    return ComputationalSessionStore(
        root / "sessions", ComputationalObjectStore(backing, chunk_size=4096),
        RecoveryLineageCoordinator(membership, members),
        artifact_manifest_digest=reference.manifest.manifest_digest,
        backend_fingerprint=vli_model_session_fingerprint(reference),
        state_schema_id=OS_STATE_SCHEMA, state_media_type="application/json",
    )


def _real_worker(host_name, reference, identities):
    """Execute original VL-I compiled neural response in a fresh Python process."""
    def execute(operation, operation_id, arguments, context):
        """Send exact E-CPU M3 context to an admitted original neural worker."""
        command = [
            sys.executable, "-m", "mailcpu.vli_neural_worker",
        ]
        payload = {
            "schema": "mailcpu.vli-neural-model-one-shot.v1",
            "host_id": host_name,
            "context_binding_digest": context.binding_digest,
            "artifact_manifest_digest": reference.manifest.manifest_digest,
            "vld_manifest_digest": reference.profile.configuration["vld_source_digest"],
            "backend_fingerprint": reference.profile.fingerprint,
            "operation_id": operation_id,
            "session_id": context.session_id,
            "logical_time": context.logical_time,
            "operation": operation,
            "arguments": arguments,
        }
        child = subprocess.Popen(
            command, cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        identities.append(child.pid)
        output, errors = child.communicate(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(), timeout=90,
        )
        if child.returncode:
            raise RuntimeError(errors.decode(errors="replace")[-2000:])
        return json.loads(output)
    return execute


def test_compiled_trained_behavior_generates_original_neural_model_and_rehosts_via_m3(tmp_path):
    """Real observed trained model -> formed VL-I neural law -> 3 independently executed hosts."""
    compiled = _compiled()
    probes = [(h, compiled.observe(h)) for h in _samples(compiled)]
    description, formation = generate_neural_ground_from_trained_observations(
        compiled, probes,
    )
    reference = _host()
    backing = Backing()
    root = tmp_path / "model"
    initial = bootstrap_vli_neural_model(
        description, observer="ecpu-formed-from-remote-model", include_living_ground=True,
    )
    current = _store(root, backing, reference).create_session(initial)
    original_temporal = read_vli_temporal_checkpoint(initial)
    independent = GenerativeConversation(
        GeneratedModelGround(description), observer="ecpu-formed-from-remote-model",
    )
    worker_pids = []
    for i, (action, prompt) in enumerate((
        ("advance", "Follow the original observed model behavior"),
        ("inspect", "Observe newly formed trained preference state"),
        ("advance", "Continue the procedural network using retained causal identity"),
    ), start=1):
        host = "host-a" if i%2 else "host-b"
        backend = VLINeuralModelSessionBackend(
            reference, _real_worker(host, reference, worker_pids),
            active_host=host, allowed_remote_hosts=frozenset({"host-a","host-b"}),
        )
        adapter = ComputationalSessionTransitionAdapter(
            _store(root, backing, reference),
            vli_model_session_contract(reference), backend,
        )
        updated = adapter.apply(
            encode_vli_model_turn(prompt, action, views=("text", "code", "tokens")),
            operation_id=f"formed-model-{i}",
            expected_revision=current.revision,
            expected_checkpoint_digest=current.checkpoint_digest,
        )
        independent.respond(prompt, action, views=("text", "code", "tokens"))
        source, checkpoint = read_vli_model_checkpoint(updated.state_bytes)
        assert source == description
        assert checkpoint == independent.checkpoint()
        assert read_vli_temporal_checkpoint(updated.state_bytes) == original_temporal
        assert checkpoint["model_ground_digest"] == formation["generated_model_ground_digest"]
        assert updated.revision == current.revision + 1
        assert backend.remote_calls == 1
        current = updated
    assert len(set(worker_pids)) == len(worker_pids) == 3
    assert _store(root, backing, reference).load_latest().checkpoint_digest == current.checkpoint_digest
