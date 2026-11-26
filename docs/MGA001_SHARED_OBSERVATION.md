# MGA-001/C — Shared observation: constructive receiver-owned path geometry

A single canonical, copyable observation is a shared resource. A directed
network can disseminate it to all requested sites iff they are reachable from
the source through current admitted carriers (in the declared snapshot model).
The reachable set is a closed cut: every eligible edge leaving that set lacks
a receiver grant. An absent typed binding, expired endpoint, expired channel
or inadequate payload capacity is not a grant candidate.

For each unreachable target, assign cost 0 to already admitted eligible
channels and 1 to eligible but not admitted channels. The shortest path
minimizes the number of new channel grants for that **individual** target.
Nonnegative costs permit a simple optimal path; a path's cost equals the
number of distinct additional grants. Grant candidates are advisory, not
permission. If no offered path exists, return that status. Multiple target
repairs are not claimed jointly optimal (a directed Steiner-type objective).

The implementation uses lexicographic shortest paths (grant count, hops,
stable channel IDs). An independent Bellman-Ford recurrence checks the
per-target optimal counts. For a READY result the zero-grant paths form a
rooted shortest-hop tree; shared prefixes are emitted only once. Native
SAB-001 carries the actual canonical bytes along each selected tree edge,
checking its report with the existing independent report verifier. Each
child receives the previous realized value. Full inventory, policy, binding
digests, source Ground, coordinate and value identity are pinned in the
plan. Changing those inputs requires replanning. Only the selected edge is
included in each native subplan; the full parent identity stays in the
aggregate receipt. No independent runtime or replacement authority is added.

Example: A -> B -> {C,D}. Separate requests use four logical carriers;
the shared tree uses three. If B -> D is ungranted, the reachable cut and a
one-grant repair are returned. Nothing executes while the request is BLOCKED.
An independently installed new policy and fresh plan are required.

Run:

    python -m unittest discover -s tests -p test_shared_observation_ground.py -v

The tests cover native OwnedNetworkFabric discovery and actual simulated
send/receive, independent exhaustive grant-subset oracles, data corruption,
expiry, missing binding, stale plan and tampered plan controls. The graph
is a snapshot of declared leases and carrier contracts, not a physical
capacity or latency guarantee. Logical carriers may internally traverse
multiple hops. No general simultaneous tensor conversion, actual Internet
delivery, collective optimal repair, atomic multicast, or physical
independence is implied. Partial sends before a failure are not rolled back.

Next: integrate a common-prefix receipt with the native DAG executor and
authenticated peer paths, then compare measured wire bytes, time and
verification work with independent per-target realization. Extend resource
repair from binary grant availability to receiver-reserved shared capacity.
