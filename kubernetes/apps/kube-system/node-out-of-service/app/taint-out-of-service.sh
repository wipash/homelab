#!/bin/sh
# Applies the well-known out-of-service taint to nodes that have stopped
# reporting entirely, so that RWO Ceph volumes are force-detached and stateful
# workloads can start on a surviving node. Removes the taint again once the
# node comes back.
#
# Kubernetes deliberately does not do this on its own: it cannot distinguish a
# node that is hung from one that is merely partitioned but still writing to
# disk, and force-detaching a volume from a live writer risks corruption.
#
# The safety judgement here is narrower than "node is NotReady":
#
#   Ready=False    the kubelet is still running and reporting, it just is not
#                  healthy. The node may well still be writing. NOT touched.
#   Ready=Unknown  no heartbeat at all for the node-monitor grace period. The
#                  kubelet is gone. This is the only case we act on.
#
# Combined with NOT_READY_SECONDS this means we only act on a node that has
# been completely silent for several minutes, which is how the hardware in
# this cluster actually fails.

set -eu

TAINT_KEY="node.kubernetes.io/out-of-service"
TAINT_VALUE="nodeshutdown"
TAINT_EFFECT="NoExecute"

# How long a node must have been silent before we declare it out of service.
# Keep this comfortably longer than a normal reboot (a Talos node is back in
# 2-4 minutes) so that routine restarts and OS upgrades never trip it.
NOT_READY_SECONDS="${NOT_READY_SECONDS:-600}"

now="$(date -u +%s)"

# Emit one line per node: <name> <readyStatus> <lastTransitionTime> <tainted>
nodes="$(
  kubectl get nodes -o go-template='
{{- range .items -}}
  {{- $name := .metadata.name -}}
  {{- $tainted := "no" -}}
  {{- range .spec.taints -}}
    {{- if eq .key "node.kubernetes.io/out-of-service" -}}{{- $tainted = "yes" -}}{{- end -}}
  {{- end -}}
  {{- range .status.conditions -}}
    {{- if eq .type "Ready" -}}
{{ $name }} {{ .status }} {{ .lastTransitionTime }} {{ $tainted }}
{{ end -}}
  {{- end -}}
{{- end -}}'
)"

echo "$nodes" | while read -r name status since tainted; do
  [ -n "$name" ] || continue

  # Node is healthy again: clear the taint so workloads and Rook's mon/osd for
  # this host can come back. The taint never clears itself.
  if [ "$status" = "True" ]; then
    if [ "$tainted" = "yes" ]; then
      echo "node/${name} is Ready again, removing ${TAINT_KEY} taint"
      kubectl taint node "$name" "${TAINT_KEY}-"
    fi
    continue
  fi

  # Ready=False means the kubelet is alive and talking. Never force-detach.
  if [ "$status" != "Unknown" ]; then
    echo "node/${name} is Ready=${status} (kubelet still reporting), leaving alone"
    continue
  fi

  [ "$tainted" = "no" ] || continue

  silent_since="$(date -u -D '%Y-%m-%dT%H:%M:%SZ' -d "$since" +%s)"
  silent_for="$(( now - silent_since ))"

  if [ "$silent_for" -lt "$NOT_READY_SECONDS" ]; then
    echo "node/${name} silent for ${silent_for}s, under ${NOT_READY_SECONDS}s threshold"
    continue
  fi

  echo "node/${name} silent for ${silent_for}s, marking out of service"
  kubectl taint node "$name" \
    "${TAINT_KEY}=${TAINT_VALUE}:${TAINT_EFFECT}" --overwrite
done
