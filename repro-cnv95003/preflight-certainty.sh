#!/bin/bash
# Quick preflight before certainty suite
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib-cnv95003.sh"

init_suite
log "=== Preflight ==="

errors=0

check() {
  local name="$1" cmd="$2"
  if eval "$cmd" >/dev/null 2>&1; then
    log "OK  $name"
  else
    log "FAIL $name"
    errors=$((errors + 1))
  fi
}

check "kubeconfig" "oc whoami"
check "source snapshot" "verify_snapshot_ready"
check "virt SC" "oc get sc $VIRT_SC"
check "non-virt SC" "oc get sc $NONVIRT_SC"
check "cephcsi ctrlplugin" "oc get deploy openshift-storage.rbd.csi.ceph.com-ctrlplugin -n openshift-storage"
check "rbd toolbox prereqs" "oc get secret rook-ceph-admin-keyring -n openshift-storage && oc get pod -l app=rook-ceph-osd -n openshift-storage"
check "kube-burner" "command -v kube-burner"
check "ceph-csi operator" "oc get deploy ceph-csi-controller-manager -n openshift-storage"

dump_cephcsi_versions

if [[ "$errors" -gt 0 ]]; then
  log "Preflight FAILED ($errors checks)"
  exit 1
fi
log "Preflight PASSED - ready to run ./run-certainty-suite.sh"
