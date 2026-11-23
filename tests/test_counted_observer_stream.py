"""COUNTED-004: direct finite-source checks for non-settling counted output orbits."""

from __future__ import annotations

from dataclasses import replace
import json
import random

import pytest

from mailcpu.counted_observer_stream import (
    CountedObserverStream,
    CountedStreamReceipt,
    EmitRule,
    verify_counted_stream_receipt,
)
from mailcpu.intention_formed_fabric import FiniteObserverLaw
from mailcpu.substrate_bootstrap import BootstrapRefused


def _nonlinear_feedback(state: int) -> int:
    """Mathematics: a three-bit feedback shift with a genuinely quadratic AND term."""

    b0, b1, b2 = (state >> i) & 1 for i in range(3)
    feedback = b2 ^ (b0 & b1) ^ b0
    return ((state << 1) & 7) | feedback


def feedback_source() -> FiniteObserverLaw:
    """Mathematics: enumerate the exact eight-state semantics of a nonlinear source."""

    return FiniteObserverLaw(
        tuple(f"s{i}" for i in range(8)),
        ("shift", "flip"),
        ("lo", "middle", "hi", "parity"),
        tuple((_nonlinear_feedback(i), i ^ 1) for i in range(8)),
        tuple(((i >> 0) & 1, (i >> 1) & 1, (i >> 2) & 1,
               i.bit_count() & 1) for i in range(8)),
    )


def _rules() -> tuple[EmitRule, ...]:
    """Mathematics: emit 0..multiple ordered messages after selected source actions."""

    return (
        EmitRule("always", "parity"),
        EmitRule("low.conditional", "lo", when_field="lo", when_equals=1, on_action="shift"),
        EmitRule("high.conditional", "hi", when_field="hi", when_equals=1, on_action="flip"),
    )


def _reference(
    source: FiniteObserverLaw,
    initial: str,
    word: tuple[str, ...],
    rules: tuple[EmitRule, ...],
    iterations: int,
) -> tuple[list[tuple[int, int, str, object]], list[int], list[int]]:
    """Mathematics: replay the original, unquotiented transition table step by step."""

    state = source.states.index(initial)
    emissions: list[tuple[int, int, str, object]] = []
    counts = [0]
    states = [state]
    field = {name: i for i, name in enumerate(source.fields)}
    actions = {name: i for i, name in enumerate(source.actions)}
    for iteration in range(1, iterations + 1):
        for offset, action in enumerate(word):
            state = source.transitions[state][actions[action]]
            observations = source.observations[state]
            for rule in rules:
                if rule.on_action is not None and rule.on_action != action:
                    continue
                if rule.when_field is not None:
                    actual = observations[field[rule.when_field]]
                    if type(actual) is not type(rule.when_equals) or actual != rule.when_equals:
                        continue
                emissions.append((
                    iteration, offset, rule.mailbox,
                    observations[field[rule.value_field]],
                ))
        counts.append(len(emissions))
        states.append(state)
    return emissions, counts, states


def test_genuinely_nonlinear_feedback_and_no_fixed_point() -> None:
    """Mathematics: the feedback map is not affine, and the selected orbit cycles."""

    f = _nonlinear_feedback
    assert (f(3) ^ f(1) ^ f(2) ^ f(0)) & 1 == 1
    source = feedback_source()
    stream = CountedObserverStream(
        source, initial_state="s1", word=("shift",), rules=_rules(),
    )
    assert stream.summary.period == 6
    assert stream.summary.preperiod == 0
    assert stream.summary.infinite
    assert stream.summary.period_emissions > 0
    assert stream.summary.source_digest == source.fingerprint
    assert stream.quotient_state_after(10**100) == stream.quotient_state_after(
        (10**100) % 6
    )


@pytest.mark.parametrize("word", [("shift",), ("shift", "flip"), ("flip", "shift")])
def test_repeating_nonlinear_feedback_matches_original_output_log(word: tuple[str, ...]) -> None:
    """Mathematics: exact multi-SEND event order and count agree with native raw-source replay."""

    source = feedback_source()
    stream = CountedObserverStream(source, initial_state="s1", word=word, rules=_rules())
    expected, prefix_counts, states = _reference(source, "s1", word, _rules(), 150)
    assert stream.length() is None
    assert [stream.count_after(t) for t in range(151)] == prefix_counts
    for i, (iteration, offset, mailbox, value) in enumerate(expected):
        observed = stream.event(i)
        assert (observed.index, observed.word_iteration, observed.action_offset,
                observed.mailbox, observed.value) == (i, iteration, offset, mailbox, value)
    for t in range(151):
        selected = stream.quotient_state_after(t)
        raw_state = states[t]
        for field in {rule.value_field for rule in _rules()} | {
            rule.when_field for rule in _rules() if rule.when_field is not None
        }:
            field_index = source.fields.index(field)
            output_index = stream.machine.fields.index(field)
            assert stream.machine.outputs[selected][output_index] == source.observations[raw_state][field_index]


def test_distant_conditional_event_ordinal_uses_cycle_count_not_step_count() -> None:
    """Mathematics: invert huge event counts without iterating 10^100 source actions."""

    source = feedback_source()
    rules = (
        EmitRule("conditional.low", "lo", when_field="lo", when_equals=1),
        EmitRule("conditional.high", "hi", when_field="hi", when_equals=1),
    )
    stream = CountedObserverStream(source, initial_state="s1", word=("shift",), rules=rules)
    summary = stream.summary
    assert summary.period == 6 and 0 < summary.period_emissions < summary.period * len(rules)
    direct, _, _ = _reference(source, "s1", ("shift",), rules, summary.period)
    assert len(direct) == summary.period_emissions
    k = 10**100 + 73
    periods, position = divmod(k, len(direct))
    expected = direct[position]
    selected = stream.event(k)
    assert selected.index == k
    assert (selected.word_iteration, selected.action_offset,
            selected.mailbox, selected.value) == (
                expected[0] + periods * summary.period, *expected[1:],
            )
    # C(F^n(x)) is now exact even for a distant n, not a short-window fit.
    n = 10**100 + 17
    whole, remainder = divmod(n, summary.period)
    _, counts, _ = _reference(source, "s1", ("shift",), rules, summary.period)
    assert stream.count_after(n) == (
        whole * summary.period_emissions + counts[remainder]
    )
    receipt = stream.issue_receipt(k)
    assert verify_counted_stream_receipt(
        receipt, source, expected_request=stream.request(k),
    )


def test_finite_transient_outputs_followed_by_silent_nontrivial_cycle() -> None:
    """Mathematics: finite output length is compatible with an infinite non-settling source."""

    source = FiniteObserverLaw(
        ("s0", "s1", "s2", "s3"),
        ("advance",),
        ("value", "transient"),
        ((1,), (2,), (3,), (2,)),
        ((0, 0), (1, 1), (2, 0), (3, 0)),
    )
    rules = (EmitRule(
        "once", "value", when_field="transient", when_equals=1,
    ),)
    stream = CountedObserverStream(
        source, initial_state="s0", word=("advance",), rules=rules,
    )
    assert stream.summary.preperiod == 2
    assert stream.summary.period == 2
    assert stream.summary.period_emissions == 0
    assert stream.length() == 1
    assert stream.event(0).word_iteration == 1
    assert stream.event(0).value == 1
    assert stream.count_after(10**200) == 1
    with pytest.raises(IndexError):
        stream.event(1)


def test_quotient_removes_unobservable_internal_bits() -> None:
    """Mathematics: preserve future observation while dropping unnecessary source identity."""

    source = FiniteObserverLaw(
        tuple(f"s{i}" for i in range(8)),
        ("advance",),
        ("low", "hidden"),
        tuple((((i + 1) & 3) + (i & 4),) for i in range(8)),
        tuple(((i & 3), ((i >> 2) & 1)) for i in range(8)),
    )
    stream = CountedObserverStream(
        source, initial_state="s5", word=("advance",),
        rules=(EmitRule("low.readout", "low"),),
    )
    assert stream.summary.quotient_states == 4
    assert stream.summary.period == 4
    for index in range(100):
        assert stream.event(index).value == (1 + index + 1) % 4
    assert stream.event(10**100).value == (1 + (10**100) + 1) % 4


def test_receipt_canonical_roundtrip_and_receiver_owned_intention() -> None:
    """Mathematics: typed receipt and full-request pin prevent semantic substitution."""

    source = feedback_source()
    stream = CountedObserverStream(
        source, initial_state="s1", word=("shift", "flip"), rules=_rules(),
    )
    k = 10**80
    receipt = stream.issue_receipt(k)
    rebuilt = CountedStreamReceipt.from_bytes(receipt.to_bytes())
    assert rebuilt == receipt
    assert rebuilt.to_bytes() == receipt.to_bytes()
    assert verify_counted_stream_receipt(
        rebuilt, source, expected_request=stream.request(k),
    )
    forged = replace(receipt, event=replace(receipt.event, value=987))
    assert not verify_counted_stream_receipt(forged, source)
    forged = replace(
        receipt, event=replace(receipt.event, word_iteration=receipt.event.word_iteration + 1)
    )
    assert not verify_counted_stream_receipt(forged, source)
    forged = replace(receipt, source_digest="a" * 64)
    assert not verify_counted_stream_receipt(forged, source)
    # A *different* valid event is mathematically valid, but does not match
    # the receiver's exact originally intended output index.
    alternative = stream.issue_receipt(k + 1)
    assert verify_counted_stream_receipt(alternative, source)
    assert not verify_counted_stream_receipt(
        alternative, source, expected_request=stream.request(k),
    )


def test_reject_noncanonical_packet_duplicate_key_and_unadmitted_rules() -> None:
    """Mathematics: refuse malformed/colliding evidence and inconsistent observer definitions."""

    stream = CountedObserverStream(
        feedback_source(), initial_state="s1", word=("shift",), rules=_rules(),
    )
    receipt = stream.issue_receipt(2)
    payload = receipt.snapshot()
    payload["event"]["index"] = "0x0002"
    with pytest.raises(BootstrapRefused):
        CountedStreamReceipt.from_snapshot(payload)
    raw = receipt.to_bytes()
    with pytest.raises(BootstrapRefused):
        CountedStreamReceipt.from_bytes(b" " + raw)
    with pytest.raises(BootstrapRefused):
        CountedStreamReceipt.from_bytes(
            raw.replace(b'"schema":', b'"schema":"shadow","schema":', 1)
        )
    with pytest.raises(BootstrapRefused):
        CountedStreamReceipt.from_bytes(raw.replace(b'"value":', b'"value":NaN, "shadow":', 1))
    with pytest.raises(BootstrapRefused):
        CountedObserverStream(
            feedback_source(), initial_state="s1", word=("shift",),
            rules=(EmitRule("m", "unobserved"),),
        )
    with pytest.raises(BootstrapRefused):
        CountedObserverStream(
            feedback_source(), initial_state="s1", word=("missing",),
            rules=_rules(),
        )
    with pytest.raises(BootstrapRefused):
        stream.event(-1)
    with pytest.raises(BootstrapRefused):
        stream.count_after(1 << 4096)


def test_many_synthetic_total_deterministic_sources_match_native_counting() -> None:
    """Mathematics: random finite graph cycles and conditional send counts match raw replay."""

    rng = random.Random(73)
    for _ in range(125):
        size = rng.randint(2, 14)
        states = tuple(f"s{i}" for i in range(size))
        source = FiniteObserverLaw(
            states, ("a", "b"), ("value", "gate"),
            tuple((rng.randrange(size), rng.randrange(size)) for _ in states),
            tuple((rng.randrange(8), rng.randrange(2)) for _ in states),
        )
        word = tuple(rng.choice(source.actions) for _ in range(rng.randint(1, 3)))
        rules = (
            EmitRule("gated", "value", when_field="gate", when_equals=1),
            EmitRule("action.b", "gate", on_action="b"),
        )
        stream = CountedObserverStream(
            source, initial_state=rng.choice(states), word=word, rules=rules,
        )
        events, counts, _ = _reference(source, stream.initial_state, word, rules, 180)
        assert [stream.count_after(i) for i in range(181)] == counts
        for k, (iteration, offset, mailbox, value) in enumerate(events):
            event = stream.event(k)
            assert (event.word_iteration, event.action_offset,
                    event.mailbox, event.value) == (iteration, offset, mailbox, value)
        if stream.length() is not None:
            assert stream.length() == len(events)
            with pytest.raises(IndexError):
                stream.event(len(events))


def test_boolean_and_integer_observations_remain_distinct_typed_events() -> None:
    """Mathematics: bool=True must not silently equal int=1 in a portable receipt."""

    source = FiniteObserverLaw(
        ("s0",), ("loop",), ("boolean", "integer"),
        ((0,),), ((True, 1),),
    )
    rules = (EmitRule("bool", "boolean"), EmitRule("int", "integer"))
    stream = CountedObserverStream(
        source, initial_state="s0", word=("loop",), rules=rules,
    )
    assert stream.event(0).value is True
    assert type(stream.event(1).value) is int
    assert stream.issue_receipt(0).to_bytes() != stream.issue_receipt(1).to_bytes()
    forged = stream.issue_receipt(0)
    altered = replace(forged, event=replace(forged.event, value=1))
    assert not verify_counted_stream_receipt(altered, source)
