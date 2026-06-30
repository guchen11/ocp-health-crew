"""Upgrade policies and runs API routes."""
import logging
import re

from flask import current_app, jsonify, request
from flask_login import current_user, login_required

from app.decorators import log_audit, operator_required
from app.models import UpgradePolicy, UpgradeRun, db

from app.routes import dashboard_bp

log = logging.getLogger(__name__)

VALID_DAYS = {'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'}
_TIME_RE = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')

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

    auto_approve = bool(data.get('auto_approve', False))
    sched_mode = 'interval'
    sched_time = None
    sched_days = None
    sched_dates = None
    if auto_approve:
        sched_mode = data.get('schedule_mode', 'interval')
        if sched_mode not in ('interval', 'daily', 'dates'):
            sched_mode = 'interval'

        sched_time = (data.get('schedule_time') or '').strip() or None
        if sched_time and not _TIME_RE.match(sched_time):
            return jsonify({'error': 'schedule_time must be HH:MM (24h)'}), 400

        sched_days = data.get('schedule_days') or None
        if sched_days is not None:
            if not isinstance(sched_days, list):
                return jsonify({'error': 'schedule_days must be a list'}), 400
            sched_days = [d.lower() for d in sched_days if d.lower() in VALID_DAYS] or None

        sched_dates = data.get('schedule_dates') or None
        if sched_dates is not None:
            if not isinstance(sched_dates, list):
                return jsonify({'error': 'schedule_dates must be a list'}), 400
            sched_dates = [d.strip() for d in sched_dates if d.strip()][:20] or None

    policy = UpgradePolicy(
        name=data['name'][:200],
        description=(data.get('description') or '')[:500],
        enabled=bool(data.get('enabled', True)),
        auto_approve=auto_approve,
        steps=_normalize_steps(data.get('steps', [])),
        scan_interval_minutes=max(5, int(data.get('scan_interval_minutes', 60))),
        schedule_mode=sched_mode,
        schedule_time=sched_time,
        schedule_days=sched_days,
        schedule_dates=sched_dates,
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
        if not new_auto:
            policy.schedule_time = None
            policy.schedule_days = None
    if 'steps' in data:
        policy.steps = _normalize_steps(data['steps'])
    if 'scan_interval_minutes' in data:
        policy.scan_interval_minutes = max(5, int(data['scan_interval_minutes']))
    if 'schedule_mode' in data:
        sm = data['schedule_mode']
        if sm in ('interval', 'daily', 'dates'):
            policy.schedule_mode = sm
    if policy.auto_approve:
        if 'schedule_time' in data:
            st = (data['schedule_time'] or '').strip() or None
            if st and not _TIME_RE.match(st):
                return jsonify({'error': 'schedule_time must be HH:MM (24h)'}), 400
            policy.schedule_time = st
        if 'schedule_days' in data:
            sd = data['schedule_days'] or None
            if sd is not None:
                if not isinstance(sd, list):
                    return jsonify({'error': 'schedule_days must be a list'}), 400
                sd = [d.lower() for d in sd if d.lower() in VALID_DAYS] or None
            policy.schedule_days = sd
        if 'schedule_dates' in data:
            sdt = data['schedule_dates'] or None
            if sdt is not None:
                if not isinstance(sdt, list):
                    return jsonify({'error': 'schedule_dates must be a list'}), 400
                sdt = [d.strip() for d in sdt if d.strip()][:20] or None
            policy.schedule_dates = sdt

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


@dashboard_bp.route('/api/upgrades/operator', methods=['POST'])
@operator_required
def api_upgrade_single_operator():
    """Upgrade a single OLM operator by name/namespace."""
    data = request.get_json(silent=True)
    if not data or not data.get('operator'):
        return jsonify({'error': 'operator name is required'}), 400

    operator = data['operator'][:200]
    namespace = (data.get('namespace') or '')[:200]

    policy = UpgradePolicy(
        name=f"Quick: {operator}"[:200],
        description=f"Ad-hoc upgrade of {operator}",
        enabled=False,
        auto_approve=False,
        steps=[{
            'type': 'upgrade_olm',
            'enabled': True,
            'target': operator,
            'namespace': namespace,
            'label': f"Upgrade OLM: {operator}",
        }],
        scan_interval_minutes=9999,
        created_by=current_user.id,
    )
    db.session.add(policy)
    db.session.commit()

    run = UpgradeRun(
        policy_id=policy.id,
        upgrade_type='pipeline',
        operator_name=operator,
        status='pending',
        created_by=current_user.id,
    )
    run.append_log(f"Quick OLM upgrade triggered by {current_user.username}")
    run.append_log(f"Target: {operator} ({namespace or 'any namespace'})")
    db.session.add(run)
    db.session.commit()

    log_audit('upgrade_operator', target=f'Run #{run.id}: {operator}')

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
