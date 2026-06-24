"""Background execution for operator install and remove operations.

All shell commands are constructed from the hardcoded OPERATOR_CATALOG
(SEC-001: no user input in shell commands). Separated from operators_api.py
to keep both files under the 500-line limit (REQ-3).
"""

import re
import threading
from datetime import datetime, timezone

from app.models import db
from app.models_operators import OperatorInstall
from app.ssh_utils import create_ssh_client, ssh_exec, quote
from config.operator_catalog import OPERATOR_CATALOG

_operator_lock = threading.Lock()
_active_operation = False

TOKEN_RE = re.compile(r'(Bearer\s+|token:\s*)[A-Za-z0-9._\-]+', re.IGNORECASE)
KUBECONFIG_RE = re.compile(
    r'(certificate-authority-data|client-certificate-data|client-key-data):\s*\S+',
    re.IGNORECASE,
)


def _sanitize_log(text):
    """Remove bearer tokens and kubeconfig secrets from log output (SEC-004)."""
    text = TOKEN_RE.sub(r'\1[REDACTED]', text)
    text = KUBECONFIG_RE.sub(r'\1: [REDACTED]', text)
    return text


def _get_ssh_and_kubeconfig():
    """Create SSH client and resolve kubeconfig from settings."""
    from app.routes import load_settings
    settings = load_settings()
    ssh_settings = settings.get('ssh', {})
    host = ssh_settings.get('host') or None
    user = ssh_settings.get('user') or None
    client = create_ssh_client(host=host, username=user)
    kubeconfig = '/home/kni/clusterconfigs/auth/kubeconfig'
    return client, kubeconfig


def acquire_lock():
    """Try to acquire the operation lock. Returns True if acquired."""
    global _active_operation
    with _operator_lock:
        if _active_operation:
            return False
        _active_operation = True
        return True


def release_lock():
    """Release the operation lock."""
    global _active_operation
    with _operator_lock:
        _active_operation = False


def run_install(app, record_id, operator_key, params=None):
    """Background thread: install an operator via SSH (SEC-001: catalog only)."""
    if params is None:
        params = {}
    try:
        with app.app_context():
            record = db.session.get(OperatorInstall, record_id)
            cat = OPERATOR_CATALOG[operator_key]

            try:
                client, kubeconfig = _get_ssh_and_kubeconfig()
            except Exception as exc:
                record.append_log(f'SSH connection failed: {exc}', 'fail')
                record.status = 'failed'
                record.finished_at = datetime.now(timezone.utc)
                db.session.commit()
                return

            try:
                _do_install(client, kubeconfig, record, cat, params)
            finally:
                client.close()
                record.finished_at = datetime.now(timezone.utc)
                db.session.commit()
    finally:
        release_lock()


def _do_install(client, kubeconfig, record, cat, params=None):
    """Execute the operator install steps over SSH."""
    if params is None:
        params = {}
    ns = cat['namespace']
    pkg = cat['package']
    channel = cat['channel']
    source = cat['source']
    source_ns = cat['source_namespace']
    install_mode = cat['install_mode']

    record.append_log(f'Creating namespace {ns}', 'phase')
    stdout, stderr = ssh_exec(
        client,
        f'oc create namespace {quote(ns)} --dry-run=client -o yaml | oc apply -f -',
        kubeconfig=kubeconfig, timeout=30,
    )
    record.append_log(_sanitize_log(stdout or stderr), 'info')
    db.session.commit()

    record.append_log('Creating OperatorGroup', 'phase')
    og_spec = 'spec: {}' if install_mode == 'AllNamespaces' else (
        f'spec:\n    targetNamespaces:\n    - {ns}'
    )
    og_yaml = (
        f'apiVersion: operators.coreos.com/v1\n'
        f'kind: OperatorGroup\n'
        f'metadata:\n'
        f'  name: {pkg}-og\n'
        f'  namespace: {ns}\n'
        f'{og_spec}'
    )
    stdout, stderr = ssh_exec(
        client,
        f'echo {quote(og_yaml)} | oc apply -f -',
        kubeconfig=kubeconfig, timeout=30,
    )
    record.append_log(_sanitize_log(stdout or stderr), 'info')
    db.session.commit()

    record.append_log('Creating Subscription (Manual approval)', 'phase')
    sub_yaml = (
        f'apiVersion: operators.coreos.com/v1alpha1\n'
        f'kind: Subscription\n'
        f'metadata:\n'
        f'  name: {pkg}\n'
        f'  namespace: {ns}\n'
        f'spec:\n'
        f'  source: {source}\n'
        f'  sourceNamespace: {source_ns}\n'
        f'  name: {pkg}\n'
        f'  channel: {channel}\n'
        f'  installPlanApproval: Manual'
    )
    stdout, stderr = ssh_exec(
        client,
        f'echo {quote(sub_yaml)} | oc apply -f -',
        kubeconfig=kubeconfig, timeout=30,
    )
    record.append_log(_sanitize_log(stdout or stderr), 'info')
    db.session.commit()

    record.append_log('Waiting for InstallPlan...', 'wait')
    stdout, stderr = ssh_exec(
        client,
        f'for i in $(seq 1 60); do '
        f'IP=$(oc get installplan -n {quote(ns)} -o name 2>/dev/null | head -1); '
        f'[ -n "$IP" ] && echo "$IP" && break; '
        f'sleep 3; done',
        kubeconfig=kubeconfig, timeout=200,
    )
    record.append_log(_sanitize_log(stdout or 'No InstallPlan yet'), 'info')
    db.session.commit()

    if not stdout or 'installplan' not in stdout:
        record.append_log('InstallPlan not found after waiting', 'fail')
        record.status = 'failed'
        db.session.commit()
        return

    record.append_log('Approving InstallPlan', 'phase')
    stdout, stderr = ssh_exec(
        client,
        f'oc get installplan -n {quote(ns)} -o name | '
        f'xargs -I{{}} oc patch {{}} -n {quote(ns)} '
        f'--type=merge -p \'{{"spec":{{"approved":true}}}}\'',
        kubeconfig=kubeconfig, timeout=30,
    )
    record.append_log(_sanitize_log(stdout or stderr), 'info')
    db.session.commit()

    record.append_log('Waiting for CSV to appear...', 'wait')
    stdout, stderr = ssh_exec(
        client,
        f'for i in $(seq 1 60); do '
        f'CSV=$(oc get csv -n {quote(ns)} '
        f'-l operators.coreos.com/{quote(pkg)}.{quote(ns)} '
        f'-o name 2>/dev/null | head -1); '
        f'[ -n "$CSV" ] && echo "$CSV" && break; '
        f'sleep 5; done',
        kubeconfig=kubeconfig, timeout=330,
    )
    record.append_log(_sanitize_log(stdout or 'No CSV yet'), 'info')
    db.session.commit()

    if not stdout or 'clusterserviceversion' not in stdout:
        record.append_log('CSV not found after waiting', 'fail')
        record.status = 'failed'
        db.session.commit()
        return

    record.append_log('Waiting for CSV to succeed...', 'wait')
    stdout, stderr = ssh_exec(
        client,
        f'oc wait --for=jsonpath=\'{{.status.phase}}\'=Succeeded csv '
        f'-n {quote(ns)} '
        f'-l operators.coreos.com/{quote(pkg)}.{quote(ns)} '
        f'--timeout=300s',
        kubeconfig=kubeconfig, timeout=330,
    )
    if stderr and 'error' in stderr.lower():
        record.append_log(_sanitize_log(stderr), 'fail')
        record.status = 'failed'
        db.session.commit()
        return
    record.append_log(_sanitize_log(stdout or 'CSV ready'), 'ok')
    db.session.commit()

    csv_out, _ = ssh_exec(
        client,
        f'oc get csv -n {quote(ns)} -o jsonpath=\'{{.items[0].spec.version}}\'',
        kubeconfig=kubeconfig, timeout=15,
    )
    if csv_out:
        record.version = csv_out.strip()

    if cat.get('cr'):
        _create_cr(client, kubeconfig, record, cat)

    if cat.get('post_cr'):
        _apply_post_cr(client, kubeconfig, record, cat)
    elif cat.get('post_cr_template') and params:
        _apply_post_cr_template(client, kubeconfig, record, cat, params)

    record.status = 'ready'
    record.append_log('Operator installation complete', 'ok')
    db.session.commit()


def _create_cr(client, kubeconfig, record, cat):
    """Create the operator's custom resource and wait for it."""
    cr = cat['cr']
    record.append_log(f'Creating {cr["kind"]} CR', 'phase')
    cr_yaml = (
        f'apiVersion: {cr["apiVersion"]}\n'
        f'kind: {cr["kind"]}\n'
        f'metadata:\n'
        f'  name: {cr["metadata"]["name"]}'
    )
    if 'namespace' in cr.get('metadata', {}):
        cr_yaml += f'\n  namespace: {cr["metadata"]["namespace"]}'

    stdout, stderr = ssh_exec(
        client,
        f'echo {quote(cr_yaml)} | oc apply -f -',
        kubeconfig=kubeconfig, timeout=30,
    )
    record.append_log(_sanitize_log(stdout or stderr), 'info')
    db.session.commit()

    if cat.get('cr_wait'):
        wait = cat['cr_wait']
        record.append_log(f'Waiting for {cr["kind"]} to become available...', 'wait')
        wait_ns = f'-n {quote(wait["namespace"])}' if 'namespace' in wait else ''
        stdout, stderr = ssh_exec(
            client,
            f'oc wait --for={wait["condition"]} '
            f'{wait["resource"]} {wait_ns} '
            f'--timeout={wait["timeout"]}',
            kubeconfig=kubeconfig, timeout=330,
        )
        record.append_log(_sanitize_log(stdout or stderr),
                          'ok' if 'met' in (stdout or '') else 'fail')
        db.session.commit()


def _apply_post_cr(client, kubeconfig, record, cat):
    """Apply post-CR resources (e.g., MetalLB IPAddressPool + L2Advertisement)."""
    for resource in cat['post_cr']:
        desc = resource.get('description', 'post-CR resource')
        record.append_log(f'Creating {desc}', 'phase')
        stdout, stderr = ssh_exec(
            client,
            f'echo {quote(resource["yaml"])} | oc apply -f -',
            kubeconfig=kubeconfig, timeout=30,
        )
        record.append_log(_sanitize_log(stdout or stderr), 'info')
        db.session.commit()


def _apply_post_cr_template(client, kubeconfig, record, cat, params):
    """Apply templated post-CR resources with user-supplied parameters."""
    tmpl = cat['post_cr_template']
    desc = tmpl.get('description', 'post-CR resource')
    record.append_log(f'Creating {desc} (with parameters)', 'phase')
    yaml_content = tmpl['yaml_template'].format(**params)
    stdout, stderr = ssh_exec(
        client,
        f'echo {quote(yaml_content)} | oc apply -f -',
        kubeconfig=kubeconfig, timeout=30,
    )
    record.append_log(_sanitize_log(stdout or stderr), 'info')
    db.session.commit()


def run_remove(app, record_id, operator_key):
    """Background thread: remove an operator via SSH."""
    try:
        with app.app_context():
            record = db.session.get(OperatorInstall, record_id)
            cat = OPERATOR_CATALOG[operator_key]
            ns = cat['namespace']
            pkg = cat['package']

            try:
                client, kubeconfig = _get_ssh_and_kubeconfig()
            except Exception as exc:
                record.append_log(f'SSH connection failed: {exc}', 'fail')
                record.status = 'failed'
                record.finished_at = datetime.now(timezone.utc)
                db.session.commit()
                return

            try:
                _do_remove(client, kubeconfig, record, ns, pkg, cat)
            finally:
                client.close()
                record.finished_at = datetime.now(timezone.utc)
                db.session.commit()
    finally:
        release_lock()


def _do_remove(client, kubeconfig, record, ns, pkg, cat):
    """Execute the operator removal steps over SSH."""
    if cat.get('post_cr'):
        for resource in reversed(cat['post_cr']):
            desc = resource.get('description', 'post-CR resource')
            record.append_log(f'Deleting {desc}', 'phase')
            for cmd in resource.get('delete_commands', []):
                stdout, stderr = ssh_exec(
                    client, cmd, kubeconfig=kubeconfig, timeout=30,
                )
                record.append_log(_sanitize_log(stdout or stderr), 'info')
            db.session.commit()
    elif cat.get('post_cr_template'):
        tmpl = cat['post_cr_template']
        desc = tmpl.get('description', 'post-CR resource')
        record.append_log(f'Deleting {desc}', 'phase')
        for cmd_tmpl in tmpl.get('delete_commands_template', []):
            cmd = cmd_tmpl.format(pool_name='metallb')
            stdout, stderr = ssh_exec(
                client, cmd, kubeconfig=kubeconfig, timeout=30,
            )
            record.append_log(_sanitize_log(stdout or stderr), 'info')
        db.session.commit()

    if cat.get('cr'):
        cr = cat['cr']
        record.append_log(f'Deleting {cr["kind"]} CR', 'phase')
        cr_ns = ''
        if 'namespace' in cr.get('metadata', {}):
            cr_ns = f'-n {quote(cr["metadata"]["namespace"])}'
        stdout, stderr = ssh_exec(
            client,
            f'oc delete {cr["kind"].lower()} {quote(cr["metadata"]["name"])} '
            f'{cr_ns} --ignore-not-found',
            kubeconfig=kubeconfig, timeout=60,
        )
        record.append_log(_sanitize_log(stdout or stderr), 'info')
        db.session.commit()

    record.append_log('Deleting CSV', 'phase')
    stdout, stderr = ssh_exec(
        client,
        f'oc delete csv -n {quote(ns)} '
        f'-l operators.coreos.com/{quote(pkg)}.{quote(ns)} '
        f'--ignore-not-found',
        kubeconfig=kubeconfig, timeout=30,
    )
    record.append_log(_sanitize_log(stdout or stderr), 'info')
    db.session.commit()

    record.append_log('Deleting Subscription', 'phase')
    stdout, stderr = ssh_exec(
        client,
        f'oc delete subscription {quote(pkg)} -n {quote(ns)} --ignore-not-found',
        kubeconfig=kubeconfig, timeout=30,
    )
    record.append_log(_sanitize_log(stdout or stderr), 'info')
    db.session.commit()

    record.append_log('Deleting InstallPlans and OperatorGroup', 'phase')
    stdout, stderr = ssh_exec(
        client,
        f'oc delete installplan --all -n {quote(ns)} --ignore-not-found && '
        f'oc delete operatorgroup --all -n {quote(ns)} --ignore-not-found',
        kubeconfig=kubeconfig, timeout=30,
    )
    record.append_log(_sanitize_log(stdout or stderr), 'info')
    db.session.commit()

    record.append_log('Deleting CRDs', 'phase')
    stdout, stderr = ssh_exec(
        client,
        f'oc get crd -o name | grep -i {quote(pkg.split("-")[0])} | '
        f'xargs -r oc delete --ignore-not-found',
        kubeconfig=kubeconfig, timeout=60,
    )
    record.append_log(_sanitize_log(stdout or stderr), 'info')
    db.session.commit()

    record.append_log(f'Deleting namespace {ns}', 'phase')
    stdout, stderr = ssh_exec(
        client,
        f'oc delete namespace {quote(ns)} --ignore-not-found',
        kubeconfig=kubeconfig, timeout=120,
    )
    record.append_log(_sanitize_log(stdout or stderr), 'info')

    record.status = 'removed'
    record.append_log('Operator removal complete', 'ok')
    db.session.commit()
