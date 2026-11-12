# Stateful transition trajectory bridge

## Purpose

`mailcpu.stateful_transition_trajectory` connects `StatefulTransitionRuntime` to E-CPU's existing trajectory and journal formats.

The bridge deliberately keeps three distinct integrity views:

1. **Runtime event chain:** the runtime's own step/revision sequence, model/program digests, and replay semantics.
2. **EventJournal projection:** a deterministic projection of every runtime event into E-CPU's generic `EventJournal`.
3. **Binary trajectory receipts:** `TrajectoryWriter` stores every event as a frame with a chained receipt and a sparse logical-time index.

This is not a second execution engine. It serializes and restores the runtime's already-committed logical history.

## Export

`export_stateful_transition_trajectory(runtime, data_path, index_path, manifest_path, stride=...)`:

- takes a detached runtime snapshot;
- writes each step/revision event into one trajectory frame;
- sets the frame logical time to `tick_after` for a step and `tick` for a revision;
- verifies the binary trajectory with `TrajectoryReader`;
- independently projects the runtime events into `EventJournal` and records its head digest;
- writes a manifest that includes the runtime snapshot without the inline event array, event count, runtime-chain head, EventJournal head, trajectory receipt head, and a content digest.

The manifest is written with a same-directory temporary file and atomic replacement.

The trajectory writer clamps timestamps to non-decreasing order. A revision does not advance logical time, so a `step → revision → step` sequence can produce frame times `1,1,2`. This preserves the important fact that a model revision can occur between logical transitions without changing the current state or tick.

## Restore

`restore_stateful_transition_trajectory(...)` checks the manifest digest and schema, verifies the binary trajectory receipt chain, validates each frame against its embedded runtime event, re-derives the EventJournal head, reconstructs the runtime snapshot from the ordered trajectory frames, and finally calls `StatefulTransitionRuntime.from_snapshot`.

The runtime's own replay verification is therefore still the last authority for state, model, revision and event semantics. The external trajectory and EventJournal representations provide independent integrity checks; they do not replace source-program/model equivalence verification.

## Time seek

`seek_stateful_transition_event(data_path, index_path, target_tick)` verifies the trajectory before using `TrajectoryReader.seek_time`. With stride one, it returns the latest indexed event at the requested logical tick. For the sequence:

```
step(tick 1) → revision(tick 1) → step(tick 2)
```

seeking tick 1 returns the revision event, not the earlier step. This is useful when a caller needs the active model revision at a state/time coordinate.

## Tests

`tests/test_stateful_transition_trajectory.py` covers:
- export/restore equality across runtime, EventJournal and trajectory receipt chains;
- logical-time seek at a same-tick revision boundary;
- rejection of modified binary frames and modified manifests;
- an empty runtime with no seekable event;
- invalid time-coordinate rejection.

## Limits

The binary trajectory and manifest are separate files, not a transactional distributed store. The manifest digest and the three hash chains detect inconsistent or partial modification when the manifest/head is trusted; they are not external signatures or a hardware trust anchor. The trajectory is an auditable record of already-committed runtime events, not a source of unverified state mutation.

## Verified same-tick example

The runtime scenario begins from state `01`:
1. A hold step commits at logical tick 1.
2. A compatible transition-program revision is committed at the same logical tick 1.
3. The next step commits at logical tick 2 and moves the state to `10`.

The binary trajectory therefore contains event times `[1, 1, 2]` and frame indices `[0, 1, 2]`. A stride-one seek to tick 1 returns trajectory frame 1, whose embedded runtime event sequence is 2 and kind is `revision`. A seek to tick 2 returns the following step and state `10`.

The IFS integration workflow pinned to this bridge checked this exact behavior, plus 128 one-step transition cases, 2,048 recurrent trajectories, and the bridge's six focused tests. The IFS result records:
- EventJournal head: `a89f87a56c9071617d6b3ea5ed419760af13f2ca9b39c513e9e13ce0c3e84181`
- Trajectory receipt head: `0244151812c64df3282e8758eb476ba51b00bcb053b89393c3b53be039fc14eb`
- Manifest digest: `402c6d3ef591ccd9fa58ffb061509ee7e425996980c61ddb9b5a77d124ea38e7`

These three digests are distinct views of the same three-event history. They should not be treated as interchangeable identities.
