#!/usr/bin/env bash
#
# Map NVMe disks to OCP hosts via oc debug.
# Runs on the bastion host (or locally if KUBECONFIG is set).
# Outputs to both stdout and a TSV file for later use.
#
set -euo pipefail

export KUBECONFIG="${KUBECONFIG:-/home/kni/clusterconfigs/auth/kubeconfig}"

OUTFILE="${1:-nvme-disk-map-$(date +%Y%m%d-%H%M%S).tsv}"
SEPARATOR="======================================================================"

echo -e "node\tpci_path\tdevice" > "$OUTFILE"

for node in $(oc get node -oname); do
    name="${node#node/}"
    echo ""
    echo "$SEPARATOR"
    echo "NODE: $name"
    echo "$SEPARATOR"

    output=$(oc debug "$node" --quiet -- chroot /host ls -al /dev/disk/by-path/ 2>/dev/null \
        | grep nvme || true)

    if [[ -z "$output" ]]; then
        echo "  (no nvme disks found)"
        continue
    fi

    echo "$output"
    while read -r line; do
        pci_path=$(echo "$line" | awk '{print $(NF-2)}')
        device=$(echo "$line" | awk '{print $NF}' | sed 's|../../||')
        echo -e "${name}\t${pci_path}\t${device}" >> "$OUTFILE"
    done <<< "$output"
done

echo ""
echo "Mapping saved to: $OUTFILE"
