"""
CNV Scenarios Configuration

Defines the available kube-burner test scenarios for the HealthCrew dashboard.
Each scenario maps to a test name understood by run-workloads.sh in the
cnv-scenarios repository.

Variables are env-var overrides passed to run-workloads.sh.  Names are
case-sensitive and must match the YAML vars files exactly.

Variables are split into:
  - CNV_GLOBAL_VARIABLES: apply to any/all scenarios
  - per-scenario "variables": unique to that test
"""

# ─── Global variables (shared across most/all scenarios) ─────────────────────
CNV_GLOBAL_VARIABLES = {
    "storageClassName": {
        "type": "str", "label": "Storage Class",
        "icon": "💿",
        "default": {"sanity": "", "full": ""},
        "placeholder": {"sanity": "default: ocs-storagecluster-ceph-rbd-virtualization", "full": "default: ocs-storagecluster-ceph-rbd-virtualization"},
    },
    "nodeSelector": {
        "type": "str", "label": "Node Selector",
        "icon": "🎯",
        "default": {"sanity": "", "full": ""},
        "placeholder": {"sanity": "e.g. node-role.kubernetes.io/worker=", "full": "e.g. node-role.kubernetes.io/worker="},
    },
    "maxWaitTimeout": {
        "type": "str", "label": "Max Wait Timeout",
        "icon": "⏱️",
        "default": {"sanity": "5m", "full": "30m"},
        "placeholder": {"sanity": "Sanity default: 5m", "full": "Full default: 30m"},
    },
    "jobPause": {
        "type": "str", "label": "Job Pause",
        "icon": "⏸️",
        "default": {"sanity": "10s", "full": "2m"},
        "placeholder": {"sanity": "Sanity default: 10s", "full": "Full default: 2m"},
    },
    "cleanup": {
        "type": "bool", "label": "Cleanup After Test",
        "icon": "🧹",
        "default": {"sanity": True, "full": True},
        "placeholder": {"sanity": "", "full": ""},
    },
}


CNV_SCENARIOS = {
    # ─── Resource Limits ─────────────────────────────────────────────────
    "cpu_limits": {
        "name": "CPU Limits",
        "icon": "🔥",
        "description": "Test CPU core allocations per VM with OS-level verification (nproc + stress-ng)",
        "category": "Resource Limits",
        "remote_name": "cpu-limits",
        "default": True,
        "variables": {
            "cpuCores": {"type": "int", "default": 1, "label": "CPU Cores", "min": 1, "max": 128},
            "vmCount": {"type": "int", "default": 1, "label": "VM Count", "min": 1, "max": 50},
            "memory": {"type": "str", "default": "2Gi", "label": "Memory per VM", "placeholder": "e.g. 2Gi, 8Gi"},
            "storage": {"type": "str", "default": "10Gi", "label": "Storage Size", "placeholder": "e.g. 10Gi, 50Gi"},
            "volumeMode": {"type": "choice", "default": "Block", "label": "Volume Mode", "choices": ["Block", "Filesystem"]},
        },
    },
    "memory_limits": {
        "name": "Memory Limits",
        "icon": "💾",
        "description": "Test memory allocations per VM with OS-level verification (free -m + stress-ng)",
        "category": "Resource Limits",
        "remote_name": "memory-limits",
        "default": True,
        "variables": {
            "memorySize": {"type": "str", "default": "2Gi", "label": "Memory Size", "placeholder": "e.g. 4Gi, 64Gi, 450Gi"},
            "vmCount": {"type": "int", "default": 1, "label": "VM Count", "min": 1, "max": 50},
            "cpuCores": {"type": "int", "default": 16, "label": "CPU Cores", "min": 1, "max": 128},
            "storage": {"type": "str", "default": "20Gi", "label": "Storage Size", "placeholder": "e.g. 20Gi, 50Gi"},
            "volumeMode": {"type": "choice", "default": "Block", "label": "Volume Mode", "choices": ["Block", "Filesystem"]},
        },
    },
    "disk_limits": {
        "name": "Disk Limits",
        "icon": "💿",
        "description": "Test disk count and sizes per VM with OS-level verification (lsblk)",
        "category": "Resource Limits",
        "remote_name": "disk-limits",
        "default": True,
        "variables": {
            "diskCount": {"type": "int", "default": 1, "label": "Disk Count", "min": 1, "max": 20},
            "diskSize": {"type": "str", "default": "10Gi", "label": "Disk Size", "placeholder": "e.g. 10Gi, 100Gi, 100Ti"},
            "vmCount": {"type": "int", "default": 1, "label": "VM Count", "min": 1, "max": 50},
            "cpuCores": {"type": "int", "default": 16, "label": "CPU Cores", "min": 1, "max": 128},
            "memory": {"type": "str", "default": "32Gi", "label": "Memory per VM", "placeholder": "e.g. 32Gi"},
            "volumeMode": {"type": "choice", "default": "Block", "label": "Volume Mode", "choices": ["Block", "Filesystem"]},
        },
    },

    # ─── Hot-plug ────────────────────────────────────────────────────────
    "disk_hotplug": {
        "name": "Disk Hot-plug",
        "icon": "🔌",
        "description": "Test hot-plugging up to 256 disks per VM with automated mounting and OS validation",
        "category": "Hot-plug",
        "remote_name": "disk-hotplug",
        "default": True,
        "variables": {
            "diskCount": {"type": "int", "default": 15, "label": "Disk Count", "min": 1, "max": 256},
            "pvcSize": {"type": "str", "default": "2Gi", "label": "PVC Size", "placeholder": "e.g. 1Gi, 5Gi"},
            "vmCount": {"type": "int", "default": 1, "label": "VM Count", "min": 1, "max": 10},
            "cpuCores": {"type": "int", "default": 2, "label": "CPU Cores", "min": 1, "max": 32},
            "memory": {"type": "str", "default": "4Gi", "label": "Memory per VM", "placeholder": "e.g. 4Gi"},
            "storage": {"type": "str", "default": "20Gi", "label": "Root Disk Size", "placeholder": "e.g. 20Gi"},
            "volumeMode": {"type": "choice", "default": "Block", "label": "Volume Mode", "choices": ["Block", "Filesystem"]},
            "validateHotplugFromOs": {"type": "bool", "default": True, "label": "Validate from OS (SSH)"},
            "validatePvcBySize": {"type": "bool", "default": True, "label": "Validate PVC sizes"},
            "hotplugPersist": {"type": "bool", "default": True, "label": "Persist hot-plugged volumes"},
            "hotplugTimeout": {"type": "str", "default": "15m", "label": "Hot-plug Timeout", "placeholder": "e.g. 15m, 30m"},
        },
    },
    "nic_hotplug": {
        "name": "NIC Hot-plug",
        "icon": "🌐",
        "description": "Test adding up to 28 network interfaces per VM (simple bridge + VLAN bridge)",
        "category": "Hot-plug",
        "remote_name": "nic-hotplug",
        "default": True,
        "variables": {
            "nicCount": {"type": "int", "default": 25, "label": "NIC Count", "min": 1, "max": 28},
            "baseInterface": {"type": "str", "default": "", "label": "Base Interface", "placeholder": "auto-detect if empty (e.g. ens2f0)"},
            "cleanupNncp": {"type": "bool", "default": True, "label": "Cleanup NNCPs after test"},
            "cpuCores": {"type": "int", "default": 8, "label": "CPU Cores", "min": 1, "max": 64},
            "memory": {"type": "str", "default": "16Gi", "label": "Memory per VM", "placeholder": "e.g. 16Gi"},
            "storage": {"type": "str", "default": "50Gi", "label": "Storage Size", "placeholder": "e.g. 50Gi"},
        },
    },

    # ─── Performance ─────────────────────────────────────────────────────
    "high_memory": {
        "name": "High Memory",
        "icon": "📈",
        "description": "Test performance with high memory allocation and guest OS validation",
        "category": "Performance",
        "remote_name": "high-memory",
        "default": True,
        "variables": {
            "highMemory": {"type": "str", "default": "450Gi", "label": "Memory Size", "placeholder": "e.g. 64Gi, 256Gi, 450Gi"},
            "vmCount": {"type": "int", "default": 1, "label": "VM Count", "min": 1, "max": 10},
            "cpuCores": {"type": "int", "default": 16, "label": "CPU Cores", "min": 1, "max": 128},
            "storage": {"type": "str", "default": "50Gi", "label": "Storage Size", "placeholder": "e.g. 50Gi"},
            "volumeMode": {"type": "choice", "default": "Block", "label": "Volume Mode", "choices": ["Block", "Filesystem"]},
            "enablePerfTest": {"type": "bool", "default": True, "label": "Enable perf test in VM"},
        },
    },
    "large_disk": {
        "name": "Large Disk",
        "icon": "🗄️",
        "description": "Test performance with very large disks and guest OS size validation",
        "category": "Performance",
        "remote_name": "large-disk",
        "default": True,
        "variables": {
            "largeDiskSize": {"type": "str", "default": "100Ti", "label": "Large Disk Size", "placeholder": "e.g. 500Gi, 1Ti, 100Ti"},
            "rootStorage": {"type": "str", "default": "50Gi", "label": "Root Storage", "placeholder": "e.g. 50Gi"},
            "vmCount": {"type": "int", "default": 1, "label": "VM Count", "min": 1, "max": 10},
            "cpuCores": {"type": "int", "default": 16, "label": "CPU Cores", "min": 1, "max": 128},
            "memory": {"type": "str", "default": "32Gi", "label": "Memory per VM", "placeholder": "e.g. 32Gi"},
            "volumeMode": {"type": "choice", "default": "Block", "label": "Volume Mode", "choices": ["Block", "Filesystem"]},
            "enablePerfTest": {"type": "bool", "default": True, "label": "Enable perf test in VM"},
        },
    },
    "minimal_resources": {
        "name": "Minimal Resources",
        "icon": "🪶",
        "description": "Test with minimal resource allocation using CirrOS VMs and password-based SSH",
        "category": "Performance",
        "remote_name": "minimal-resources",
        "default": True,
        "variables": {
            "vmCount": {"type": "int", "default": 1, "label": "VM Count", "min": 1, "max": 50},
            "minCpu": {"type": "str", "default": "100m", "label": "Min CPU", "placeholder": "e.g. 100m, 250m (milliCPU)"},
            "minMemory": {"type": "str", "default": "64Mi", "label": "Min Memory", "placeholder": "e.g. 64Mi, 128Mi, 256Mi"},
            "minStorage": {"type": "str", "default": "100Mi", "label": "Min Storage", "placeholder": "e.g. 100Mi, 256Mi"},
        },
    },

    # ─── Scale ───────────────────────────────────────────────────────────
    "per_host_density": {
        "name": "Per-Host Density",
        "icon": "📊",
        "description": "Test VM density with single-node or multi-node distribution, multiple namespaces",
        "category": "Scale",
        "remote_name": "per-host-density",
        "default": False,
        "variables": {
            "vmsPerNamespace": {"type": "int", "default": 30, "label": "VMs per Namespace", "min": 1, "max": 1000},
            "namespaceCount": {"type": "int", "default": 15, "label": "Namespace Count", "min": 1, "max": 100},
            "scaleMode": {"type": "choice", "default": "single-node", "label": "Scale Mode", "choices": ["single-node", "multi-node"]},
            "targetNode": {"type": "str", "default": "", "label": "Target Node", "placeholder": "auto-select if empty (single-node only)"},
            "cleanup": {"type": "bool", "default": True, "label": "Cleanup namespaces after test"},
            "percentage_of_vms_to_validate": {"type": "int", "default": 50, "label": "VM Validation % (SSH)", "min": 0, "max": 100},
            "max_ssh_retries": {"type": "int", "default": 240, "label": "Max SSH Retries", "min": 1, "max": 1000},
            "vmMemory": {"type": "str", "default": "256Mi", "label": "VM Memory", "placeholder": "e.g. 256Mi, 512Mi"},
            "vmCpuCores": {"type": "int", "default": 100, "label": "VM CPU (milliCPU)", "min": 50, "max": 16000},
            "vmCpuRequest": {"type": "str", "default": "100m", "label": "CPU Request", "placeholder": "e.g. 100m (milliCPU)"},
            "vmCpuLimit": {"type": "str", "default": "1000m", "label": "CPU Limit", "placeholder": "e.g. 1000m (milliCPU)"},
            "sourceStorageSize": {"type": "int", "default": 256, "label": "Source DV Size (MiB)", "min": 64, "max": 10240},
            "vmStorageSize": {"type": "int", "default": 256, "label": "VM Disk Size (MiB)", "min": 64, "max": 10240},
            "imageUrl": {"type": "str", "default": "", "label": "VM Image URL", "placeholder": "default: Alpine 3.22 cloud image"},
            "shutdownBatchSize": {"type": "int", "default": 50, "label": "Shutdown Batch Size", "min": 1, "max": 500},
            "sleepBetweenPhases": {"type": "str", "default": "2m", "label": "Sleep Between Phases", "placeholder": "e.g. 2m, 5m"},
            "skipVmShutdown": {"type": "bool", "default": False, "label": "Skip VM Shutdown phase"},
            "skipVmRestart": {"type": "bool", "default": False, "label": "Skip VM Restart phase"},
            "qpsCreate": {"type": "int", "default": 20, "label": "Create QPS", "min": 1, "max": 200},
            "burstCreate": {"type": "int", "default": 40, "label": "Create Burst", "min": 1, "max": 400},
            "qpsShutdown": {"type": "int", "default": 10, "label": "Shutdown QPS", "min": 1, "max": 200},
            "burstShutdown": {"type": "int", "default": 20, "label": "Shutdown Burst", "min": 1, "max": 400},
            "qpsStartup": {"type": "int", "default": 30, "label": "Startup QPS", "min": 1, "max": 200},
            "burstStartup": {"type": "int", "default": 60, "label": "Startup Burst", "min": 1, "max": 400},
        },
    },
    "virt_capacity_benchmark": {
        "name": "Virt Capacity Benchmark",
        "icon": "🏋️",
        "description": "Comprehensive capacity testing with volume resize, restart, snapshot, and migration",
        "category": "Scale",
        "remote_name": "virt-capacity-benchmark",
        "default": False,
        "variables": {
            "vmCount": {"type": "int", "default": 5, "label": "VM Count", "min": 1, "max": 100},
            "rootVolumeSize": {"type": "int", "default": 20, "label": "Root Volume (GiB)", "min": 5, "max": 500},
            "dataVolumeSize": {"type": "int", "default": 10, "label": "Data Volume (GiB)", "min": 1, "max": 500},
            "volumeSizeIncrement": {"type": "int", "default": 5, "label": "Volume Resize Increment (GiB)", "min": 1, "max": 100},
            "skipResizeJob": {"type": "bool", "default": True, "label": "Skip Resize Job"},
            "skipMigrationJob": {"type": "bool", "default": True, "label": "Skip Migration Job"},
            "cleanup": {"type": "bool", "default": True, "label": "Cleanup after test"},
            "percentage_of_vms_to_validate": {"type": "int", "default": 25, "label": "VM Validation % (SSH)", "min": 0, "max": 100},
            "max_ssh_retries": {"type": "int", "default": 8, "label": "Max SSH Retries", "min": 1, "max": 100},
        },
    },
}


CNV_SCENARIO_CATEGORIES = {
    "Resource Limits": {"icon": "📏", "description": "CPU, memory, and disk boundary testing"},
    "Hot-plug": {"icon": "🔌", "description": "Disk and NIC hot-plug testing"},
    "Performance": {"icon": "⚡", "description": "High memory, large disk, minimal resources"},
    "Scale": {"icon": "📊", "description": "VM density and capacity benchmarks"},
}


# Category display order
CNV_CATEGORY_ORDER = ["Resource Limits", "Hot-plug", "Performance", "Scale"]
