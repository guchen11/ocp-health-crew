"""Windows CNV scenario built-in templates."""

from config.template_builder import build_template

_WINDOWS_IMAGE = (
    'http://f01-h08-000-1029u.rdu2.scalelab.redhat.com:9002/winmssql2022.qcow2'
)

_WINDOWS_ENV = {'windowsImageUrl': _WINDOWS_IMAGE}


def _win(name, description, tests, timeout='30m'):
    return build_template(
        name=name,
        description=description,
        icon='🪟',
        mode='sanity',
        tests=tests,
        timeout=timeout,
        os_type='windows',
        env_vars=_WINDOWS_ENV,
    )


WINDOWS_TEMPLATES = [
    _win(
        'Windows Sanity - CPU Limits',
        '1 vCPU Windows Server 2022 VM with WMI + PowerShell CPU burn.',
        ['cpu-limits'],
    ),
    _win(
        'Windows Sanity - Memory Limits',
        '2 GiB Windows Server 2022 VM with WMI memory + burn workers.',
        ['memory-limits'],
    ),
    _win(
        'Windows Sanity - Disk Limits',
        'Windows Server 2022 VM with data disks validated via Get-Disk.',
        ['disk-limits'],
    ),
    _win(
        'Windows Sanity - Disk Hot-plug',
        'Windows Server 2022 VM with hot-plugged disks, GPT/NTFS init.',
        ['disk-hotplug'],
    ),
    _win(
        'Windows Sanity - HammerDB MSSQL',
        'Windows Server 2022 + MSSQL + HammerDB TPC-C + FIO data gen.',
        ['hammerdb-mssql'],
    ),
    _win(
        'Windows Sanity - NIC Hot-plug',
        'Windows Server 2022 VM with 2 hot-plugged NICs, VirtIO + IP check.',
        ['nic-hotplug'],
    ),
    _win(
        'Windows Sanity - Large Disk',
        'Windows Server 2022 VM with large data disk validated via Get-Disk.',
        ['large-disk'],
    ),
    _win(
        'Windows Sanity - High Memory',
        'Windows Server 2022 VM with WMI memory validation.',
        ['high-memory'],
    ),
    _win(
        'Windows Sanity - Per-Host Density',
        '2 Windows Server 2022 VMs on single node with SSH sampling.',
        ['per-host-density'],
    ),
]
