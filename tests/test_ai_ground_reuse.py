"""AGA-002: reuse verified E-CPU realizers; never infer universal AI execution."""
from __future__ import annotations

import copy
import importlib.util
import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest
from mailcpu.ai_ground_atlas import AtlasRefused, digest, load
from mailcpu.ai_ground_reuse import (
    GroundReuseRefused, GroundReuseSession, certify_boolean, evaluate_direct,
    inspection, verify_boolean,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "mailcpu" / "ai_ground_atlas.v1.json"


def _native_available() -> bool:
    try:
        return all(importlib.util.find_spec("mailcpu." + x) is not None for x in (
            "weight_space", "observer_orbit", "interpreter", "semantic_translation"))
    except ModuleNotFoundError:
        return False


native = pytest.mark.skipif(not _native_available(), reason="full E-CPU runtime unavailable locally")


def atlas():
    return load(CATALOG)


def _reseal(v):
    v["catalog_digest"] = digest({k: value for k, value in v.items() if k != "catalog_digest"})
    return v


def test_direct_semantics_are_exact_on_exhaustive_domain():
    for gate in ("xor", "and"):
        for x, y in itertools.product((0, 1), repeat=2):
            assert evaluate_direct(gate, x, y) == ((x ^ y) if gate == "xor" else (x & y))


@pytest.mark.parametrize("gate", ["or", "attention", "model.compile", "", 0, None])
def test_unknown_operators_refused_without_implicit_emulation(gate):
    with pytest.raises(GroundReuseRefused):
        evaluate_direct(gate, 0, 1)


@pytest.mark.parametrize("pair", [(2, 0), (1, -1), (True, 0), (0, False), (0.1, 1), (0, "1")])
def test_domain_deviation_refused(pair):
    with pytest.raises(GroundReuseRefused, match="Boolean domain"):
        evaluate_direct("xor", *pair)


def test_unknown_catalog_target_refuses():
    with pytest.raises(AtlasRefused, match="unrecognized"):
        inspection(atlas(), "forward.general_llm")


def test_untrusted_certificate_rejected_without_running_a_model():
    with pytest.raises(GroundReuseRefused, match="missing or extra"):
        verify_boolean(atlas(), {"gate": "xor"})


@native
@pytest.mark.parametrize("gate", ["xor", "and"])
def test_native_e_cpu_already_provides_two_neural_and_two_interpreter_realizations(gate):
    certificate = certify_boolean(atlas(), gate)
    assert certificate == verify_boolean(atlas(), certificate)
    assert certificate["catalog_ground"] == "model.compile"
    assert certificate["admission"] == "not_a_hypervisor_grant_or_general_ai_ground"
    assert len(certificate["models"]) == 2
    assert all(m["parameters"] == 10000 for m in certificate["models"])
    assert certificate["models"][0]["weight_digest"] != certificate["models"][1]["weight_digest"]
    assert len(certificate["observations"]) == 4
    assert all(len(set((x["expected"], *x["neural_outputs"], x["reference_interpreter"],
                            x["queued_interpreter"]))) == 1 for x in certificate["observations"])


@native
def test_query_is_native_e_cpu_observer_receipt_over_direct_semantic_ground():
    from mailcpu.observer_orbit import ObserverContract, ObserverReceipt, verify_observer_receipt
    cat = atlas()
    session = GroundReuseSession(cat, certify_boolean(cat, "xor"))
    for x, y in itertools.product((0, 1), repeat=2):
        result = session.query(x, y, request_id=f"test-xor-{x}-{y}")
        assert result["result"] == x ^ y
        assert result["neural_forward_evaluations_this_query"] == 0
        assert result["method"] == "exact_direct_semantic_ground"
        contract = ObserverContract.from_dict(result["observer_contract"])
        receipt = ObserverReceipt.from_dict(result["observer_receipt"])
        assert verify_observer_receipt(contract, receipt)
        assert receipt.projection["value"] == result["result"]


@native
def test_reused_ground_query_does_not_reenter_any_neural_model(monkeypatch):
    from mailcpu import weight_space
    cat = atlas()
    session = GroundReuseSession(cat, certify_boolean(cat, "and"))
    monkeypatch.setattr(weight_space, "compile_boolean_gate", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("network recompiled during direct query")))
    assert session.query(1, 1, request_id="no-network-work")["result"] == 1
    assert session.query(0, 1, request_id="still-no-network-work")["result"] == 0


@native
def test_rehashed_false_certificate_is_refused_by_independent_verification():
    cat = atlas()
    cert = certify_boolean(cat, "xor")
    manipulated = copy.deepcopy(cert)
    manipulated["observations"][1]["expected"] ^= 1
    manipulated["certificate_digest"] = digest({k: v for k, v in manipulated.items() if k != "certificate_digest"})
    with pytest.raises(GroundReuseRefused, match="independently executed"):
        verify_boolean(cat, manipulated)


@native
def test_certificate_does_not_follow_changed_atlas_or_source_pin():
    cat = atlas()
    cert = certify_boolean(cat, "xor")
    mutated = copy.deepcopy(cat)
    mutated["sources"]["ECPU"]["ref"] = "a" * 40
    _reseal(mutated)
    with pytest.raises(GroundReuseRefused, match="atlas identity"):
        verify_boolean(mutated, cert)


@native
def test_source_anchor_is_mandatory_for_known_realization():
    cat = atlas()
    changed = copy.deepcopy(cat)
    entry = next(x for x in changed["entries"] if x["id"] == "model.compile")
    entry["source_anchors"].remove("ECPU:mailcpu/weight_space.py")
    _reseal(changed)
    with pytest.raises(GroundReuseRefused, match="source anchor"):
        certify_boolean(changed, "xor")


@native
def test_unknown_full_attention_does_not_become_executable_from_catalog():
    result = inspection(atlas(), "forward.attention")
    assert not result["execution_admitted"]
    assert result["proven_reuse_recipe"] is None
    assert result["status"] == "no_general_execution_claim"
    with pytest.raises(GroundReuseRefused, match="not known"):
        inspection(atlas(), "forward.attention", gate="xor")


@native
def test_cli_certificate_is_reconstructible_in_a_new_process(tmp_path):
    cert_path = tmp_path / "cert.json"
    cmd = [sys.executable, "-m", "mailcpu.ai_ground_reuse"]
    p = subprocess.run(cmd + ["certify", "xor", "--output", str(cert_path), "--catalog", str(CATALOG)],
                       cwd=ROOT, text=True, capture_output=True)
    assert p.returncode == 0, p.stderr
    p = subprocess.run(cmd + ["query", "--certificate", str(cert_path), "--left", "1", "--right", "0",
                              "--catalog", str(CATALOG)], cwd=ROOT, text=True, capture_output=True)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["result"] == 1
    p = subprocess.run(cmd + ["query", "--certificate", str(cert_path), "--left", "3", "--right", "0",
                              "--catalog", str(CATALOG)], cwd=ROOT, text=True, capture_output=True)
    assert p.returncode != 0
