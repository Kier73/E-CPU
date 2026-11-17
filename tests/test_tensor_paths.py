"""Verified SIMT tile and path-native tensor realization regression tests."""

from __future__ import annotations

import copy

import pytest

from mailcpu.classifier import HypervisorArbitrationEvent, HypervisorRequest
from mailcpu.egpu import EGPUError, EGPUHost
from mailcpu.path_ground_probe import (
    TransferObservation, characterize_transfer, fir_response,
)
from mailcpu.path_tensor import PathTensorError, PathTensorHost
from mailcpu.tensor_stream import TensorStreamError, compile_matmul_tile, execute_tiled_matmul
from mailcpu.transit_simt import TransitSIMTError, TransitSIMTHost


def _event(payload, sequence=1, granted=True):
    """Mathematics: bind a unique E-GPU method to a typed receiver-side execute request."""

    return HypervisorArbitrationEvent(
        "source", "tensor", sequence, 500 + sequence,
        HypervisorRequest(
            EGPUHost.operation_name, EGPUHost.resource_name, payload,
            frozenset({"execute"}),
            frozenset({"execute"}) if granted else frozenset(),
            False,
        ),
    )


def _tile():
    """Mathematics: construct a signed 2x3 by 3x2 multiplication with an accumulator."""

    return {
        "method": "tensor.matmul.tile", "shape": [2, 2, 3],
        "left": [2, -1, 4, 1, 3, -2],
        "right": [3, 5, -4, 2, 1, -3],
        "accumulate": [7, -8, 9, 0],
        "max_steps": 12,
    }


def test_tensor_tile_uses_existing_simt_and_exact_independent_oracle():
    """Mathematics: path routing, SIMT multiply-accumulate and signed scalar truth agree."""

    host = EGPUHost(host_id="egpu.tensor")
    result = host.handle(_event(_tile()))
    assert result["result"]["outputs"]["result"] == [21, -12, -2, 17]
    assert result["result"]["steps"] == 12
    assert result["route"] == ["egpu.tensor.dispatch", "egpu.tensor.simt", "egpu.tensor.verify"]
    assert host.execute_authorized_method("tensor.matmul.tile", _tile()) == result
    assert "tensor.matmul.tile" in host.available_methods


@pytest.mark.parametrize("change,match", [
    ({"shape": [9, 9, 1]}, "lane bound"),
    ({"left": [1]}, "exactly"),
    ({"right": [0] * 5}, "exactly"),
    ({"accumulate": [1, 2, 3, True]}, "integers"),
    ({"max_steps": 2}, "budget"),
    ({"method": "vector.add"}, "fields"),
])
def test_tensor_tile_refuses_invalid_shape_or_budget(change, match):
    """Mathematics: tensor descriptors fail closed before any SIMT state transition."""

    payload = {**_tile(), **change}
    with pytest.raises(TensorStreamError, match=match):
        compile_matmul_tile(payload, TransitSIMTHost())


def test_simt_mac_exact_and_overflow_fails_closed():
    """Mathematics: MAC=C+A*B is lane-wise and retains strict intermediate integer bounds."""

    simt = TransitSIMTHost(max_integer_bits=6)

    def run(values):
        """Mathematics: execute one exact SIMT instruction sequence under receiver authority."""

        payload = {
            "lanes": 2, "inputs": {"a": values[0], "b": values[1], "c": values[2]},
            "program": [
                ["load", "a", "a"], ["load", "b", "b"], ["load", "c", "c"],
                ["mac", "o", "c", "a", "b"], ["store", "out", "o"], ["halt"],
            ],
            "max_steps": 6,
        }
        return simt.handle(HypervisorArbitrationEvent(
            "origin", "simt", 1, 1,
            HypervisorRequest(
                TransitSIMTHost.operation_name, TransitSIMTHost.resource_name,
                payload, frozenset({"execute"}), frozenset({"execute"}),
            ),
        ))

    assert run(([2, -3], [4, 6], [1, 2]))["outputs"]["out"] == [9, -16]
    with pytest.raises(TransitSIMTError, match="integer exceeds"):
        run(([16, 1], [4, 1], [1, 1]))


def test_streaming_matmul_dispatches_bounded_work_units_without_local_dot_products():
    """Mathematics: remote callback owns all arithmetic transitions; the coordinator checks each tile."""

    host = EGPUHost(host_id="egpu.tiles")
    calls = []

    def dispatch(payload):
        """Mathematics: model one already-authorized remote E-GPU tile execution."""

        calls.append(copy.deepcopy(payload))
        return host.execute_authorized_method("tensor.matmul.tile", payload)

    a = [[(i * 5 + k * 3) % 11 - 5 for k in range(29)] for i in range(17)]
    b = [[(k * 2 - j * 7) % 13 - 6 for j in range(18)] for k in range(29)]
    report = execute_tiled_matmul(a, b, dispatch, tile_rows=4, tile_cols=5, chunk_depth=7)
    expected = [[sum(a[i][k] * b[k][j] for k in range(29)) for j in range(18)] for i in range(17)]
    assert report["values"] == expected
    assert report["shape"] == [17, 18]
    assert report["work_units"] == 5 * 4 * 5
    assert len(report["tile_receipt_digests"]) == report["work_units"]
    assert calls[0]["shape"] == [4, 5, 7]
    assert calls[-1]["shape"] == [1, 3, 1]
    assert report["verification"] == "independent-integer-oracle"


def test_streaming_matmul_refuses_corrupted_result_even_with_rehashed_digest():
    """Mathematics: digest integrity alone cannot replace the independent integer oracle."""

    host = EGPUHost()

    def corrupt(payload):
        """Mathematics: return an internally consistent fabricated SIMT observation."""

        from mailcpu.tensor_stream import _digest

        response = host.execute_authorized_method("tensor.matmul.tile", payload)
        response["result"]["outputs"]["result"][0] += 1
        result = response["result"]
        result["state_digest"] = _digest({k: v for k, v in result.items() if k != "state_digest"})
        response["result_digest"] = _digest(result)
        response["receipt_digest"] = _digest({
            k: v for k, v in response.items() if k not in ("result", "receipt_digest")
        })
        return response

    with pytest.raises(TensorStreamError, match="independent integer oracle"):
        execute_tiled_matmul([[3]], [[4]], corrupt, tile_rows=1, tile_cols=1, chunk_depth=1)


@pytest.mark.parametrize("field", ["left", "right", "accumulate"])
def test_streaming_matmul_keeps_original_intention_when_dispatch_mutates_request(field):
    """Mathematics: callback mutation cannot redefine the independent verification reference."""
    host = EGPUHost()

    def mutate(payload):
        """Mathematics: execute a changed request with an internally valid receipt."""
        payload[field][0] += 1
        return host.execute_authorized_method("tensor.matmul.tile", payload)

    with pytest.raises(TensorStreamError, match="independent integer oracle"):
        execute_tiled_matmul([[3]], [[4]], mutate, tile_rows=1, tile_cols=1, chunk_depth=1)


def test_tensor_checkpoint_recovers_verified_prefix_on_a_different_host(tmp_path):
    """Mathematics: a persisted prefix preserves accumulation across host changes without redispatch."""
    import json

    first, replacement = EGPUHost(host_id="first"), EGPUHost(host_id="replacement")
    filename = tmp_path / "tensor.json"
    calls = []

    def persist(state):
        """Mathematics: persist one complete JSON checkpoint for a fresh coordinator invocation."""
        filename.write_text(json.dumps(state), encoding="utf-8")

    def interrupted(payload):
        """Mathematics: interrupt after two completed depth chunks."""
        calls.append(copy.deepcopy(payload))
        if len(calls) == 3:
            raise ConnectionError("host lost")
        return first.execute_authorized_method("tensor.matmul.tile", payload)

    a, b = [[2, 3, 4, 5]], [[7], [11], [13], [17]]
    options = dict(tile_rows=1, tile_cols=1, chunk_depth=1)
    with pytest.raises(ConnectionError, match="host lost"):
        execute_tiled_matmul(a, b, interrupted, checkpoint_sink=persist, **options)
    saved = json.loads(filename.read_text(encoding="utf-8"))
    assert len(saved["tiles"]) == 2
    resumed = []

    def dispatch(payload):
        """Mathematics: execute only the remaining suffix on another already-authorized host."""
        resumed.append(copy.deepcopy(payload))
        return replacement.execute_authorized_method("tensor.matmul.tile", payload)

    report = execute_tiled_matmul(a, b, dispatch, checkpoint=saved, checkpoint_sink=persist, **options)
    assert report["values"] == [[184]]
    assert len(resumed) == 2
    assert resumed[0] == calls[2]
    assert report["tile_receipt_digests"][:2] == [t["response"]["receipt_digest"] for t in saved["tiles"]]
    restored = json.loads(filename.read_text(encoding="utf-8"))
    replay = execute_tiled_matmul(a, b, dispatch, checkpoint=restored, **options)
    assert replay == report and len(resumed) == 2
    with pytest.raises(TensorStreamError, match="different plan"):
        execute_tiled_matmul([[2, 3, 4, 6]], b, dispatch, checkpoint=restored, **options)
    assert len(resumed) == 2


def test_tensor_checkpoint_refuses_rehashed_false_evidence_before_dispatch():
    """Mathematics: self-consistent hashes cannot promote false saved arithmetic into a verified prefix."""
    from mailcpu.tensor_stream import _digest

    host, saved = EGPUHost(), []
    options = dict(tile_rows=1, tile_cols=1, chunk_depth=1)
    execute_tiled_matmul([[3]], [[4]],
                         lambda p: host.execute_authorized_method("tensor.matmul.tile", p),
                         checkpoint_sink=saved.append, **options)
    damaged = copy.deepcopy(saved[0])
    response = damaged["tiles"][0]["response"]
    result = response["result"]
    result["outputs"]["result"][0] += 1
    result["state_digest"] = _digest({k: v for k, v in result.items() if k != "state_digest"})
    response["result_digest"] = _digest(result)
    response["receipt_digest"] = _digest({k: v for k, v in response.items() if k not in ("result", "receipt_digest")})
    damaged["checkpoint_digest"] = _digest({k: v for k, v in damaged.items() if k != "checkpoint_digest"})

    def forbidden(payload):
        """Mathematics: no new dispatch may occur before the saved prefix is verified."""
        raise AssertionError("unexpected dispatch")

    with pytest.raises(TensorStreamError, match="independent integer oracle"):
        execute_tiled_matmul([[3]], [[4]], forbidden, checkpoint=damaged, **options)
    with pytest.raises(TensorStreamError, match="independent semantic verification"):
        execute_tiled_matmul([[3]], [[4]], forbidden, checkpoint=saved[0], verify_semantics=False, **options)


def test_tensor_checkpoint_sink_cannot_mutate_later_accumulation():
    """Mathematics: the persistence callback receives detached evidence, not mutable execution state."""
    host = EGPUHost()

    def mutate(state):
        """Mathematics: overwrite the sink's own copy of an admitted result."""
        state["tiles"][-1]["response"]["result"]["outputs"]["result"][0] = 999
        state["tiles"].clear()

    report = execute_tiled_matmul(
        [[2, 3]], [[5], [7]], lambda p: host.execute_authorized_method("tensor.matmul.tile", p),
        tile_rows=1, tile_cols=1, chunk_depth=1, checkpoint_sink=mutate,
    )
    assert report["values"] == [[31]]


def _calibrated_path(mechanism="software_fir_reference"):
    """Mathematics: infer a finite LTI Ground from impulse, shift and two held-out probes."""

    dimension = 32
    kernel = (0.5, -0.25, 0.125)
    env = "a" * 64

    def sample(stimulus, identity):
        """Mathematics: a reference-only transfer observation for one finite frame."""

        return TransferObservation(
            tuple(stimulus), fir_response(stimulus, kernel), mechanism, env, identity,
        )

    impulse = sample((1.0,) + (0.0,) * 31, "impulse")
    shifted = sample((0.0, 1.0) + (0.0,) * 30, "shifted")
    first = sample(tuple(float((i * 3) % 9 - 4) for i in range(32)), "heldout-a")
    second = sample(tuple(float((i * 7) % 13 - 6) for i in range(32)), "heldout-b")
    calibration = (impulse, shifted, (first, second))
    candidate = characterize_transfer(impulse, shifted, (first, second), taps=3, tolerance=0.0)
    return candidate, calibration, sample


def test_path_convolution_enters_path_substrate_not_simt_and_streams_high_volume():
    """Mathematics: convolution y=h*x is executed per path frame; all results are independently checked."""

    candidate, calibration, reference_transmit = _calibrated_path()
    events = []

    def transmit(stimulus, identity):
        """Mathematics: record active path observations as the simulation's transit work witness."""

        events.append(identity)
        return reference_transmit(stimulus, identity)

    path = PathTensorHost(path_id="controlled.path", candidate=candidate,
                          calibration=calibration, transmit=transmit)
    class SimtMustNotRun(TransitSIMTHost):
        """SIMT is forbidden in the alternate path substrate realization."""

        def handle(self, event):
            """Mathematics: fail if a transfer-backed tensor unexpectedly dispatches SIMT."""

            raise AssertionError("path-native tensor must not call SIMT")

    host = EGPUHost(host_id="egpu.signal", simt_host=SimtMustNotRun(), tensor_path_host=path)
    series = [[(i * 7) % 17 - 8 for i in range(2560)],
              [(i * 5) % 13 - 6 for i in range(1935)]]
    payload = {"method": "tensor.path.fir", "request_id": "test-conv-01",
               "samples": series, "max_frames": 200}
    response = host.handle(_event(payload))
    expected = [
        [sum(candidate.kernel[j] * row[i-j] for j in range(min(i+1, 3))) for i in range(len(row))]
        for row in series
    ]
    assert response["result"]["values"] == expected
    assert response["result"]["frames"] == len(events)
    assert response["result"]["frames"] > 100
    assert response["route"] == ["egpu.signal.dispatch", "egpu.signal.path", "egpu.signal.verify"]
    assert response["result"]["mechanism"] == "software_fir_reference"
    assert response["result"]["sample_transits"] == len(events) * 32
    assert "tensor.path.fir" in host.available_methods


def test_path_tensor_refuses_unbound_path_and_false_transfer_observations():
    """Mathematics: no path contract, no capacity claim, and no acceptance of a changed live transfer."""

    candidate, calibration, reference_transmit = _calibrated_path()
    payload = {"method": "tensor.path.fir", "request_id": "no-claim",
               "samples": [[1, 2, 3, 4]], "max_frames": 2}
    assert "tensor.path.fir" not in EGPUHost().available_methods
    with pytest.raises(EGPUError, match="no characterized path"):
        EGPUHost().handle(_event(payload))
    with pytest.raises(PathTensorError, match="calibration"):
        PathTensorHost(path_id="controlled.path", candidate=candidate,
                       calibration=(calibration[0], calibration[1], ()),
                       transmit=reference_transmit)

    def corrupted(stimulus, identity):
        """Mathematics: a path transformation contradicting the admitted Ground is refused."""

        base = reference_transmit(stimulus, identity)
        changed = list(base.response)
        changed[-1] += 1.0
        return TransferObservation(tuple(stimulus), tuple(changed),
                                   base.mechanism, base.environment_digest, identity)

    path = PathTensorHost(path_id="controlled.path", candidate=candidate,
                          calibration=calibration, transmit=corrupted)
    with pytest.raises(EGPUError, match="contradicts calibrated path"):
        EGPUHost(tensor_path_host=path).handle(_event(payload))


def test_path_tensor_refuses_improper_frame_identity_and_budget():
    """Mathematics: bounded frame observations must bind exact request identity and remain within capacity."""

    candidate, calibration, reference_transmit = _calibrated_path()

    def swap(stimulus, identity):
        """Mathematics: report the right output against an alien frame identity."""

        return reference_transmit(stimulus, "other-request")

    path = PathTensorHost(path_id="path.test", candidate=candidate,
                          calibration=calibration, transmit=swap)
    with pytest.raises(PathTensorError, match="not bound"):
        path.execute({"method": "tensor.path.fir", "request_id": "run01",
                      "samples": [[1, 2, 3]], "max_frames": 1})
    healthy = PathTensorHost(path_id="path.test", candidate=candidate,
                             calibration=calibration, transmit=reference_transmit)
    with pytest.raises(PathTensorError, match="frame budget"):
        healthy.execute({"method": "tensor.path.fir", "request_id": "run02",
                         "samples": [[1] * 100], "max_frames": 1})
