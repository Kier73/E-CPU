"""SAB-009 active installation and semantic continuity across code substrates."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from mailcpu.active_host_formation import (
    FormationPolicy, FormationRefused, FormedGroundRealizer,
    LocalInterpreterSurface, SeedManifest, actively_form, compile_seed,
)
from mailcpu.ground_native_realization import (
    AffineGround, GroundIntention, RealizationPolicy, RealizationRefused,
    equivalent_observations, verify_receipt, realize_under_contract,
)

GROUND = AffineGround(5, 7, 65521, 19)
OTHER_GROUND = AffineGround(3, 8, 65521, 19)
COORD = 10**12 + 913


def policy(surface_id: str, engine: str) -> FormationPolicy:
    return FormationPolicy(frozenset({(surface_id, engine)}), COORD + 1000)


def observation_policy(surface_id: str, engine: str) -> RealizationPolicy:
    return RealizationPolicy(frozenset({(surface_id, "formed." + engine)}), COORD + 1000)


class ActiveFormationTests(unittest.TestCase):
    """One receiving surface gains an E-CPU capability by explicit installation."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ecpu-sab009-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def surface(self, engine="python", surface_id="unformed-host"):
        folder = self.root / surface_id
        folder.mkdir(exist_ok=True)
        exe = sys.executable if engine == "python" else shutil.which("node")
        if exe is None:
            self.skipTest("node 22 runtime unavailable")
        return LocalInterpreterSurface(surface_id, engine, folder, exe)

    def form(self, engine="python", surface_id="unformed-host"):
        surface = self.surface(engine, surface_id)
        rights = policy(surface_id, engine)
        return actively_form(surface, GROUND, rights, coordinate=COORD)

    def test_blank_receiver_is_actively_formed(self):
        surface = self.surface()
        self.assertEqual(list(surface.directory.iterdir()), [])
        formed = actively_form(surface, GROUND, policy(surface.surface_id, "python"), coordinate=COORD)
        self.assertEqual(sorted(p.name for p in surface.directory.iterdir()),
                         ["ecpu-seed-manifest.json", "ecpu-seed.py"])
        receipt = realize_under_contract(formed, GroundIntention("first", GROUND, COORD),
                                         observation_policy(surface.surface_id, "python"))
        self.assertEqual(receipt.payload["output"], {"value": 46511})
        self.assertTrue(receipt.payload["evidence"]["runtime_installed_by_receiver"])

    @unittest.skipUnless(shutil.which("node"), "Node interpreter is required")
    def test_python_and_javascript_are_distinct_formations_with_one_ground(self):
        py = self.form("python", "host-py")
        js = self.form("javascript", "host-js")
        request = GroundIntention("cross-engine", GROUND, COORD)
        py_policy = observation_policy("host-py", "python")
        js_policy = observation_policy("host-js", "javascript")
        a = realize_under_contract(py, request, py_policy)
        b = realize_under_contract(js, request, js_policy)
        self.assertEqual((a.payload["output"], b.payload["output"]),
                         ({"value": 46511}, {"value": 46511}))
        self.assertNotEqual(py.manifest.source_sha256, js.manifest.source_sha256)
        self.assertTrue(equivalent_observations((a, b), request,
                        {py.method: py_policy, js.method: js_policy}))
        self.assertNotEqual(a.payload["evidence_digest"], b.payload["evidence_digest"])

    @unittest.skipUnless(shutil.which("node"), "Node interpreter is required")
    def test_large_coordinate_remains_exact_in_javascript_bigint(self):
        target = self.form("javascript", "host-js")
        request = GroundIntention("very-far", GROUND, 10**18)
        # A new policy with a higher coordinate is intentionally a different grant.
        form = FormationPolicy(frozenset({("host-js", "javascript")}), 10**18)
        with self.assertRaises(FormationRefused):
            target.formation_policy.permits("host-js", "javascript", 10**18)
        # The same compiled code can realize the larger coordinate under a fresh
        # separate formation, provided that changed authorization is installed.
        folder = self.root / "host-js2"
        folder.mkdir()
        surface = LocalInterpreterSurface("host-js2", "javascript", folder, shutil.which("node"))
        formed = actively_form(surface, GROUND,
                FormationPolicy(frozenset({("host-js2", "javascript")}), 10**18),
                coordinate=10**18)
        receipt = formed.observe(request, RealizationPolicy(frozenset({("host-js2", formed.method)}), 10**18))
        verify_receipt(receipt, request, RealizationPolicy(frozenset({("host-js2", formed.method)}), 10**18))

    def test_reconstructed_host_retains_exact_installed_identity(self):
        original = self.form()
        intended = GroundIntention("restart", GROUND, COORD)
        before = original.observe(intended, observation_policy("unformed-host", "python"))
        reopened = self.surface()
        # A fresh controller + fresh Python process reuses the immutable seed.
        restored = actively_form(reopened, GROUND, policy("unformed-host", "python"), coordinate=COORD)
        after = restored.observe(intended, observation_policy("unformed-host", "python"))
        self.assertEqual(before.fingerprint, after.fingerprint)
        self.assertEqual(original.manifest.fingerprint, restored.manifest.fingerprint)

    def test_active_formation_refuses_non_granted_receiver_before_staging(self):
        surface = self.surface()
        with self.assertRaises(FormationRefused):
            actively_form(surface, GROUND,
                FormationPolicy(frozenset({("other-host", "python")}), COORD + 1000), coordinate=COORD)
        self.assertEqual(list(surface.directory.iterdir()), [])

    def test_formation_lease_expires_without_executing(self):
        surface = self.surface()
        with self.assertRaises(FormationRefused):
            actively_form(surface, GROUND,
                FormationPolicy(frozenset({("unformed-host", "python")}), COORD - 1),
                coordinate=COORD)
        self.assertEqual(list(surface.directory.iterdir()), [])

    def test_formation_budget_refuses_installation(self):
        surface = self.surface()
        with self.assertRaises(FormationRefused):
            actively_form(surface, GROUND,
                FormationPolicy(frozenset({("unformed-host", "python")}), COORD + 1000,
                                max_seed_bytes=512), coordinate=COORD)
        self.assertEqual(list(surface.directory.iterdir()), [])

    def test_tampered_staged_program_is_refused_before_execution(self):
        formed = self.form()
        code = formed.surface._source_path
        code.write_bytes(code.read_bytes() + b"\n# changed\n")
        with self.assertRaises(FormationRefused):
            formed.observe(GroundIntention("tampered", GROUND, COORD),
                           observation_policy("unformed-host", "python"))

    def test_tampered_staged_manifest_is_refused(self):
        formed = self.form()
        stored = formed.surface._manifest_path
        payload = json.loads(stored.read_text())
        payload["ground"] = "1" * 64
        stored.write_text(json.dumps(payload))
        with self.assertRaises(FormationRefused):
            formed.observe(GroundIntention("tampered-manifest", GROUND, COORD),
                           observation_policy("unformed-host", "python"))

    def test_reimposition_of_conflicting_ground_is_refused(self):
        first = self.form()
        with self.assertRaises(FormationRefused):
            actively_form(first.surface, OTHER_GROUND, policy("unformed-host", "python"), coordinate=COORD)
        observation = first.observe(GroundIntention("old-ground", GROUND, COORD),
                                    observation_policy("unformed-host", "python"))
        self.assertEqual(observation.payload["output"]["value"], 46511)

    def test_data_reception_without_execution_is_not_formable(self):
        class DataOnlyReceiver:
            surface_id = "bytes-only"
            engine = "python"
            received = None
            def stage(self, manifest, source):
                self.received = source
            def activate(self, manifest, request, *, timeout, max_bytes):
                raise FormationRefused("no interpreter or executable transition")
        receiver = DataOnlyReceiver()
        with self.assertRaises(FormationRefused):
            actively_form(receiver, GROUND, policy("bytes-only", "python"), coordinate=COORD)
        self.assertTrue(receiver.received)

    def test_receiver_advertisement_cannot_change_execution_method(self):
        formed = self.form()
        wrong = RealizationPolicy(frozenset({("unformed-host", "formed.javascript")}), COORD + 1000)
        with self.assertRaises(RealizationRefused):
            formed.observe(GroundIntention("wrong-engine", GROUND, COORD), wrong)

    def test_formed_host_refuses_unrelated_ground(self):
        formed = self.form()
        with self.assertRaises(FormationRefused):
            formed.observe(GroundIntention("ground-swap", OTHER_GROUND, COORD),
                           observation_policy("unformed-host", "python"))

    def test_initial_seed_installation_is_immutable_and_idempotent(self):
        formed = self.form()
        source = formed.surface._source_path.read_bytes()
        formed.surface.stage(formed.manifest, source)
        self.assertEqual(formed.surface._source_path.read_bytes(), source)
        with self.assertRaises(FormationRefused):
            formed.surface.stage(replace(formed.manifest, source_sha256="f"*64), source)

    def test_malformed_formation_authority_is_rejected(self):
        with self.assertRaises(FormationRefused):
            FormationPolicy(frozenset({("abc", "arbitrary-source")}), COORD)
        with self.assertRaises(FormationRefused):
            FormationPolicy(frozenset({("abc", "python")}), True)

    def test_source_generator_is_deterministic_and_not_host_specific(self):
        source = compile_seed(GROUND, "python")
        self.assertEqual(source, compile_seed(GROUND, "python"))
        self.assertNotEqual(source, compile_seed(OTHER_GROUND, "python"))
        self.assertNotIn(b"unformed-host", source)
        self.assertNotIn(b"site-packages", source)


if __name__ == "__main__":
    unittest.main()