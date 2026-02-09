"""
CNV Health Dashboard - Admin Blueprint

User management and audit log viewing for admin users.
"""

from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, request, jsonify, flash
from flask_login import login_required, current_user
from app.models import db, User, AuditLog
from app.auth import log_audit

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    """Decorator to restrict access to admin users only."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            return "Access denied. Admin role required.", 403
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/users')
@admin_required
def users():
    """User management page."""
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin_users.html', users=all_users, active_page='admin')


@admin_bp.route('/users/create', methods=['POST'])
@admin_required
def create_user():
    """Create a new user."""
    username = request.form.get('username', '').strip()
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    role = request.form.get('role', 'operator')

    if not username or not email or not password:
        return jsonify({'success': False, 'error': 'All fields are required.'})

    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'error': 'Username already taken.'})

    if User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'error': 'Email already registered.'})

    if role not in ('admin', 'operator', 'viewer'):
        return jsonify({'success': False, 'error': 'Invalid role.'})

    user = User(username=username, email=email, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    log_audit('user_create', target=f'User {username}', details=f'Role: {role}')
    return jsonify({'success': True, 'message': f'User {username} created.'})


@admin_bp.route('/users/<int:user_id>/update', methods=['POST'])
@admin_required
def update_user(user_id):
    """Update a user's role."""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found.'})

    # Prevent demoting self
    if user.id == current_user.id:
        return jsonify({'success': False, 'error': 'Cannot change your own role.'})

    new_role = request.form.get('role', user.role)
    if new_role not in ('admin', 'operator', 'viewer'):
        return jsonify({'success': False, 'error': 'Invalid role.'})

    old_role = user.role
    user.role = new_role
    db.session.commit()

    log_audit('user_update', target=f'User {user.username}',
              details=f'Role: {old_role} -> {new_role}')
    return jsonify({'success': True, 'message': f'User {user.username} updated.'})


@admin_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@admin_required
def reset_user_password(user_id):
    """Reset a user's password."""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found.'})

    new_password = request.form.get('password', '')
    if len(new_password) < 6:
        return jsonify({'success': False, 'error': 'Password must be at least 6 characters.'})

    user.set_password(new_password)
    db.session.commit()

    log_audit('password_reset', target=f'User {user.username}',
              details='Password reset by admin')
    return jsonify({'success': True, 'message': f'Password reset for {user.username}.'})


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    """Delete a user."""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found.'})

    if user.id == current_user.id:
        return jsonify({'success': False, 'error': 'Cannot delete yourself.'})

    username = user.username
    db.session.delete(user)
    db.session.commit()

    log_audit('user_delete', target=f'User {username}')
    return jsonify({'success': True, 'message': f'User {username} deleted.'})


@admin_bp.route('/audit')
@admin_required
def audit_log():
    """Audit log page."""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    action_filter = request.args.get('action', '')

    query = AuditLog.query.order_by(AuditLog.timestamp.desc())
    if action_filter:
        query = query.filter(AuditLog.action == action_filter)

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    logs = pagination.items

    # Get unique actions for filter dropdown
    actions = db.session.query(AuditLog.action).distinct().all()
    actions = sorted([a[0] for a in actions])

    return render_template('admin_audit.html',
                           logs=logs,
                           pagination=pagination,
                           actions=actions,
                           current_action=action_filter,
                           active_page='admin')
