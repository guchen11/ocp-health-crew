#!/bin/bash
set -euo pipefail

KUBECONFIG=/root/mno/kubeconfig
export KUBECONFIG

echo "=== Step 1: Create source namespace ==="
oc create namespace source-ns --dry-run=client -o yaml | oc apply -f -

echo "=== Step 2: Create source DataVolume ==="
oc apply -f /root/repro-cnv95003/dv-source.yml

echo "=== Step 3: Wait for source DV to complete (up to 10m) ==="
oc wait datavolume/source-dv -n source-ns --for=condition=Ready --timeout=600s

echo "=== Step 4: Verify PVC is Bound ==="
oc get pvc source-dv -n source-ns

echo "=== Step 5: Create VolumeSnapshot ==="
oc apply -f /root/repro-cnv95003/dv-volsnap.yml

echo "=== Step 6: Wait for snapshot to be ready (up to 5m) ==="
for i in $(seq 1 60); do
    READY=$(oc get volumesnapshot source-snapshot -n source-ns -o jsonpath='{.status.readyToUse}' 2>/dev/null || echo "false")
    if [ "$READY" = "true" ]; then
        echo "Snapshot ready!"
        break
    fi
    echo "Waiting for snapshot... ($i/60)"
    sleep 5
done

oc get volumesnapshot source-snapshot -n source-ns
echo "=== Source DV + Snapshot ready ==="
