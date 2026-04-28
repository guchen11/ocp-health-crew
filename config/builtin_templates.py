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
    # ─── CPU Limits ───────────────────────────────────────────────────────
    _tpl(
        name='CNV Sanity - CPU Limits',
        description='CPU Limits sanity: 1 vCPU socket with nproc + stress-ng verification.',
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
        name='CNV Full - CPU Limits',
        description='CPU Limits full: 512 vCPUs per VM with nproc + stress-ng verification.',
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

    # ─── Memory Limits ────────────────────────────────────────────────────
    _tpl(
        name='CNV Sanity - Memory Limits',
        description='Memory Limits sanity: 2 GiB per VM with free + stress-ng verification.',
        icon='💾', mode='sanity', tests=['memory-limits'], timeout='30m',
        env_vars={
            'memory_limits.memorySize': '2Gi',
            'memory_limits.cpuCores': '4',
            'memory_limits.storage': '20Gi',
        },
    ),
    _tpl(
        name='CNV Full - Memory Limits',
        description='Memory Limits full: 350 GiB per VM with free + stress-ng + memtester.',
        icon='💾', mode='full', tests=['memory-limits'], timeout='4h',
        env_vars={
            'memory_limits.memorySize': '350Gi',
            'memory_limits.cpuCores': '16',
            'memory_limits.storage': '50Gi',
        },
    ),

    # ─── Disk Limits ──────────────────────────────────────────────────────
    _tpl(
        name='CNV Sanity - Disk Limits',
        description='Disk Limits sanity: 1x 10 GiB disk per VM with lsblk verification.',
        icon='💿', mode='sanity', tests=['disk-limits'], timeout='30m',
        env_vars={
            'disk_limits.diskCount': '1',
            'disk_limits.diskSize': '10Gi',
            'disk_limits.cpuCores': '4',
            'disk_limits.memory': '8Gi',
        },
    ),
    _tpl(
        name='CNV Full - Disk Limits',
        description='Disk Limits full: 100 TiB single disk with fio + hdparm benchmarks.',
        icon='💿', mode='full', tests=['disk-limits'], timeout='4h',
        env_vars={
            'disk_limits.diskCount': '1',
            'disk_limits.diskSize': '100Ti',
            'disk_limits.cpuCores': '16',
            'disk_limits.memory': '32Gi',
        },
    ),

    # ─── Disk Hot-plug ────────────────────────────────────────────────────
    _tpl(
        name='CNV Sanity - Disk Hot-plug',
        description='Disk Hot-plug sanity: 15 disks with OS validation and persistence.',
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
        name='CNV Full - Disk Hot-plug',
        description='Disk Hot-plug full: 255 disks (SCSI) with OS validation and persistence.',
        icon='🔌', mode='full', tests=['disk-hotplug'], timeout='4h',
        env_vars={
            'disk_hotplug.diskCount': '255',
            'disk_hotplug.pvcSize': '1Gi',
            'disk_hotplug.cpuCores': '16',
            'disk_hotplug.memory': '32Gi',
            'disk_hotplug.hotplugTimeout': '30m',
        },
    ),

    # ─── NIC Hot-plug ─────────────────────────────────────────────────────
    _tpl(
        name='CNV Sanity - NIC Hot-plug',
        description='NIC Hot-plug sanity: 5 NICs with bridge + VLAN attachment.',
        icon='🌐', mode='sanity', tests=['nic-hotplug'], timeout='30m',
        env_vars={
            'nic_hotplug.nicCount': '5',
            'nic_hotplug.cpuCores': '4',
            'nic_hotplug.memory': '8Gi',
        },
    ),
    _tpl(
        name='CNV Full - NIC Hot-plug',
        description='NIC Hot-plug full: 28 NICs with NNCP, NAD, and IP verification.',
        icon='🌐', mode='full', tests=['nic-hotplug'], timeout='2h',
        env_vars={
            'nic_hotplug.nicCount': '28',
            'nic_hotplug.cpuCores': '16',
            'nic_hotplug.memory': '64Gi',
        },
    ),

    # ─── High Memory ──────────────────────────────────────────────────────
    _tpl(
        name='CNV Sanity - High Memory',
        description='High Memory sanity: 64 GiB VM with guest OS memory validation.',
        icon='📈', mode='sanity', tests=['high-memory'], timeout='30m',
        env_vars={
            'high_memory.highMemory': '64Gi',
            'high_memory.cpuCores': '4',
            'high_memory.enablePerfTest': 'false',
        },
    ),
    _tpl(
        name='CNV Full - High Memory',
        description='High Memory full: 350 GiB VM with stress-ng + memtester verification.',
        icon='📈', mode='full', tests=['high-memory'], timeout='4h',
        env_vars={
            'high_memory.highMemory': '350Gi',
            'high_memory.cpuCores': '16',
            'high_memory.enablePerfTest': 'true',
        },
    ),

    # ─── Large Disk ───────────────────────────────────────────────────────
    _tpl(
        name='CNV Sanity - Large Disk',
        description='Large Disk sanity: 100 GiB attached disk with size validation.',
        icon='🗄️', mode='sanity', tests=['large-disk'], timeout='30m',
        env_vars={
            'large_disk.largeDiskSize': '100Gi',
            'large_disk.cpuCores': '4',
            'large_disk.memory': '16Gi',
            'large_disk.enablePerfTest': 'false',
        },
    ),
    _tpl(
        name='CNV Full - Large Disk',
        description='Large Disk full: 100 TiB attached disk with fio + hdparm benchmarks.',
        icon='🗄️', mode='full', tests=['large-disk'], timeout='4h',
        env_vars={
            'large_disk.largeDiskSize': '100Ti',
            'large_disk.cpuCores': '16',
            'large_disk.memory': '32Gi',
            'large_disk.enablePerfTest': 'true',
        },
    ),

    # ─── Minimal Resources ────────────────────────────────────────────────
    _tpl(
        name='CNV Sanity - Minimal Resources',
        description='Minimal Resources sanity: 500m CPU, 512 MiB memory, 1 GiB disk.',
        icon='🪶', mode='sanity', tests=['minimal-resources'], timeout='30m',
        env_vars={
            'minimal_resources.minCpu': '500m',
            'minimal_resources.minMemory': '512Mi',
            'minimal_resources.minStorage': '1Gi',
        },
    ),
    _tpl(
        name='CNV Full - Minimal Resources',
        description='Minimal Resources full: 100m CPU, 256 MiB memory, 256 MiB disk (CirrOS).',
        icon='🪶', mode='full', tests=['minimal-resources'], timeout='1h',
        env_vars={
            'minimal_resources.minCpu': '100m',
            'minimal_resources.minMemory': '256Mi',
            'minimal_resources.minStorage': '256Mi',
        },
    ),

    # ─── Per-Host Density ─────────────────────────────────────────────────
    _tpl(
        name='CNV Sanity - Per-Host Density',
        description='Per-Host Density sanity: 30 VMs across 2 namespaces, multi-node.',
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
        name='CNV Full - Per-Host Density',
        description='Per-Host Density full: 10,000 VMs across 20 namespaces, multi-node.',
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

    # ─── Per-Host Density (single-node: max VMs per host) ────────────────
    _tpl(
        name='CNV Full - Max VMs Per Host',
        description='Per-Host Density full: 460 VMs on a single node, cordon remaining workers.',
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

    # ─── Per-Host Density (500 Namespaces) ────────────────────────────────
    _tpl(
        name='CNV Full - 500 Namespaces',
        description='Per-Host Density full: 500 namespaces with 1 VM each, multi-node.',
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
        name='CNV Sanity - Virt Capacity Benchmark',
        description='Capacity Benchmark sanity: 5 VMs, skip resize and migration.',
        icon='🏋️', mode='sanity', tests=['virt-capacity-benchmark'], timeout='1h',
        env_vars={
            'virt_capacity_benchmark.vmCount': '5',
            'virt_capacity_benchmark.skipResizeJob': 'true',
            'virt_capacity_benchmark.skipMigrationJob': 'true',
            'virt_capacity_benchmark.percentage_of_vms_to_validate': '25',
        },
    ),
    _tpl(
        name='CNV Full - Virt Capacity Benchmark',
        description='Capacity Benchmark full: 20 VMs with resize, restart, snapshot, migration.',
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
