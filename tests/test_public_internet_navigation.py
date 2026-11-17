"""INTERNET-004: read-only RFC navigation contract and negative controls."""
import base64
from dataclasses import replace
from hashlib import sha256
import copy
import json
import unittest

from mailcpu.public_internet_navigation import (
    NavigationRefused, Policy, Response, rfc_url, normalize_url,
    extract_links, navigate, verify_capsule, digest, strict_loads,
)


class MockInternet:
    def __init__(self):
        self.calls = []
        self.pages = {
            rfc_url(9293): b'<html><title>TCP</title><a href="rfc793.html">old TCP</a>'
                           b'<a href="https://evil.example/path">bad</a>'
                           b'<a href="rfc8767.html">DNS</a></html>',
            rfc_url(793): b'<html><title>TCP predecessor</title></html>',
            rfc_url(8767): b'<html><title>DNS stale</title></html>',
        }

    def __call__(self, url, *, limit, timeout):
        self.calls.append(url)
        return Response(self.pages[url], 200, "text/html; charset=utf-8")


class PublicNavigationTests(unittest.TestCase):
    def setUp(self):
        self.policy = Policy((9293,), 793, max_pages=3)
        self.internet = MockInternet()

    def test_real_structural_path_and_independent_replay(self):
        c = navigate(self.policy, self.internet)
        self.assertEqual(c["path"], [rfc_url(9293), rfc_url(793)])
        self.assertEqual(self.internet.calls, c["path"])
        self.assertEqual(verify_capsule(c, self.policy)["pages"], 2)
        self.assertNotIn("evil.example", json.dumps(c))

    def test_direct_goal(self):
        c = navigate(Policy((793,), 793), self.internet)
        self.assertEqual(c["path"], [rfc_url(793)])
        self.assertEqual(len(self.internet.calls), 1)

    def test_unreachable_does_not_become_guessed_answer(self):
        c = navigate(Policy((793,), 8767, max_pages=2), self.internet)
        self.assertEqual(c["status"], "unresolved_within_budget")
        self.assertEqual(c["path"], [])
        verify_capsule(c, Policy((793,), 8767, max_pages=2))

    def test_rfc_link_identity_alias_is_normalized_without_following_redirect(self):
        _, links = extract_links(rfc_url(9293),b'<a href="rfc793">legacy</a>')
        self.assertEqual(links,(rfc_url(793),))

    def test_injected_untrusted_link_cannot_escape_host(self):
        for href in ("https://evil.example/rfc/rfc793.html", "http://www.rfc-editor.org/rfc/rfc793.html",
                     "https://127.0.0.1/rfc/rfc793.html", "https://www.rfc-editor.org:444/rfc/rfc793.html",
                     "https://www.rfc-editor.org/rfc/../secret", "https://www.rfc-editor.org/rfc/rfc793.html?a=1"):
            with self.assertRaises(NavigationRefused):
                normalize_url(href)
        _, links = extract_links(rfc_url(9293), b'<a href="file:///etc/passwd">bad</a><a href="rfc793.html">good</a>')
        self.assertEqual(links, (rfc_url(793),))

    def test_changed_raw_bytes_refused_even_if_hash_is_recomputed(self):
        c = navigate(self.policy, self.internet)
        bad = copy.deepcopy(c)
        bad["visits"][0]["html_b64"] = base64.b64encode(b'<html><a href="rfc793.html">text modified</a></html>').decode()
        bad["visits"][0]["content_sha256"] = sha256(base64.b64decode(bad["visits"][0]["html_b64"])).hexdigest()
        bad["visits"][0]["size_bytes"] = len(base64.b64decode(bad["visits"][0]["html_b64"]))
        bad["capsule_digest"] = digest({k:v for k,v in bad.items() if k != "capsule_digest"})
        with self.assertRaisesRegex(NavigationRefused, "links or title"):
            verify_capsule(bad, self.policy)

    def test_forged_target_link_refused_even_if_rehashed(self):
        c = navigate(self.policy, self.internet)
        bad = copy.deepcopy(c)
        bad["visits"][0]["html_b64"] = base64.b64encode(b'<html><title>TCP</title></html>').decode()
        raw = base64.b64decode(bad["visits"][0]["html_b64"])
        bad["visits"][0]["content_sha256"] = sha256(raw).hexdigest()
        bad["visits"][0]["size_bytes"] = len(raw)
        bad["visits"][0]["links"] = []
        bad["capsule_digest"] = digest({k:v for k,v in bad.items() if k != "capsule_digest"})
        with self.assertRaisesRegex(NavigationRefused, "child was not linked"):
            verify_capsule(bad, self.policy)

    def test_parent_and_order_are_independently_checked(self):
        c = navigate(self.policy, self.internet)
        bad = copy.deepcopy(c)
        bad["visits"][1]["parent"] = None
        bad["capsule_digest"] = digest({k:v for k,v in bad.items() if k != "capsule_digest"})
        with self.assertRaisesRegex(NavigationRefused, "root observation"):
            verify_capsule(bad, self.policy)

    def test_independently_pinned_content_rejects_same_host_change(self):
        c = navigate(self.policy, self.internet)
        pins = {rfc_url(9293): c["visits"][0]["content_sha256"]}
        self.assertTrue(verify_capsule(c, self.policy, pinned_content_sha256=pins)["verified"])
        pins[rfc_url(9293)] = "0" * 64
        with self.assertRaisesRegex(NavigationRefused, "independent pin"):
            verify_capsule(c, self.policy, pinned_content_sha256=pins)

    def test_replayed_capsule_uses_external_pinned_identity(self):
        c = navigate(self.policy, self.internet)
        verify_capsule(c, self.policy, expected_capsule_digest=c["capsule_digest"])
        with self.assertRaisesRegex(NavigationRefused, "receiver-owned"):
            verify_capsule(c, self.policy, expected_capsule_digest="1" * 64)

    def test_strict_duplicate_json_and_nonfinite_refused(self):
        with self.assertRaises(NavigationRefused):
            strict_loads(b'{"a":1,"a":2}')
        with self.assertRaises(NavigationRefused):
            strict_loads(b'{"a": NaN}')

    def test_resource_budgets(self):
        for settings in ({"max_pages":0},{"max_depth":10},{"page_budget":100},
                         {"timeout_seconds":0},{"total_budget":100}):
            with self.subTest(settings=settings), self.assertRaises(NavigationRefused):
                Policy((9293,),793,**settings)
        with self.assertRaisesRegex(NavigationRefused, "representation"):
            navigate(Policy((9293,), 793, page_budget=4096), lambda url,**kw: Response(b'x'*4097,200,"text/html"))

    def test_redirect_and_wrong_media_type_refused(self):
        for bad in (Response(b"abc", 302, "text/html"), Response(b"abc",200,"application/json"),
                    Response(b"abc",200,"text/html","gzip")):
            with self.assertRaises(NavigationRefused):
                navigate(self.policy, lambda url,**kw: bad)

    def test_policy_change_refused(self):
        c = navigate(self.policy,self.internet)
        with self.assertRaisesRegex(NavigationRefused,"changed Ground"):
            verify_capsule(c,replace(self.policy,target=8767))


if __name__ == "__main__":
    unittest.main()
