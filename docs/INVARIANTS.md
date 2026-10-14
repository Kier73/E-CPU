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

## Determinism and canonical form

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `D-1` | Logical time advances by exactly one per accepted event and is not derived from wall-clock time. | `mailcpu/journal.py` | `tests/test_runtime.py::test_logical_time_advances_exactly_one_per_accepted_event` | `README.md` 5 |
| `D-2` | Canonical trace and result forms are invariant under transport message identity. | `mailcpu/model.py` | `tests/test_conformance.py::test_differential_random_program_corpus` | `README.md` 2 |
| `D-3` | The canonical value algebra is injective and invariant under mapping-key permutation. | `mailcpu/_codec.py` | `tests/test_codec.py::test_canonical_algebra_distinguishes_container_types`, `tests/test_codec.py::test_canonical_encoding_is_permutation_invariant` | `REPLACEMENT_SPEC.md` 7.11 |
| `D-4` | The transport value algebra preserves scalars and bytes and does not claim to preserve tuple identity. | `mailcpu/_codec.py` | `tests/test_codec.py::test_transport_algebra_round_trips_scalars_and_bytes`, `tests/test_codec.py::test_transport_algebra_does_not_conserve_tuple_identity` | `REPLACEMENT_SPEC.md` 7.11 |
| `D-5` | A digest is never computed over a non-canonical encoding. | `mailcpu/durable_transport.py` | `tests/test_durable_transport.py::test_durable_mailbox_rejects_tampered_complete_records` | `REPLACEMENT_SPEC.md` 7.11 |

## Receipts, journal, and checkpoints

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `J-1` | The event journal is a hash chain `H_n = SHA256(H_{n-1} \|\| c_n)`. | `mailcpu/journal.py` | `tests/test_runtime.py::test_event_journal_is_a_sha256_hash_chain` | `GLOSSARY.md` receipt |
| `J-2` | A record failing chain verification causes construction or restore to fail. | `mailcpu/journal.py` | `tests/test_checkpoint.py::test_checkpoint_detects_tampering` | `README.md` 7 |
| `C-1` | Checkpoint restore rejects a state whose digest does not match its content. | `mailcpu/checkpoint.py` | `tests/test_checkpoint.py::test_checkpoint_detects_tampering` | `README.md` 5 |
| `C-2` | Checkpointed state round-trips without loss for every admitted component. | `mailcpu/checkpoint.py` | `tests/test_checkpoint.py::test_checkpoint_restores_process_filesystem_bus_and_memory`, `tests/test_checkpoint.py::test_checkpoint_preserves_service_controller` | `README.md` 5 |
| `C-3` | Trajectory records are indexed by `(sequence, logical_time, byte_offset)` and are receipt-verifiable. | `mailcpu/trajectory.py` | `tests/test_trajectory.py::test_trajectory_receipts_index_seek_and_replay` | `GLOSSARY.md` trajectory |

## Authority

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `A-1` | Authorisation is a function of held capabilities alone. | `mailcpu/kernel.py` | `tests/test_classifier.py::test_headless_dispatch_derives_grants_from_kernel_capabilities` | `ARCHITECTURE.md` 5 |
| `A-2` | A request whose capability right is absent is denied regardless of model confidence. | `mailcpu/classifier.py` | `tests/test_classifier.py::test_hypervisor_denies_missing_authority_and_reviews_ambiguity` | `BOUNDARY_JEV.md` R-1 |
| `A-3` | Only an explicit `ALLOW` reaches a registered handler. | `mailcpu/classifier.py` | `tests/test_classifier.py::test_hypervisor_allows_clear_read_and_dispatches_one_handler`, `tests/test_classifier.py::test_headless_dispatch_derives_grants_from_kernel_capabilities` | `BOUNDARY_JEV.md` R-5 |
| `A-4` | Every hypervisor decision is appended to the journal before the reply returns. | `mailcpu/classifier.py` | `tests/test_classifier.py::test_hypervisor_decision_is_journaled_before_the_reply` | `BOUNDARY_JEV.md` R-6 |
| `A-5` | `SIGKILL` and `SIGSTOP` are non-ignorable. | `mailcpu/kernel.py` | `tests/test_signals_environment.py::test_kill_and_stop_dispositions_cannot_be_ignored` | `REPLACEMENT_SPEC.md` 7.5 |
| `A-6** | The default exit code for a fatal signal is single-sourced in the signal vocabulary. | `mailcpu/signals.py` | `tests/test_public_surface.py::test_signal_vocabulary_is_the_single_source_of_default_exit_codes` | `ARCHITECTURE.md` 7.2 |

## Memory

| ID | Statement | Establishes | Enforced by | Required by |
|---|---|---|---|---|
| `M-1` | A write to a shared page allocates a new page hash and leaves the original immutable. | `mailcpu/memory.py` | `tests/test_runtime.py::test_virtual_memory_cross_page_write_and_copy_on_write` | `ARCHITECTURE.md` 7.3 |
| `M-2` | `mem_reclaim` evicts a private page losslessly and a later access restores it exactly. | `mailcpu/memory.py` | `tests/test_runtime.py::test_memory_reclaim_evicts_private_pages_and_faults_back_losslessly` | `ARCHITECTURE.md` 7.3 |
| `M-3` | Quota and capability checks fail before mutation. | `mailcpu/headless.py` | `tests/test_runtime.py::test_failed_quota_spawn_does_not_publish_process_state`, `tests/test_runtime.py::test_headless_memory_syscalls_cover_private_and_shared_abi` | `REPLACEMENT_SPEC.md` 7.9 |
| `M-4` | An unreserved access produces a typed page fault. | `mailcpu/memory.py` | `tests/test_runtime.py::test_virtual_memory_reports_typed_page_faults` | `REPLACEMENT_SPEC.md` 7.9 |
| `M-5** | An undersized destination returns `-ERANGE` before memory mutation. | `mailcpu/headless.py` | `tests/test_headless.py::test_scheduled_process_context_abi_packs_argv_environment_and_cwd_atomically` | `REPLACEMENT_SPEC.md` 7.4 |
| `M-6` | A read is non-consuming with respect to the register mailbox it observes. | `mailcpu/interpreter.py` | `tests/test_conformance.py::test_queue_register_read_is_non_consuming` | `PLAN.md` 4.5 |

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
| `N-1` | No layer opens a host socket. | `mailcpu/network.py` | `tests/test_network.py::test_no_package_layer_imports_a_host_socket` | `ARCHITECTURE.md` 7.7 |
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
| `S-6**` | Every public function, method, and class carries a docstring. | `mailcpu/` | `tests/test_public_surface.py::test_every_public_callable_carries_a_docstring` | `STYLE.md` 7.3 |

## Marking an invariant

An entry marked `**` was established during the repository's preparation pass
and had no registry entry before it. Entries are not removed when the property
they describe is removed; they are marked `Withdrawn` with the clause that
withdrew them.

## Adding an entry

An entry is added when a specification clause states an obligation that no
existing entry enforces. An entry MUST name a test that exists. An entry with no
resolvable test is rejected by `scripts/verify_invariants.py`.
