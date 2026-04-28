"""
Mapping of validation message patterns to the oc/virtctl commands that produced them.

Used by the report HTML renderer to show the actual command next to each
validation check result. Entries are matched top-down; first match wins.

Each tuple: (pattern1, pattern2_or_None, command_string)
  - pattern1 must appear in the message (case-insensitive)
  - pattern2 (if not None) must also appear
"""

VALIDATION_CMD_MAP = [
    # --- General (all scenarios) ---
    ("Found", "VMs", "oc get vmi -n <ns> --no-headers | wc -l"),
    ("Found", "VM", "oc get vmi -n <ns> --no-headers | wc -l"),
    ("VM running", None, "oc get vmi -n <ns> -o jsonpath='{.status.phase}'"),
    ("VMs running", None,
     "oc get vmi -n <ns> --field-selector=status.phase=Running --no-headers | wc -l"),
    ("SSH reachab", None, "virtctl ssh <vm> -- echo ok"),
    ("SSH connect", None, "virtctl ssh <vm> -- echo ok"),

    # --- cpu-limits ---
    ("VM spec CPU cores", None,
     "oc get vmi <name> -o jsonpath='{.spec.domain.cpu.cores}'"),
    ("VM spec CPU sockets", None,
     "oc get vmi <name> -o jsonpath='{.spec.domain.cpu.sockets}'"),
    ("CPU max sockets", None,
     "oc get vmi <name> -o jsonpath='{.spec.domain.cpu.sockets}'"),
    ("Guest OS CPU count", None, "virtctl ssh <vm> -- nproc"),
    ("nproc", None, "virtctl ssh <vm> -- nproc"),
    ("stress-ng-cpu process count", None,
     "virtctl ssh <vm> -- pgrep -c stress-ng-cpu"),
    ("stress-ng-cpu", None, "virtctl ssh <vm> -- pgrep -c stress-ng-cpu"),

    # --- memory-limits / high-memory ---
    ("VM spec memory", None,
     "oc get vmi <name> -o jsonpath='{.spec.domain.memory.guest}'"),
    ("Guest OS memory", None, "virtctl ssh <vm> -- free -m | grep Mem"),
    ("memtester", None, "virtctl ssh <vm> -- pgrep -c memtester"),
    ("stress-ng-vm", None, "virtctl ssh <vm> -- pgrep -c stress-ng-vm"),
    ("stress-ng", "memory", "virtctl ssh <vm> -- pgrep -c stress-ng-vm"),
    ("stress-ng", "process", "virtctl ssh <vm> -- pgrep -c stress-ng"),
    ("hugepage", None,
     "oc get vmi <name> -o jsonpath='{.spec.domain.memory.hugepages}'"),

    # --- disk-limits ---
    ("disk count", None,
     "virtctl ssh <vm> -- lsblk --noheadings | wc -l"),
    ("disk size", None, "virtctl ssh <vm> -- lsblk -b --noheadings"),
    ("lsblk", None, "virtctl ssh <vm> -- lsblk --noheadings"),
    ("block device", None, "virtctl ssh <vm> -- lsblk --noheadings"),

    # --- disk-hotplug ---
    ("hotplug", "disk", "virtctl addvolume <vm> --volume-name=<pvc>"),
    ("addvolume", None, "virtctl addvolume <vm> --volume-name=<pvc>"),
    ("removevolume", None,
     "virtctl removevolume <vm> --volume-name=<pvc>"),
    ("PVC bound", None,
     "oc get pvc -n <ns> -o jsonpath='{.status.phase}'"),
    ("PVC creat", None, "oc create -f <pvc.yaml> -n <ns>"),
    ("mount", "disk", "virtctl ssh <vm> -- mount | grep /dev/"),
    ("SCSI", None, "virtctl ssh <vm> -- lsblk -S --noheadings"),
    ("persist", "disk", "virtctl ssh <vm> -- lsblk --noheadings"),
    ("persist", "restart", "virtctl restart <vm>"),

    # --- nic-hotplug ---
    ("NIC", "count",
     "virtctl ssh <vm> -- ip link show | grep -c UP"),
    ("vNIC", None, "virtctl ssh <vm> -- ip link show"),
    ("network interface", None, "virtctl ssh <vm> -- ip link show"),
    ("network attachment", None, "oc get net-attach-def -n <ns>"),
    ("NAD", None, "oc get net-attach-def -n <ns>"),
    ("NNCP", None, "oc get nncp"),
    ("NodeNetworkConfigurationPolicy", None, "oc get nncp"),
    ("bridge", None,
     "oc get nncp -o jsonpath='{.spec.desiredState.interfaces}'"),
    ("IP address", None, "virtctl ssh <vm> -- ip addr show"),
    ("ip addr", None, "virtctl ssh <vm> -- ip addr show"),
    ("VLAN", None, "virtctl ssh <vm> -- ip link show | grep vlan"),

    # --- large-disk ---
    ("fio", None,
     "virtctl ssh <vm> -- fio --name=test --rw=read --bs=1M ..."),
    ("hdparm", None, "virtctl ssh <vm> -- hdparm -t /dev/<disk>"),
    ("large disk", None, "virtctl ssh <vm> -- lsblk -b --noheadings"),

    # --- minimal-resources ---
    ("minimal", "boot",
     "oc get vmi -n <ns> -o jsonpath='{.status.phase}'"),
    ("CirrOS", None, "virtctl ssh <vm> -- cat /etc/cirros/version"),
    ("resource limit", None,
     "oc get vmi <name> -o jsonpath='{.spec.domain.resources}'"),
    ("CPU request", None,
     "oc get vmi <name> -o jsonpath='{.spec.domain.resources.requests.cpu}'"),
    ("memory request", None,
     "oc get vmi <name> -o jsonpath='{.spec.domain.resources.requests.memory}'"),

    # --- per-host-density ---
    ("namespace", "count",
     "oc get ns --no-headers | grep <prefix> | wc -l"),
    ("namespace", "creat", "oc create ns <name>"),
    ("VM creat", None, "oc get vm -A --no-headers | wc -l"),
    ("VM density", None,
     "oc get vmi --field-selector=spec.nodeName=<node> --no-headers | wc -l"),
    ("node cordon", None, "oc adm cordon <node>"),
    ("VM shutdown", None, "virtctl stop <vm>"),
    ("VM restart", None, "virtctl start <vm>"),
    ("scale", "namespace",
     "oc get ns --no-headers | grep <prefix> | wc -l"),

    # --- virt-capacity-benchmark ---
    ("volume resize", None,
     "oc patch pvc <name> -p '{\"spec\":{\"resources\":{\"requests\":{\"storage\":...}}}}'"),
    ("resize", None,
     "oc patch vm <name> --type=merge -p '{\"spec\":...}'"),
    ("restart", None, "virtctl restart <vm>"),
    ("snapshot", "creat", "oc apply -f <snapshot.yaml>"),
    ("snapshot", None, "oc get volumesnapshot -n <ns>"),
    ("VolumeSnapshot", None, "oc get volumesnapshot -n <ns>"),
    ("migration", "live", "virtctl migrate <vm>"),
    ("migration", None, "virtctl migrate <vm>"),
    ("VMIM", None, "oc get vmim -n <ns>"),
    ("VirtualMachineInstanceMigration", None, "oc get vmim -n <ns>"),
    ("clone", None, "oc get datavolume -n <ns>"),
    ("DataVolume", None, "oc get dv -n <ns>"),
]


def infer_command(msg):
    """Match a validation message to its likely oc/virtctl command."""
    lower = msg.lower()
    for pattern1, pattern2, cmd in VALIDATION_CMD_MAP:
        if pattern1.lower() in lower:
            if pattern2 is None or pattern2.lower() in lower:
                return cmd
    return None
