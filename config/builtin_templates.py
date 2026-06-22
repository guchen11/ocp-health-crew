"""
Built-in Templates for CNV Scenarios

Pre-configured run templates seeded into the database on first startup.
Each scenario has a sanity (quick validation) and full (regression) variant.
Values for full templates sourced from the CNV 4.22 regression test report.
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
    # ─── Maximum virtual CPUs per virtual machine ─────────────────────────
    _tpl(
        name='Sanity - Maximum virtual CPUs per virtual machine',
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
        name='Full - Maximum virtual CPUs per virtual machine',
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

    # ─── Maximum memory per virtual machine ───────────────────────────────
    _tpl(
        name='Sanity - Maximum memory per virtual machine',
        description='2 GiB per VM with free + stress-ng verification.',
        icon='💾', mode='sanity', tests=['memory-limits'], timeout='30m',
        env_vars={
            'memory_limits.memorySize': '2Gi',
            'memory_limits.cpuCores': '4',
            'memory_limits.storage': '20Gi',
        },
    ),
    _tpl(
        name='Full - Maximum memory per virtual machine',
        description='350 GiB per VM with free + stress-ng + memtester.',
        icon='💾', mode='full', tests=['memory-limits'], timeout='4h',
        env_vars={
            'memory_limits.memorySize': '350Gi',
            'memory_limits.cpuCores': '16',
            'memory_limits.storage': '50Gi',
        },
    ),

    # ─── Minimum memory per virtual machine ──────────────────────────────
    _tpl(
        name='Sanity - Minimum memory per virtual machine',
        description='256 MiB per VM with alpine OS verification.',
        icon='💾', mode='sanity', tests=['memory-limits'], timeout='30m',
        env_vars={
            'memory_limits.memorySize': '256Mi',
            'memory_limits.cpuCores': '1',
            'memory_limits.storage': '256Mi',
        },
    ),
    _tpl(
        name='Full - Minimum memory per virtual machine',
        description='256 MiB per VM with alpine OS and stress-ng verification.',
        icon='💾', mode='full', tests=['memory-limits'], timeout='1h',
        env_vars={
            'memory_limits.memorySize': '256Mi',
            'memory_limits.cpuCores': '1',
            'memory_limits.storage': '256Mi',
        },
    ),

    # ─── Minimum CPU per virtual machine ─────────────────────────────────
    _tpl(
        name='Sanity - Minimum CPU per virtual machine',
        description='256m CPU with alpine OS verification.',
        icon='🔥', mode='sanity', tests=['cpu-limits'], timeout='30m',
        env_vars={
            'cpu_limits.cpuCores': '1',
            'cpu_limits.cpuSockets': '1',
            'cpu_limits.cpuMaxSockets': '1',
            'cpu_limits.cpuRequest': '256m',
            'cpu_limits.bootloaderEfi': 'true',
            'cpu_limits.memory': '256Mi',
            'cpu_limits.storage': '256Mi',
        },
    ),
    _tpl(
        name='Full - Minimum CPU per virtual machine',
        description='256m CPU with alpine OS and stress-ng verification.',
        icon='🔥', mode='full', tests=['cpu-limits'], timeout='1h',
        env_vars={
            'cpu_limits.cpuCores': '1',
            'cpu_limits.cpuSockets': '1',
            'cpu_limits.cpuMaxSockets': '1',
            'cpu_limits.cpuRequest': '256m',
            'cpu_limits.bootloaderEfi': 'true',
            'cpu_limits.memory': '256Mi',
            'cpu_limits.storage': '256Mi',
        },
    ),

    # ─── Minimum disk per virtual machine ────────────────────────────────
    _tpl(
        name='Sanity - Minimum disk per virtual machine',
        description='256 MiB disk with alpine OS and lsblk verification.',
        icon='💿', mode='sanity', tests=['disk-limits'], timeout='30m',
        env_vars={
            'disk_limits.diskCount': '1',
            'disk_limits.diskSize': '256Mi',
            'disk_limits.cpuCores': '1',
            'disk_limits.memory': '256Mi',
        },
    ),
    _tpl(
        name='Full - Minimum disk per virtual machine',
        description='256 MiB disk with alpine OS and lsblk verification.',
        icon='💿', mode='full', tests=['disk-limits'], timeout='1h',
        env_vars={
            'disk_limits.diskCount': '1',
            'disk_limits.diskSize': '256Mi',
            'disk_limits.cpuCores': '1',
            'disk_limits.memory': '256Mi',
        },
    ),

    # ─── Maximum single disk size per virtual machine ─────────────────────
    _tpl(
        name='Sanity - Maximum single disk size per virtual machine',
        description='10 GiB single disk with lsblk + I/O verification.',
        icon='💿', mode='sanity', tests=['disk-limits'], timeout='30m',
        env_vars={
            'disk_limits.diskCount': '1',
            'disk_limits.diskSize': '10Gi',
            'disk_limits.cpuCores': '4',
            'disk_limits.memory': '8Gi',
        },
    ),
    _tpl(
        name='Full - Maximum single disk size per virtual machine',
        description='100 TiB single disk with lsblk + I/O verification.',
        icon='💿', mode='full', tests=['disk-limits'], timeout='4h',
        env_vars={
            'disk_limits.diskCount': '1',
            'disk_limits.diskSize': '100Ti',
            'disk_limits.cpuCores': '16',
            'disk_limits.memory': '32Gi',
        },
    ),

    # ─── Maximum number of hot-pluggable disks per virtual machine ───────
    _tpl(
        name='Sanity - Maximum number of hot-pluggable disks per virtual machine',
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
        name='Full - Maximum number of hot-pluggable disks per virtual machine',
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

    # ─── Add 28 vNICS to a VM ────────────────────────────────────────────
    _tpl(
        name='Sanity - Add 28 vNICS to a VM',
        description='5 NICs with bridge + VLAN attachment.',
        icon='🌐', mode='sanity', tests=['nic-hotplug'], timeout='30m',
        env_vars={
            'nic_hotplug.nicCount': '5',
            'nic_hotplug.cpuCores': '4',
            'nic_hotplug.memory': '8Gi',
        },
    ),
    _tpl(
        name='Full - Add 28 vNICS to a VM',
        description='28 NICs with NNCP, NAD, and IP verification.',
        icon='🌐', mode='full', tests=['nic-hotplug'], timeout='2h',
        env_vars={
            'nic_hotplug.nicCount': '28',
            'nic_hotplug.cpuCores': '16',
            'nic_hotplug.memory': '64Gi',
        },
    ),

    # ─── Maximum number of defined VMs ────────────────────────────────────
    _tpl(
        name='Sanity - Maximum number of defined VMs',
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
            'maxWaitTimeout': '45m',
        },
    ),
    _tpl(
        name='Full - Maximum number of defined VMs',
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
        name='Sanity - Maximum number of VMs per host',
        description='30 VMs on a single node, cordon remaining workers.',
        icon='📊', mode='sanity', tests=['per-host-density'], timeout='1h',
        env_vars={
            'per_host_density.vmsPerNamespace': '30',
            'per_host_density.namespaceCount': '1',
            'per_host_density.scaleMode': 'single-node',
            'per_host_density.percentage_of_vms_to_validate': '50',
            'per_host_density.max_ssh_retries': '60',
            'per_host_density.vmMemory': '256Mi',
            'per_host_density.vmCpuRequest': '100m',
            'per_host_density.sleepBetweenPhases': '1m',
            'maxWaitTimeout': '45m',
        },
    ),
    _tpl(
        name='Full - Maximum number of VMs per host',
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
        name='Sanity - Scale out with 500 Namespaces',
        description='10 namespaces with 1 VM each, multi-node.',
        icon='📊', mode='sanity', tests=['per-host-density'], timeout='1h',
        env_vars={
            'per_host_density.vmsPerNamespace': '1',
            'per_host_density.namespaceCount': '10',
            'per_host_density.scaleMode': 'multi-node',
            'per_host_density.percentage_of_vms_to_validate': '50',
            'per_host_density.max_ssh_retries': '60',
            'per_host_density.vmMemory': '256Mi',
            'per_host_density.vmCpuRequest': '100m',
            'maxWaitTimeout': '45m',
        },
    ),
    _tpl(
        name='Full - Scale out with 500 Namespaces',
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

    # ─── HCP & ACM ───────────────────────────────────────────────────────
    _tpl(
        name='Sanity - HCP & ACM',
        description='50 HCP worker nodes across 1 hosted cluster.',
        icon='☁️', mode='sanity', tests=['hcp-scale'], timeout='2h',
        env_vars={
            'hcp.clusterCount': '1',
            'hcp.workersPerCluster': '50',
            'hcp.workerCpu': '1',
            'hcp.workerMemory': '4Gi',
            'hcp.workerRootVolume': '16Gi',
        },
    ),
    _tpl(
        name='Full - HCP & ACM',
        description='600 HCP worker nodes across 3 hosted clusters.',
        icon='☁️', mode='full', tests=['hcp-scale'], timeout='12h',
        env_vars={
            'hcp.clusterCount': '3',
            'hcp.workersPerCluster': '200',
            'hcp.workerCpu': '1',
            'hcp.workerMemory': '4Gi',
            'hcp.workerRootVolume': '16Gi',
        },
    ),
]
