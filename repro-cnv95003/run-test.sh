#!/bin/bash
set -euo pipefail

KUBECONFIG=/root/mno/kubeconfig
export KUBECONFIG

TEST_DIR=/root/repro-cnv95003
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
LOG_FILE="${TEST_DIR}/results-${TIMESTAMP}.log"

echo "=== CNV-95003 Reproduction Test ===" | tee "$LOG_FILE"
echo "Timestamp: $(date -u)" | tee -a "$LOG_FILE"
echo "OCP: $(oc get clusterversion -o jsonpath='{.items[0].status.desired.version}')" | tee -a "$LOG_FILE"
echo "CNV: $(oc get csv -n openshift-cnv --no-headers | grep kubevirt-hyperconverged | awk '{print $NF}')" | tee -a "$LOG_FILE"
echo "ODF: $(oc get storagecluster -n openshift-storage -o jsonpath='{.items[0].status.phase}')" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

echo "=== Pre-test: Verify snapshot exists ==="  | tee -a "$LOG_FILE"
oc get volumesnapshot source-snapshot -n source-ns -o jsonpath='{.status.readyToUse}' | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

echo "=== Starting kube-burner (QPS=10, BURST=10, 2 iterations x 50 replicas = 100 VMs) ===" | tee -a "$LOG_FILE"
START_TIME=$(date +%s)

cd "$TEST_DIR"
kube-burner init -c kube-burner-config.yml 2>&1 | tee -a "$LOG_FILE"

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo "" | tee -a "$LOG_FILE"
echo "=== Test completed in ${ELAPSED}s ===" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

echo "=== VM status summary ===" | tee -a "$LOG_FILE"
oc get vmi -A --no-headers -l repro=cnv95003 | awk '{print $4}' | sort | uniq -c | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

echo "=== DV status summary ===" | tee -a "$LOG_FILE"
oc get dv -A --no-headers | grep "dv-clone" | awk '{print $NF}' | sort | uniq -c | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

echo "=== Pod latency (from kube-burner) in log above ===" | tee -a "$LOG_FILE"
echo "Results saved to: $LOG_FILE"
