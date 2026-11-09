from __future__ import annotations

import itertools

import pytest

from mailcpu import (
    DataflowMultiplyFrontierReceipt,
    OperationTimingProbe,
    PlacementObservation,
    PlacementProfile,
    PlacementProfileError,
    PlacementProfileKey,
    rank_placement_profiles,
)


WORKLOAD_CLASS = "a" * 64
OPERATOR_CONTRACT = "b" * 64
GROUND = "c" * 64
ORIGIN_ENVIRONMENT = "d" * 64
IMPLEMENTATION_A = "e" * 64
IMPLEMENTATION_B = "f" * 64
WORKLOAD = "1" * 64
EXECUTION = "2" * 64
VERIFICATION = "3" * 64
ROUTE = "4" * 64


def _key(
    host: str,
    implementation: str,
    *,
    peer_path: tuple[str, ...] = (),
    origin_environment_digest: str = ORIGIN_ENVIRONMENT,
) -> PlacementProfileKey:
    return PlacementProfileKey(
        workload_class_digest=WORKLOAD_CLASS,
        operator_id="mailcpu.dataflow.multiply_frontier",
        operator_version=1,
        operator_contract_digest=OPERATOR_CONTRACT,
        computational_ground_fingerprint=GROUND,
        origin_environment_digest=origin_environment_digest,
        target_host_id=host,
        implementation_fingerprint=implementation,
        peer_path=peer_path,
    )


def _sample(duration_ns: int, *, actor: str = "peer-a/origin") :
    values = itertools.count(1_000, duration_ns)
    probe = OperationTimingProbe(actor, monotonic_ns=lambda: next(values))
    return probe.finish(probe.start("total_completion", correlation_id=WORKLOAD))


def _observation(
    key: PlacementProfileKey,
    duration_ns: int,
    *,
    receipt: DataflowMultiplyFrontierReceipt | None = None,
    execution_digest: str = EXECUTION,
) -> PlacementObservation:
    return PlacementObservation.from_timing_sample(
        key,
        _sample(duration_ns),
        workload_digest=WORKLOAD,
        execution_digest=execution_digest,
        verification_digest=VERIFICATION,
        verification_method="mailcpu-reference-and-scalar-oracle",
        route_receipt=receipt,
    )


def _remote_receipt(
    *,
    host: str = "remote-egpu",
    implementation: str = IMPLEMENTATION_B,
    peer_path: tuple[str, ...] = ("peer-a", "peer-b"),
    route_witness_digest: str = ROUTE,
) -> DataflowMultiplyFrontierReceipt:
    return DataflowMultiplyFrontierReceipt(
        request_digest=WORKLOAD,
        results=(("node-1", 21),),
        host_id=host,
        peer_id=peer_path[-1],
        peer_path=peer_path,
        route_witness_digest=route_witness_digest,
        forwarding_receipt_digest="5" * 64,
        operator_effect_digest="6" * 64,
        implementation_fingerprint=implementation,
        backend_receipt_digest="7" * 64,
    )


def test_profile_aggregates_only_correlated_total_completion_samples() -> None:
    key = _key("local-cpu", IMPLEMENTATION_A)
    profile = PlacementProfile(
        key,
        (
            _observation(key, 100),
            _observation(key, 130, execution_digest="8" * 64),
            _observation(key, 110, execution_digest="9" * 64),
        ),
    )

    assert profile.durations_ns == (100, 130, 110)
    assert profile.summary == {
        "count": 3,
        "min_ns": 100,
        "median_ns": 110,
        "p95_ns": 130,
        "max_ns": 130,
        "mean_ns": 113,
    }


def test_profile_round_trip_preserves_timing_and_verification_evidence() -> None:
    key = _key(
        "remote-egpu",
        IMPLEMENTATION_B,
        peer_path=("peer-a", "peer-b"),
    )
    receipt = _remote_receipt()
    profile = PlacementProfile(
        key,
        (_observation(key, 250, receipt=receipt),),
    )

    restored = PlacementProfile.from_dict(profile.to_dict())

    assert restored == profile
    assert restored.digest == profile.digest
    assert restored.observations[0].route_receipt == receipt
    assert restored.observations[0].timing_sample.elapsed_ns == 250


def test_remote_observation_requires_exact_host_implementation_and_route_receipt() -> None:
    key = _key(
        "remote-egpu",
        IMPLEMENTATION_B,
        peer_path=("peer-a", "peer-b"),
    )

    with pytest.raises(PlacementProfileError, match="typed binary frontier receipt"):
        _observation(key, 250)

    with pytest.raises(PlacementProfileError, match="does not match"):
        _observation(key, 250, receipt=_remote_receipt(host="other-host"))

    with pytest.raises(PlacementProfileError, match="does not match"):
        _observation(key, 250, receipt=_remote_receipt(peer_path=("peer-a", "peer-c")))

    # The route witness is request-specific; a new workload event may produce
    # a new witness digest while remaining on the same profiled placement path.
    observation = _observation(
        key,
        250,
        receipt=_remote_receipt(route_witness_digest="8" * 64),
    )
    assert observation.route_receipt is not None
    assert observation.route_receipt.route_witness_digest == "8" * 64


def test_profile_rejects_duplicate_samples_and_mismatched_profile_keys() -> None:
    key = _key("local-cpu", IMPLEMENTATION_A)
    first = _observation(key, 100)
    profile = PlacementProfile(key, (first,))

    with pytest.raises(PlacementProfileError, match="different placement profile"):
        profile.add(_observation(_key("other-host", IMPLEMENTATION_B), 90))

    with pytest.raises(PlacementProfileError, match="duplicate observations"):
        PlacementProfile(key, (first, first))


def test_placement_ranking_uses_repeated_measurements_and_remains_advisory() -> None:
    faster_key = _key("local-cpu", IMPLEMENTATION_A)
    slower_key = _key(
        "remote-egpu",
        IMPLEMENTATION_B,
        peer_path=("peer-a", "peer-b"),
    )
    faster = PlacementProfile(
        faster_key,
        tuple(
            _observation(faster_key, value, execution_digest=f"{index:064x}")
            for index, value in enumerate((100, 110, 105), start=10)
        ),
    )
    receipt = _remote_receipt()
    slower = PlacementProfile(
        slower_key,
        tuple(
            _observation(slower_key, value, receipt=receipt, execution_digest=f"{index:064x}")
            for index, value in enumerate((300, 320, 310), start=20)
        ),
    )

    ranking = rank_placement_profiles((slower, faster), minimum_observations=3)

    assert ranking.complete is True
    assert ranking.best_profile_digest == faster.digest
    assert ranking.ordered_profile_digests == (faster.digest, slower.digest)
    assert ranking.recommendation_authoritative is False
    assert ranking.to_dict()["recommendation_authoritative"] is False
    assert type(ranking).from_dict(ranking.to_dict()) == ranking
    tampered = ranking.to_dict()
    tampered["recommendation_authoritative"] = True
    with pytest.raises(PlacementProfileError, match="authority"):
        type(ranking).from_dict(tampered)


def test_placement_ranking_refuses_to_rank_until_all_candidates_meet_sample_floor() -> None:
    faster_key = _key("local-cpu", IMPLEMENTATION_A)
    slower_key = _key(
        "remote-egpu",
        IMPLEMENTATION_B,
        peer_path=("peer-a", "peer-b"),
    )
    faster = PlacementProfile(
        faster_key,
        tuple(_observation(faster_key, value, execution_digest=f"{index:064x}") for index, value in enumerate((100, 110, 105), 10)),
    )
    slower = PlacementProfile(
        slower_key,
        (_observation(slower_key, 300, receipt=_remote_receipt()),),
    )

    ranking = rank_placement_profiles((faster, slower), minimum_observations=3)

    assert ranking.complete is False
    assert ranking.best_profile_digest is None
    assert ranking.ordered_profile_digests == ()
    assert ranking.insufficient_profiles == ((slower.digest, 1),)
    assert type(ranking).from_dict(ranking.to_dict()) == ranking
    tampered = ranking.to_dict()
    tampered["complete"] = True
    with pytest.raises(PlacementProfileError, match="completeness"):
        type(ranking).from_dict(tampered)


def test_placement_profiles_must_share_workload_contract_ground_and_origin_environment() -> None:
    first = PlacementProfile(
        _key("host-a", IMPLEMENTATION_A),
        (_observation(_key("host-a", IMPLEMENTATION_A), 100),),
    )
    second_key = _key(
        "host-b",
        IMPLEMENTATION_B,
        origin_environment_digest="a" * 64,
    )
    second = PlacementProfile(second_key, (_observation(second_key, 110),))

    with pytest.raises(PlacementProfileError, match="do not share"):
        rank_placement_profiles((first, second))


def test_profile_refuses_non_total_completion_or_unbound_sample() -> None:
    key = _key("local-cpu", IMPLEMENTATION_A)
    probe = OperationTimingProbe("peer-a/origin", monotonic_ns=lambda: next(itertools.count(1, 10)))
    non_total = probe.finish(probe.start("backend_compute", correlation_id=WORKLOAD))

    with pytest.raises(PlacementProfileError, match="only total_completion"):
        PlacementObservation.from_timing_sample(
            key,
            non_total,
            workload_digest=WORKLOAD,
            execution_digest=EXECUTION,
            verification_digest=VERIFICATION,
            verification_method="mailcpu-reference-and-scalar-oracle",
        )

    total = _sample(100)
    with pytest.raises(PlacementProfileError, match="correlation"):
        PlacementObservation.from_timing_sample(
            key,
            total,
            workload_digest="a" * 64,
            execution_digest=EXECUTION,
            verification_digest=VERIFICATION,
            verification_method="mailcpu-reference-and-scalar-oracle",
        )


def test_profile_deserialization_rejects_tampered_duration_and_summary() -> None:
    key = _key("local-cpu", IMPLEMENTATION_A)
    profile = PlacementProfile(key, (_observation(key, 100),))
    payload = profile.to_dict()
    payload["observations"][0]["timing_sample"]["elapsed_ns"] = 999

    with pytest.raises(PlacementProfileError, match="elapsed duration"):
        PlacementProfile.from_dict(payload)

    payload = profile.to_dict()
    payload["observations"][0]["timing_sample"]["elapsed_ns"] = False
    with pytest.raises(PlacementProfileError, match="strict integer"):
        PlacementProfile.from_dict(payload)

