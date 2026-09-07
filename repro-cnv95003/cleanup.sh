#!/bin/bash
set -euo pipefail

KUBECONFIG=/root/mno/kubeconfig
export KUBECONFIG

echo "=== Cleaning up repro VMs ==="
for ns in $(oc get ns --no-headers -o name | grep vm-density); do
    echo "Deleting $ns..."
    oc delete "$ns" --wait=false
done

echo "=== Cleaning up source namespace ==="
oc delete namespace source-ns --wait=false 2>/dev/null || true

echo "=== Cleanup initiated (namespaces deleting in background) ==="
