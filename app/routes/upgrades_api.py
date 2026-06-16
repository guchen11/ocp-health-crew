"""Upgrade policies and runs API routes."""
import logging

from flask import current_app, jsonify, request
from flask_login import current_user, login_required

from app.decorators import log_audit, operator_required
from app.models import UpgradePolicy, UpgradeRun, db

from app.routes import dashboard_bp

log = logging.getLogger(__name__)

VALID_STEP_TYPES = {
    'upgrade_olm', 'upgrade_cvo',
    'test_suite', 'template', 'health_check',
}


def _normalize_steps(raw_steps):
    """Validate and normalize pipeline steps list."""
    if not isinstance(raw_steps, list):
        return []
    steps = []
    for s in raw_steps:
        stype = s.get('type', '')
        if stype not in VALID_STEP_TYPES:
            continue
        entry = {
            'type': stype,
            'enabled': bool(s.get('enabled', True)),
            'id': s.get('id'),
            'label': s.get('label', stype),
        }
        if stype == 'upgrade_olm':
            entry['target'] = s.get('target', '*')
            entry['namespace'] = s.get('namespace', '')
        steps.append(entry)
    return steps


@dashboard_bp.route('/api/upgrades/scan', methods=['GET'])
@operator_required
def api_upgrades_scan():
    """Trigger a one-time scan for available upgrades."""
    from app.routes.upgrade_scanner import run_scan
    return jsonify(run_scan())


@dashboard_bp.route('/api/upgrades/policies', methods=['GET'])
@login_required
def api_upgrade_policies_list():
    """List all upgrade policies."""
    policies = UpgradePolicy.query.order_by(UpgradePolicy.created_at.desc()).all()
    return jsonify([p.to_dict() for p in policies])


@dashboard_bp.route('/api/upgrades/policies', methods=['POST'])
@operator_required
def api_upgrade_policies_create():
    """Create a new upgrade policy (pipeline of steps)."""
    data = request.get_json(silent=True)
    if not data or not data.get('name'):
        return jsonify({'error': 'name is required'}), 400

    policy = UpgradePolicy(
        name=data['name'][:200],
        description=(data.get('description') or '')[:500],
        enabled=bool(data.get('enabled', True)),
        auto_approve=bool(data.get('auto_approve', False)),
        steps=_normalize_steps(data.get('steps', [])),
        scan_interval_minutes=max(5, int(data.get('scan_interval_minutes', 60))),
        created_by=current_user.id,
    )
    db.session.add(policy)
    db.session.commit()

    log_audit('upgrade_policy_create', target=f'Policy #{policy.id}: {policy.name}')
    return jsonify(policy.to_dict()), 201


@dashboard_bp.route('/api/upgrades/policies/<int:pid>', methods=['PUT'])
@operator_required
def api_upgrade_policies_update(pid):
    """Update an upgrade policy."""
    policy = UpgradePolicy.query.get_or_404(pid)
    if policy.created_by != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'forbidden'}), 403

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'invalid JSON'}), 400

    if 'name' in data:
        policy.name = data['name'][:200]
    if 'description' in data:
        policy.description = (data['description'] or '')[:500]
    if 'enabled' in data:
        policy.enabled = bool(data['enabled'])
    if 'auto_approve' in data:
        new_auto = bool(data['auto_approve'])
        if new_auto and not policy.auto_approve:
            from datetime import datetime, timezone
            policy.last_scanned_at = datetime.now(timezone.utc)
        policy.auto_approve = new_auto
    if 'steps' in data:
        policy.steps = _normalize_steps(data['steps'])
    if 'scan_interval_minutes' in data:
        policy.scan_interval_minutes = max(5, int(data['scan_interval_minutes']))

    db.session.commit()
    log_audit('upgrade_policy_update', target=f'Policy #{policy.id}: {policy.name}')
    return jsonify(policy.to_dict())


@dashboard_bp.route('/api/upgrades/policies/<int:pid>', methods=['DELETE'])
@operator_required
def api_upgrade_policies_delete(pid):
    """Delete an upgrade policy."""
    policy = UpgradePolicy.query.get_or_404(pid)
    if policy.created_by != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'forbidden'}), 403

    name = policy.name
    db.session.delete(policy)
    db.session.commit()
    log_audit('upgrade_policy_delete', target=f'Policy #{pid}: {name}')
    return jsonify({'ok': True})


@dashboard_bp.route('/api/upgrades/policies/<int:pid>/trigger', methods=['POST'])
@operator_required
def api_upgrade_policies_trigger(pid):
    """Manually trigger a policy pipeline."""
    policy = UpgradePolicy.query.get_or_404(pid)
    steps = policy.steps or []
    enabled_steps = [s for s in steps if s.get('enabled', True)]

    if not enabled_steps:
        return jsonify({'error': 'no enabled steps in this policy'}), 400

    has_upgrade = any(s.get('type', '').startswith('upgrade') for s in enabled_steps)
    if has_upgrade:
        try:
            from app.ssh_utils import create_ssh_client
            from app.routes.upgrade_scanner import scan_olm, scan_cvo
            client = create_ssh_client()
            try:
                olm_pending = scan_olm(client)
                cvo_data = scan_cvo(client)
                cvo_pending = cvo_data.get('available_updates', []) if cvo_data else []
            finally:
                client.close()

            has_olm = any(s.get('type') == 'upgrade_olm' for s in enabled_steps)
            has_cvo = any(s.get('type') == 'upgrade_cvo' for s in enabled_steps)
            upgrades_available = (has_olm and olm_pending) or (has_cvo and cvo_pending)

            if not upgrades_available:
                return jsonify({
                    'error': 'No upgrades available. Tests will not run.',
                    'no_upgrades': True,
                }), 200
        except Exception as exc:
            log.warning("Pre-trigger scan failed, proceeding anyway: %s", exc)

    run = UpgradeRun(
        policy_id=policy.id,
        upgrade_type='pipeline',
        operator_name=policy.name,
        status='pending',
        created_by=current_user.id,
    )
    run.append_log(f"Manually triggered by {current_user.username}")
    run.append_log(f"Pipeline: {len(enabled_steps)} enabled step(s)")
    db.session.add(run)
    db.session.commit()

    log_audit('upgrade_trigger', target=f'Run #{run.id}: {policy.name}')

    from app.routes.upgrade_executor import execute_pipeline
    execute_pipeline(run.id, current_app._get_current_object())
    return jsonify(run.to_dict()), 201


@dashboard_bp.route('/api/upgrades/runs', methods=['GET'])
@login_required
def api_upgrade_runs_list():
    """List upgrade runs."""
    runs = UpgradeRun.query.order_by(UpgradeRun.created_at.desc()).limit(50).all()
    return jsonify([r.to_dict() for r in runs])


@dashboard_bp.route('/api/upgrades/runs/<int:rid>', methods=['GET'])
@login_required
def api_upgrade_runs_get(rid):
    """Get upgrade run detail."""
    return jsonify(UpgradeRun.query.get_or_404(rid).to_dict())


@dashboard_bp.route('/api/upgrades/runs/<int:rid>/abort', methods=['POST'])
@operator_required
def api_upgrade_runs_abort(rid):
    """Abort an upgrade run."""
    run = UpgradeRun.query.get_or_404(rid)
    if run.status not in ('pending', 'upgrading', 'waiting', 'testing'):
        return jsonify({'error': 'run is not active'}), 400

    run.status = 'failed'
    run.append_log(f"Aborted by {current_user.username}")
    db.session.commit()
    log_audit('upgrade_abort', target=f'Run #{rid}')
    return jsonify(run.to_dict())
