"""Shared deterministic fixture for the VGI Transit recovery proof."""

from __future__ import annotations

from mailcpu import (
    HeadlessOS,
    HypervisorPolicy,
    LexicalDecisionModel,
    SystemIdentity,
    SystemSeed,
    SystemSeedEnvelope,
    VirtualBudget,
    VirtualLayerWorkload,
    VirtualOperatorRef,
    VirtualGroundRef,
)
from vgi import SIGNAL8_GROUND, Signal8Backend

from mailcpu import VGI_SIGNAL8_OPERATOR_ID


SYSTEM_ID = SystemIdentity("vgi-continuity-system", 1)
EXECUTOR_ID = "vgi-continuity-executor"
SEED_PURPOSE = "vgi-semantic-continuity"
NODE_ID = "node-vgi"


def configure_receiver():
    """Create the deterministic pre-admission Ground shared by sender and receiver."""
    operating_system = HeadlessOS()
    operating_system.hypervisor.classifier = LexicalDecisionModel()
    operating_system.hypervisor.policy = HypervisorPolicy(
        embedding_review_confidence=1.0
    )
    envelope = SystemSeedEnvelope(
        SYSTEM_ID,
        EXECUTOR_ID,
        SEED_PURPOSE,
        SystemSeed.from_system(operating_system),
    )
    admission = operating_system.seed_admission.admit(envelope)
    if not admission.accepted:
        raise AssertionError(f"test Ground admission failed: {admission.error}")
    return operating_system, envelope


def make_vgi_task() -> dict[str, object]:
    """Build a typed expression that adds two signals, then selects by identity."""
    return {
        "name": "add-then-select",
        "inputs": ["input.a", "input.b"],
        "outputs": [
            {
                "label": "selected",
                "expression": {
                    "type": "if",
                    "guard": {
                        "type": "is_identity",
                        "value": {
                            "type": "add",
                            "left": {"type": "input", "address": "input.a"},
                            "right": {"type": "input", "address": "input.b"},
                        },
                        "tolerance_rad": 1e-8,
                    },
                    "when_true": {"type": "input", "address": "input.b"},
                    "when_false": {"type": "input", "address": "input.a"},
                },
            }
        ],
    }


def make_vgi_workload() -> VirtualLayerWorkload:
    """Build the portable task envelope bound to the admitted system and Signal8 Grounds."""
    operating_system, envelope = configure_receiver()
    backend = Signal8Backend()
    initial_memory = {
        "input.a": backend.encode_symbol(3, observer=1).to_dict(),
        "input.b": backend.encode_symbol(5, observer=3).to_dict(),
    }
    request = {
        "schema": "vgi.signal8.request.v1",
        "ground_fingerprint": SIGNAL8_GROUND.fingerprint,
        "task": make_vgi_task(),
        "initial_memory": initial_memory,
        "max_steps": 128,
    }
    return VirtualLayerWorkload(
        workload_id="vgi-semantic-continuity-001",
        system=SYSTEM_ID,
        ground=VirtualGroundRef.from_envelope(envelope),
        intention={"goal": {"kind": "execute-vgi-task"}},
        operators=(VirtualOperatorRef(VGI_SIGNAL8_OPERATOR_ID, 1, "cpu"),),
        input_value=request,
        budget=VirtualBudget(
            max_energy=100_000,
            max_bytes=1_000_000,
            max_virtual_ticks=1_000,
        ),
        logical_time=7,
        eligible_nodes=(NODE_ID,),
        max_hops=2,
    )
