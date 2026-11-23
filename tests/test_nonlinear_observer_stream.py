"""NCR-STREAM-003: nonaffine Boolean stream count and indexed observation tests.

The foreign NCR source is installed at a receiver-pinned Git revision by the
dedicated workflow. These tests refuse a missing external verifier in that CI.
"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import unittest

from mailcpu.nonlinear_observer_stream import (
    NCRConditionalObserverStream,
    NonlinearEmittedEvent,
    NonlinearStreamReceipt,
    admit_ncr_stream_ground,
    verify_nonlinear_stream_receipt,
)
from mailcpu.substrate_bootstrap import BootstrapRefused

try:
    from navigable_compute.nonlinear_koopman import (
        PolynomialInvariants,
        construct_polynomial_laws,
        construct_koopman_ground,
        navigate_nonlinear,
    )
    from navigable_compute.nonlinear_koopman_verify import (
        verify_koopman_ground, verify_nonlinear_result,
    )
    from navigable_compute.nonlinear_koopman_wire import encode_nonlinear
    NCR_AVAILABLE = True
except ImportError:
    NCR_AVAILABLE = False

PINNED_SOURCE = "559a1a813012d13ed37c04e2a117467e34ed3cb1"


def build_packet(*, width: int = 4):
    """Construct a real nonlinear source with a permanent Boolean observer bit."""

    if width not in (4, 128):
        raise ValueError("test requires 4-bit or 128-bit source")
    # The first four coordinates have a ranked dependency with the quadratic
    # interaction x1*x2 -> x0; the remaining bits are protected and preserved.
    tiers = (0, 1, 1, 2) + (-1,) * (width - 4)
    inputs = ((1, 2), (3,), (3,), ()) + ((),) * (width - 4)
    source = PolynomialInvariants(
        width, tiers, tuple(range(width)), inputs, 2,
        ((1,), (0,), (1 << (width - 1),)),
    )
    prototype = construct_polynomial_laws(source, (0,))
    # Set every eligible coefficient to get the nonlinear interaction.
    full = (1 << len(prototype.coefficient_orbits)) - 1
    family = construct_polynomial_laws(source, (full, 0))
    ground = construct_koopman_ground(family)
    assert verify_koopman_ground(family, ground)
    # Last protected bit remains high in the 128-bit case. The constant
    # observer remains high in both cases, making infinite emission valid.
    initial = 15 | ((1 << (width - 1)) if width == 128 else 0)
    raw = encode_nonlinear(family, ground)
    return family, ground, initial, raw


@unittest.skipUnless(NCR_AVAILABLE, "external NCR source only available in pinned workflow")
class TestNCRConditionalObserverStream(unittest.TestCase):
    """Receiver-owned source pin, finite transient, infinite tail and independent proofs."""

    @classmethod
    def setUpClass(cls):
        """Mathematics: create a source once for independent tests at one fixed revision."""

        cls.family, cls.ground, cls.initial, cls.raw = build_packet()
        cls.digest = sha256(cls.raw).hexdigest()
        cls.admitted = admit_ncr_stream_ground(
            cls.raw, receiver_expected_sha256=cls.digest,
            source_commit=PINNED_SOURCE,
        )

    def observer(self, *, gate_bit=None, value_bit=0, word=(0,)):
        """Mathematics: construct a conditional output Ground with exact source semantics."""

        return NCRConditionalObserverStream(
            self.admitted, initial=self.initial, word=word,
            gate_bit=gate_bit, value_bit=value_bit, mailbox="mailcpu.observed",
        )

    def test_true_nonaffine_source_is_verified_without_state_enumeration(self):
        """Mathematics: a quadratic Boolean interaction is not an affine GF2 source map."""

        operator = self.family.operators[0]
        left, right = 1 << 1, 1 << 2
        # A GF(2) affine map would have zero second Boolean derivative.
        second_difference = (
            operator.apply(left | right)
            ^ operator.apply(left)
            ^ operator.apply(right)
            ^ operator.apply(0)
        ) & 1
        self.assertEqual(second_difference, 1)
        self.assertGreaterEqual(self.admitted.feature_dimension, 2)

    def test_every_requested_output_agrees_with_original_nonlinear_source(self):
        """Mathematics: both observer-value and event-time addresses match direct source transitions."""

        oracle = self.observer()
        self.assertIsNone(oracle.length())
        current = self.initial
        for t in range(1, 60):
            current = self.family.operators[0].apply(current)
            expected = self.family.project_observer(current) & 1
            event = oracle.event(t - 1)
            self.assertEqual((event.index, event.iteration, event.value), (t - 1, t, expected))
            upstream = navigate_nonlinear(self.family, self.ground, self.initial, (0,), t)
            self.assertTrue(verify_nonlinear_result(self.family, self.ground, upstream))
            self.assertEqual(expected, int(upstream.observed_decimal) & 1)

    def test_conditional_count_matches_independent_state_observation(self):
        """Mathematics: the kth gated event is selected without replaying k source words."""

        oracle = self.observer(gate_bit=0, value_bit=1)
        # Rank-draining source has no active bits after its certified horizon.
        self.assertIsNotNone(oracle.length())
        state = self.initial
        recorded = []
        for iteration in range(1, 20):
            state = self.family.operators[0].apply(state)
            if self.family.project_observer(state) & 1:
                recorded.append((iteration, 1))
        self.assertEqual(oracle.length(), len(recorded))
        for i, (iteration, value) in enumerate(recorded):
            event = oracle.event(i)
            self.assertEqual((event.iteration, event.value), (iteration, value))
        with self.assertRaises(IndexError):
            oracle.event(len(recorded))
        # A constantly false observer gate returns an empty finite stream.
        empty = self.observer(gate_bit=2)
        self.assertEqual(empty.length(), 0)
        with self.assertRaises(IndexError):
            empty.event(0)

    def test_two_action_word_and_state_settling(self):
        """Mathematics: rank bound counts source actions rather than observer query count."""

        observer = self.observer(gate_bit=1, value_bit=0, word=(0, 1))
        self.assertEqual(observer.stabilization_iteration, 2)
        self.assertIsNone(observer.length())
        state = self.initial
        for iteration in range(1, 22):
            for step in (0, 1):
                state = self.family.operators[step].apply(state)
            result = observer.event(iteration - 1)
            self.assertEqual(result.iteration, iteration)
            self.assertEqual(result.value, self.family.project_observer(state) & 1)

    def test_astronomical_event_is_addressable_and_independently_rebuilt(self):
        """Mathematics: a 10^100th emission uses feature power and bounded transient only."""

        observer = self.observer(gate_bit=1, value_bit=0)
        index = 10**100 + 17
        event = observer.event(index)
        self.assertEqual(event.iteration, index + 1)
        self.assertEqual(event.value, 0)
        receipt = observer.issue_receipt(index)
        self.assertEqual(receipt.event, event)
        self.assertTrue(verify_nonlinear_stream_receipt(
            receipt, packet=self.raw, receiver_expected_sha256=self.digest,
            source_commit=PINNED_SOURCE,
        ))
        restored = NonlinearStreamReceipt.from_snapshot(
            json.loads(json.dumps(receipt.snapshot()))
        )
        self.assertEqual(receipt, restored)
        self.assertEqual(receipt.digest, restored.digest)

    def test_reject_fabricated_emission_and_rehashed_receipt(self):
        """Mathematics: SHA self-consistency cannot replace receiver-source reconstruction."""

        observer = self.observer(gate_bit=1)
        legit = observer.issue_receipt(10)
        fraud = replace(legit, event=replace(legit.event, value=1))
        self.assertNotEqual(fraud.digest, legit.digest)
        self.assertFalse(verify_nonlinear_stream_receipt(
            fraud, packet=self.raw, receiver_expected_sha256=self.digest,
            source_commit=PINNED_SOURCE,
        ))
        self.assertFalse(verify_nonlinear_stream_receipt(
            legit, packet=self.raw, receiver_expected_sha256=self.digest,
            source_commit="0" * 40,
        ))
        tampered = legit.snapshot()
        tampered["event"]["iteration"] = "0x000c"
        with self.assertRaises(BootstrapRefused):
            NonlinearStreamReceipt.from_snapshot(tampered)
        unknown = legit.snapshot()
        unknown["authorization"] = "claimed"
        with self.assertRaises(BootstrapRefused):
            NonlinearStreamReceipt.from_snapshot(unknown)
        false_word = replace(legit, word=(1,))
        self.assertFalse(verify_nonlinear_stream_receipt(
            false_word, packet=self.raw, receiver_expected_sha256=self.digest,
            source_commit=PINNED_SOURCE,
        ))

    def test_reject_modified_source_or_unpinned_verifier(self):
        """Mathematics: packet bytes and exact source revision are receiver-owned pins."""

        with self.assertRaises(BootstrapRefused):
            admit_ncr_stream_ground(
                self.raw + b" ", receiver_expected_sha256=self.digest,
                source_commit=PINNED_SOURCE,
            )
        with self.assertRaises(BootstrapRefused):
            admit_ncr_stream_ground(
                self.raw, receiver_expected_sha256=self.digest,
                source_commit="moving-main",
            )
        with self.assertRaises(BootstrapRefused):
            NCRConditionalObserverStream(
                self.admitted, initial=1 << self.admitted.source_width,
            )
        with self.assertRaises(BootstrapRefused):
            self.observer(gate_bit=10)
        with self.assertRaises(BootstrapRefused):
            NCRConditionalObserverStream(
                self.admitted, initial=self.initial, max_transient_iterations=0,
            )

    def test_128bit_state_does_not_require_2_pow_128_enumeration(self):
        """Mathematics: huge source cardinality can retain a compact nonlinear observer law."""

        family, ground, initial, raw = build_packet(width=128)
        digest = sha256(raw).hexdigest()
        admitted = admit_ncr_stream_ground(
            raw, receiver_expected_sha256=digest, source_commit=PINNED_SOURCE,
        )
        self.assertEqual(admitted.source_width, 128)
        self.assertLessEqual(admitted.feature_dimension, 16)
        observer = NCRConditionalObserverStream(
            admitted, initial=initial, gate_bit=1, value_bit=2,
        )
        last = observer.issue_receipt(10**100 + 173)
        self.assertEqual(last.event.value, 1)  # protected bit 127 never changes
        self.assertTrue(verify_nonlinear_stream_receipt(
            last, packet=raw, receiver_expected_sha256=digest,
            source_commit=PINNED_SOURCE,
        ))


if __name__ == "__main__":
    unittest.main()
