"""Template CRUD API routes."""
from flask import jsonify, request
from flask_login import current_user, login_required

from app.decorators import operator_required

from app.models import Build, Template, db

from app.routes import dashboard_bp

@dashboard_bp.route('/api/templates', methods=['GET'])
@login_required
def api_templates_list():
    """List templates visible to current user (own + shared)."""
    from sqlalchemy import or_
    templates = Template.query.filter(
        or_(Template.created_by == current_user.id, Template.shared == True)
    ).order_by(Template.updated_at.desc()).all()
    return jsonify([t.to_dict() for t in templates])


@dashboard_bp.route('/api/templates', methods=['POST'])
@operator_required
def api_templates_create():
    """Create a new template from JSON body."""
    data = request.get_json(silent=True)
    if not data or not data.get('name') or not data.get('config'):
        return jsonify({'error': 'name and config are required'}), 400

    tmpl = Template(
        name=data['name'][:200],
        description=(data.get('description') or '')[:500],
        icon=data.get('icon', '📋')[:10],
        created_by=current_user.id,
        shared=bool(data.get('shared', False)),
        config=data['config'],
    )
    db.session.add(tmpl)
    db.session.commit()
    return jsonify(tmpl.to_dict()), 201


@dashboard_bp.route('/api/templates/<int:tmpl_id>', methods=['PUT'])
@operator_required
def api_templates_update(tmpl_id):
    """Update an existing template (owner or admin only)."""
    tmpl = Template.query.get_or_404(tmpl_id)
    if tmpl.created_by != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'forbidden'}), 403

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'invalid JSON'}), 400

    if 'name' in data:
        tmpl.name = data['name'][:200]
    if 'description' in data:
        tmpl.description = (data['description'] or '')[:500]
    if 'icon' in data:
        tmpl.icon = data['icon'][:10]
    if 'shared' in data:
        tmpl.shared = bool(data['shared'])
    if 'config' in data:
        tmpl.config = data['config']

    db.session.commit()
    return jsonify(tmpl.to_dict())


@dashboard_bp.route('/api/templates/<int:tmpl_id>', methods=['DELETE'])
@operator_required
def api_templates_delete(tmpl_id):
    """Delete a template (owner or admin only)."""
    tmpl = Template.query.get_or_404(tmpl_id)
    if tmpl.created_by != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'forbidden'}), 403

    db.session.delete(tmpl)
    db.session.commit()
    return jsonify({'ok': True})


@dashboard_bp.route('/api/templates/from-build/<int:build_num>', methods=['POST'])
@operator_required
def api_templates_from_build(build_num):
    """Create a template from a past build's options."""
    from app.models import Build
    build = Build.query.filter_by(build_number=build_num).first_or_404()

    data = request.get_json(silent=True) or {}
    name = data.get('name', f'From Build #{build_num}')[:200]
    description = data.get('description', f'Saved from build #{build_num}')[:500]
    icon = data.get('icon', '📋')[:10]
    shared = bool(data.get('shared', False))

    config = build.options or {}
    # Also store the checks/tests list in config for full reproducibility
    if build.checks:
        config['_checks'] = build.checks

    tmpl = Template(
        name=name,
        description=description,
        icon=icon,
        created_by=current_user.id,
        shared=shared,
        config=config,
    )
    db.session.add(tmpl)
    db.session.commit()
    return jsonify(tmpl.to_dict()), 201

