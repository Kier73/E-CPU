# Invariant Registry

Machine-checkable invariants. Each entry names the invariant, the module that
establishes it, the test that would fail if it were violated, and the clause of
the specification that requires it.

`scripts/verify_invariants.py` checks that every registry entry still resolves:
that the named test exists, that the named module still exists, and that the
named symbol is still defined. An entry that has become unresolvable is a
defect, because it means an invariant has lost its enforcement point.

## Reading this document

An invariant is a statement that MUST hold for every execution admitted to the
system. Each entry has:

| Field | Meaning |
|---|---|
| `ID` | Stable identifier. Never reused. |
| `Statement` | The invariant, in one sentence. |
| `Establishes` | The module whose code establishes it. |
| `Enforced by` | The test that fails on violation. |
| `Required by` | The specification clause making it mandatory. |

## Transition algebra

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `T-1` | `T` is total on validated programs and returns `step_limit` rather than halting when the step budget is exhausted. | `mailcpu/interpreter.py` | `tests/test_conformance.py::test_step_budget_exhaustion_reports_step_limit_not_halt` | `README.md` 3 |
| `T-2` | Every backend agrees with the reference interpreter on `(status, state, trace, outputs)`. | `mailcpu/interpreter.py` | `tests/test_conformance.py::test_differential_random_program_corpus` | `README.md` 2 |
| `T-3` | Every `BRANCH` target satisfies `0 <= j < n` for program length `n`. | `mailcpu/model.py` | `tests/test_conformance.py::test_invalid_branch_target_is_exposed` | `README.md` 2 |
| `T-4` | `SYSCALL` is refused by the reference and mailbox interpreters. | `mailcpu/interpreter.py` | `tests/test_runtime.py::test_reference_and_mailbox_interpreters_refuse_syscall` | `README.md` 7 |
| `T-5` | The opcode arity table is single-sourced, so the validator and the assembler cannot disagree. | `mailcpu/model.py` | `tests/test_assembler.py::test_opcode_arity_is_single_sourced_for_assembler_and_validator` | `README.md` 2 |
| `T-6` | The checked-in golden corpus equals both the reference and queue execution projections, and its recorder verifies by default instead of rewriting evidence. | `scripts/record_golden.py`, `mailcpu/interpreter.py` | `tests/test_golden_traces.py::test_checked_in_golden_traces_match_reference_and_queue`, `tests/test_golden_traces.py::test_golden_recorder_verifies_without_rewriting` | `README.md` 2 |

## Determinism and canonical form

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `D-1` | Logical time advances by exactly one per accepted event and is not derived from wall-clock time. | `mailcpu/journal.py` | `tests/test_runtime.py::test_logical_time_advances_exactly_one_per_accepted_event` | `README.md` 5 |
| `D-2` | Canonical trace and result forms are invariant under transport message identity. | `mailcpu/model.py` | `tests/test_conformance.py::test_differential_random_program_corpus` | `README.md` 2 |
| `D-3` | The canonical value algebra is injective and invariant under mapping-key permutation. | `mailcpu/_codec.py` | `tests/test_codec.py::test_canonical_algebra_distinguishes_container_types`, `tests/test_codec.py::test_canonical_encoding_is_permutation_invariant` | `REPLACEMENT_SPEC.md` 7.11 |
| `D-4` | The transport value algebra preserves scalars and bytes; canonical external paths preserve tuple identity. | `mailcpu/_codec.py`, `mailcpu/socket_transport.py` | `tests/test_codec.py::test_transport_algebra_round_trips_scalars_and_bytes`, `tests/test_socket_transport.py::test_tcp_loopback_transports_typed_messages_and_preserves_fifo` | `REPLACEMENT_SPEC.md` 7.11 |
| `D-5` | A digest is never computed over a non-canonical encoding. | `mailcpu/durable_transport.py` | `tests/test_durable_transport.py::test_durable_mailbox_rejects_tampered_complete_records` | `REPLACEMENT_SPEC.md` 7.11 |
| `D-6` | An externally connected revision relay preserves the canonical proposal body through TCP framing, durable mailbox decode, quorum replication, and remote hypervisor admission. | `mailcpu/socket_transport.py`, `mailcpu/revision_relay.py` | `tests/test_external_connections.py::test_external_tcp_revision_encoding_and_hypervisor_admission` | `INTEGRATION_SPEC.md` 10.4 |

## Receipts, journal, and checkpoints

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `J-1` | The event journal is a hash chain `H_n = SHA256(H_{n-1} \|\| c_n)`. | `mailcpu/journal.py` | `tests/test_runtime.py::test_event_journal_is_a_sha256_hash_chain` | `GLOSSARY.md` receipt |
| `J-2` | A record failing chain verification causes construction or restore to fail. | `mailcpu/journal.py` | `tests/test_checkpoint.py::test_checkpoint_detects_tampering` | `README.md` 7 |
| `C-1` | Checkpoint restore rejects a state whose digest does not match its content. | `mailcpu/checkpoint.py` | `tests/test_checkpoint.py::test_checkpoint_detects_tampering` | `README.md` 5 |
| `C-2` | Checkpointed state round-trips without loss for every admitted component. | `mailcpu/checkpoint.py` | `tests/test_checkpoint.py::test_checkpoint_restores_process_filesystem_bus_and_memory`, `tests/test_checkpoint.py::test_checkpoint_preserves_service_controller` | `README.md` 5 |
| `C-3` | Trajectory records are indexed by `(sequence, logical_time, byte_offset)` and are receipt-verifiable. | `mailcpu/trajectory.py` | `tests/test_trajectory.py::test_trajectory_receipts_index_seek_and_replay` | `GLOSSARY.md` trajectory |
| `C-4` | A persisted single-task scheduler trajectory preserves the semantic instruction projection and matches the reference interpreter trace. | `mailcpu/vm.py`, `mailcpu/scheduler.py` | `tests/test_trajectory.py::test_vm_semantic_trajectory_replays_reference_trace` | `INTEGRATION_SPEC.md` 2.3 |
| `C-5` | A digest-checked checkpoint restore produces the same post-checkpoint semantic trajectory as uninterrupted execution. | `mailcpu/checkpoint.py`, `mailcpu/headless.py` | `tests/test_checkpoint.py::test_checkpoint_resume_matches_uninterrupted_semantic_trajectory` | `INTEGRATION_SPEC.md` 4.2 |
| `C-6` | Trajectory resume verifies the existing prefix and preserves its sequence, logical time, sparse-index stride, and receipt-chain identity without truncation. | `mailcpu/trajectory.py` | `tests/test_trajectory.py::test_trajectory_resume_appends_one_verified_receipt_chain`, `tests/test_trajectory.py::test_trajectory_resume_refuses_tampered_prefix` | `INTEGRATION_SPEC.md` 2.3 |
| `C-7` | A checkpoint taken with one task blocked and another task ready preserves the ready order, FIFO mailbox causality, per-task semantic trajectory, and terminal state across restore. | `mailcpu/scheduler.py`, `mailcpu/bus.py`, `mailcpu/checkpoint.py` | `tests/test_checkpoint.py::test_multitask_checkpoint_resume_preserves_causal_mailbox_trajectory` | `INTEGRATION_SPEC.md` 4.2 |

## Authority

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `A-1` | Authorisation is a function of held capabilities alone. | `mailcpu/kernel.py` | `tests/test_classifier.py::test_headless_dispatch_derives_grants_from_kernel_capabilities` | `ARCHITECTURE.md` 5 |
| `A-2` | A request whose capability right is absent is denied regardless of model confidence. | `mailcpu/classifier.py` | `tests/test_classifier.py::test_hypervisor_denies_missing_authority_and_reviews_ambiguity` | `ARCHITECTURE.md` 5 |
| `A-3` | Only an explicit `ALLOW` reaches a registered handler. | `mailcpu/classifier.py` | `tests/test_classifier.py::test_hypervisor_allows_clear_read_and_dispatches_one_handler`, `tests/test_classifier.py::test_headless_dispatch_derives_grants_from_kernel_capabilities` | `ARCHITECTURE.md` 5 |
| `A-4` | Every hypervisor decision is appended to the journal before the reply returns. | `mailcpu/classifier.py` | `tests/test_classifier.py::test_hypervisor_decision_is_journaled_before_the_reply` | `ARCHITECTURE.md` 7.9 |
| `A-5` | `SIGKILL` and `SIGSTOP` are non-ignorable. | `mailcpu/kernel.py` | `tests/test_signals_environment.py::test_kill_and_stop_dispositions_cannot_be_ignored` | `REPLACEMENT_SPEC.md` 7.5 |
| `A-6** | The default exit code for a fatal signal is single-sourced in the signal vocabulary. | `mailcpu/signals.py` | `tests/test_public_surface.py::test_signal_vocabulary_is_the_single_source_of_default_exit_codes` | `ARCHITECTURE.md` 7.2 |

| `A-7` | The arbitration loop admits one decision per `(source, channel, sequence)`, reuses the original receipt on an exact retransmission, and refuses a changed payload under that identity across checkpoint restore. | `mailcpu/classifier.py`, `mailcpu/headless.py` | `tests/test_classifier.py::test_hypervisor_rsi_loop_reuses_exact_retransmission_receipt`, `tests/test_classifier.py::test_hypervisor_rsi_loop_refuses_conflicting_retransmission`, `tests/test_classifier.py::test_hypervisor_rsi_loop_ledger_survives_checkpoint_restore` | `INTEGRATION_SPEC.md` 12.1 |
| `A-8` | A candidate classifier replaces the active model only after reproducing every supplied policy witness in a shadow hypervisor; a mismatch preserves the active model and records refusal. | `mailcpu/classifier.py` | `tests/test_classifier.py::test_hypervisor_revision_gate_admits_witnessed_candidate_and_restores`, `tests/test_classifier.py::test_hypervisor_revision_gate_refuses_mismatch_without_replacing_active_model` | `INTEGRATION_SPEC.md` 12.1 |
| `A-9` | Every arbitration decision and exact retransmission is bound to the classifier revision that produced the original receipt, including after checkpoint restore. | `mailcpu/classifier.py`, `mailcpu/headless.py` | `tests/test_classifier.py::test_hypervisor_arbitration_binds_revision_across_replay_and_restore` | `INTEGRATION_SPEC.md` 12.1 |
| `A-10` | A revision proposal admits at most once per `(source, channel, sequence)`, replays the stored admission after checkpoint restore, and refuses changed or unconstructable candidates without mutating authority. | `mailcpu/classifier.py`, `mailcpu/headless.py` | `tests/test_classifier.py::test_hypervisor_revision_proposal_is_idempotent_and_checkpointable`, `tests/test_classifier.py::test_hypervisor_revision_proposal_refuses_conflict_and_bad_model_without_mutation` | `INTEGRATION_SPEC.md` 12.1 |
| `A-11` | A revision proposal is acknowledged only after typed reconstruction and peer binding succeed; malformed transport payloads remain queued and cannot reach revision admission. | `mailcpu/revision_transport.py` | `tests/test_revision_transport.py::test_revision_transport_refuses_malformed_payload_before_acknowledgement` | `INTEGRATION_SPEC.md` 12.1 |
| `A-12` | The composed revision receive path arbitrates while the reliable frame remains queued; a conflicting proposal is refused before dequeue or acknowledgement. | `mailcpu/revision_transport.py` | `tests/test_revision_transport.py::test_revision_transport_keeps_conflicting_proposal_queued_before_ack` | `INTEGRATION_SPEC.md` 12.1 |
| `A-13` | A durable revision relay persists proposals through the replicated mailbox before transport acknowledgement, preserves FIFO across remote-store reopen, and consumes only after hypervisor arbitration; malformed or conflicting messages remain queued. | `mailcpu/revision_relay.py`, `mailcpu/replicated_mailbox.py` | `tests/test_revision_relay.py::test_replicated_revision_relay_preserves_fifo_quorum_and_restart`, `tests/test_revision_relay.py::test_replicated_revision_relay_leaves_malformed_and_conflicting_messages_queued` | `INTEGRATION_SPEC.md` 10.4 |
| `A-14` | A typed intent revision reconstructs only an `IntentPrototypeModel`, reproduces every held-out prediction, and cannot make any witnessed action more permissive; target identity, admission, and exact replay survive checkpoint and external relay. | `mailcpu/classifier.py`, `mailcpu/revision_relay.py` | `tests/test_classifier.py::test_hypervisor_intent_revision_is_typed_witnessed_and_checkpointable`, `tests/test_classifier.py::test_hypervisor_intent_revision_refuses_stale_baseline_without_mutation`, `tests/test_external_connections.py::test_external_tcp_intent_revision_training_reaches_remote_hypervisor` | `INTEGRATION_SPEC.md` 12.1 |
| `A-15` | After a peer reset, restored reliable/channel/mailbox state retransmits the pending sequence, recovers the lost acknowledgement, applies the equal durable operation once, and admits the target-aware proposal once. | `mailcpu/socket_transport.py`, `mailcpu/reliability.py`, `mailcpu/replicated_mailbox.py`, `mailcpu/revision_relay.py` | `tests/test_cross_host_recovery.py::test_external_recovery_reconnects_lost_ack_and_admits_one_intent_revision` | `INTEGRATION_SPEC.md` 10.5 |
| `A-16` | The cross-host recovery coordinator preserves the composite checkpoint product, rejects a direction-mismatched channel before binding, and reports transport, quorum, mailbox, and semantic admission state through the existing ledgers. | `mailcpu/recovery.py` | `tests/test_cross_host_recovery.py::test_external_recovery_reconnects_lost_ack_and_admits_one_intent_revision`, `tests/test_cross_host_recovery.py::test_recovery_checkpoint_roundtrip_and_direction_mismatch_fail_closed` | `INTEGRATION_SPEC.md` 10.5 |
| `A-17` | The typed process adapter allows exactly one executable launch only after `PROCESS` classification and `execute` authority; a caller without that right is denied with no process mutation. | `mailcpu/headless.py`, `mailcpu/classifier.py` | `tests/test_classifier.py::test_headless_hypervisor_process_adapter_gates_launch_by_execute_capability` | `INTEGRATION_SPEC.md` 10.6 |
| `A-18` | The typed package adapter classifies digest installation as `PACKAGE`, leaves the filesystem unchanged on default review or missing `write`, and installs only the registry-verified image after explicit destructive-policy admission. | `mailcpu/headless.py`, `mailcpu/classifier.py`, `mailcpu/registry.py` | `tests/test_classifier.py::test_headless_hypervisor_package_adapter_gates_verified_installation` | `INTEGRATION_SPEC.md` 10.6 |
| `A-19` | A multi-peer recovery checkpoint restores every peer factor under its original direction, replays a lost peer sequence idempotently, preserves partial quorum as uncommitted, and reaches commitment only when the existing `1+|A|≥q` predicate is satisfied. | `mailcpu/recovery.py`, `mailcpu/replicated_mailbox.py` | `tests/test_multi_peer_recovery.py::test_multi_peer_recovery_rebinds_lost_ack_and_preserves_quorum_state`, `tests/test_multi_peer_recovery.py::test_multi_peer_recovery_rejects_direction_mismatch_before_binding` | `INTEGRATION_SPEC.md` 10.5 |
| `A-20` | A hypervisor operation effect is committed at most once per `(source, channel, sequence)`; exact retransmission returns the canonical effect after checkpoint restore without invoking the handler, while changed payloads are refused and denied operations have no effect. | `mailcpu/classifier.py`, `mailcpu/headless.py` | `tests/test_classifier.py::test_hypervisor_effect_ledger_replays_process_launch_after_duplicate_and_restore`, `tests/test_classifier.py::test_hypervisor_effect_ledger_records_denial_without_invoking_handler` | `INTEGRATION_SPEC.md` 12.1 |
| `A-21` | A peer-bound hypervisor operation crosses the existing reliable/TCP path, is authorized from receiver-local capabilities, and after lost-ACK retransmission returns one checkpointed effect without duplicate native mutation; a forged remote right remains denied. | `mailcpu/hypervisor_transport.py`, `mailcpu/headless.py` | `tests/test_hypervisor_transport.py::test_operation_event_round_trips_over_real_tcp_and_receiver_rebuilds_authority` | `INTEGRATION_SPEC.md` 10.7 |
| `A-22` | An operation recovery checkpoint restores transport, reliable FIFO, and headless effect-ledger state under the original direction; retry/rebind/replay clears the sender's pending sequence without a second native mutation, and direction mismatch fails before binding. | `mailcpu/recovery.py` | `tests/test_operation_recovery.py::test_operation_recovery_coordinator_rebinds_lost_ack_and_replays_effect`, `tests/test_operation_recovery.py::test_operation_recovery_coordinator_refuses_direction_before_rebind` | `INTEGRATION_SPEC.md` 10.7 |
| `A-23` | A receiver-local digest-verified package image crosses the peer-bound operation path, is admitted only by explicit destructive policy, installs exact image bytes, and returns the verified digest effect. | `mailcpu/hypervisor_transport.py`, `mailcpu/recovery.py`, `mailcpu/registry.py` | `tests/test_remote_package_operation.py::test_remote_package_operation_installs_receiver_local_verified_image` | `INTEGRATION_SPEC.md` 10.7 |
| `A-24` | An operation result crosses a reverse reliable channel before request acknowledgement, and duplicate response transport frames return one checkpointed effect by semantic operation identity while preserving the single native mutation. | `mailcpu/hypervisor_transport.py` | `tests/test_operation_response.py::test_operation_response_returns_effect_and_deduplicates_after_lost_response_ack` | `INTEGRATION_SPEC.md` 10.7 |
| `A-25` | A duplex operation checkpoint restores request-outbound/response-inbound or request-inbound/response-outbound factors together, validates reciprocal peer identity, and survives both lost acknowledgements with one native effect; live process/package states can form an advisory intent candidate only when held-out prediction and monotonicity admit it. | `mailcpu/recovery.py` | `tests/test_duplex_operation_recovery.py::test_duplex_recovery_rebinds_both_loss_paths_and_trains_from_live_operations`, `tests/test_duplex_operation_recovery.py::test_duplex_recovery_rejects_role_mismatch_before_socket_rebind` | `INTEGRATION_SPEC.md` 10.7 |
| `A-26` | A receiver advertises typed recovery constraints over reliable AF_INET control frames; the sender's cross-transport offer yields only the bounded intersection or remains queued/refused, and the agreement round-trips with a stable digest. | `mailcpu/recovery_policy.py` | `tests/test_recovery_policy.py::test_receiver_advertised_policy_negotiates_over_real_tcp_and_round_trips`, `tests/test_recovery_policy.py::test_policy_channel_leaves_wrong_kind_queued_without_acknowledgement`, `tests/test_recovery_policy.py::test_policy_intersection_refuses_unsupported_or_unsafe_migration` | `INTEGRATION_SPEC.md` 10.7 |
| `A-27` | An exact recovery agreement moves a pending reliable channel from a real socket substrate into shared memory without changing protocol sequence or payload; a shadow-target preflight rejects invalid channel state before import; the migrated receiver delivers once, the target acknowledgement clears the sender, and agreement or target refusal leaves the target unchanged. | `mailcpu/migration.py` | `tests/test_cross_transport_migration.py::test_socket_channel_migrates_to_shared_memory_and_completes_original_fifo`, `tests/test_cross_transport_migration.py::test_cross_transport_migration_refuses_mismatched_agreement_without_target_mutation`, `tests/test_cross_transport_migration.py::test_cross_transport_migration_refuses_target_substrate_before_import`, `tests/test_cross_transport_migration.py::test_cross_transport_migration_preflights_channel_before_import` | `INTEGRATION_SPEC.md` 10.7 |
| `A-28` | An exact socket-to-memory agreement moves one duplex role's request/result channels, semantic result ledger, and hypervisor snapshot through one shadow target; retransmitted results replay without a second native effect, both ACK paths clear pending frames, and invalid response-ledger state leaves the target unchanged. | `mailcpu/migration.py`, `mailcpu/recovery.py` | `tests/test_cross_transport_duplex_migration.py::test_duplex_socket_state_migrates_into_one_memory_host_without_replaying_effect`, `tests/test_cross_transport_duplex_migration.py::test_duplex_migration_rejects_invalid_response_ledger_before_target_import` | `INTEGRATION_SPEC.md` 10.7 |
| `A-29` | A system seed round-trips a complete origin state, deterministically reaches a requested scheduler coordinate, rewinds by replay from the origin, and refuses origin tampering, expected-state digest mismatch, or unreachable coordinates. | `mailcpu/seed.py` | `tests/test_system_seed.py::test_system_seed_round_trips_exact_state_and_navigates_forward_and_backward`, `tests/test_system_seed.py::test_system_seed_rejects_tampered_origin_and_expected_state`, `tests/test_system_seed.py::test_system_seed_refuses_unreachable_coordinate` | `INTEGRATION_SPEC.md` 10.7 |
| `A-30` | A typed system seed envelope preserves complete seed state and external-input frontier across canonical encoding and both memory and AF_INET transport; distinct system identities/incarnations derive distinct routes, duplicate frontier receipts are refused, and digest, normalization, identity, or route changes fail before seed restoration. | `mailcpu/seed.py` | `tests/test_seed_envelope.py::test_seed_envelope_round_trips_and_separates_shared_mailboxes`, `tests/test_seed_envelope.py::test_seed_envelope_crosses_real_socket_transport`, `tests/test_seed_envelope.py::test_seed_envelope_rejects_tampering_before_state_restore`, `tests/test_seed_envelope.py::test_seed_envelope_freezes_frontier_and_rejects_duplicate_receipts`, `tests/test_seed_envelope.py::test_seed_envelope_rejects_route_mismatch_before_restore`, `tests/test_seed_envelope.py::test_seed_envelope_restore_requires_expected_identity`, `tests/test_seed_envelope.py::test_seed_envelope_rejects_digest_valid_noncanonical_payload` | `INTEGRATION_SPEC.md` 10.7 |
| `A-31` | The Hypervisor seed admission coordinator shadow-restores a candidate before mutation, admits new or higher-incarnation systems, enforces same-incarnation origin/frontier/coordinate monotonicity, replays exact envelope fingerprints with the original receipt, preserves the registry on refusal, and restores its registry and replay ledger through the OS checkpoint. | `mailcpu/seed_admission.py`, `mailcpu/headless.py` | `tests/test_seed_admission.py::test_seed_admission_accepts_monotone_progress_and_replays_exact_bytes`, `tests/test_seed_admission.py::test_seed_admission_refuses_stale_frontier_incarnation_and_digest_conflicts_without_mutation`, `tests/test_seed_admission.py::test_seed_admission_shadow_restores_before_registry_mutation`, `tests/test_seed_admission.py::test_seed_admission_checkpoint_restores_registry_and_replay_ledger`, `tests/test_seed_admission.py::test_seed_admission_supports_multiple_systems_in_one_hypervisor_registry` | `INTEGRATION_SPEC.md` 10.8 |
| `A-32` | A typed external input event carries a digest-bound payload and target coordinate, exact seed replay injects it before the target tick, rewind removes only later event suffixes, future events are refused, and Hypervisor frontier advancement admits the resulting envelope while exact retransmission replays its receipt without regressing a later FIFO frontier and changed payload conflicts. | `mailcpu/seed.py`, `mailcpu/seed_admission.py` | `tests/test_seed_input.py::test_system_seed_replays_external_input_and_rewinds_its_event_prefix`, `tests/test_seed_input.py::test_system_seed_rejects_input_event_digest_tampering`, `tests/test_seed_input.py::test_system_seed_rejects_future_input_events`, `tests/test_seed_input.py::test_hypervisor_seed_admission_advances_and_replays_live_input`, `tests/test_seed_input.py::test_hypervisor_seed_admission_retransmission_preserves_a_later_fifo_frontier` | `INTEGRATION_SPEC.md` 10.9 |

## Memory

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `M-1` | A write to a shared page allocates a new page hash and leaves the original immutable. | `mailcpu/memory.py` | `tests/test_runtime.py::test_virtual_memory_cross_page_write_and_copy_on_write` | `ARCHITECTURE.md` 7.3 |
| `M-2` | `mem_reclaim` evicts a private page losslessly and a later access restores it exactly. | `mailcpu/memory.py` | `tests/test_runtime.py::test_memory_reclaim_evicts_private_pages_and_faults_back_losslessly` | `ARCHITECTURE.md` 7.3 |
| `M-3` | Quota and capability checks fail before mutation. | `mailcpu/headless.py` | `tests/test_runtime.py::test_failed_quota_spawn_does_not_publish_process_state`, `tests/test_runtime.py::test_headless_memory_syscalls_cover_private_and_shared_abi` | `REPLACEMENT_SPEC.md` 7.9 |
| `M-4` | An unreserved access produces a typed page fault. | `mailcpu/memory.py` | `tests/test_runtime.py::test_virtual_memory_reports_typed_page_faults` | `REPLACEMENT_SPEC.md` 7.9 |
| `M-5** | An undersized destination returns `-ERANGE` before memory mutation. | `mailcpu/headless.py` | `tests/test_headless.py::test_scheduled_process_context_abi_packs_argv_environment_and_cwd_atomically` | `REPLACEMENT_SPEC.md` 7.4 |
| `M-6` | A read is non-consuming with respect to the register mailbox it observes. | `mailcpu/interpreter.py` | `tests/test_conformance.py::test_queue_register_read_is_non_consuming` | `PLAN.md` 4.5 |
| `M-7` | Remote-backed reclaim publishes a page identity before reservation, and a later fault restores exact bytes through the same digest. | `mailcpu/memory.py`, `mailcpu/remote_memory.py` | `tests/test_remote_memory.py::test_virtual_memory_reclaim_faults_through_remote_page_backing` | `ARCHITECTURE.md` 7.3 |
| `M-8` | Remote-backed reclaim and fault recovery restore exact page bytes through the same content identity when the page provider is reached over an external TCP path. | `mailcpu/memory.py`, `mailcpu/remote_memory.py`, `mailcpu/socket_transport.py` | `tests/test_external_connections.py::test_external_tcp_remote_page_backing_drives_virtual_memory_fault` | `INTEGRATION_SPEC.md` 10.4 |

## Dynamic ELF planning

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `E-1` | Dynamic ELF dependencies and relative relocations are decoded deterministically, while undefined symbols require explicit bindings. | `mailcpu/elf.py` | `tests/test_dynamic_elf.py::test_dynamic_elf_parses_dependencies_and_relative_relocation_plan`, `tests/test_dynamic_elf.py::test_dynamic_elf_requires_explicit_external_symbol_binding` | `INTEGRATION_SPEC.md` 11.5 |
| `E-2` | Dynamic linking commits staged images and relocation writes only after provider, target, and relocation preconditions pass. | `mailcpu/linker.py`, `mailcpu/memory.py` | `tests/test_linker.py::test_dynamic_linker_missing_provider_and_readonly_target_preserve_memory`, `tests/test_linker.py::test_dynamic_linker_resolves_provider_and_applies_relocation_transactionally` | `INTEGRATION_SPEC.md` 11.5 |
| `E-3` | An interpreted runtime loads main and interpreter graphs through one clone-then-commit transition and separates interpreter initial entry from main `AT_ENTRY`. | `mailcpu/linker.py`, `mailcpu/elf.py` | `tests/test_linker.py::test_dynamic_linker_runtime_loads_interpreter_and_builds_startup_handoff` | `INTEGRATION_SPEC.md` 11.5 |
| `E-4` | Missing interpreter providers preserve caller memory before any runtime handoff commit. | `mailcpu/linker.py` | `tests/test_linker.py::test_dynamic_linker_missing_interpreter_preserves_memory` | `INTEGRATION_SPEC.md` 11.5 |
| `E-5` | Startup stack materialization publishes aligned argc, argv, envp, auxiliary-vector, and string pointers inside one committed mapping. | `mailcpu/elf.py` | `tests/test_elf_startup.py::test_startup_stack_materializes_aligned_vectors_and_auxiliary_state` | `INTEGRATION_SPEC.md` 11.5 |
| `E-6` | Startup stack overlap and invalid environment failures leave the original memory snapshot unchanged. | `mailcpu/elf.py` | `tests/test_elf_startup.py::test_startup_stack_failure_preserves_original_memory`, `tests/test_elf_startup.py::test_startup_stack_rejects_invalid_environment_before_mapping` | `INTEGRATION_SPEC.md` 11.5 |
| `E-7` | Runtime admission commits linked images and startup stacks only after an exact machine-width backend validates the complete handoff. | `mailcpu/runtime.py` | `tests/test_elf_runtime_admission.py::test_runtime_loader_commits_only_after_backend_admission` | `INTEGRATION_SPEC.md` 11.5 |
| `E-8` | Missing, rejecting, or link-failing runtime admission preserves the caller's virtual-memory snapshot. | `mailcpu/runtime.py` | `tests/test_elf_runtime_admission.py::test_runtime_loader_missing_backend_preserves_memory`, `tests/test_elf_runtime_admission.py::test_runtime_loader_backend_rejection_preserves_memory`, `tests/test_elf_runtime_admission.py::test_runtime_loader_link_failure_preserves_memory` | `INTEGRATION_SPEC.md` 11.5 |

## Numbered POSIX boundary

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `U-1` | Numbered pointer I/O uses the native virtual-memory transfer law and preserves byte cardinality on success. | `mailcpu/posix_abi.py` | `tests/test_posix_abi.py::test_posix_pointer_io_open_and_stat_follow_native_memory_laws` | `INTEGRATION_SPEC.md` 11.6 |
| `U-2` | POSIX `mmap`, `mprotect`, and `pipe` translate into page and descriptor transitions without fabricating return values. | `mailcpu/posix_abi.py` | `tests/test_posix_abi.py::test_posix_mmap_protection_and_pipe_are_real_translations` | `INTEGRATION_SPEC.md` 11.6 |
| `U-3` | `wait4(WNOHANG)` does not reap an unexited child, while a completed wait writes the encoded exit status before returning the child identity. | `mailcpu/posix_abi.py` | `tests/test_posix_abi.py::test_posix_wait4_encodes_status_and_wnohang_without_reaping_early` | `INTEGRATION_SPEC.md` 11.6 |
| `U-4` | Unsupported numbers and invalid pointers return explicit errno results, and a failed pointer read leaves the descriptor projection unchanged. | `mailcpu/posix_abi.py` | `tests/test_posix_abi.py::test_posix_unsupported_and_invalid_transitions_are_explicit` | `INTEGRATION_SPEC.md` 11.6 |
| `U-5` | `O_CLOEXEC` remains descriptor-local and is not confused with shared open-description flags. | `mailcpu/posix_abi.py`, `mailcpu/kernel.py` | `tests/test_posix_abi.py::test_posix_open_cloexec_sets_descriptor_local_flag` | `INTEGRATION_SPEC.md` 11.6 |
| `U-6` | `execve` decodes bounded argv and environment vectors, replaces the supplied environment, and preserves ordinary descriptors through native image replacement. | `mailcpu/posix_abi.py`, `mailcpu/headless.py`, `mailcpu/kernel.py` | `tests/test_posix_abi.py::test_posix_execve_decodes_argv_and_environment_before_atomic_replacement` | `INTEGRATION_SPEC.md` 11.6 |
| `U-7` | Malformed `execve` vectors fail before image replacement while process errno records the explicit failure. | `mailcpu/posix_abi.py` | `tests/test_posix_abi.py::test_posix_execve_rejects_invalid_vectors_before_mutating_the_old_image` | `INTEGRATION_SPEC.md` 11.6 |

## Descriptors and blocking

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `F-1` | An oversized write commits only the admitted prefix and returns its cardinality. | `mailcpu/kernel.py` | `tests/test_signals_environment.py::test_pipe_write_commits_available_prefix_and_returns_partial_count` | `ARCHITECTURE.md` 7.5 |
| `F-2` | A descriptor wait preserves the program counter and register state across blocking. | `mailcpu/headless.py` | `tests/test_headless.py::test_scheduled_read_into_blocks_on_driver_input_and_wakes_from_device_feed` | `ARCHITECTURE.md` 7.5 |
| `F-3` | A deadline wait wakes exactly once; expiry cannot reset the same wait. | `mailcpu/headless.py` | `tests/test_headless.py::test_deadline_wait_wakes_exactly_once_and_cannot_be_reset` | `ARCHITECTURE.md` 7.5 |
| `F-4` | Non-zero blocking `poll` timeouts are refused. | `mailcpu/headless.py` | `tests/test_network_fds.py::test_non_zero_blocking_poll_timeouts_are_refused` | `README.md` 7 |
| `F-5` | `FD_CLOEXEC` is descriptor-local and distinct from shared open-description flags. | `mailcpu/kernel.py` | `tests/test_network_fds.py::test_fcntl_flags_are_shared_and_checkpointed`, `tests/test_virtual_environment.py::test_descriptor_local_close_on_exec_survives_checkpoint_and_dup_clears_alias_flag` | `ARCHITECTURE.md` 7.4 |
| `F-6**` | A descriptor right transfers one shared open description and is reclaimed only when the final alias closes. | `mailcpu/kernel.py` | `tests/test_network_fds.py::test_fd_rights_transfer_preserves_shared_file_description_and_checkpoint`, `tests/test_network_fds.py::test_pending_network_rights_survive_sender_close_and_cancel_on_destination_reap` | `ARCHITECTURE.md` 7.4 |

## Processes

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `P-1` | A bounded run reaching its tick budget remains `runnable`; an empty `WAIT` remains `blocked`. Neither becomes success. | `mailcpu/headless.py` | `tests/test_headless.py::test_tick_budget_exhaustion_is_never_reported_as_success` | `REPLACEMENT_SPEC.md` 7.1 |
| `P-2` | `exec` validates the replacement image before committing it, leaving the prior instruction stream unreachable. | `mailcpu/headless.py` | `tests/test_headless.py::test_scheduled_exec_replaces_image_after_trap_without_old_program_continuing`, `tests/test_headless.py::test_scheduled_exec_failure_leaves_old_image_intact` | `REPLACEMENT_SPEC.md` 7.6 |
| `P-3` | `exec` preserves PID, descriptors, authority, environment, and lineage. | `mailcpu/headless.py` | `tests/test_headless.py::test_exec_replaces_image_preserves_process_identity_and_descriptors` | `REPLACEMENT_SPEC.md` 7.6 |
| `P-4` | A child is reaped exactly once; reaping releases scheduler, memory, descriptor, and process-table state. | `mailcpu/headless.py` | `tests/test_headless.py::test_waitpid_reaps_exited_child_and_releases_state` | `REPLACEMENT_SPEC.md` 7.7 |
| `P-5` | Orphan adoption selects the nearest live subreaper, falls back to init, and journals the transfer. | `mailcpu/kernel.py` | `tests/test_headless.py::test_exiting_parent_adopts_orphan_to_init_and_init_waits`, `tests/test_headless.py::test_nearest_subreaper_owns_nested_orphans_and_survives_checkpoint` | `REPLACEMENT_SPEC.md` 7.8 |
| `P-6` | `fork` shares pages by content-addressed identity and diverges only on write. | `mailcpu/headless.py` | `tests/test_headless.py::test_scheduled_fork_uses_cow_memory_and_distinct_parent_child_returns` | `ARCHITECTURE.md` 7.2 |
| `P-7**` | Subreaper and session identities checkpoint and survive restore. | `mailcpu/kernel.py` | `tests/test_checkpoint.py::test_checkpoint_preserves_subreaper_and_session_identity` | `ARCHITECTURE.md` 7.2 |

## Network

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `N-1` | Host-socket access is confined to the explicit external transport boundary; semantic network layers remain host-socket-free. | `mailcpu/socket_transport.py`, `mailcpu/network.py` | `tests/test_network.py::test_host_socket_access_is_confined_to_external_transport` | `ARCHITECTURE.md` 7.7 |
| `N-2` | A malformed frame is rejected and never reaches the journal as an accepted event. | `mailcpu/network.py` | `tests/test_network.py::test_e0_network_rejects_wire_errors_and_reports_http_errors` | `ARCHITECTURE.md` 7.7 |
| `N-3**` | The owned fabric commits a frame only after the E0 decoder has emitted its journaled events. | `mailcpu/owned_network.py` | `tests/test_owned_network.py::test_owned_link_driver_commits_only_after_e0_accepts` | `INTEGRATION_SPEC.md` 8 |
| `N-4` | Effective MTU is the minimum interface MTU along the selected route. | `mailcpu/owned_network.py` | `tests/test_owned_network.py::test_owned_fabric_routes_across_namespace_forwarding_interfaces` | `INTEGRATION_SPEC.md` 8 |
| `N-5` | A network handle is released exactly once, on reap of its creating or accepting process. | `mailcpu/headless.py` | `tests/test_owned_network.py::test_network_handle_is_released_once_on_reap_of_its_accepting_process` | `INTEGRATION_SPEC.md` 9 |
| `N-6` | Every reported network result carries an evidence tier of `E0` or `E1`. | `mailcpu/owned_network.py` | `tests/test_owned_network.py::test_headless_route_send_uses_owned_forwarding_and_preserves_evidence` | `ARCHITECTURE.md` 6 |

## Reliability and persistence

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `R-1` | The reliable channel admits at most `W` in-flight frames; a full window returns typed backpressure. | `mailcpu/reliability.py` | `tests/test_reliability.py::test_reliable_channel_enforces_bounded_inflight_window_and_reopens_after_ack` | `REPLACEMENT_SPEC.md` 7.11 |
| `R-2**` | Capacity is released only through acknowledgement or explicit retry failure. | `mailcpu/reliability.py` | `tests/test_reliability.py::test_reliable_channel_failed_sequence_releases_window_slot`, `tests/test_reliability.py::test_reliable_channel_enforces_bounded_inflight_window_and_reopens_after_ack` | `REPLACEMENT_SPEC.md` 7.11 |
| `R-3` | A tampered complete record is refused; only an incomplete final append is truncated. | `mailcpu/durable_transport.py` | `tests/test_durable_transport.py::test_durable_mailbox_rejects_tampered_complete_records`, `tests/test_durable_transport.py::test_durable_mailbox_recovers_only_an_incomplete_final_append` | `REPLACEMENT_SPEC.md` 7.11 |
| `R-4` | Reliable control state restores across a transport reopen. | `mailcpu/reliability.py` | `tests/test_durable_transport.py::test_reliable_channel_continues_across_durable_transport_reopen` | `REPLACEMENT_SPEC.md` 7.11 |

## Images and execution regimes

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `I-1**` | Image v2 reconstruction compares the decoded program against the readable graph and refuses disagreement. | `mailcpu/headless.py` | `tests/test_images.py::test_image_v2_requires_graph_and_binary_program_identity_and_reads_v1` | `REPLACEMENT_SPEC.md` 7.1 |
| `I-2` | An execution regime other than `MAILCPU` fails closed. | `mailcpu/image.py` | `tests/test_images.py::test_unsupported_execution_regime_refuses_without_fake_fallback` | `README.md` 7 |
| `I-3**` | `parse_elf` validates `PT_LOAD` bounds, alignment, and overlap; foreign execution fails closed. | `mailcpu/elf.py` | `tests/test_elf.py::test_elf_parser_rejects_truncation_and_invalid_segment_overlap`, `tests/test_elf.py::test_elf_parser_refuses_a_foreign_machine` | `REPLACEMENT_SPEC.md` 7.6 |
| `I-4` | Executable loading crosses kernel descriptors and refuses a source file without execute mode. | `mailcpu/headless.py` | `tests/test_headless.py::test_executable_loading_uses_kernel_descriptors` | `REPLACEMENT_SPEC.md` 7.1 |

## Public surface

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `S-1**` | The parser's registered command domain equals `cli._COMMANDS` exactly. | `mailcpu/cli.py` | `tests/test_cli_surface.py::test_declared_command_grammar_equals_registered_grammar` | `README.md` 4 |
| `S-2**` | No exported symbol shadows a Python builtin. | `mailcpu/__init__.py` | `tests/test_public_surface.py::test_no_export_shadows_a_builtin` | `README.md` 10 |
| `S-3**` | Every name in `__all__` is importable and every importable public name is in `__all__`. | `mailcpu/__init__.py` | `tests/test_public_surface.py::test_every_declared_export_resolves`, `tests/test_public_surface.py::test_every_public_name_is_declared` | `README.md` 10 |
| `S-4**` | The vendored address permutation is not exported from the package root. | `mailcpu/__init__.py` | `tests/test_public_surface.py::test_vendored_primitive_is_not_exported_from_the_package_root` | `BOUNDARY_PROCEDURAL_MODEL.md` 2 |
| `S-5**` | The vendored address permutation is reversible. | `mailcpu/vl_procedural_primitives.py` | `tests/test_classifier.py::test_vl_feistel_primitive_is_reversible_and_drives_procedural_addresses` | `BOUNDARY_PROCEDURAL_MODEL.md` 2 |
| `S-6**` | Every public function, method, and class carries a docstring. | `mailcpu/` | `tests/test_public_surface.py::test_every_public_callable_carries_a_docstring` | `ARCHITECTURE.md` 1 |

## Reversibility and chronofolded execution

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `V-1` | Every reversible gate involution satisfies `G(G(s)) = s` identically. | `mailcpu/reversible_gates.py` | `tests/test_reversible.py::test_gate_involution_identity` | `ITERATION_2_BUILD_PLAN.md` 4.1 |
| `V-2` | Chronofold Bennett replay restores the initial tape exactly without intermediate tape persistence. | `mailcpu/chronofold.py` | `tests/test_reversible.py::test_chronofold_bennett_constant_space_replay_and_reversal` | `ITERATION_2_BUILD_PLAN.md` 4.1 |

## Communication substrates and timing channels

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `K-1` | State `V` is reconstructed exactly from any `k` of `n` surviving residues under Garner-free CRT. | `mailcpu/rrns.py` | `tests/test_delay_loops.py::test_rrns_encoding_and_erasure_recovery` | `ITERATION_2_BUILD_PLAN.md` 4.2 |
| `K-2` | Dynamic slot clamping enforces `\Delta_{\text{slot}} \ge 3 \sigma_{\text{jitter}}`, preventing packet reordering. | `mailcpu/delay_loop.py` | `tests/test_delay_loops.py::test_dynamic_slot_clamping` | `ITERATION_2_BUILD_PLAN.md` 4.2 |
| `K-3` | Cadence demodulation recovers exact byte streams under Gaussian jitter with bit error rate zero. | `mailcpu/timing_channel.py` | `tests/test_timing_channel.py::test_timing_channel_resilience_to_gaussian_jitter` | `ITERATION_2_BUILD_PLAN.md` 4.2 |

## Algebraic law certification and orbit leaps

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `L-1` | Closed-form orbit leap matches step-by-step navigation for all coordinates within the certified horizon. | `mailcpu/law_certifier.py` | `tests/test_law_certifier.py::test_int_law_certification_and_leap` | `ITERATION_2_BUILD_PLAN.md` 4.4 |
| `L-2` | Evaluating an orbit leap at or beyond the certified horizon raises `HorizonExceeded`. | `mailcpu/law_certifier.py` | `tests/test_law_certifier.py::test_guarded_navigation_horizon` | `ITERATION_2_BUILD_PLAN.md` 4.4 |

## Chemical time and holonomy consensus

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `H-1` | All Wilczek-Zee geometric phase operators belong to `SU(2)` with `U^\dagger U = I` and `\det U = 1`. | `mailcpu/holonomy_engine.py` | `tests/test_chemical_time.py::test_su2_wilczek_zee_unitary_group` | `ITERATION_2_BUILD_PLAN.md` 4.5 |
| `H-2` | Step counts exceeding the task validity horizon trigger a typed `HorizonExceeded` fault. | `mailcpu/chemical_time.py` | `tests/test_chemical_time.py::test_horizon_tracker` | `ITERATION_2_BUILD_PLAN.md` 4.5 |

## Neural lifter and policy gate

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `Q-1` | Advisory neural routing outputs are dispatched if and only if they reproduce 100% of withheld witness probes. | `mailcpu/neural_lifter.py` | `tests/test_neural_lifter.py::test_policy_gate_isolation_truth_preservation`, `tests/test_neural_lifter.py::test_policy_gate_fallback_on_model_mismatch` | `ITERATION_2_BUILD_PLAN.md` 4.6 |
| `Q-2` | A structural intent candidate can be fitted from observed operation states and classify held-out states without changing the active hypervisor model; activation remains a typed revision-gate obligation. | `mailcpu/intent_embedding.py`, `mailcpu/classifier.py` | `tests/test_external_connections.py::test_external_operation_states_form_advisory_hypervisor_training_corpus` | `HYPERVISOR_PROFILE.md` 3.3 |
| `Q-3` | The default structural intent corpus contains distinct process and package domains and classifies held-out states into those labels with normalized probabilities while preserving exact model checkpoint identity. | `mailcpu/intent_embedding.py` | `tests/test_intent_embedding.py::test_prototype_model_routes_held_out_typed_requests_and_round_trips` | `HYPERVISOR_PROFILE.md` 3.3 |

## Marking an invariant

An entry marked `**` was established during the repository's preparation pass
and had no registry entry before it. Entries are not removed when the property
they describe is removed; they are marked `Withdrawn` with the clause that
withdrew them.

## Adding an entry

An entry is added when a specification clause states an obligation that no
existing entry enforces. An entry MUST name a test that exists. An entry with no
resolvable test is rejected by `scripts/verify_invariants.py`.
