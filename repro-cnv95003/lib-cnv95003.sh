#!/bin/bash
# Shared helpers for CNV-95003 certainty test suite
set -euo pipefail

export KUBECONFIG="${KUBECONFIG:-/root/mno/kubeconfig}"

IMG_419="registry.redhat.io/odf4/cephcsi-rhel9@sha256:5d0da2db0e67c7054df6d94755ac050033514131ad879e388a93e30bf3c5d80a"
IMG_422="registry.redhat.io/odf4/cephcsi-rhel9@sha256:3928e6499dd866ed08168004803f174d187f3db185e7fddda4711b15a9565f07"

SOURCE_NS="source-ns"
SOURCE_SNAP="source-snapshot"
VIRT_SC="ocs-storagecluster-ceph-rbd-virtualization"
NONVIRT_SC="ocs-storagecluster-ceph-rbd"
RESULTS_DIR="/root/repro-cnv95003"
SUITE_LOG="${RESULTS_DIR}/certainty-suite.log"
SUITE_CSV="${RESULTS_DIR}/certainty-suite-results.csv"

log() {
  echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$SUITE_LOG"
}

init_suite() {
  mkdir -p "$RESULTS_DIR"
  if [[ ! -f "$SUITE_CSV" ]]; then
    echo "test,phase,metric,value_ms,notes" > "$SUITE_CSV"
  fi
}

record_result() {
  local test="$1" phase="$2" metric="$3" value="$4" notes="${5:-}"
  echo "${test},${phase},${metric},${value},${notes}" >> "$SUITE_CSV"
}

verify_snapshot_ready() {
  local ns="${1:-$SOURCE_NS}" snap="${2:-$SOURCE_SNAP}"
  local ready
  ready=$(oc get volumesnapshot "$snap" -n "$ns" \
    -o jsonpath='{.status.readyToUse}' 2>/dev/null || echo "false")
  if [[ "$ready" != "true" ]]; then
    log "ERROR: VolumeSnapshot $ns/$snap not ready (readyToUse=$ready)"
    return 1
  fi
}

cephcsi_version_on_pod() {
  local pod="$1"
  oc exec -n openshift-storage "$pod" -c csi-rbdplugin -- cephcsi --version 2>/dev/null \
    | grep -oE 'release-[0-9.]+' | head -1 || true
}

wait_for_cephcsi_version() {
  local expected="$1"
  local timeout="${2:-300}"
  local start end
  start=$(date +%s)
  log "Waiting for ALL ceph-csi pods to report $expected (timeout ${timeout}s)..."

  while true; do
    end=$(date +%s)
    if (( end - start >= timeout )); then
      log "ERROR: timeout waiting for cephcsi $expected"
      dump_cephcsi_versions
      return 1
    fi

    local all_ok=true
    local pod ver

    while IFS= read -r pod; do
      [[ -z "$pod" ]] && continue
      pod=${pod#pod/}
      ver=$(cephcsi_version_on_pod "$pod")
      if [[ "$ver" != *"$expected"* ]]; then
        all_ok=false
      fi
    done < <(oc get pods -n openshift-storage \
      -l 'app in (openshift-storage.rbd.csi.ceph.com-ctrlplugin,openshift-storage.rbd.csi.ceph.com-nodeplugin)' \
      -o name 2>/dev/null | grep -v Terminating || true)

    if $all_ok; then
      log "All ceph-csi pods on $expected"
      dump_cephcsi_versions
      return 0
    fi
    sleep 5
  done
}

dump_cephcsi_versions() {
  log "ceph-csi pod versions:"
  local pod ver
  while IFS= read -r pod; do
    [[ -z "$pod" ]] && continue
    pod=${pod#pod/}
    ver=$(cephcsi_version_on_pod "$pod")
    log "  $pod -> ${ver:-unknown}"
  done < <(oc get pods -n openshift-storage \
    -l 'app in (openshift-storage.rbd.csi.ceph.com-ctrlplugin,openshift-storage.rbd.csi.ceph.com-nodeplugin)' \
    -o name 2>/dev/null || true)
}

pause_csi_operator() {
  log "Pausing ceph-csi-controller-manager (prevents image revert during swap)..."
  oc scale deployment ceph-csi-controller-manager -n openshift-storage --replicas=0
  sleep 5
}

resume_csi_operator() {
  log "Resuming ceph-csi-controller-manager..."
  oc scale deployment ceph-csi-controller-manager -n openshift-storage --replicas=1
  oc rollout status deployment ceph-csi-controller-manager -n openshift-storage --timeout=180s
}

swap_cephcsi_image() {
  local img="$1"
  local expected_release="$2"
  log "Swapping cephcsi image to digest ${img##*@}"
  for cname in csi-rbdplugin csi-omap-generator log-rotator; do
    oc set image deployment/openshift-storage.rbd.csi.ceph.com-ctrlplugin \
      -n openshift-storage "${cname}=${img}" 2>/dev/null || true
    oc set image ds/openshift-storage.rbd.csi.ceph.com-nodeplugin \
      -n openshift-storage "${cname}=${img}" 2>/dev/null || true
  done
  oc rollout status deployment/openshift-storage.rbd.csi.ceph.com-ctrlplugin \
    -n openshift-storage --timeout=180s
  oc rollout status ds/openshift-storage.rbd.csi.ceph.com-nodeplugin \
    -n openshift-storage --timeout=300s
  wait_for_cephcsi_version "$expected_release" 300
  sleep 10
}

swap_to_419() { swap_cephcsi_image "$IMG_419" "release-4.19"; }
swap_to_422() { swap_cephcsi_image "$IMG_422" "release-4.22"; }

cleanup_pvcs_by_prefix() {
  local ns="$1" prefix="$2"
  log "Cleaning PVCs matching ${prefix}* in $ns..."
  mapfile -t pvcs < <(oc get pvc -n "$ns" -o name 2>/dev/null | grep "/${prefix}" || true)
  for p in "${pvcs[@]}"; do
    oc delete "$p" -n "$ns" --wait=false 2>/dev/null || true
  done
  local i cnt
  for i in $(seq 1 120); do
    sleep 3
    cnt=$(oc get pvc -n "$ns" --no-headers 2>/dev/null | grep -c "$prefix" 2>/dev/null || true)
    [[ "${cnt:-0}" -eq 0 ]] && break
  done
  sleep 5
}

run_pvc_clone_test() {
  local label="$1"
  local count="${2:-100}"
  local sc="${3:-$VIRT_SC}"
  local snap_ns="${4:-$SOURCE_NS}"
  local snap_name="${5:-$SOURCE_SNAP}"
  local prefix="${6:-clone-test}"
  local ns="${7:-$SOURCE_NS}"

  verify_snapshot_ready "$snap_ns" "$snap_name"
  cleanup_pvcs_by_prefix "$ns" "$prefix"

  log "=== PVC clone: $label ($count PVCs, SC=$sc, snap=$snap_ns/$snap_name) ==="
  local start end ms bound elapsed=0
  start=$(date +%s%N)

  local i
  for i in $(seq 1 "$count"); do
    oc apply -n "$ns" -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ${prefix}-${i}
spec:
  dataSource:
    name: ${snap_name}
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
  accessModes: [ReadWriteMany]
  storageClassName: ${sc}
  volumeMode: Block
  resources:
    requests:
      storage: 10Gi
EOF
  done >/dev/null

  while (( elapsed < 600 )); do
    sleep 10
    elapsed=$((elapsed + 10))
    bound=$(oc get pvc -n "$ns" --no-headers 2>/dev/null \
      | grep "$prefix" | grep -c Bound 2>/dev/null || true)
    log "  ${elapsed}s: ${bound:-0}/${count} bound"
    if [[ "${bound:-0}" -ge "$count" ]]; then
      end=$(date +%s%N)
      ms=$(( (end - start) / 1000000 ))
      log "==> $label: ${ms}ms ($((ms / 1000))s)"
      record_result "pvc-clone" "$label" "bind_${count}" "$ms" "sc=${sc}"
      cleanup_pvcs_by_prefix "$ns" "$prefix"
      echo "$ms"
      return 0
    fi
  done

  log "==> $label: TIMEOUT"
  record_result "pvc-clone" "$label" "bind_${count}" "TIMEOUT" "sc=${sc}"
  cleanup_pvcs_by_prefix "$ns" "$prefix"
  return 1
}

create_fresh_snapshot() {
  local ns="$1" snap_name="$2" src_pvc="$3"
  log "Creating fresh snapshot $ns/$snap_name from PVC $src_pvc"
  oc apply -n "$ns" -f - <<EOF
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: ${snap_name}
spec:
  volumeSnapshotClassName: ocs-storagecluster-rbdplugin-snapclass
  source:
    persistentVolumeClaimName: ${src_pvc}
EOF
  local i ready
  for i in $(seq 1 60); do
    ready=$(oc get volumesnapshot "$snap_name" -n "$ns" \
      -o jsonpath='{.status.readyToUse}' 2>/dev/null || echo "false")
    [[ "$ready" == "true" ]] && { log "Fresh snapshot $snap_name ready"; return 0; }
    sleep 5
  done
  log "ERROR: fresh snapshot $snap_name not ready"
  return 1
}

rbd_uuid_from_handle() {
  local handle="$1"
  echo "$handle" | grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' || true
}

rbd_pool_for_sc() {
  local sc="${1:-$VIRT_SC}"
  local pool
  pool=$(oc get storageclass "$sc" -o jsonpath='{.parameters.pool}' 2>/dev/null || true)
  [[ -n "$pool" ]] && echo "$pool" || echo "ocs-storagecluster-cephblockpool"
}

ensure_rbd_toolbox() {
  local pod="rbd-test4"
  if oc get pod "$pod" -n openshift-storage -o jsonpath='{.status.phase}' 2>/dev/null \
    | grep -q Running; then
    return 0
  fi

  oc delete pod "$pod" -n openshift-storage --ignore-not-found --wait=true 2>/dev/null || true

  local mon_host mon_init osd_img
  mon_host=$(oc get secret rook-ceph-config -n openshift-storage \
    -o jsonpath='{.data.mon_host}' | base64 -d)
  mon_init=$(oc get secret rook-ceph-config -n openshift-storage \
    -o jsonpath='{.data.mon_initial_members}' | base64 -d)
  osd_img=$(oc get pod -n openshift-storage -l app=rook-ceph-osd \
    -o jsonpath='{.items[0].spec.containers[0].image}')

  oc apply -n openshift-storage -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: rbd-test4-ceph-conf
data:
  ceph.conf: |
    [global]
    mon_host = ${mon_host}
    mon_initial_members = ${mon_init}
    auth_cluster_required = cephx
    auth_service_required = cephx
    auth_client_required = cephx
---
apiVersion: v1
kind: Pod
metadata:
  name: ${pod}
spec:
  restartPolicy: Never
  containers:
  - name: toolbox
    image: ${osd_img}
    command: ["sleep","3600"]
    volumeMounts:
    - name: ceph-conf
      mountPath: /etc/ceph/ceph.conf
      subPath: ceph.conf
    - name: ceph-keyring
      mountPath: /etc/ceph/ceph.client.admin.keyring
      subPath: keyring
  volumes:
  - name: ceph-conf
    configMap:
      name: rbd-test4-ceph-conf
  - name: ceph-keyring
    secret:
      secretName: rook-ceph-admin-keyring
EOF
  oc wait pod/"$pod" -n openshift-storage --for=condition=Ready --timeout=120s
}

get_rbd_exec_pod() {
  if oc get pod rbd-test4 -n openshift-storage -o jsonpath='{.status.phase}' 2>/dev/null \
    | grep -q Running; then
    echo "toolbox:rbd-test4"
    return 0
  fi
  echo ""
}

rbd_image_from_pvc() {
  local pvc="$1" ns="$2"
  local pv handle uuid
  pv=$(oc get pvc "$pvc" -n "$ns" -o jsonpath='{.spec.volumeName}' 2>/dev/null || true)
  [[ -z "$pv" ]] && return 1
  handle=$(oc get pv "$pv" -o jsonpath='{.spec.csi.volumeHandle}' 2>/dev/null || true)
  [[ -z "$handle" ]] && return 1
  uuid=$(rbd_uuid_from_handle "$handle")
  [[ -z "$uuid" ]] && return 1
  echo "csi-vol-${uuid}"
}

rbd_snap_image_from_handle() {
  local handle="$1"
  local uuid
  uuid=$(rbd_uuid_from_handle "$handle")
  [[ -z "$uuid" ]] && return 1
  echo "csi-snap-${uuid}"
}

rbd_list_images() {
  local pool="$1"
  local exec_target pod
  exec_target=$(get_rbd_exec_pod)
  [[ -z "$exec_target" ]] && return 1
  pod="${exec_target#*:}"
  oc exec -n openshift-storage "$pod" -c toolbox -- rbd ls "$pool" 2>/dev/null || true
}

rbd_info_features() {
  local image="$1" pool="${2:-}"
  local exec_target pod out
  [[ -z "$pool" ]] && pool=$(rbd_pool_for_sc "$VIRT_SC")
  exec_target=$(get_rbd_exec_pod)
  if [[ -z "$exec_target" ]]; then
    log "WARN: no RBD toolbox pod; call ensure_rbd_toolbox first"
    return 1
  fi
  pod="${exec_target#*:}"
  log "rbd info: pool=$pool image=$image"
  out=$(oc exec -n openshift-storage "$pod" -c toolbox -- \
    rbd info "$pool/$image" 2>&1) || {
    log "WARN: rbd info failed for $pool/$image: $out"
    return 1
  }
  echo "$out" | grep -E '^\s+features:|^\s+op_features:' || true
}

rbd_features_for_pvc() {
  local pvc="$1" ns="$2" pool="${3:-}"
  local image
  image=$(rbd_image_from_pvc "$pvc" "$ns") || return 1
  rbd_info_features "$image" "$pool"
}

ensure_cdi_clone_permissions() {
  oc apply -f "${RESULTS_DIR}/cdi-clone-rbac.yml"
  oc annotate namespace "${SOURCE_NS}" cdi.kubevirt.io/clone-source=true --overwrite
  log "CDI cross-namespace clone RBAC applied on ${SOURCE_NS}"
}

cleanup_vm_density() {
  log "Cleaning kube-burner vm-density namespaces..."
  for ns in vm-density-0 vm-density-1; do
    oc delete vm -n "$ns" -l repro=cnv95003 --wait=false 2>/dev/null || true
    oc delete dv -n "$ns" --all --wait=false 2>/dev/null || true
    oc delete namespace "$ns" --wait=false 2>/dev/null || true
  done
}

run_kubeburner_vm_test() {
  local label="$1"
  local test_dir="${RESULTS_DIR}"
  cleanup_vm_density
  sleep 15

  log "=== VM creation (kube-burner): $label - 100 VMs (2x50) ==="
  local start end ms logfile
  start=$(date +%s%N)
  logfile="${test_dir}/kubeburner-${label}-$(date +%Y%m%d-%H%M%S).log"

  (
    cd "$test_dir"
    kube-burner init -c kube-burner-config.yml
  ) 2>&1 | tee "$logfile"

  end=$(date +%s%N)
  ms=$(( (end - start) / 1000000 ))
  local running
  running=$(oc get vmi -A --no-headers -l repro=cnv95003 2>/dev/null | grep -c Running || true)
  log "==> $label: ${ms}ms ($((ms / 1000))s), Running VMIs: ${running:-0}/100"
  record_result "vm-creation" "$label" "kubeburner_100vm" "$ms" "running=${running:-0}"

  grep -E 'PodReady|Ready|Initialized|PodScheduled' "$logfile" | tail -20 | tee -a "$SUITE_LOG" || true
  cleanup_vm_density
  echo "$ms"
}
