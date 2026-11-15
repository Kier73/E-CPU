"""Executable physical-process and negative proof controls (does not require E-CPU)."""
from __future__ import annotations

from pathlib import Path
import socket

import pytest

pytest.importorskip('vgi.structural_memory')

from examples.vgi_similarity_transfer_process import (
    orchestrate, restored, _recv_payload,
)


def test_new_process_recovers_identical_result_and_certificate(tmp_path:Path):
    result=orchestrate(tmp_path)
    assert result['producer_pid'] != result['receiver_pid']
    assert result['receiver_pid'] != result['recovered_pid']
    assert result['different_receiver_process'] is True
    assert result['no_basis_rediscovery'] is True
    assert result['result_matches_dense_reference'] is True
    assert result['stored_cut_digest'] == result['restored_receipt_digest']
    assert result['transit_effect_replay_verified'] is False
    assert result['block_sizes']==[2,2,2]
    assert result['record_bytes'] < 10_000


def test_tampered_socket_payload_rejected_before_durable_cut(tmp_path:Path):
    result=orchestrate(tmp_path,tamper=True)
    assert result['tampered_transfer_rejected'] is True
    assert result['receiver_exit_code'] != 0
    assert not (tmp_path/'cut.json').exists()
    assert not (tmp_path/'record.json').exists()


def test_recovery_refuses_changed_out_of_band_graph_and_memory_pins(tmp_path:Path):
    result=orchestrate(tmp_path)
    with pytest.raises((ValueError,TypeError),match='pinned'):
        restored(tmp_path,'0'*64,result['memory_sha256'])
    with pytest.raises((ValueError,TypeError),match='pinned'):
        restored(tmp_path,result['graph_fingerprint'],'0'*64)


def test_durable_record_tampering_fails_reverification(tmp_path:Path):
    result=orchestrate(tmp_path)
    path=tmp_path/'record.json'
    payload=path.read_bytes()
    path.write_bytes(payload[:-1] + bytes([payload[-1]^1]))
    with pytest.raises((ValueError,TypeError)):
        restored(tmp_path,result['graph_fingerprint'],result['memory_sha256'])


def test_durable_result_tampering_fails_reverification(tmp_path:Path):
    import json
    result=orchestrate(tmp_path)
    cut=tmp_path/'cut.json'
    obj=json.loads(cut.read_text())
    obj['result'][0] += 1
    cut.write_text(json.dumps(obj))
    with pytest.raises(ValueError,match='differs from durable'):
        restored(tmp_path,result['graph_fingerprint'],result['memory_sha256'])


def test_transfer_rejects_oversized_frame_without_reading_payload():
    local,remote=socket.socketpair()
    try:
        remote.sendall((1_048_577).to_bytes(4,'big'))
        with pytest.raises(ValueError,match='invalid bounded record length'):
            _recv_payload(local)
    finally:
        local.close();remote.close()