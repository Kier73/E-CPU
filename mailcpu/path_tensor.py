"""PATH-TENSOR-001: stream tensor convolution through a characterized path transfer.

A physical path may perform a linear filter as signals propagate. The
transmit callback is the path observation boundary: software reference
callbacks cannot claim physical computation. No SIMT arithmetic is invoked by
this realization; the independent oracle is verification, not realization.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, Mapping, Sequence

from .path_ground_probe import (
    PathGroundRefused, TransferGroundCandidate, TransferObservation,
    fir_response, verify_transfer_candidate,
)

PATH_TENSOR_SCHEMA = "mailcpu.path-tensor-stream.v1"
_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:-]{0,95}\Z")


class PathTensorError(ValueError):
    """Mathematics: refuse an unqualified path, malformed tensor, or contradictory transfer."""


def _digest(value: Any) -> str:
    """Mathematics: bind an observed frame or tensor via canonical SHA-256 encoding."""

    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def _name(value: Any, label: str) -> str:
    """Mathematics: require a bounded, unambiguous path or invocation identifier."""

    if type(value) is not str or _ID.fullmatch(value) is None:
        raise PathTensorError(f"{label} has invalid identity")
    return value


def _bound(value: Any, label: str, maximum: int) -> int:
    """Mathematics: admit a positive finite integer not exceeding capacity."""

    if type(value) is not int or not 1 <= value <= maximum:
        raise PathTensorError(f"{label} is outside configured bounds")
    return value


class PathTensorHost:
    """Receiver-bound convolution realizer over a qualified path input/output law.

    The callback is bound by the receiver and returns one independently
    observed TransferObservation per frame. This abstraction does NOT say
    which mechanism implements the law. A software FIR callback proves
    integration only; instrument_observation requires deployment-origin proof.
    """

    def __init__(
        self, *,
        path_id: str,
        candidate: TransferGroundCandidate,
        calibration: tuple[TransferObservation, TransferObservation, Sequence[TransferObservation]],
        transmit: Callable[[tuple[float, ...], str], TransferObservation],
        max_frames: int = 65_536,
        max_tensor_elements: int = 1_048_576,
    ) -> None:
        """Mathematics: bind a path only with its independently reconstructible FIR calibration."""

        self.path_id = _name(path_id, "path")
        if not isinstance(candidate, TransferGroundCandidate):
            raise PathTensorError("path needs typed transfer Ground candidate")
        if not isinstance(calibration, (tuple, list)) or len(calibration) != 3:
            raise PathTensorError("path needs impulse, shifted, and held-out calibration")
        if not verify_transfer_candidate(
            candidate, calibration[0], calibration[1], calibration[2],
            taps=len(candidate.kernel), tolerance=candidate.tolerance,
        ):
            raise PathTensorError("path transfer calibration does not reconstruct")
        if candidate.observed_dimension < len(candidate.kernel):
            raise PathTensorError("path frame shorter than characterized impulse response")
        if not callable(transmit):
            raise TypeError("path transmit callback must be callable")
        self.candidate = candidate
        self._transmit = transmit
        self.max_frames = _bound(max_frames, "max_frames", 1_000_000)
        self.max_tensor_elements = _bound(max_tensor_elements, "max_tensor_elements", 8_000_000)

    def execute(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Mathematics: perform each convolution frame by transmitting it through the bound path.

        For a kernel of K taps and a calibrated frame dimension N, carry K-1
        previous samples and send at most N-K+1 new samples per frame. The
        observed final new-sample positions are the tensor outputs, so there
        is no software FIR execution within the realization loop. A reference
        projection is computed independently for checking every observation.
        """

        if not isinstance(payload, Mapping) or set(payload) != {
            "method", "request_id", "samples", "max_frames",
        } or payload.get("method") != "tensor.path.fir":
            raise PathTensorError("path tensor method or payload fields are invalid")
        request_id = _name(payload["request_id"], "request")
        budget = _bound(payload["max_frames"], "requested frame count", self.max_frames)
        raw_samples = payload["samples"]
        if not isinstance(raw_samples, (list, tuple)) or not raw_samples:
            raise PathTensorError("tensor samples must contain one or more rows")
        n = len(self.candidate.kernel)
        dimension = self.candidate.observed_dimension
        stride = dimension - n + 1
        rows: list[tuple[float, ...]] = []
        total = 0
        for row in raw_samples:
            if not isinstance(row, (list, tuple)) or not row:
                raise PathTensorError("tensor rows must be non-empty")
            try:
                # Use the same bounded finite-sample validation as the
                # calibrated transfer interface, in chunks for long streams.
                converted = tuple(float(x) for x in row)
            except (ValueError, OverflowError, TypeError) as exc:
                raise PathTensorError("tensor row cannot be encoded as finite samples") from exc
            if any(type(x) not in (int, float) or not -1e6 <= float(x) <= 1e6
                   for x in row):
                raise PathTensorError("tensor row contains invalid/nonfinite samples")
            total += len(row)
            if total > self.max_tensor_elements:
                raise PathTensorError("tensor exceeds path input capacity")
            rows.append(converted)
        needed = sum((len(row) + stride - 1) // stride for row in rows)
        if needed > budget:
            raise PathTensorError("tensor stream exceeds requested frame budget")

        results: list[list[float]] = []
        observations: list[dict[str, Any]] = []
        identities: set[str] = set()
        for row_index, row in enumerate(rows):
            tail = (0.0,) * (n - 1)
            result_row: list[float] = []
            for offset in range(0, len(row), stride):
                chunk = row[offset : offset + stride]
                stimulus = tail + chunk + (0.0,) * (stride - len(chunk))
                identity = f"{request_id}:{row_index}:{offset // stride}"
                if len(identity) > 128:
                    raise PathTensorError("frame observation identity exceeds bound")
                observation = self._transmit(stimulus, identity)
                if not isinstance(observation, TransferObservation):
                    raise PathTensorError("path did not return a typed transfer observation")
                if (observation.observation_id != identity
                        or observation.mechanism != self.candidate.mechanism
                        or observation.environment_digest != self.candidate.environment_digest
                        or observation.stimulus != stimulus):
                    raise PathTensorError("path observation is not bound to requested frame")
                if observation.observation_id in identities:
                    raise PathTensorError("path observation reused a frame identity")
                identities.add(identity)
                predicted = fir_response(stimulus, self.candidate.kernel)
                discrepancy = max(abs(a - b) for a, b in zip(predicted, observation.response))
                if discrepancy > self.candidate.tolerance:
                    raise PathTensorError("live transfer contradicts calibrated path Ground")
                result_row.extend(observation.response[n - 1 : n - 1 + len(chunk)])
                observations.append({
                    "frame_id": identity,
                    "path_id": self.path_id,
                    "input_digest": _digest(list(stimulus)),
                    "observed_digest": _digest(list(observation.response)),
                    "observation_digest": _digest(observation.to_dict()),
                    "maximum_absolute_error": discrepancy,
                })
                # This tail belongs to the observed input stream, not padded zeros.
                tail = (tail + chunk)[-(n - 1):] if n > 1 else ()
            results.append(result_row)
        state = {
            "schema": PATH_TENSOR_SCHEMA,
            "method": "tensor.path.fir",
            "request_id": request_id,
            "path_id": self.path_id,
            "ground_digest": self.candidate.digest,
            "mechanism": self.candidate.mechanism,
            "values": results,
            "shape": [len(row) for row in results],
            "frames": len(observations),
            "sample_transits": len(observations) * dimension,
            "frame_receipts": observations,
            "verification": "held-out-calibrated-ground-and-frame-oracle",
        }
        return {**state, "state_digest": _digest(state)}
