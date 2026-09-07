#!/bin/bash
set -euo pipefail

KUBECONFIG=/root/mno/kubeconfig
export KUBECONFIG

NS="dv-isolation-test"
SNAP_NS="source-ns"
SNAP_NAME="source-snapshot"
DV_COUNT=50
RESULTS="/root/repro-cnv95003/dv-only-results.log"

echo "=== DV-Only Isolation Test (no VMs) ===" | tee "$RESULTS"
echo "Testing pure snapshot clone latency without VM overhead" | tee -a "$RESULTS"
echo "Timestamp: $(date -u)" | tee -a "$RESULTS"
echo "DV count: $DV_COUNT" | tee -a "$RESULTS"
echo "" | tee -a "$RESULTS"

oc create namespace "$NS" --dry-run=client -o yaml | oc apply -f -

echo "=== Creating $DV_COUNT DataVolumes from snapshot ===" | tee -a "$RESULTS"
START=$(date +%s%N)

for i in $(seq 1 $DV_COUNT); do
    oc apply -f - <<EOF
apiVersion: cdi.kubevirt.io/v1beta1
kind: DataVolume
metadata:
  name: dv-test-$i
  namespace: $NS
spec:
  source:
    snapshot:
      namespace: $SNAP_NS
      name: $SNAP_NAME
  storage:
    resources:
      requests:
        storage: 10Gi
    storageClassName: ocs-storagecluster-ceph-rbd-virtualization
    volumeMode: Block
EOF
done

CREATE_END=$(date +%s%N)
CREATE_MS=$(( (CREATE_END - START) / 1000000 ))
echo "All $DV_COUNT DVs submitted in ${CREATE_MS}ms" | tee -a "$RESULTS"

echo "=== Waiting for all DVs to complete ===" | tee -a "$RESULTS"
READY_COUNT=0
MAX_WAIT=600
ELAPSED=0
while [ $READY_COUNT -lt $DV_COUNT ] && [ $ELAPSED -lt $MAX_WAIT ]; do
    sleep 5
    ELAPSED=$((ELAPSED + 5))
    READY_COUNT=$(oc get pvc -n "$NS" --no-headers 2>/dev/null | grep -c Bound || echo 0)
    echo "  ${ELAPSED}s: $READY_COUNT/$DV_COUNT PVCs Bound" | tee -a "$RESULTS"
done

TOTAL_END=$(date +%s%N)
TOTAL_MS=$(( (TOTAL_END - START) / 1000000 ))

echo "" | tee -a "$RESULTS"
echo "=== DV Clone Timing Results ===" | tee -a "$RESULTS"
echo "Submit time: ${CREATE_MS}ms" | tee -a "$RESULTS"
echo "Total time (submit + clone): ${TOTAL_MS}ms ($((TOTAL_MS/1000))s)" | tee -a "$RESULTS"
echo "Avg per DV: $((TOTAL_MS / DV_COUNT))ms" | tee -a "$RESULTS"
echo "" | tee -a "$RESULTS"

echo "=== Per-DV timing (creation to Bound) ===" | tee -a "$RESULTS"
for i in $(seq 1 $DV_COUNT); do
    CREATED=$(oc get dv "dv-test-$i" -n "$NS" -o jsonpath='{.metadata.creationTimestamp}' 2>/dev/null)
    PHASE=$(oc get dv "dv-test-$i" -n "$NS" -o jsonpath='{.status.phase}' 2>/dev/null)
    PVC_STATUS=$(oc get pvc "dv-test-$i" -n "$NS" -o jsonpath='{.status.phase}' 2>/dev/null)
    echo "  dv-test-$i: created=$CREATED phase=$PHASE pvc=$PVC_STATUS" >> "$RESULTS"
done

echo "=== DV Phase Summary ===" | tee -a "$RESULTS"
oc get dv -n "$NS" --no-headers | awk '{print $NF}' | sort | uniq -c | tee -a "$RESULTS"

echo "Results saved to $RESULTS"
