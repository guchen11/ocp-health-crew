#!/bin/bash
set -euo pipefail

KUBECONFIG=/root/mno/kubeconfig
export KUBECONFIG

MON=$(oc get pods -n openshift-storage -l app=rook-ceph-mon --no-headers -o name | head -1)
CEPH_CMD="oc exec -n openshift-storage $MON -c mon -- ceph -m 172.30.143.36:3300 --keyring /etc/ceph/keyring-store/keyring --name mon."
RESULTS="/root/repro-cnv95003/ceph-monitor.log"

echo "=== Ceph Monitoring During Clone Test ===" > "$RESULTS"
echo "Started: $(date -u)" >> "$RESULTS"

for i in $(seq 1 24); do
    echo "" >> "$RESULTS"
    echo "--- Sample $i at $(date -u) ---" >> "$RESULTS"
    echo "OSD Perf:" >> "$RESULTS"
    $CEPH_CMD osd perf 2>/dev/null >> "$RESULTS"
    echo "IO:" >> "$RESULTS"
    $CEPH_CMD status 2>/dev/null | grep -A2 "io:" >> "$RESULTS"
    echo "Block Pool:" >> "$RESULTS"
    $CEPH_CMD osd pool stats ocs-storagecluster-cephblockpool 2>/dev/null >> "$RESULTS"
    sleep 5
done

echo "" >> "$RESULTS"
echo "=== Monitoring Complete ===" >> "$RESULTS"
echo "Results saved to $RESULTS"
