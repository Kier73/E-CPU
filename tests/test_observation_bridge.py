from __future__ import annotations

import hashlib
import json

import pytest

from mailcpu import (
    DurableMailboxTransport,
    DelayObservation,
    DelayLoopEngine,
    DnsResolverSim,
    Instruction,
    LogicalClock,
    MailCPUVirtualMachine,
    Message,
    Op,
    ObservationAuthorityPolicy,
    ObservationConflictError,
    ObservationConsensus,
    ObservationError,
    PhaseObservation,
    Program,
    ReliabilityPolicy,
    ReliableChannel,
    ResolverObservation,
    ResolverObservationEndpoint,
    SubstrateObservationEndpoint,
    TimingChannelConfig,
    TimingObservation,
    TimingObservationProducer,
    TemporalObservation,
    GatedObservationCoordinator,
    GatedObservationError,
    load_gated_checkpoint,
)
from mailcpu.chemical_time import HorizonTracker, SystemEpoch
from mailcpu.chronofold import ChronoFold
from mailcpu.rrns import primes_below
from mailcpu.timing_channel import CadenceDemodulator


def _vm_with_target() -> tuple[MailCPUVirtualMachine, int]:
    """Mathematics: construct VM product `V=(E,S,M)` with one valid target task `p`."""

    vm = MailCPUVirtualMachine()
    pid = vm.spawn_program(Program((Instruction(Op.HALT),)), "observation-target")
    return vm, pid


def _gated_fixture(tmp_path):
    """Mathematics: construct two source channels with disjoint FIFO domains `Q_A` and `Q_B` over one durable log."""

    vm, pid = _vm_with_target()
    path = tmp_path / "gated-observation.log"
    transport = DurableMailboxTransport(path)
    sender_a = ReliableChannel(transport, "A", "R-A", "gate-A", peer="R-A")
    sender_b = ReliableChannel(transport, "B", "R-B", "gate-B", peer="R-B")
    receiver_a = ReliableChannel(transport, "R-A", "R-A", "gate-A", peer="A")
    receiver_b = ReliableChannel(transport, "R-B", "R-B", "gate-B", peer="B")
    coordinator = GatedObservationCoordinator(
        vm,
        ObservationAuthorityPolicy("timing", ("A", "B"), quorum=2, strict=True),
        {"A": receiver_a, "B": receiver_b},
        pid,
        "gated",
    )
    return vm, pid, path, transport, sender_a, sender_b, coordinator


def test_resolver_observation_codec_and_register_projection() -> None:
    r"""Mathematics: `decode(encode(O))=O` and `register_values` realizes the stated status/hit/TTL/time projection."""

    resolver = DnsResolverSim(clock=LogicalClock(12.0))
    result = resolver.query("codec.test", recursion_desired=True)
    observation = ResolverObservation.from_query(
        "resolver-A",
        "codec.test",
        "A",
        12,
        result,
    )

    assert ResolverObservation.from_payload(observation.to_payload()) == observation
    assert observation.register_values() == {
        "resolver_time": 12,
        "resolver_hit": 0,
        "resolver_ttl": 300,
        "resolver_status": 0,
    }
    with pytest.raises(ObservationError, match="version"):
        ResolverObservation.from_payload(("RESOLVER_OBSERVATION", 99, *observation.to_payload()[2:]))


def test_malformed_observation_remains_queued_and_unacknowledged(tmp_path) -> None:
    r"""Mathematics: malformed `E^{-1}(payload)=⊥` leaves `Q` and ACK mailbox unchanged because validation precedes consume."""

    path = tmp_path / "malformed-observation.log"
    transport = DurableMailboxTransport(path)
    receiver_channel = ReliableChannel(
        transport,
        "B",
        "B",
        "resolver-observation",
        ReliabilityPolicy(3, 2),
        peer="A",
    )
    endpoint = ResolverObservationEndpoint(receiver_channel, target_pid=1)
    transport.send(
        "B",
        Message(
            sender="A",
            recipient="B",
            op="RDATA",
            addr="B",
            body=("resolver-observation", 1, ("not", "a", "valid", "observation")),
        ),
    )

    vm, _ = _vm_with_target()
    with pytest.raises(ObservationError, match="payload shape"):
        endpoint.receive(vm)
    assert len(transport.list("B")) == 1
    assert transport.list(receiver_channel.ack_address) == ()


def test_durable_observation_reaches_vm_and_ack_survives_restart(tmp_path) -> None:
    r"""Mathematics: `O --reliable,durable--> R[p,*]` and sender restore removes exactly `P[s]` after ACK replay."""

    vm, pid = _vm_with_target()
    path = tmp_path / "observation.log"
    sender_transport = DurableMailboxTransport(path)
    sender_channel = ReliableChannel(
        sender_transport,
        "A",
        "B",
        "resolver-observation",
        ReliabilityPolicy(3, 2),
    )
    sender = ResolverObservationEndpoint(sender_channel)
    resolver = DnsResolverSim(clock=LogicalClock(20.0))
    observation = ResolverObservation.from_query(
        "A",
        "vm.test",
        "A",
        20,
        resolver.query("vm.test", recursion_desired=True),
    )
    assert sender.publish(observation) == 1
    sender_snapshot = sender.snapshot()

    receiver_transport = DurableMailboxTransport(path)
    receiver = ResolverObservationEndpoint(
        ReliableChannel(
            receiver_transport,
            "B",
            "B",
            "resolver-observation",
            ReliabilityPolicy(3, 2),
            peer="A",
        ),
        target_pid=pid,
    )
    assert receiver.receive(vm) == (1, observation)
    task = vm.scheduler.tasks[pid]
    assert task.backend.read_register("resolver_time") == 20
    assert task.backend.read_register("resolver_hit") == 0
    assert task.backend.read_register("resolver_ttl") == 300
    assert task.backend.read_register("resolver_status") == 0

    sender_after_restore = ResolverObservationEndpoint.from_snapshot(sender_snapshot, receiver_transport)
    assert sender_after_restore.process_ack() == (1,)
    assert sender_after_restore.channel.pending_sequences() == ()

    restored_vm = MailCPUVirtualMachine.from_snapshot(vm.snapshot())
    restored_task = restored_vm.scheduler.tasks[pid]
    assert restored_task.backend.read_register("resolver_time") == 20
    assert restored_task.backend.read_register("resolver_ttl") == 300


def test_observation_duplicate_is_idempotent_and_conflict_is_rejected(tmp_path) -> None:
    r"""Mathematics: receipt map `A[(p,source,s)]` makes duplicate application a no-op and unequal payload a contradiction."""

    vm, pid = _vm_with_target()
    path = tmp_path / "duplicate-observation.log"
    transport = DurableMailboxTransport(path)
    receiver_channel = ReliableChannel(
        transport,
        "B",
        "B",
        "resolver-observation",
        peer="A",
    )
    endpoint = ResolverObservationEndpoint(receiver_channel, target_pid=pid)
    first = ResolverObservation("A", "duplicate.test", "A", 1, "NOERROR", True, 9, "192.0.2.1")
    transport.send("B", Message("A", "B", "RDATA", "B", body=("resolver-observation", 1, first.to_payload())))
    assert endpoint.receive(vm) == (1, first)
    epoch_after_first = vm.scheduler.system_epoch.event_lambda

    duplicate = transport.send(
        "B",
        Message("A", "B", "RDATA", "B", body=("resolver-observation", 1, first.to_payload())),
    )
    assert duplicate.message_id
    assert endpoint.receive(vm) is None
    assert vm.scheduler.system_epoch.event_lambda == epoch_after_first

    conflict = ResolverObservation("A", "duplicate.test", "A", 1, "NOERROR", True, 8, "192.0.2.1")
    transport.send("B", Message("A", "B", "RDATA", "B", body=("resolver-observation", 1, conflict.to_payload())))
    with pytest.raises(ValueError, match="conflicts with prior payload"):
        endpoint.receive(vm)
    assert len(transport.list("B")) == 1


def test_apply_before_consume_recovers_from_checkpoint_between_the_two_steps(tmp_path) -> None:
    r"""Mathematics: if `A` is checkpointed after apply but before consume, replay has `A' = A` and still performs `Q→Q\{F_s}`."""

    vm, pid = _vm_with_target()
    path = tmp_path / "apply-before-consume.log"
    transport = DurableMailboxTransport(path)
    receiver_channel = ReliableChannel(
        transport,
        "B",
        "B",
        "resolver-observation",
        peer="A",
    )
    endpoint = ResolverObservationEndpoint(receiver_channel, target_pid=pid)
    observation = ResolverObservation("A", "crash-order.test", "A", 3, "NXDOMAIN", True, 2, "")
    transport.send("B", Message("A", "B", "RDATA", "B", body=("resolver-observation", 1, observation.to_payload())))

    sequence, payload = receiver_channel.peek() or (0, None)
    assert sequence == 1
    vm.apply_resolver_observation(pid, ResolverObservation.from_payload(payload), sequence)
    checkpointed_vm = MailCPUVirtualMachine.from_snapshot(vm.snapshot())
    assert checkpointed_vm.scheduler.tasks[pid].backend.read_register("resolver_status") == 1

    restored_endpoint = ResolverObservationEndpoint.from_snapshot(endpoint.snapshot(), transport)
    assert restored_endpoint.receive(checkpointed_vm) == (1, observation)
    assert transport.list("B") == ()


def test_timing_observation_captures_integer_phase_and_resumes_pll_state() -> None:
    r"""Mathematics: `T=encode(y,d,b',q,e)` is float-free and producer snapshot preserves the PLL recurrence."""

    config = TimingChannelConfig(base_delay_ms=20.0, quantum_ms=5.0, bits_per_symbol=4, pll_alpha=0.1)
    producer = TimingObservationProducer("timing-A", CadenceDemodulator(config))
    first = producer.observe_interval(4, 35.25)
    assert first == TimingObservation.from_payload(first.to_payload())
    assert first.symbol == 3
    assert first.observed_us == 35250
    assert first.quantum_us == 5000
    assert first.phase_error_us == 250
    assert first.tracked_base_us == 20025
    assert all(isinstance(value, int) for value in first.register_values().values())

    restored = TimingObservationProducer.from_snapshot(producer.snapshot())
    assert restored.observe_interval(5, 40.25) == producer.observe_interval(5, 40.25)


def test_delay_observation_preserves_recovery_and_explicit_loss() -> None:
    r"""Mathematics: `k`-of-`n` CRT success carries `V`, while `<k` survivors carry `(None,False,lost=True)`."""

    engine = DelayLoopEngine()
    group = engine.add_group(50000, 3, primes_below(200, 5))
    readable = DelayObservation.from_engine("delay-A", 7, engine, group.group_id)
    assert readable.ok is True
    assert readable.value == 50000
    assert readable.surviving_slots == 5
    assert DelayObservation.from_payload(readable.to_payload()) == readable

    group.slots[0].alive = False
    group.slots[1].alive = False
    scrubbed = DelayObservation.from_engine("delay-A", 8, engine, group.group_id, operation="scrub")
    assert scrubbed.ok is True
    assert scrubbed.value == 50000
    assert scrubbed.surviving_slots == 3
    assert scrubbed.scrub_count == 1

    lost_group = engine.add_group(1234, 3, primes_below(150, 4))
    lost_group.slots[0].alive = False
    lost_group.slots[1].alive = False
    failed = DelayObservation.from_engine("delay-A", 9, engine, lost_group.group_id, operation="scrub")
    assert failed.ok is False
    assert failed.value is None
    assert failed.lost is True
    assert failed.register_values()["delay_value"] == -1


def test_generic_timing_endpoint_reaches_vm_and_ack_survives_restart(tmp_path) -> None:
    r"""Mathematics: timing observation `T --durable,reliable--> π(T)` survives sender and VM restoration."""

    vm, pid = _vm_with_target()
    path = tmp_path / "timing-observation.log"
    sender_transport = DurableMailboxTransport(path)
    sender = SubstrateObservationEndpoint(
        ReliableChannel(sender_transport, "A", "B", "timing-observation"),
        register_prefix="timing",
        observation_kind="timing",
    )
    observation = TimingObservationProducer("A").observe_interval(13, 35.0)
    assert sender.publish(observation) == 1
    sender_snapshot = sender.snapshot()

    receiver_transport = DurableMailboxTransport(path)
    receiver = SubstrateObservationEndpoint(
        ReliableChannel(
            receiver_transport,
            "B",
            "B",
            "timing-observation",
            peer="A",
        ),
        target_pid=pid,
        register_prefix="timing",
        observation_kind="timing",
    )
    assert receiver.receive(vm) == (1, observation)
    task = vm.scheduler.tasks[pid]
    assert task.backend.read_register("timing_time") == 13
    assert task.backend.read_register("timing_symbol") == 3
    assert task.backend.read_register("timing_delay_us") == 35000

    restored_sender = SubstrateObservationEndpoint.from_snapshot(sender_snapshot, receiver_transport)
    assert restored_sender.observation_kind == "timing"
    assert restored_sender.process_ack() == (1,)
    restored_vm = MailCPUVirtualMachine.from_snapshot(vm.snapshot())
    assert restored_vm.scheduler.tasks[pid].backend.read_register("timing_symbol") == 3


def test_endpoint_rejects_wrong_codec_without_consuming_or_acknowledging(tmp_path) -> None:
    r"""Mathematics: if `K_endpoint≠tag(payload)`, validation returns `⊥` before either `Q` or ACK state changes."""

    path = tmp_path / "wrong-observation-kind.log"
    transport = DurableMailboxTransport(path)
    receiver_channel = ReliableChannel(
        transport,
        "B",
        "B",
        "delay-observation",
        peer="A",
    )
    endpoint = SubstrateObservationEndpoint(
        receiver_channel,
        target_pid=1,
        observation_kind="delay",
    )
    timing = TimingObservationProducer("A").observe_interval(1, 35.0)
    transport.send(
        "B",
        Message("A", "B", "RDATA", "B", body=("delay-observation", 1, timing.to_payload())),
    )
    vm, _ = _vm_with_target()
    with pytest.raises(ObservationError, match="kind"):
        endpoint.receive(vm)
    assert len(transport.list("B")) == 1
    assert transport.list(receiver_channel.ack_address) == ()


def test_temporal_observation_quantizes_chemical_time_and_rejects_off_axis_phase() -> None:
    r"""Mathematics: `T=(λ,q(D),round(10^6τ),h,h-t,valid)` round-trips while non-quarter-turn `D` is refused."""

    epoch = SystemEpoch(event_lambda=7, chronon_phase=-1j, chemical_tau=2.25)
    observation = TemporalObservation.from_epoch(
        "chemical-A",
        3,
        epoch,
        HorizonTracker(task_id=4, t_horizon=10, family="test"),
    )
    assert observation.phase_quadrant == 1
    assert observation.chemical_tau_micro == 2_250_000
    assert observation.horizon_remaining == 7
    assert observation.horizon_valid is True
    assert TemporalObservation.from_payload(observation.to_payload()) == observation
    assert all(isinstance(value, int) for value in observation.register_values().values())

    with pytest.raises(ObservationError, match="quarter-turn"):
        TemporalObservation.from_epoch("chemical-A", 3, SystemEpoch(0, 0.5 + 0.5j, 1.0))


def test_temporal_scheduler_adapter_and_phase_codec_preserve_discrete_state() -> None:
    r"""Mathematics: scheduler projection observes `SystemEpoch` and chronofold projection preserves `q=active mod 4`."""

    from mailcpu.scheduler import DeterministicScheduler

    scheduler = DeterministicScheduler()
    pid = scheduler.add(
        Program((Instruction(Op.HALT),)),
        "chemical-worker",
        enable_chronofold=True,
        chemical_cost=1.5,
        t_horizon=5,
    )
    scheduler.run(max_ticks=1)
    temporal = TemporalObservation.from_scheduler("chemical-A", scheduler.tick, scheduler, pid)
    assert temporal.event_lambda == 1
    assert temporal.chemical_tau_micro == 1_500_000
    assert temporal.horizon == 5

    fold = ChronoFold(
        initial_tape=0,
        trace=[1, 2, 3, 4],
        period_header=0,
        period_length=1,
        period_stride=-1,
        active_chronons=6,
        sector_reads=2,
    )
    phase = PhaseObservation.from_chronofold("phase-A", 8, fold)
    assert phase.phase_quadrant == 2
    assert phase.trace_length == 4
    assert PhaseObservation.from_payload(phase.to_payload()) == phase
    with pytest.raises(ObservationError, match="quadrant"):
        PhaseObservation("phase-A", 8, 6, 2, 4, 1, 0, 1, -1)


def test_temporal_observation_reaches_vm_and_sender_ack_survives_restart(tmp_path) -> None:
    r"""Mathematics: fixed-point temporal observation `T --durable,reliable--> π(T)` is checkpoint-continuable."""

    vm, pid = _vm_with_target()
    path = tmp_path / "temporal-observation.log"
    sender_transport = DurableMailboxTransport(path)
    sender = SubstrateObservationEndpoint(
        ReliableChannel(sender_transport, "A", "B", "temporal-observation"),
        observation_kind="temporal",
        register_prefix="temporal",
    )
    observation = TemporalObservation.from_epoch(
        "A",
        11,
        SystemEpoch(9, 1 + 0j, 3.125),
        HorizonTracker(task_id=pid, t_horizon=20),
    )
    assert sender.publish(observation) == 1
    sender_snapshot = sender.snapshot()
    receiver_transport = DurableMailboxTransport(path)
    receiver = SubstrateObservationEndpoint(
        ReliableChannel(receiver_transport, "B", "B", "temporal-observation", peer="A"),
        target_pid=pid,
        observation_kind="temporal",
        register_prefix="temporal",
    )
    assert receiver.receive(vm) == (1, observation)
    task = vm.scheduler.tasks[pid]
    assert task.backend.read_register("temporal_event") == 9
    assert task.backend.read_register("temporal_phase") == 0
    assert task.backend.read_register("temporal_chemical_micro") == 3_125_000
    assert task.backend.read_register("temporal_remaining") == 9
    assert SubstrateObservationEndpoint.from_snapshot(sender_snapshot, receiver_transport).process_ack() == (1,)
    restored_vm = MailCPUVirtualMachine.from_snapshot(vm.snapshot())
    assert restored_vm.scheduler.tasks[pid].backend.read_register("temporal_valid") == 1


def test_phase_observation_reaches_vm_without_float_registers(tmp_path) -> None:
    r"""Mathematics: reversible phase payload `P` projects only integer counters and quarter-turn code into VM state."""

    vm, pid = _vm_with_target()
    path = tmp_path / "phase-observation.log"
    sender_transport = DurableMailboxTransport(path)
    sender = SubstrateObservationEndpoint(
        ReliableChannel(sender_transport, "A", "B", "phase-observation"),
        observation_kind="phase",
        register_prefix="phase",
    )
    observation = PhaseObservation.from_chronofold(
        "A",
        12,
        ChronoFold(initial_tape=0, trace=[1, 2, 3], active_chronons=5, sector_reads=4),
    )
    assert sender.publish(observation) == 1
    receiver_transport = DurableMailboxTransport(path)
    receiver = SubstrateObservationEndpoint(
        ReliableChannel(receiver_transport, "B", "B", "phase-observation", peer="A"),
        target_pid=pid,
        observation_kind="phase",
        register_prefix="phase",
    )
    assert receiver.receive(vm) == (1, observation)
    task = vm.scheduler.tasks[pid]
    assert task.backend.read_register("phase_active") == 5
    assert task.backend.read_register("phase_quadrant") == 1
    assert task.backend.read_register("phase_trace") == 3
    assert all(isinstance(value, int) for value in observation.register_values().values())


def test_gated_coordinator_admission_finalization_and_atomic_commit(tmp_path) -> None:
    r"""Mathematics: `peek→ingest→finalize→save→consume→apply→consume` authorizes one representative exactly once."""

    vm, pid, path, transport, sender_a, sender_b, coordinator = _gated_fixture(tmp_path)
    observation_a = TimingObservationProducer("A").observe_interval(30, 35.0)
    observation_b = TimingObservationProducer("B").observe_interval(30, 35.0)
    assert sender_a.send(observation_a.to_payload()) == 1
    assert sender_b.send(observation_b.to_payload()) == 1
    links = coordinator.ingest_available()
    assert {link.source for link in links} == {"A", "B"}
    assert len(transport.list("R-A")) == 1
    assert len(transport.list("R-B")) == 1
    assert coordinator.finalize_event("timing", 30).status == "AUTHORIZED"
    assert vm.scheduler.tasks[pid].backend.read_register("gated_symbol") == 0
    result = coordinator.commit_event("timing", 30, path.with_suffix(".checkpoint"))
    assert result.status == "AUTHORIZED"
    assert vm.scheduler.tasks[pid].backend.read_register("gated_symbol") == 3
    assert transport.list("R-A") == ()
    assert transport.list("R-B") == ()
    assert coordinator.process_acks({"A": sender_a, "B": sender_b}) == {"A": (1,), "B": (1,)}
    assert coordinator.commit_event("timing", 30, path.with_suffix(".checkpoint")).status == "AUTHORIZED"
    assert vm.scheduler.system_epoch.event_lambda == 1


def test_gated_commit_refuses_pending_or_conflicting_evidence(tmp_path) -> None:
    r"""Mathematics: only `δ(e)=AUTHORIZED` enters commit; missing quorum and dissent cannot alter VM state."""

    vm, pid, path, _transport, sender_a, _sender_b, coordinator = _gated_fixture(tmp_path)
    observation_a = TimingObservationProducer("A").observe_interval(31, 35.0)
    assert sender_a.send(observation_a.to_payload()) == 1
    coordinator.ingest_available()
    assert coordinator.status("timing", 31).status == "PENDING"
    with pytest.raises(GatedObservationError, match="AUTHORIZED"):
        coordinator.commit_event("timing", 31, path.with_suffix(".checkpoint"))
    assert vm.scheduler.system_epoch.event_lambda == 0
    assert vm.scheduler.tasks[pid].backend.read_register("gated_symbol") == 0


def test_gated_checkpoint_recovers_after_apply_before_representative_consume(tmp_path) -> None:
    r"""Mathematics: checkpoint after `apply` and before `consume` replays representative frame as VM receipt no-op."""

    vm, pid, path, transport, sender_a, sender_b, coordinator = _gated_fixture(tmp_path)
    observation_a = TimingObservationProducer("A").observe_interval(32, 35.0)
    observation_b = TimingObservationProducer("B").observe_interval(32, 35.0)
    sender_a.send(observation_a.to_payload())
    sender_b.send(observation_b.to_payload())
    coordinator.ingest_available()
    coordinator.finalize_event("timing", 32)
    checkpoint = path.with_suffix(".checkpoint")
    coordinator._apply_representative(("timing", 32), checkpoint)
    assert vm.scheduler.tasks[pid].backend.read_register("gated_symbol") == 3
    restored = load_gated_checkpoint(checkpoint, {"A": transport, "B": transport})
    assert restored.vm.scheduler.tasks[pid].backend.read_register("gated_symbol") == 3
    assert len(transport.list("R-A")) == 1
    restored.commit_event("timing", 32, checkpoint)
    assert transport.list("R-A") == ()
    assert restored.vm.scheduler.system_epoch.event_lambda == 1


def test_gated_checkpoint_recovers_after_frame_consumption_before_post_save(tmp_path) -> None:
    r"""Mathematics: persisted consume intent plus absent `F_s` proves the prior receive completed after restart."""

    vm, pid, path, transport, sender_a, sender_b, coordinator = _gated_fixture(tmp_path)
    observation_a = TimingObservationProducer("A").observe_interval(33, 35.0)
    observation_b = TimingObservationProducer("B").observe_interval(33, 35.0)
    sender_a.send(observation_a.to_payload())
    sender_b.send(observation_b.to_payload())
    coordinator.ingest_available()
    coordinator.finalize_event("timing", 33)
    checkpoint = path.with_suffix(".checkpoint")
    coordinator._apply_representative(("timing", 33), checkpoint)
    representative = coordinator._representatives[("timing", 33)]
    coordinator._consume_intents.setdefault(("timing", 33), {})[representative.source] = representative
    coordinator.save_checkpoint(checkpoint)
    coordinator.channels[representative.source].receive()
    assert transport.list("R-A") == ()

    restored = load_gated_checkpoint(checkpoint, {"A": transport, "B": transport})
    restored.commit_event("timing", 33, checkpoint)
    assert restored.vm.scheduler.tasks[pid].backend.read_register("gated_symbol") == 3
    assert restored.vm.scheduler.system_epoch.event_lambda == 1
    assert transport.list("R-B") == ()


def test_gated_checkpoint_digest_tamper_fails_closed(tmp_path) -> None:
    r"""Mathematics: an altered checkpoint state `S'≠S` fails when `SHA256(S')≠digest(S)` before VM restoration."""

    _vm, _pid, path, transport, sender_a, sender_b, coordinator = _gated_fixture(tmp_path)
    observation_a = TimingObservationProducer("A").observe_interval(34, 35.0)
    observation_b = TimingObservationProducer("B").observe_interval(34, 35.0)
    sender_a.send(observation_a.to_payload())
    sender_b.send(observation_b.to_payload())
    coordinator.ingest_available()
    coordinator.finalize_event("timing", 34)
    checkpoint = path.with_suffix(".checkpoint")
    coordinator.save_checkpoint(checkpoint)
    raw = checkpoint.read_text(encoding="utf-8")
    checkpoint.write_text(raw.replace('"register_prefix": "gated"', '"register_prefix": "tampered"', 1), encoding="utf-8")
    with pytest.raises(GatedObservationError, match="digest"):
        load_gated_checkpoint(checkpoint, {"A": transport, "B": transport})


def test_gated_checkpoint_rejects_hashed_but_stale_live_frame(tmp_path) -> None:
    r"""Mathematics: even when `digest(S')` is recomputed, restore requires `head(Q_s)=L(e,s)` for every unconsumed link."""

    _vm, _pid, path, transport, sender_a, sender_b, coordinator = _gated_fixture(tmp_path)
    observation_a = TimingObservationProducer("A").observe_interval(35, 35.0)
    observation_b = TimingObservationProducer("B").observe_interval(35, 35.0)
    sender_a.send(observation_a.to_payload())
    sender_b.send(observation_b.to_payload())
    coordinator.ingest_available()
    coordinator.finalize_event("timing", 35)
    checkpoint = path.with_suffix(".checkpoint")
    coordinator.save_checkpoint(checkpoint)

    document = json.loads(checkpoint.read_text(encoding="utf-8"))
    source_link = document["state"]["coordinator"]["links"][0]["sources"][0]
    source_link["sequence"] = 2
    representative_link = document["state"]["coordinator"]["representatives"][0]["link"]
    representative_link["sequence"] = 2
    state = document["state"]
    document["digest"] = hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    checkpoint.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(GatedObservationError, match="live reliable frame"):
        load_gated_checkpoint(checkpoint, {"A": transport, "B": transport})


def test_gated_checkpoint_rejects_missing_consensus_link(tmp_path) -> None:
    r"""Mathematics: restore requires equality of event/source relations `dom(E)=dom(L)` and refuses a hashed partial projection."""

    _vm, _pid, path, transport, sender_a, sender_b, coordinator = _gated_fixture(tmp_path)
    observation_a = TimingObservationProducer("A").observe_interval(36, 35.0)
    observation_b = TimingObservationProducer("B").observe_interval(36, 35.0)
    sender_a.send(observation_a.to_payload())
    sender_b.send(observation_b.to_payload())
    coordinator.ingest_available()
    checkpoint = path.with_suffix(".checkpoint")
    coordinator.save_checkpoint(checkpoint)

    document = json.loads(checkpoint.read_text(encoding="utf-8"))
    del document["state"]["coordinator"]["links"][0]
    state = document["state"]
    document["digest"] = hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    checkpoint.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(GatedObservationError, match="different events"):
        load_gated_checkpoint(checkpoint, {"A": transport, "B": transport})


def test_gated_multi_event_fifo_recovers_lost_ack_retransmissions_after_checkpoint(tmp_path) -> None:
    r"""Mathematics: physical retries may interleave as `F_2,F'_1,F'_2`, while gated commits apply events exactly once in logical order `1,2`."""

    vm, pid, path, transport, sender_a, sender_b, coordinator = _gated_fixture(tmp_path)
    first_a = TimingObservationProducer("A").observe_interval(40, 35.0)
    first_b = TimingObservationProducer("B").observe_interval(40, 35.0)
    second_a = TimingObservationProducer("A").observe_interval(41, 40.0)
    second_b = TimingObservationProducer("B").observe_interval(41, 40.0)
    assert sender_a.send(first_a.to_payload()) == 1
    assert sender_a.send(second_a.to_payload()) == 2
    assert sender_b.send(first_b.to_payload()) == 1
    assert sender_b.send(second_b.to_payload()) == 2

    assert {link.event for link in coordinator.ingest_available()} == {("timing", 40)}
    assert coordinator.finalize_event("timing", 40).status == "AUTHORIZED"
    checkpoint = path.with_suffix(".checkpoint")
    coordinator.commit_event("timing", 40, checkpoint)
    assert vm.scheduler.system_epoch.event_lambda == 1

    for _ in range(3):
        sender_a.tick()
        sender_b.tick()
    restored = load_gated_checkpoint(checkpoint, {"A": transport, "B": transport})
    assert {link.event for link in restored.ingest_available()} == {("timing", 41)}
    assert restored.finalize_event("timing", 41).status == "AUTHORIZED"
    restored.commit_event("timing", 41, checkpoint)
    assert restored.ingest_available() == ()
    assert transport.list("R-A") == ()
    assert transport.list("R-B") == ()
    assert restored.vm.scheduler.system_epoch.event_lambda == 2
    assert restored.vm.scheduler.tasks[pid].backend.read_register("gated_symbol") == 4
    assert restored.process_acks({"A": sender_a, "B": sender_b}) == {"A": (1, 2), "B": (1, 2)}
    assert sender_a.pending_sequences() == ()
    assert sender_b.pending_sequences() == ()


def test_strict_consensus_requires_matching_all_sources_and_is_snapshotable() -> None:
    r"""Mathematics: strict authority requires `∀s∈A, E_e[s]=C*` and explicit finalization before authorization."""

    policy = ObservationAuthorityPolicy("timing", ("A", "B"), quorum=2, strict=True)
    consensus = ObservationConsensus(policy)
    observation_a = TimingObservationProducer("A").observe_interval(21, 35.0)
    observation_b = TimingObservationProducer("B").observe_interval(21, 35.0)
    assert consensus.ingest(observation_a).status == "PENDING"
    assert consensus.ingest(observation_b).status == "QUORUM"
    assert consensus.status("timing", 21).status == "QUORUM"
    assert consensus.authorized_observation("timing", 21) is None
    finalized = consensus.finalize("timing", 21)
    assert finalized.status == "AUTHORIZED"
    assert consensus.authorized_observation("timing", 21) == observation_a

    restored = ObservationConsensus.from_snapshot(consensus.snapshot())
    assert restored.status("timing", 21) == finalized
    assert restored.authorized_observation("timing", 21) == observation_a


def test_consensus_rejects_disagreement_and_same_source_rewrite() -> None:
    r"""Mathematics: unequal canonical payloads create `CONFLICT`; `E_e[s]≠payload` raises without overwriting evidence."""

    strict = ObservationConsensus(ObservationAuthorityPolicy("timing", ("A", "B"), 2))
    first = TimingObservationProducer("A").observe_interval(3, 35.0)
    different = TimingObservationProducer("B").observe_interval(3, 40.0)
    strict.ingest(first)
    assert strict.ingest(different).status == "CONFLICT"
    assert strict.finalize("timing", 3).status == "CONFLICT"
    assert strict.authorized_observation("timing", 3) is None

    same_source = ObservationConsensus(ObservationAuthorityPolicy("timing", ("A", "B"), 2))
    same_source.ingest(first)
    rewrite = TimingObservation("A", 3, 40000, 4, 20000, 5000, 0)
    with pytest.raises(ObservationConflictError, match="conflicting payload"):
        same_source.ingest(rewrite)
    assert same_source.status("timing", 3).status == "CONFLICT"


def test_non_strict_quorum_records_dissent_without_claiming_truth() -> None:
    r"""Mathematics: non-strict policy authorizes `|G*|≥q` while retaining `D=A\G*` as dissent telemetry."""

    consensus = ObservationConsensus(
        ObservationAuthorityPolicy("timing", ("A", "B", "C"), quorum=2, strict=False)
    )
    accepted_a = TimingObservationProducer("A").observe_interval(5, 35.0)
    accepted_b = TimingObservationProducer("B").observe_interval(5, 35.0)
    dissent = TimingObservationProducer("C").observe_interval(5, 40.0)
    consensus.ingest(accepted_a)
    consensus.ingest(accepted_b)
    decision = consensus.ingest(dissent)
    assert decision.status == "QUORUM"
    assert decision.dissenting_sources == ("C",)
    assert consensus.finalize("timing", 5).status == "AUTHORIZED"
    assert consensus.authorized_observation("timing", 5) == accepted_a


def test_consensus_is_not_vm_execution_authority() -> None:
    r"""Mathematics: consensus state `C` changes no VM register or epoch until explicit `apply_substrate_observation` is invoked."""

    vm, pid = _vm_with_target()
    consensus = ObservationConsensus(ObservationAuthorityPolicy("phase", ("A", "B"), 2))
    phase_a = PhaseObservation.from_chronofold("A", 2, ChronoFold(initial_tape=0, active_chronons=5))
    phase_b = PhaseObservation.from_chronofold("B", 2, ChronoFold(initial_tape=0, active_chronons=5))
    consensus.ingest(phase_a)
    consensus.ingest(phase_b)
    assert consensus.finalize("phase", 2).status == "AUTHORIZED"
    assert vm.scheduler.system_epoch.event_lambda == 0
    assert vm.scheduler.tasks[pid].backend.read_register("phase_quadrant") == 0
    vm.apply_substrate_observation(pid, consensus.authorized_observation("phase", 2), 1, "phase")
    assert vm.scheduler.system_epoch.event_lambda == 1
    assert vm.scheduler.tasks[pid].backend.read_register("phase_quadrant") == 1
