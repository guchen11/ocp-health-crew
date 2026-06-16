"""Test Suite CRUD and execution API routes."""
import logging

from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import or_

from config.settings import AVAILABLE_CHECKS, CNV_SCENARIOS

from app.decorators import log_audit, operator_required
from app.models import Host, SuiteRun, TestSuite, db, MAX_SUITE_ITEMS

from app.routes import dashboard_bp

log = logging.getLogger(__name__)

VALID_TASK_TYPES = {'health_check', 'cnv_scenarios', 'cnv_combined'}
VALID_REMOTE_NAMES = {s['remote_name'] for s in CNV_SCENARIOS.values()}


def _validate_suite_items(items):
    """Validate suite item configs (SEC-001). Returns (ok, error_msg)."""
    if not isinstance(items, list):
        return False, 'items must be a list'
    if not items:
        return True, ''
    if len(items) > MAX_SUITE_ITEMS:
        return False, f'maximum {MAX_SUITE_ITEMS} items per suite'

    registered_hosts = {h.host for h in Host.query.all()}
    valid_checks = set(AVAILABLE_CHECKS.keys())

    for idx, item in enumerate(items):
        config = item.get('config')
        if not config or not isinstance(config, dict):
            return False, f'item {idx}: config is required'

        task_type = config.get('task_type', 'health_check')
        if task_type not in VALID_TASK_TYPES:
            return False, f'item {idx}: invalid task_type "{task_type}"'

        server_host = config.get('server_host', '')
        if server_host and server_host not in registered_hosts:
            return False, f'item {idx}: unregistered server_host "{server_host}"'

        if task_type in ('cnv_scenarios', 'cnv_combined'):
            tests = config.get('scenario_tests', [])
            for t in tests:
                if t not in VALID_REMOTE_NAMES:
                    log.warning("Suite item %d: scenario '%s' not in registry (may be valid on remote)", idx, t)

    return True, ''


@dashboard_bp.route('/api/suites', methods=['GET'])
@login_required
def api_suites_list():
    """List suites visible to current user (own + shared) (SEC-003)."""
    suites = TestSuite.query.filter(
        or_(TestSuite.created_by == current_user.id, TestSuite.shared == True)
    ).order_by(TestSuite.updated_at.desc()).all()
    return jsonify([s.to_dict() for s in suites])


@dashboard_bp.route('/api/suites', methods=['POST'])
@operator_required
def api_suites_create():
    """Create a new test suite."""
    data = request.get_json(silent=True)
    if not data or not data.get('name'):
        return jsonify({'error': 'name is required'}), 400

    items = data.get('items', [])
    ok, err = _validate_suite_items(items)
    if not ok:
        return jsonify({'error': err}), 400

    suite = TestSuite(
        name=data['name'][:200],
        description=(data.get('description') or '')[:500],
        icon=data.get('icon', '📦')[:10],
        created_by=current_user.id,
        shared=bool(data.get('shared', False)),
        stop_on_failure=bool(data.get('stop_on_failure', True)),
        items=items,
    )
    db.session.add(suite)
    db.session.commit()

    log_audit('suite_create', target=f'Suite #{suite.id}: {suite.name}')
    return jsonify(suite.to_dict()), 201


@dashboard_bp.route('/api/suites/<int:suite_id>', methods=['GET'])
@login_required
def api_suites_get(suite_id):
    """Get a single suite by ID."""
    suite = TestSuite.query.get_or_404(suite_id)
    if suite.created_by != current_user.id and not suite.shared and not current_user.is_admin:
        return jsonify({'error': 'forbidden'}), 403
    return jsonify(suite.to_dict())


@dashboard_bp.route('/api/suites/<int:suite_id>', methods=['PUT'])
@operator_required
def api_suites_update(suite_id):
    """Update an existing suite (owner or admin only)."""
    suite = TestSuite.query.get_or_404(suite_id)
    if suite.created_by != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'forbidden'}), 403

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'invalid JSON'}), 400

    if 'name' in data:
        suite.name = data['name'][:200]
    if 'description' in data:
        suite.description = (data['description'] or '')[:500]
    if 'icon' in data:
        suite.icon = data['icon'][:10]
    if 'shared' in data:
        suite.shared = bool(data['shared'])
    if 'stop_on_failure' in data:
        suite.stop_on_failure = bool(data['stop_on_failure'])
    if 'items' in data:
        ok, err = _validate_suite_items(data['items'])
        if not ok:
            return jsonify({'error': err}), 400
        suite.items = data['items']

    db.session.commit()
    log_audit('suite_update', target=f'Suite #{suite.id}: {suite.name}')
    return jsonify(suite.to_dict())


@dashboard_bp.route('/api/suites/<int:suite_id>', methods=['DELETE'])
@operator_required
def api_suites_delete(suite_id):
    """Delete a suite (owner or admin only)."""
    suite = TestSuite.query.get_or_404(suite_id)
    if suite.created_by != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'forbidden'}), 403

    name = suite.name
    db.session.delete(suite)
    db.session.commit()
    log_audit('suite_delete', target=f'Suite #{suite_id}: {name}')
    return jsonify({'ok': True})


@dashboard_bp.route('/api/suites/<int:suite_id>/run', methods=['POST'])
@operator_required
def api_suites_run(suite_id):
    """Execute a test suite sequentially."""
    from app.routes.suite_executor import run_suite

    suite = TestSuite.query.get_or_404(suite_id)
    if suite.created_by != current_user.id and not suite.shared and not current_user.is_admin:
        return jsonify({'error': 'forbidden'}), 403

    items = suite.items or []
    if not items:
        return jsonify({'error': 'suite has no items'}), 400

    if len(items) > 20:
        log.warning(
            "User %s triggered suite '%s' with %d items (SEC-004)",
            current_user.username, suite.name, len(items),
        )

    run_items = []
    for item in items:
        run_items.append({
            'template_name': item.get('template_name', ''),
            'config': item.get('config', {}),
            'item_status': 'pending',
            'build_number': None,
        })

    suite_run = SuiteRun(
        suite_id=suite.id,
        name=suite.name,
        status='pending',
        created_by=current_user.id,
        stop_on_failure=suite.stop_on_failure,
        items=run_items,
        total_items=len(run_items),
        completed_items=0,
        current_item_index=-1,
    )
    db.session.add(suite_run)
    db.session.commit()

    log_audit('suite_run', target=f'SuiteRun #{suite_run.id} from Suite #{suite.id}')
    run_suite(suite_run.id, current_user.id)

    return jsonify(suite_run.to_dict()), 201


@dashboard_bp.route('/api/suite-runs', methods=['GET'])
@login_required
def api_suite_runs_list():
    """List suite runs for current user."""
    runs = SuiteRun.query.filter_by(
        created_by=current_user.id
    ).order_by(SuiteRun.started_at.desc()).limit(50).all()
    return jsonify([r.to_dict() for r in runs])


@dashboard_bp.route('/api/suite-runs/<int:run_id>', methods=['GET'])
@login_required
def api_suite_runs_get(run_id):
    """Get suite run status."""
    sr = SuiteRun.query.get_or_404(run_id)
    if sr.created_by != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'forbidden'}), 403
    return jsonify(sr.to_dict())


@dashboard_bp.route('/api/suite-runs/<int:run_id>/abort', methods=['POST'])
@operator_required
def api_suite_runs_abort(run_id):
    """Abort remaining items in a suite run (SEC-003: owner or admin)."""
    sr = SuiteRun.query.get_or_404(run_id)
    if sr.created_by != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'forbidden'}), 403

    if sr.status not in ('pending', 'running'):
        return jsonify({'error': 'suite run is not active'}), 400

    sr.status = 'aborted'
    items = list(sr.items or [])
    for item in items:
        if item.get('item_status') in ('pending', None):
            item['item_status'] = 'skipped'
    sr.items = items
    db.session.commit()

    log_audit('suite_abort', target=f'SuiteRun #{run_id}')
    return jsonify(sr.to_dict())
