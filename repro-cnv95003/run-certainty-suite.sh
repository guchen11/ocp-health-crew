#!/bin/bash
# CNV-95003 certainty test suite - run on clod30 bastion
# Usage:
#   ./run-certainty-suite.sh          # full suite (tests 1-5)
#   ./run-certainty-suite.sh 1        # single test
#   ./run-certainty-suite.sh 1 2 4    # selected tests
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib-cnv95003.sh"

TESTS=("$@")
if [[ ${#TESTS[@]} -eq 0 ]]; then
  TESTS=(1 2 3 4 5)
fi

init_suite
log "========================================"
log "CNV-95003 Certainty Suite starting"
log "Tests: ${TESTS[*]}"
log "Cluster OCP: $(oc get clusterversion -o jsonpath='{.items[0].status.desired.version}' 2>/dev/null || echo unknown)"
dump_cephcsi_versions
pause_csi_operator
log "========================================"

run_test_1_ababa_pvc() {
  log "--- TEST 1: A/B/A PVC clone with rollout gate ---"
  verify_snapshot_ready

  local t419 t422 t419b
  t419=$(run_pvc_clone_test "baseline-4.19" 100 "$VIRT_SC" "$SOURCE_NS" "$SOURCE_SNAP" "t1-a")
  swap_to_422
  t422=$(run_pvc_clone_test "swapped-4.22" 100 "$VIRT_SC" "$SOURCE_NS" "$SOURCE_SNAP" "t1-b")
  swap_to_419
  t419b=$(run_pvc_clone_test "restored-4.19" 100 "$VIRT_SC" "$SOURCE_NS" "$SOURCE_SNAP" "t1-ap")

  log "TEST 1 summary: baseline=${t419}ms swapped=${t422}ms restored=${t419b}ms"
  record_result "test1-ababa" "summary" "baseline" "$t419" ""
  record_result "test1-ababa" "summary" "swapped" "$t422" ""
  record_result "test1-ababa" "summary" "restored" "$t419b" ""
}

run_test_2_vm_ababa() {
  log "--- TEST 2: VM creation A/B/A (kube-burner, Purti methodology) ---"
  verify_snapshot_ready
  ensure_cdi_clone_permissions

  local t419 t422 t419b
  swap_to_419
  t419=$(run_kubeburner_vm_test "vm-baseline-4.19")
  swap_to_422
  t422=$(run_kubeburner_vm_test "vm-swapped-4.22")
  swap_to_419
  t419b=$(run_kubeburner_vm_test "vm-restored-4.19")

  log "TEST 2 summary: baseline=${t419}ms swapped=${t422}ms restored=${t419b}ms"
  record_result "test2-vm-ababa" "summary" "baseline" "$t419" ""
  record_result "test2-vm-ababa" "summary" "swapped" "$t422" ""
  record_result "test2-vm-ababa" "summary" "restored" "$t419b" ""
}

run_test_3_fresh_snapshot() {
  log "--- TEST 3: Fresh snapshot 100-clone A/B ---"
  local fresh_ns="fresh-snap-ns"
  oc create namespace "$fresh_ns" --dry-run=client -o yaml | oc apply -f -

  log "Importing source PVC for fresh snapshot..."
  oc apply -n "$fresh_ns" -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: fresh-source-pvc
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: ${VIRT_SC}
  volumeMode: Block
  resources:
    requests:
      storage: 10Gi
  dataSourceRef:
    name: ${SOURCE_SNAP}
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
    namespace: ${SOURCE_NS}
EOF

  local i phase
  for i in $(seq 1 120); do
    phase=$(oc get pvc fresh-source-pvc -n "$fresh_ns" \
      -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
    [[ "$phase" == "Bound" ]] && break
    sleep 5
  done
  [[ "$phase" != "Bound" ]] && { log "ERROR: fresh-source-pvc not bound"; return 1; }

  create_fresh_snapshot "$fresh_ns" "fresh-snapshot" "fresh-source-pvc"

  local t419 t422
  swap_to_419
  t419=$(run_pvc_clone_test "fresh-baseline-4.19" 100 "$VIRT_SC" "$fresh_ns" "fresh-snapshot" "t3-a" "$fresh_ns")
  swap_to_422
  t422=$(run_pvc_clone_test "fresh-swapped-4.22" 100 "$VIRT_SC" "$fresh_ns" "fresh-snapshot" "t3-b" "$fresh_ns")

  log "TEST 3 summary: fresh baseline=${t419}ms fresh swapped=${t422}ms"
  swap_to_419
  oc delete namespace "$fresh_ns" --wait=false 2>/dev/null || true
}

run_test_4_rbd_features() {
  log "--- TEST 4: RBD image features on clone path ---"
  verify_snapshot_ready
  ensure_rbd_toolbox

  local ns="$SOURCE_NS" prefix="t4-feature" pool
  pool=$(rbd_pool_for_sc "$VIRT_SC")
  log "Using RBD pool: $pool"

  local snap_vsc snap_image
  snap_vsc=$(oc get volumesnapshot "$SOURCE_SNAP" -n "$ns" \
    -o jsonpath='{.status.boundVolumeSnapshotContentName}' 2>/dev/null || true)
  if [[ -n "$snap_vsc" ]]; then
    snap_handle=$(oc get volumesnapshotcontent "$snap_vsc" \
      -o jsonpath='{.status.snapshotHandle}' 2>/dev/null || true)
    snap_image=$(rbd_snap_image_from_handle "$snap_handle" 2>/dev/null || true)
  fi
  if [[ -n "$snap_image" ]]; then
    log "Source snapshot backing image $snap_image:"
    rbd_info_features "$snap_image" "$pool" | tee "${RESULTS_DIR}/rbd-features-source-snap.txt"
  fi

  pause_csi_operator
  for ver_label in "4.19" "4.22"; do
    if [[ "$ver_label" == "4.19" ]]; then swap_to_419; else swap_to_422; fi
    cleanup_pvcs_by_prefix "$ns" "$prefix"

    local before_snaps after_snaps new_snaps
    before_snaps=$(mktemp)
    rbd_list_images "$pool" | grep '^csi-snap-' | sort > "$before_snaps" || true

    log "Creating 5 clone PVCs under cephcsi $ver_label for feature inspection..."
    local i
    for i in $(seq 1 5); do
      oc apply -n "$ns" -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ${prefix}-${i}
spec:
  dataSource:
    name: ${SOURCE_SNAP}
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
  accessModes: [ReadWriteMany]
  storageClassName: ${VIRT_SC}
  volumeMode: Block
  resources:
    requests:
      storage: 10Gi
EOF
    done >/dev/null

    for i in $(seq 1 60); do
      sleep 5
      local bound
      bound=$(oc get pvc -n "$ns" --no-headers 2>/dev/null \
        | grep "$prefix" | grep -c Bound 2>/dev/null || true)
      [[ "${bound:-0}" -ge 5 ]] && break
    done

    after_snaps=$(mktemp)
    rbd_list_images "$pool" | grep '^csi-snap-' | sort > "$after_snaps" || true
    new_snaps=$(mktemp)
    comm -13 "$before_snaps" "$after_snaps" > "$new_snaps" || true

    log "RBD clone-volume features for cephcsi $ver_label:"
    for i in $(seq 1 5); do
      local feat_file="${RESULTS_DIR}/rbd-features-${ver_label}-pvc${i}.txt"
      rbd_features_for_pvc "${prefix}-${i}" "$ns" "$pool" | tee "$feat_file"
      record_result "test4-rbd" "$ver_label" "pvc${i}" "n/a" \
        "$(tr '\n' ';' < "$feat_file")"
    done

    log "New snapshot backing images during clone ($ver_label):"
    local snap_line n=0
    while IFS= read -r snap_line; do
      [[ -z "$snap_line" ]] && continue
      n=$((n + 1))
      local snap_file="${RESULTS_DIR}/rbd-features-${ver_label}-newsnap${n}.txt"
      rbd_info_features "$snap_line" "$pool" | tee "$snap_file"
      record_result "test4-rbd" "$ver_label" "newsnap${n}" "n/a" \
        "$(tr '\n' ';' < "$snap_file")"
    done < "$new_snaps"

    rm -f "$before_snaps" "$after_snaps" "$new_snaps"
    cleanup_pvcs_by_prefix "$ns" "$prefix"
  done
  swap_to_419
  resume_csi_operator
}

run_test_5_sc_comparison() {
  log "--- TEST 5: Virt vs non-virt SC delta (30 PVCs each) ---"
  verify_snapshot_ready
  local count=30

  for ver_label in "4.19" "4.22"; do
    if [[ "$ver_label" == "4.19" ]]; then swap_to_419; else swap_to_422; fi

    local t_virt t_non
    t_virt=$(run_pvc_clone_test "sc-virt-${ver_label}" "$count" "$VIRT_SC" \
      "$SOURCE_NS" "$SOURCE_SNAP" "t5-virt" "$SOURCE_NS")
    t_non=$(run_pvc_clone_test "sc-nonvirt-${ver_label}" "$count" "$NONVIRT_SC" \
      "$SOURCE_NS" "$SOURCE_SNAP" "t5-non" "$SOURCE_NS")

    log "TEST 5 $ver_label: virt=${t_virt}ms nonvirt=${t_non}ms"
    record_result "test5-sc" "$ver_label" "virt_${count}" "$t_virt" ""
    record_result "test5-sc" "$ver_label" "nonvirt_${count}" "$t_non" ""
  done
  swap_to_419
}

for t in "${TESTS[@]}"; do
  case "$t" in
    1) run_test_1_ababa_pvc ;;
    2) run_test_2_vm_ababa ;;
    3) run_test_3_fresh_snapshot ;;
    4) run_test_4_rbd_features ;;
    5) run_test_5_sc_comparison ;;
    *)
      log "Unknown test: $t (use 1-5)"
      exit 1
      ;;
  esac
done

log "========================================"
log "SUITE COMPLETE"
log "Results CSV: $SUITE_CSV"
log "Full log: $SUITE_LOG"
cat "$SUITE_CSV"
log "========================================"

# Ensure cluster left on 4.19 cephcsi and operator restored
swap_to_419 2>/dev/null || true
resume_csi_operator
