"""
Built-in Templates for CNV Scenarios

Pre-configured run templates seeded into the database on first startup.
Each scenario has a sanity (quick validation) and full (regression) variant.
Values for full templates sourced from the CNV 4.21 regression test report.
"""


def _tpl(name, description, icon, mode, tests, env_vars,
         timeout='2h', parallel=False, email=True):
    """Build a template dict with standard structure."""
    return {
        'name': name,
        'description': description,
        'icon': icon,
        'config': {
            'task_type': 'cnv_scenarios',
            'run_name': name,
            'scenario_mode': mode,
            'scenario_tests': tests,
            'scenario_parallel': parallel,
            'kb_timeout': timeout,
            'kb_log_level': '',
            'email': email,
            'env_vars': env_vars,
        },
    }


BUILTIN_TEMPLATES = [
    # ─── Maximum virtual CPUs per VM ──────────────────────────────────────
    _tpl(
        name='Sanity - Max vCPUs per VM',
        description='1 vCPU socket with nproc + stress-ng verification.',
        icon='🔥', mode='sanity', tests=['cpu-limits'], timeout='30m',
        env_vars={
            'cpu_limits.cpuCores': '1',
            'cpu_limits.cpuSockets': '1',
            'cpu_limits.cpuMaxSockets': '1',
            'cpu_limits.bootloaderEfi': 'true',
            'cpu_limits.memory': '512Mi',
            'cpu_limits.storage': '10Gi',
        },
    ),
    _tpl(
        name='Full - Max vCPUs per VM',
        description='512 vCPUs per VM with nproc + stress-ng verification.',
        icon='🔥', mode='full', tests=['cpu-limits'], timeout='2h',
        env_vars={
            'cpu_limits.cpuCores': '1',
            'cpu_limits.cpuSockets': '512',
            'cpu_limits.cpuMaxSockets': '512',
            'cpu_limits.bootloaderEfi': 'false',
            'cpu_limits.memory': '8Gi',
            'cpu_limits.storage': '10Gi',
        },
    ),

    # ─── Maximum memory per VM ────────────────────────────────────────────
    _tpl(
        name='Sanity - Max Memory per VM',
        description='2 GiB per VM with free + stress-ng verification.',
        icon='💾', mode='sanity', tests=['memory-limits'], timeout='30m',
        env_vars={
            'memory_limits.memorySize': '2Gi',
            'memory_limits.cpuCores': '4',
            'memory_limits.storage': '20Gi',
        },
    ),
    _tpl(
        name='Full - Max Memory per VM',
        description='350 GiB per VM with free + stress-ng + memtester.',
        icon='💾', mode='full', tests=['memory-limits'], timeout='4h',
        env_vars={
            'memory_limits.memorySize': '350Gi',
            'memory_limits.cpuCores': '16',
            'memory_limits.storage': '50Gi',
        },
    ),

    # ─── Disk count and size limits ───────────────────────────────────────
    _tpl(
        name='Sanity - Disk Count and Size',
        description='1x 10 GiB disk per VM with lsblk verification.',
        icon='💿', mode='sanity', tests=['disk-limits'], timeout='30m',
        env_vars={
            'disk_limits.diskCount': '1',
            'disk_limits.diskSize': '10Gi',
            'disk_limits.cpuCores': '4',
            'disk_limits.memory': '8Gi',
        },
    ),
    _tpl(
        name='Full - Disk Count and Size',
        description='100 TiB single disk with lsblk verification.',
        icon='💿', mode='full', tests=['disk-limits'], timeout='4h',
        env_vars={
            'disk_limits.diskCount': '1',
            'disk_limits.diskSize': '100Ti',
            'disk_limits.cpuCores': '16',
            'disk_limits.memory': '32Gi',
        },
    ),

    # ─── Maximum hot-pluggable disks per VM ───────────────────────────────
    _tpl(
        name='Sanity - Max Hot-plug Disks per VM',
        description='15 hot-pluggable disks with OS validation and persistence.',
        icon='🔌', mode='sanity', tests=['disk-hotplug'], timeout='30m',
        env_vars={
            'disk_hotplug.diskCount': '15',
            'disk_hotplug.pvcSize': '2Gi',
            'disk_hotplug.cpuCores': '2',
            'disk_hotplug.memory': '4Gi',
            'disk_hotplug.hotplugTimeout': '15m',
        },
    ),
    _tpl(
        name='Full - Max Hot-plug Disks per VM',
        description='255 hot-pluggable disks (SCSI) with OS validation and persistence.',
        icon='🔌', mode='full', tests=['disk-hotplug'], timeout='4h',
        env_vars={
            'disk_hotplug.diskCount': '255',
            'disk_hotplug.pvcSize': '1Gi',
            'disk_hotplug.cpuCores': '16',
            'disk_hotplug.memory': '32Gi',
            'disk_hotplug.hotplugTimeout': '30m',
        },
    ),

    # ─── Add vNICs to a VM ────────────────────────────────────────────────
    _tpl(
        name='Sanity - Add vNICs to a VM',
        description='5 NICs with bridge + VLAN attachment.',
        icon='🌐', mode='sanity', tests=['nic-hotplug'], timeout='30m',
        env_vars={
            'nic_hotplug.nicCount': '5',
            'nic_hotplug.cpuCores': '4',
            'nic_hotplug.memory': '8Gi',
        },
    ),
    _tpl(
        name='Full - Add 28 vNICs to a VM',
        description='28 NICs with NNCP, NAD, and IP verification.',
        icon='🌐', mode='full', tests=['nic-hotplug'], timeout='2h',
        env_vars={
            'nic_hotplug.nicCount': '28',
            'nic_hotplug.cpuCores': '16',
            'nic_hotplug.memory': '64Gi',
        },
    ),

    # ─── High memory performance ──────────────────────────────────────────
    _tpl(
        name='Sanity - High Memory per VM',
        description='64 GiB VM with guest OS memory validation.',
        icon='📈', mode='sanity', tests=['high-memory'], timeout='30m',
        env_vars={
            'high_memory.highMemory': '64Gi',
            'high_memory.cpuCores': '4',
            'high_memory.enablePerfTest': 'false',
        },
    ),
    _tpl(
        name='Full - High Memory per VM',
        description='350 GiB VM with stress-ng + memtester verification.',
        icon='📈', mode='full', tests=['high-memory'], timeout='4h',
        env_vars={
            'high_memory.highMemory': '350Gi',
            'high_memory.cpuCores': '16',
            'high_memory.enablePerfTest': 'true',
        },
    ),

    # ─── Maximum single disk size per VM ──────────────────────────────────
    _tpl(
        name='Sanity - Max Single Disk Size',
        description='100 GiB attached disk with size validation.',
        icon='🗄️', mode='sanity', tests=['large-disk'], timeout='30m',
        env_vars={
            'large_disk.largeDiskSize': '100Gi',
            'large_disk.cpuCores': '4',
            'large_disk.memory': '16Gi',
            'large_disk.enablePerfTest': 'false',
        },
    ),
    _tpl(
        name='Full - Max Single Disk Size',
        description='100 TiB attached disk with fio + hdparm benchmarks.',
        icon='🗄️', mode='full', tests=['large-disk'], timeout='4h',
        env_vars={
            'large_disk.largeDiskSize': '100Ti',
            'large_disk.cpuCores': '16',
            'large_disk.memory': '32Gi',
            'large_disk.enablePerfTest': 'true',
        },
    ),

    # ─── Minimum CPU/Memory/Disk per VM ───────────────────────────────────
    _tpl(
        name='Sanity - Min CPU/Memory/Disk per VM',
        description='500m CPU, 512 MiB memory, 1 GiB disk.',
        icon='🪶', mode='sanity', tests=['minimal-resources'], timeout='30m',
        env_vars={
            'minimal_resources.minCpu': '500m',
            'minimal_resources.minMemory': '512Mi',
            'minimal_resources.minStorage': '1Gi',
        },
    ),
    _tpl(
        name='Full - Min CPU/Memory/Disk per VM',
        description='100m CPU, 256 MiB memory, 256 MiB disk (CirrOS).',
        icon='🪶', mode='full', tests=['minimal-resources'], timeout='1h',
        env_vars={
            'minimal_resources.minCpu': '100m',
            'minimal_resources.minMemory': '256Mi',
            'minimal_resources.minStorage': '256Mi',
        },
    ),

    # ─── Maximum number of defined VMs ────────────────────────────────────
    _tpl(
        name='Sanity - Max Defined VMs',
        description='30 VMs across 2 namespaces, multi-node.',
        icon='📊', mode='sanity', tests=['per-host-density'], timeout='1h',
        env_vars={
            'per_host_density.vmsPerNamespace': '15',
            'per_host_density.namespaceCount': '2',
            'per_host_density.scaleMode': 'multi-node',
            'per_host_density.percentage_of_vms_to_validate': '50',
            'per_host_density.max_ssh_retries': '60',
            'per_host_density.vmMemory': '256Mi',
            'per_host_density.vmCpuRequest': '100m',
            'per_host_density.sleepBetweenPhases': '1m',
            'maxWaitTimeout': '30m',
        },
    ),
    _tpl(
        name='Full - Max Defined VMs (10K)',
        description='10,000 VMs across 20 namespaces, multi-node.',
        icon='📊', mode='full', tests=['per-host-density'], timeout='48h',
        env_vars={
            'per_host_density.vmsPerNamespace': '500',
            'per_host_density.namespaceCount': '20',
            'per_host_density.scaleMode': 'multi-node',
            'per_host_density.percentage_of_vms_to_validate': '10',
            'per_host_density.max_ssh_retries': '240',
            'per_host_density.vmMemory': '256Mi',
            'per_host_density.vmCpuRequest': '100m',
            'per_host_density.sleepBetweenPhases': '2m',
            'maxWaitTimeout': '48h',
            'jobPause': '2m',
        },
    ),

    # ─── Maximum number of VMs per host ───────────────────────────────────
    _tpl(
        name='Full - Max VMs per Host (460)',
        description='460 VMs on a single node, cordon remaining workers.',
        icon='📊', mode='full', tests=['per-host-density'], timeout='12h',
        env_vars={
            'per_host_density.vmsPerNamespace': '460',
            'per_host_density.namespaceCount': '1',
            'per_host_density.scaleMode': 'single-node',
            'per_host_density.percentage_of_vms_to_validate': '10',
            'per_host_density.max_ssh_retries': '240',
            'per_host_density.vmMemory': '256Mi',
            'per_host_density.vmCpuRequest': '100m',
            'per_host_density.sleepBetweenPhases': '2m',
            'maxWaitTimeout': '30m',
            'jobPause': '2m',
        },
    ),

    # ─── Scale out with 500 Namespaces ────────────────────────────────────
    _tpl(
        name='Full - Scale 500 Namespaces',
        description='500 namespaces with 1 VM each, multi-node.',
        icon='📊', mode='full', tests=['per-host-density'], timeout='12h',
        env_vars={
            'per_host_density.vmsPerNamespace': '1',
            'per_host_density.namespaceCount': '500',
            'per_host_density.scaleMode': 'multi-node',
            'per_host_density.percentage_of_vms_to_validate': '10',
            'per_host_density.max_ssh_retries': '240',
            'per_host_density.vmMemory': '256Mi',
            'per_host_density.vmCpuRequest': '100m',
            'maxWaitTimeout': '30m',
        },
    ),

    # ─── Virt Capacity Benchmark ──────────────────────────────────────────
    _tpl(
        name='Sanity - Virt Capacity Benchmark',
        description='5 VMs, skip resize and migration.',
        icon='🏋️', mode='sanity', tests=['virt-capacity-benchmark'], timeout='1h',
        env_vars={
            'virt_capacity_benchmark.vmCount': '5',
            'virt_capacity_benchmark.skipResizeJob': 'true',
            'virt_capacity_benchmark.skipMigrationJob': 'true',
            'virt_capacity_benchmark.percentage_of_vms_to_validate': '25',
        },
    ),
    _tpl(
        name='Full - Virt Capacity Benchmark',
        description='20 VMs with resize, restart, snapshot, migration.',
        icon='🏋️', mode='full', tests=['virt-capacity-benchmark'], timeout='6h',
        env_vars={
            'virt_capacity_benchmark.vmCount': '20',
            'virt_capacity_benchmark.skipResizeJob': 'false',
            'virt_capacity_benchmark.skipMigrationJob': 'false',
            'virt_capacity_benchmark.percentage_of_vms_to_validate': '50',
            'virt_capacity_benchmark.max_ssh_retries': '30',
        },
    ),

    # ─── Legacy: Create 10K VMs (preserved from original) ────────────────
    _tpl(
        name='Create 10K VMs',
        description='Per-Host Density: 10,000 VMs in 1 namespace, create-only, multi-node, 48h timeout.',
        icon='🚀', mode='full', tests=['per-host-density'], timeout='48h',
        env_vars={
            'per_host_density.vmsPerNamespace': '10000',
            'per_host_density.namespaceCount': '1',
            'per_host_density.scaleMode': 'multi-node',
            'per_host_density.targetNode': '',
            'per_host_density.cleanup': 'false',
            'per_host_density.percentage_of_vms_to_validate': '0',
            'per_host_density.max_ssh_retries': '240',
            'per_host_density.vmMemory': '256Mi',
            'per_host_density.vmCpuCores': '100',
            'per_host_density.vmCpuRequest': '100m',
            'per_host_density.vmCpuLimit': '1000m',
            'per_host_density.sourceStorageSize': '256',
            'per_host_density.vmStorageSize': '256',
            'per_host_density.imageUrl': '',
            'per_host_density.shutdownBatchSize': '50',
            'per_host_density.sleepBetweenPhases': '2m',
            'per_host_density.skipVmShutdown': 'true',
            'per_host_density.skipVmRestart': 'true',
            'per_host_density.qpsCreate': '20',
            'per_host_density.burstCreate': '40',
            'per_host_density.qpsShutdown': '10',
            'per_host_density.burstShutdown': '20',
            'per_host_density.qpsStartup': '30',
            'per_host_density.burstStartup': '60',
            'maxWaitTimeout': '48h',
            'jobPause': '2m',
            'cleanup': 'false',
        },
    ),
]
