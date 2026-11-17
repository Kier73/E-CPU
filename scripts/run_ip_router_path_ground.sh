#!/usr/bin/env bash
# PATH-GROUND-004: real Linux IPv4 router forwarding between disposable network namespaces.
# Invokes kernel routing; NO Python process acts as a forwarding node.
# Requires sudo CAP_NET_ADMIN for namespace/veth and CAP_NET_RAW for observers.
# Run only on an owned Linux runner (e.g. GitHub-hosted Ubuntu), never public routers.
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "PATH-GROUND-004 requires Linux" >&2; exit 2
fi
for cmd in ip sudo python; do
  command -v "$cmd" >/dev/null || { echo "Missing required executable: $cmd" >&2; exit 2; }
done
sudo -n true || { echo "PATH-GROUND-004 requires passwordless local namespace privileges" >&2; exit 2; }

PYTHON="$(command -v python)"
BASE="${1:-artifacts/path-ground-004}"
mkdir -p "$BASE"
BASE="$(cd "$BASE" && pwd)"
TMP="$(mktemp -d)"
PREFIX="ecpg4_${BASHPID}_${RANDOM}"
declare -a NS=()
declare -a PIDS=()
function cleanup {
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  for ns in "${NS[@]}"; do
    sudo ip netns del "$ns" 2>/dev/null || true
  done
  rm -rf "$TMP"
}
trap cleanup EXIT

function add_namespace {
  local name="$1"
  sudo ip netns add "$name"
  NS+=("$name")
  sudo ip -n "$name" link set lo up
}

function link_pair {
  # nsa, ifa, address/cidr a, nsb, ifb, address/cidr b
  local nsa="$1" ifa="$2" adda="$3" nsb="$4" ifb="$5" addb="$6"
  # The temporary host-side names disappear immediately after netns moves.
  sudo ip link add ecpg4a type veth peer name ecpg4b
  sudo ip link set ecpg4a netns "$nsa"
  sudo ip link set ecpg4b netns "$nsb"
  sudo ip -n "$nsa" link set ecpg4a name "$ifa"
  sudo ip -n "$nsb" link set ecpg4b name "$ifb"
  if [[ "$adda" != "none" ]]; then sudo ip -n "$nsa" addr add "$adda" dev "$ifa"; fi
  if [[ "$addb" != "none" ]]; then sudo ip -n "$nsb" addr add "$addb" dev "$ifb"; fi
  sudo ip -n "$nsa" link set "$ifa" up
  sudo ip -n "$nsb" link set "$ifb" up
}

function wait_ready {
  local signal="$1"
  for (( i=0; i<120; i++ )); do
    if [[ -f "$signal" ]]; then return 0; fi
    sleep 0.05
  done
  echo "Timed out waiting for local socket observer: $signal" >&2
  for logfile in "$TMP"/*.log; do
    [[ -e "$logfile" ]] && { echo "LOG $logfile" >&2; cat "$logfile" >&2; }
  done
  return 1
}

function run_route {
  # route id, source namespace, destination namespace, source IP, destination IP, zero to two router namespaces
  local route="$1" source_ns="$2" dest_ns="$3" source_ip="$4" dest_ip="$5"
  shift 5
  local routers=("$@")
  local receiver_ready="$TMP/ready-dest-$route"
  local receiver_out="$TMP/receiver-$route.json"
  local receiver_log="$TMP/receiver-$route.log"
  sudo ip netns exec "$dest_ns" "$PYTHON" -m examples.run_ip_router_path_ground \
    --role receiver --destination-ip "$dest_ip" \
    --output "$receiver_out" --ready "$receiver_ready" > "$receiver_log" 2>&1 &
  local receiver_pid="$!"
  PIDS+=("$receiver_pid")
  wait_ready "$receiver_ready"

  local idx=0
  local capture_pids=()
  for router in "${routers[@]}"; do
    idx=$((idx+1))
    local ready="$TMP/ready-$route-r$idx"
    local output="$TMP/router-$route-r$idx.json"
    local logfile="$TMP/router-$route-r$idx.log"
    local -a live_args=()
    if [[ -n "${PG6_SIGNING_DIR:-}" ]]; then
      live_args=(
        --live-plan "$PG6_SIGNING_DIR/$route.r$idx.plan.json"
        --live-key "$PG6_SIGNING_DIR/$route.r$idx.key"
        --live-receipt "$BASE/live-$route-r$idx.json"
      )
    fi
    sudo ip netns exec "$router" "$PYTHON" -m examples.run_ip_router_path_ground \
      --role router --router-id "$route.r$idx" \
      --ingress in --egress out --destination-ip "$dest_ip" \
      --output "$output" --ready "$ready" "${live_args[@]}" > "$logfile" 2>&1 &
    local pid="$!"
    PIDS+=("$pid")
    capture_pids+=("$pid")
    wait_ready "$ready"
  done

  # Both real kernel observers are bound before any source datagram is emitted.
  sudo ip netns exec "$source_ns" "$PYTHON" -m examples.run_ip_router_path_ground \
    --role sender --source-ip "$source_ip" --destination-ip "$dest_ip" \
    --output "$TMP/sender-$route.json"
  if ! wait "$receiver_pid"; then
    echo "Receiver $route failed:" >&2
    cat "$receiver_log" >&2
    exit 1
  fi
  local capindex=0
  for pid in "${capture_pids[@]}"; do
    capindex=$((capindex + 1))
    if ! wait "$pid"; then
      echo "Router capture $route.r$capindex failed:" >&2
      cat "$TMP/router-$route-r$capindex.log" >&2
      exit 1
    fi
  done
  echo "Native packet experiment $route observed."
}

S0="$PREFIX-s0"; D0="$PREFIX-d0"
SB="$PREFIX-sb"; BR="$PREFIX-br"; DB="$PREFIX-db"
S1="$PREFIX-s1"; R1="$PREFIX-r1"; D1="$PREFIX-d1"
S2="$PREFIX-s2"; R2A="$PREFIX-r2a"; R2B="$PREFIX-r2b"; D2="$PREFIX-d2"

for ns in "$S0" "$D0" "$SB" "$BR" "$DB" "$S1" "$R1" "$D1" "$S2" "$R2A" "$R2B" "$D2"; do
  add_namespace "$ns"
done

# Direct control: one veth pair, no intermediate bridge/router.
link_pair "$S0" out 10.73.0.1/30 "$D0" in 10.73.0.2/30

# Distinguish an intermediate L2 forwarding element from an L3 router.
# Native Linux bridge switching must preserve the IPv4 TTL field.
link_pair "$SB" out 10.73.6.1/30 "$BR" in none
link_pair "$BR" out none "$DB" in 10.73.6.2/30
sudo ip -n "$BR" link add br0 type bridge
sudo ip -n "$BR" link set br0 up
sudo ip -n "$BR" link set in master br0
sudo ip -n "$BR" link set out master br0

# One IPv4 forwarding operation: s1 -> r1 -> d1.
link_pair "$S1" out 10.73.1.1/30 "$R1" in 10.73.1.2/30
link_pair "$R1" out 10.73.2.1/30 "$D1" in 10.73.2.2/30
sudo ip -n "$S1" route add 10.73.2.2/32 via 10.73.1.2 dev out
# Legitimate reverse paths ensure Linux rp_filter, where enabled, does not
# silently drop packets because the receiver lacks a route to the source.
sudo ip -n "$D1" route add 10.73.1.1/32 via 10.73.2.1 dev in
sudo ip netns exec "$R1" sysctl -qw net.ipv4.ip_forward=1

# Two real kernel forwarding operations: s2 -> r2a -> r2b -> d2.
link_pair "$S2" out 10.73.3.1/30 "$R2A" in 10.73.3.2/30
link_pair "$R2A" out 10.73.4.1/30 "$R2B" in 10.73.4.2/30
link_pair "$R2B" out 10.73.5.1/30 "$D2" in 10.73.5.2/30
sudo ip -n "$S2" route add 10.73.5.2/32 via 10.73.3.2 dev out
sudo ip -n "$R2A" route add 10.73.5.2/32 via 10.73.4.2 dev out
sudo ip -n "$R2B" route add 10.73.3.1/32 via 10.73.4.1 dev in
sudo ip -n "$D2" route add 10.73.3.1/32 via 10.73.5.1 dev in
sudo ip netns exec "$R2A" sysctl -qw net.ipv4.ip_forward=1
sudo ip netns exec "$R2B" sysctl -qw net.ipv4.ip_forward=1

run_route direct "$S0" "$D0" 10.73.0.1 10.73.0.2
run_route bridge "$SB" "$DB" 10.73.6.1 10.73.6.2 "$BR"
run_route one "$S1" "$D1" 10.73.1.1 10.73.2.2 "$R1"
run_route two "$S2" "$D2" 10.73.3.1 10.73.5.2 "$R2A" "$R2B"

cp "$TMP"/*.json "$BASE/"
"$PYTHON" -m examples.run_ip_router_path_ground \
  --role verify --input-dir "$BASE" --output "$BASE/verified-ground.json"

echo "PATH-GROUND-004 retained the source, receiver, intermediate raw header and native Ground proofs: $BASE"
