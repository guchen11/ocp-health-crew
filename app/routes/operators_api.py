"""Operator management API routes.

Provides endpoints to list, install, remove, and check status of OCP
operators. All shell commands are constructed from the hardcoded
OPERATOR_CATALOG (SEC-001: no user input in shell commands).
"""

import json
import logging
import threading

from flask import current_app, jsonify, request
from flask_login import current_user, login_required

from app.decorators import log_audit, operator_required
from app.models import db
from app.models_operators import OperatorInstall
from app.routes import dashboard_bp
from app.routes.operators_executor import (
    _get_ssh_and_kubeconfig,
    acquire_lock,
    run_install,
    run_remove,
)
from app.ssh_utils import ssh_exec
from config.operator_catalog import OPERATOR_CATALOG

log = logging.getLogger(__name__)


@dashboard_bp.route('/api/operators', methods=['GET'])
@login_required
def api_operators_list():
    """List installed operators by querying subscriptions + CSVs."""
    try:
        client, kubeconfig = _get_ssh_and_kubeconfig()
        try:
            stdout_csv, _ = ssh_exec(client, 'oc get csv -A -o json',
                                     kubeconfig=kubeconfig, timeout=30)
            stdout_sub, _ = ssh_exec(client,
                                     'oc get sub -A -o json',
                                     kubeconfig=kubeconfig, timeout=15)
        finally:
            client.close()
    except Exception as exc:
        log.error("Failed to list operators: %s", exc)
        return jsonify({'error': 'Failed to connect to cluster'}), 502

    subscribed_csvs = set()
    try:
        subs = json.loads(stdout_sub) if stdout_sub else {'items': []}
        for sub in subs.get('items', []):
            sub_name = sub.get('metadata', {}).get('name', '')
            pkg_name = sub.get('spec', {}).get('name', '')
            if _is_dependency_subscription(sub_name, pkg_name):
                continue
            csv_name = sub.get('status', {}).get('installedCSV', '')
            if csv_name:
                subscribed_csvs.add(csv_name)
    except (json.JSONDecodeError, KeyError):
        pass

    operators = []
    try:
        data = json.loads(stdout_csv) if stdout_csv else {'items': []}
        seen = {}
        for item in data.get('items', []):
            name = item.get('metadata', {}).get('name', '')
            ns = item.get('metadata', {}).get('namespace', '')
            spec = item.get('spec', {})
            phase = item.get('status', {}).get('phase', 'Unknown')
            version = spec.get('version', '')
            display = spec.get('displayName', name)
            provider = spec.get('provider', {}).get('name', '')
            created = item.get('metadata', {}).get('creationTimestamp', '')
            install_modes = spec.get('installModes', [])
            managed = 'All Namespaces' if any(
                m.get('type') == 'AllNamespaces' and m.get('supported')
                for m in install_modes
            ) else ns
            crds = [c.get('name', '') for c in
                    spec.get('customresourcedefinitions', {}).get('owned', [])]
            catalog_key = _match_catalog_key(name)

            if name not in seen and name in subscribed_csvs:
                seen[name] = {
                    'name': name,
                    'display_name': display,
                    'namespace': ns,
                    'version': version,
                    'provider': provider,
                    'phase': phase,
                    'managed_namespaces': managed,
                    'created': created,
                    'provided_apis': crds[:5],
                    'catalog_key': catalog_key,
                }
        operators = sorted(seen.values(), key=lambda o: o['display_name'])
    except (json.JSONDecodeError, KeyError) as exc:
        log.error("Failed to parse CSV list: %s", exc)
        return jsonify({'error': 'Failed to parse operator list'}), 500

    catalog_status = {}
    for cat_key, cat_info in OPERATOR_CATALOG.items():
        catalog_status[cat_key] = {
            'installed': any(
                cat_info['package'] in op.get('name', '')
                for op in operators
            ),
            **cat_info,
        }

    return jsonify({
        'operators': operators,
        'catalog': catalog_status,
    })


def _match_catalog_key(csv_name):
    """Return the catalog key if this CSV matches a catalog operator."""
    for key, cat in OPERATOR_CATALOG.items():
        if cat['package'] in csv_name:
            return key
    return None


def _is_dependency_subscription(sub_name, pkg_name):
    """Return True if this subscription was auto-created by OLM as a dependency.

    OLM-generated dependency subscriptions have names like:
      cephcsi-operator-stable-4.21-redhat-operators-openshift-marketplace
    User-created ones match the package name:
      metallb-operator, kubernetes-nmstate-operator, odf-operator
    """
    if not pkg_name:
        return False
    if sub_name == pkg_name:
        return False
    if 'openshift-marketplace' in sub_name:
        return True
    if sub_name.startswith(pkg_name + '-'):
        suffix = sub_name[len(pkg_name) + 1:]
        if '-' in suffix:
            return True
    return False


@dashboard_bp.route('/api/operators/install', methods=['POST'])
@operator_required
def api_operator_install():
    """Install an operator from the curated catalog with optional parameters."""
    import re as _re
    data = request.get_json(silent=True) or {}
    operator_key = data.get('operator_key', '')
    params = data.get('parameters', {})

    if operator_key not in OPERATOR_CATALOG:
        return jsonify({'error': 'Unknown operator'}), 400

    catalog_entry = OPERATOR_CATALOG[operator_key]

    validated_params = {}
    for param_def in catalog_entry.get('parameters', []):
        pid = param_def['id']
        value = params.get(pid, param_def.get('default', ''))
        if param_def.get('required') and not value:
            return jsonify({'error': f'Parameter "{param_def["label"]}" is required'}), 400
        if value and param_def.get('pattern'):
            if not _re.match(param_def['pattern'], value):
                return jsonify({'error': f'Parameter "{param_def["label"]}" has invalid format'}), 400
        if param_def.get('type') == 'select' and value not in param_def.get('options', []):
            return jsonify({'error': f'Invalid value for "{param_def["label"]}"'}), 400
        validated_params[pid] = value

    if not acquire_lock():
        return jsonify({'error': 'Another operation is in progress'}), 409

    record = OperatorInstall(
        operator_key=operator_key,
        display_name=catalog_entry['display'],
        namespace=catalog_entry['namespace'],
        status='installing',
        installed_by=current_user.id,
    )
    db.session.add(record)
    db.session.commit()

    log_audit(
        action='operator_install',
        target=catalog_entry['display'],
        details=f"Installing {catalog_entry['package']} to {catalog_entry['namespace']} params={validated_params}",
    )

    app = current_app._get_current_object()
    threading.Thread(
        target=run_install,
        args=(app, record.id, operator_key, validated_params),
        daemon=True,
    ).start()

    return jsonify({
        'id': record.id,
        'status': 'installing',
        'message': f'Installing {catalog_entry["display"]}...',
    })


@dashboard_bp.route('/api/operators/<int:record_id>/status', methods=['GET'])
@login_required
def api_operator_status(record_id):
    """Get status and logs of an operator install/remove operation."""
    record = db.session.get(OperatorInstall, record_id)
    if not record:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(record.to_dict())


@dashboard_bp.route('/api/operators/<int:record_id>', methods=['DELETE'])
@operator_required
def api_operator_remove(record_id):
    """Remove an installed operator by history record ID."""
    record = db.session.get(OperatorInstall, record_id)
    if not record:
        return jsonify({'error': 'Not found'}), 404
    if record.operator_key not in OPERATOR_CATALOG:
        return jsonify({'error': 'Unknown operator in catalog'}), 400
    return _start_remove(record.operator_key, record)


@dashboard_bp.route('/api/operators/uninstall', methods=['POST'])
@operator_required
def api_operator_uninstall():
    """Uninstall a catalog operator directly (from cluster operators list)."""
    data = request.get_json(silent=True) or {}
    operator_key = data.get('operator_key', '')
    if operator_key not in OPERATOR_CATALOG:
        return jsonify({'error': 'Unknown operator'}), 400
    catalog_entry = OPERATOR_CATALOG[operator_key]
    record = OperatorInstall(
        operator_key=operator_key,
        display_name=catalog_entry['display'],
        namespace=catalog_entry['namespace'],
        status='removing',
        installed_by=current_user.id,
    )
    db.session.add(record)
    db.session.commit()
    return _start_remove(operator_key, record)


def _start_remove(operator_key, record):
    """Start a remove operation in a background thread."""
    if not acquire_lock():
        return jsonify({'error': 'Another operation is in progress'}), 409

    record.status = 'removing'
    db.session.commit()

    log_audit(
        action='operator_remove',
        target=record.display_name,
        details=f"Removing {record.operator_key} from {record.namespace}",
    )

    app = current_app._get_current_object()
    threading.Thread(
        target=run_remove,
        args=(app, record.id, record.operator_key),
        daemon=True,
    ).start()

    return jsonify({
        'id': record.id,
        'status': 'removing',
        'message': f'Removing {record.display_name}...',
    })


@dashboard_bp.route('/api/operators/history', methods=['GET'])
@login_required
def api_operator_history():
    """List all operator install/remove records."""
    records = (OperatorInstall.query
               .order_by(OperatorInstall.started_at.desc())
               .limit(50)
               .all())
    return jsonify([r.to_dict() for r in records])
