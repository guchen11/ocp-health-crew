"""Curated operator catalog for the Operator Dashboard.

Each entry defines the OLM resources needed to install an operator.
All values are hardcoded (SEC-001: no user input flows into shell commands).
Parameters define user-configurable values with validation constraints.

Install procedures match tested Jira tickets:
  - NMState: CNV-91017
  - MetalLB: CNV-91019
"""

OPERATOR_CATALOG = {
    'nmstate': {
        'display': 'NMState',
        'icon': 'net',
        'description': 'Node network configuration management',
        'package': 'kubernetes-nmstate-operator',
        'namespace': 'openshift-nmstate',
        'channel': 'stable',
        'source': 'redhat-operators',
        'source_namespace': 'openshift-marketplace',
        'install_mode': 'OwnNamespace',
        'parameters': [],
        'cr': {
            'apiVersion': 'nmstate.io/v1',
            'kind': 'NMState',
            'metadata': {'name': 'nmstate'},
        },
        'cr_wait': {
            'resource': 'nmstate/nmstate',
            'condition': "jsonpath='{.status.conditions[?(@.type==\"Available\")].status}'=True",
            'timeout': '300s',
        },
        'post_cr': None,
    },
    'metallb': {
        'display': 'MetalLB',
        'icon': 'lb',
        'description': 'Bare-metal load balancer for Kubernetes',
        'package': 'metallb-operator',
        'namespace': 'metallb-system',
        'channel': 'stable',
        'source': 'redhat-operators',
        'source_namespace': 'openshift-marketplace',
        'install_mode': 'AllNamespaces',
        'parameters': [
            {
                'id': 'ip_range',
                'label': 'IP Address Range',
                'description': 'Address range for the IPAddressPool (e.g. 198.18.0.100-198.18.0.120)',
                'default': '198.18.0.100-198.18.0.120',
                'required': True,
                'pattern': r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}-\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$',
            },
            {
                'id': 'pool_name',
                'label': 'Pool Name',
                'description': 'Name for the IPAddressPool resource',
                'default': 'metallb',
                'required': True,
                'pattern': r'^[a-z0-9][-a-z0-9]*[a-z0-9]$',
            },
            {
                'id': 'auto_assign',
                'label': 'Auto Assign',
                'description': 'Automatically assign IPs from this pool',
                'default': 'true',
                'type': 'select',
                'options': ['true', 'false'],
            },
        ],
        'cr': {
            'apiVersion': 'metallb.io/v1beta1',
            'kind': 'MetalLB',
            'metadata': {
                'name': 'metallb',
                'namespace': 'metallb-system',
            },
        },
        'cr_wait': {
            'resource': 'metallb/metallb',
            'namespace': 'metallb-system',
            'condition': "condition=Available",
            'timeout': '300s',
        },
        'post_cr_template': {
            'description': 'IPAddressPool + L2Advertisement',
            'yaml_template': (
                'apiVersion: metallb.io/v1beta1\n'
                'kind: IPAddressPool\n'
                'metadata:\n'
                '  name: {pool_name}\n'
                '  namespace: metallb-system\n'
                'spec:\n'
                '  addresses:\n'
                '    - {ip_range}\n'
                '  autoAssign: {auto_assign}\n'
                '---\n'
                'apiVersion: metallb.io/v1beta1\n'
                'kind: L2Advertisement\n'
                'metadata:\n'
                '  name: l2advertisement\n'
                '  namespace: metallb-system\n'
                'spec:\n'
                '  ipAddressPools:\n'
                '    - {pool_name}'
            ),
            'delete_commands_template': [
                'oc delete l2advertisement l2advertisement -n metallb-system --ignore-not-found',
                'oc delete ipaddresspool {pool_name} -n metallb-system --ignore-not-found',
            ],
        },
        'post_cr': None,
    },
    'acm': {
        'display': 'Advanced Cluster Management',
        'icon': 'acm',
        'description': 'Cluster lifecycle, governance, and HCP (installs MCE automatically)',
        'package': 'advanced-cluster-management',
        'namespace': 'open-cluster-management',
        'channel': 'release-2.16',
        'source': 'redhat-operators',
        'source_namespace': 'openshift-marketplace',
        'install_mode': 'AllNamespaces',
        'parameters': [],
        'cr': {
            'apiVersion': 'operator.open-cluster-management.io/v1',
            'kind': 'MultiClusterHub',
            'metadata': {
                'name': 'multiclusterhub',
                'namespace': 'open-cluster-management',
            },
        },
        'cr_wait': {
            'resource': 'multiclusterhub/multiclusterhub',
            'namespace': 'open-cluster-management',
            'condition': "jsonpath='{.status.phase}'=Running",
            'timeout': '900s',
        },
        'post_cr': None,
    },
    'oadp': {
        'display': 'OADP',
        'icon': 'backup',
        'description': 'OpenShift API for Data Protection (backup/restore)',
        'package': 'redhat-oadp-operator',
        'namespace': 'openshift-adp',
        'channel': 'stable-1.6',
        'source': 'redhat-operators',
        'source_namespace': 'openshift-marketplace',
        'install_mode': 'OwnNamespace',
        'parameters': [],
        'cr': None,
        'cr_wait': None,
        'post_cr': None,
    },
}
