"""Custom health checks CRUD API routes."""
import json as json_lib
from datetime import datetime

from flask import Response, jsonify, request
from flask_login import current_user, login_required

from app.decorators import log_audit, operator_required

from app.models import CustomCheck, db

from app.routes import dashboard_bp

@dashboard_bp.route('/api/custom-checks', methods=['GET'])
@login_required
def api_get_custom_checks():
    """List all custom checks (user's own)."""
    from app.models import CustomCheck
    checks = CustomCheck.query.filter_by(created_by=current_user.id).order_by(CustomCheck.created_at.desc()).all()
    return jsonify([c.to_dict() for c in checks])


@dashboard_bp.route('/api/custom-checks', methods=['POST'])
@operator_required
def api_create_custom_check():
    """Create a new custom check (command or script)."""
    from app.models import CustomCheck

    # Support both JSON and multipart/form-data (for file upload)
    if request.content_type and 'multipart/form-data' in request.content_type:
        data = request.form.to_dict()
        script_file = request.files.get('script_file')
    else:
        data = request.get_json(silent=True) or {}
        script_file = None

    name = data.get('name', '').strip()
    check_type = data.get('check_type', 'command')

    # Validate: must have a name, and either a command or a script
    command = data.get('command', '').strip()
    script_content = data.get('script_content', '').strip()
    script_filename = ''

    if script_file and script_file.filename:
        script_content = script_file.read().decode('utf-8', errors='replace')
        script_filename = script_file.filename
        check_type = 'script'

    if not name:
        return jsonify({'success': False, 'error': 'Name is required.'}), 400
    if check_type == 'command' and not command:
        return jsonify({'success': False, 'error': 'Command is required.'}), 400
    if check_type == 'script' and not script_content:
        return jsonify({'success': False, 'error': 'Script content is required (paste or upload a file).'}), 400

    check = CustomCheck(
        name=name,
        check_type=check_type,
        command=command,
        script_content=script_content if check_type == 'script' else None,
        script_filename=script_filename or data.get('script_filename', ''),
        expected_value=data.get('expected_value', '').strip(),
        match_type=data.get('match_type', 'contains'),
        description=data.get('description', '').strip(),
        run_with=data.get('run_with', 'health_check'),
        linked_scenario=data.get('linked_scenario', '').strip() or None,
        enabled=data.get('enabled', True) if isinstance(data.get('enabled'), bool) else data.get('enabled', 'true').lower() != 'false',
        created_by=current_user.id,
    )
    db.session.add(check)
    db.session.commit()
    detail = f'Script: {script_filename}' if check_type == 'script' else f'Command: {command}'
    log_audit('custom_check_create', target=name, details=detail)
    return jsonify({'success': True, 'check': check.to_dict()})


@dashboard_bp.route('/api/custom-checks/<int:check_id>', methods=['PUT'])
@operator_required
def api_update_custom_check(check_id):
    """Update an existing custom check."""
    from app.models import CustomCheck
    check = CustomCheck.query.get(check_id)
    if not check:
        return jsonify({'success': False, 'error': 'Check not found.'}), 404
    if check.created_by != current_user.id and not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Permission denied.'}), 403

    # Support both JSON and multipart/form-data
    if request.content_type and 'multipart/form-data' in request.content_type:
        data = request.form.to_dict()
        script_file = request.files.get('script_file')
    else:
        data = request.get_json(silent=True) or {}
        script_file = None

    if 'name' in data:
        check.name = data['name'].strip()
    if 'check_type' in data:
        check.check_type = data['check_type']
    if 'command' in data:
        check.command = data['command'].strip()
    if 'script_content' in data:
        check.script_content = data['script_content'].strip() or None
    if script_file and script_file.filename:
        check.script_content = script_file.read().decode('utf-8', errors='replace')
        check.script_filename = script_file.filename
        check.check_type = 'script'
    if 'script_filename' in data:
        check.script_filename = data['script_filename'].strip()
    if 'expected_value' in data:
        check.expected_value = data['expected_value'].strip()
    if 'match_type' in data:
        check.match_type = data['match_type']
    if 'description' in data:
        check.description = data['description'].strip()
    if 'run_with' in data:
        check.run_with = data['run_with']
    if 'linked_scenario' in data:
        check.linked_scenario = data['linked_scenario'].strip() or None
    if 'enabled' in data:
        val = data['enabled']
        check.enabled = val if isinstance(val, bool) else str(val).lower() != 'false'

    db.session.commit()
    log_audit('custom_check_update', target=check.name)
    return jsonify({'success': True, 'check': check.to_dict()})


@dashboard_bp.route('/api/custom-checks/<int:check_id>', methods=['DELETE'])
@operator_required
def api_delete_custom_check(check_id):
    """Delete a custom check."""
    from app.models import CustomCheck
    check = CustomCheck.query.get(check_id)
    if not check:
        return jsonify({'success': False, 'error': 'Check not found.'}), 404
    if check.created_by != current_user.id and not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Permission denied.'}), 403

    name = check.name
    db.session.delete(check)
    db.session.commit()
    log_audit('custom_check_delete', target=name)
    return jsonify({'success': True})


@dashboard_bp.route('/api/custom-checks/export', methods=['GET'])
@login_required
def api_export_custom_checks():
    """Export all custom checks for this user as a JSON file."""
    from app.models import CustomCheck
    checks = CustomCheck.query.filter_by(created_by=current_user.id).order_by(CustomCheck.name).all()
    export_data = {
        'version': 1,
        'exported_by': current_user.username,
        'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'checks': [],
    }
    for cc in checks:
        export_data['checks'].append({
            'name': cc.name,
            'check_type': cc.check_type or 'command',
            'command': cc.command or '',
            'script_content': cc.script_content or '',
            'script_filename': cc.script_filename or '',
            'expected_value': cc.expected_value or '',
            'match_type': cc.match_type or 'contains',
            'description': cc.description or '',
            'run_with': cc.run_with or 'health_check',
            'linked_scenario': cc.linked_scenario or '',
            'enabled': cc.enabled,
        })

    from flask import Response
    import json as _json
    payload = _json.dumps(export_data, indent=2)
    filename = f'custom_checks_{current_user.username}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    log_audit('custom_check_export', details=f'{len(checks)} checks exported')
    return Response(
        payload,
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@dashboard_bp.route('/api/custom-checks/import', methods=['POST'])
@operator_required
def api_import_custom_checks():
    """Import custom checks from a JSON file."""
    from app.models import CustomCheck
    import json as _json

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'success': False, 'error': 'No file uploaded.'}), 400

    try:
        raw = file.read().decode('utf-8', errors='replace')
        data = _json.loads(raw)
    except Exception as e:
        return jsonify({'success': False, 'error': f'Invalid JSON file: {e}'}), 400

    checks_data = data.get('checks', [])
    if not checks_data:
        return jsonify({'success': False, 'error': 'No checks found in the file.'}), 400

    mode = request.form.get('mode', 'merge')  # merge | replace

    if mode == 'replace':
        # Delete existing checks for this user before importing
        CustomCheck.query.filter_by(created_by=current_user.id).delete()
        db.session.flush()

    imported = 0
    skipped = 0
    for item in checks_data:
        name = item.get('name', '').strip()
        if not name:
            skipped += 1
            continue

        # In merge mode, skip if same name already exists
        if mode == 'merge':
            existing = CustomCheck.query.filter_by(created_by=current_user.id, name=name).first()
            if existing:
                skipped += 1
                continue

        check_type = item.get('check_type', 'command')
        command = item.get('command', '').strip()
        script_content = item.get('script_content', '').strip()

        if check_type == 'command' and not command:
            skipped += 1
            continue
        if check_type == 'script' and not script_content:
            skipped += 1
            continue

        cc = CustomCheck(
            name=name,
            check_type=check_type,
            command=command,
            script_content=script_content or None,
            script_filename=item.get('script_filename', ''),
            expected_value=item.get('expected_value', ''),
            match_type=item.get('match_type', 'contains'),
            description=item.get('description', ''),
            run_with=item.get('run_with', 'health_check'),
            linked_scenario=item.get('linked_scenario', '').strip() or None,
            enabled=item.get('enabled', True),
            created_by=current_user.id,
        )
        db.session.add(cc)
        imported += 1

    db.session.commit()
    log_audit('custom_check_import', details=f'{imported} imported, {skipped} skipped (mode={mode})')
    return jsonify({
        'success': True,
        'imported': imported,
        'skipped': skipped,
        'total': len(checks_data),
    })
