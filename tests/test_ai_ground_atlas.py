"""Non-authoritative, source-pinned AI Ground descriptions: coverage and refusal gates."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mailcpu.ai_ground_atlas import (
    AtlasRefused, canonical, dependency_closure, digest, find, load, validate,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "mailcpu" / "ai_ground_atlas.v1.json"


def reseal(value: dict) -> dict:
    clone = copy.deepcopy(value)
    clone["catalog_digest"] = digest({k: v for k, v in clone.items() if k != "catalog_digest"})
    return clone


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load(CATALOG)

    def test_all_eight_ai_workflow_stages_are_present_and_open_world(self):
        doc = self.catalog
        self.assertTrue(doc["open_world"])
        self.assertEqual(set(doc["stages"]), {e["stage"] for e in doc["entries"]})
        self.assertGreaterEqual(len(doc["entries"]), 80)
        self.assertEqual(len({e["id"] for e in doc["entries"]}), len(doc["entries"]))
        self.assertEqual(self.catalog["schema"], "mailcpu.ai-ground-atlas.v1")

    def test_all_candidates_are_catalogued_not_automatically_admitted(self):
        self.assertTrue(all(x["ground_admission"] == "catalogued_only" for x in self.catalog["entries"]))
        self.assertTrue(all(x["realization_status"] in {"mainline_scoped", "research_scoped", "candidate"}
                            for x in self.catalog["entries"]))
        self.assertTrue(any(x["realization_status"] == "candidate" for x in self.catalog["entries"]))

    def test_model_scale_does_not_change_ground_name_or_meaning(self):
        for key in ("model.parameters", "model.tensor", "forward.moe_route", "forward.moe_expert",
                    "forward.kv_cache", "forward.autoregressive"):
            self.assertEqual(find(self.catalog, key)["ground_admission"], "catalogued_only")
        self.assertIn("tensor", find(self.catalog, "model.parameters")["representation"].lower())

    def test_dependency_closure_covers_model_neural_training_and_agent_workflows(self):
        for key, ancestor in (("forward.moe_expert", "model.parameters"),
                              ("learn.checkpoint", "learn.objective"),
                              ("agent.tool", "ground.authority"),
                              ("operate.session", "forward.autoregressive"),
                              ("operate.recovery", "ground.lineage")):
            with self.subTest(key=key):
                closure = dependency_closure(self.catalog, key)
                self.assertIn(ancestor, closure)
                self.assertEqual(closure[-1], key)
                self.assertEqual(len(closure), len(set(closure)))

    def test_distinct_effect_classes_do_not_grant_authority(self):
        for key in ("agent.tool", "data.privacy", "operate.policy"):
            self.assertEqual(find(self.catalog, key)["effect_class"], "effectful")
            self.assertEqual(find(self.catalog, key)["ground_admission"], "catalogued_only")

    def test_missing_ground_refuses(self):
        with self.assertRaisesRegex(AtlasRefused, "unrecognized"):
            find(self.catalog, "forward.unknown")

    def test_digest_checks_canonical_pinned_record(self):
        clone = copy.deepcopy(self.catalog)
        clone["entries"][0]["name"] = "modified"
        with self.assertRaisesRegex(AtlasRefused, "digest disagrees"):
            validate(clone)
        self.assertEqual(validate(reseal(clone))["entries"][0]["name"], "modified")

    def test_duplicate_id_refuses_even_with_recomputed_catalog_digest(self):
        clone = copy.deepcopy(self.catalog)
        clone["entries"].append(copy.deepcopy(clone["entries"][0]))
        with self.assertRaisesRegex(AtlasRefused, "duplicate Ground"):
            validate(reseal(clone))

    def test_implicit_admission_refuses_even_with_recomputed_hash(self):
        clone = copy.deepcopy(self.catalog)
        clone["entries"][0]["ground_admission"] = "admitted"
        with self.assertRaisesRegex(AtlasRefused, "may not assert admitted"):
            validate(reseal(clone))

    def test_unknown_dependency_refuses(self):
        clone = copy.deepcopy(self.catalog)
        clone["entries"][0]["dependencies"] = ["ground.unknown"]
        with self.assertRaisesRegex(AtlasRefused, "unresolved Ground"):
            validate(reseal(clone))

    def test_dependency_cycle_refuses(self):
        clone = copy.deepcopy(self.catalog)
        clone["entries"][0]["dependencies"] = ["ground.observer"]
        with self.assertRaisesRegex(AtlasRefused, "cyclic"):
            validate(reseal(clone))

    def test_unsafe_source_path_refuses(self):
        clone = copy.deepcopy(self.catalog)
        clone["entries"][0]["source_anchors"][0] = "ECPU:../../private"
        with self.assertRaisesRegex(AtlasRefused, "unsafe/unknown"):
            validate(reseal(clone))

    def test_invalid_source_revision_refuses(self):
        clone = copy.deepcopy(self.catalog)
        clone["sources"]["ECPU"]["ref"] = "main"
        with self.assertRaisesRegex(AtlasRefused, "exact commit"):
            validate(reseal(clone))

    def test_research_claims_require_research_source(self):
        clone = copy.deepcopy(self.catalog)
        clone["entries"][0]["realization_status"] = "research_scoped"
        with self.assertRaisesRegex(AtlasRefused, "without a research anchor"):
            validate(reseal(clone))

    def test_duplicate_json_keys_refuse(self):
        with tempfile.TemporaryDirectory() as temp:
            malformed = Path(temp) / "atlas.json"
            malformed.write_text('{"schema": "a", "schema": "b"}', encoding="utf-8")
            with self.assertRaisesRegex(AtlasRefused, "duplicate JSON key"):
                load(malformed)

    def test_cli_validate_list_and_closure(self):
        for arguments in (("validate",), ("list", "--stage", "inference"),
                          ("closure", "forward.moe_expert")):
            cmd = [sys.executable, "-m", "mailcpu.ai_ground_atlas", *arguments, "--catalog", str(CATALOG)]
            done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True)
            value = json.loads(done.stdout)
            if arguments[0] == "validate":
                self.assertEqual(value["count"], len(self.catalog["entries"]))
            elif arguments[0] == "list":
                self.assertTrue(all(x["stage"] == "inference" for x in value))
            else:
                self.assertIn("forward.moe_route", value["dependency_closure"])

    def test_native_representation_refs_bind_full_ground_and_source_revision(self):
        try:
            from mailcpu.semantic_translation import RepresentationRef
            from mailcpu.ai_ground_atlas import representation_ref
        except ImportError:
            self.skipTest("Requires full E-CPU mailcpu.semantic_translation in this environment")
        for name in ("ground.observer", "model.tensor", "forward.moe_expert", "learn.optimizer",
                     "agent.tool", "operate.recovery"):
            ref = representation_ref(self.catalog, name)
            self.assertIsInstance(ref, RepresentationRef)
            self.assertEqual(ref, representation_ref(self.catalog, name))
            self.assertEqual(len(ref.content_digest), 64)
        a = representation_ref(self.catalog, "forward.moe_expert").content_digest
        mutated = copy.deepcopy(self.catalog)
        mutated["entries"] = [dict(x, transition_relation="changed") if x["id"] == "forward.moe_expert" else x
                              for x in mutated["entries"]]
        self.assertNotEqual(a, representation_ref(mutated, "forward.moe_expert").content_digest)

    def test_mainline_source_paths_exist_in_repo(self):
        if not (ROOT / "mailcpu" / "semantic_translation.py").exists():
            self.skipTest("Full E-CPU checkout is unavailable locally")
        for entry in self.catalog["entries"]:
            for anchor in entry["source_anchors"]:
                alias, path = anchor.split(":", 1)
                if alias == "ECPU":
                    self.assertTrue((ROOT / path).is_file(), f"broken E-CPU source anchor {path}")


if __name__ == "__main__":
    unittest.main()
