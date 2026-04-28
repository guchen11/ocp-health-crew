"""Shared route decorators and audit helper.

Provides role-checking decorators and a unified audit logger so that
app.routes, app.admin, and app.auth share a single implementation of each.
"""

from functools import wraps

from flask import request
from flask_login import login_required, current_user


def operator_required(f):
    """Require the current user to have operator or admin role."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_operator:
            return "Access denied. Operator role required.", 403
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Require the current user to have the admin role."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            return "Access denied. Admin role required.", 403
        return f(*args, **kwargs)
    return decorated


def log_audit(action, target=None, details=None, user_id=None, username=None):
    """Record an audit log entry.

    Accepts optional *user_id* / *username* for contexts where there is no
    authenticated session (e.g. scheduler).  Falls back to ``current_user``
    when available.  Never raises -- audit must not break application flow.
    """
    from app.models import db, AuditLog
    try:
        if user_id is None and current_user and current_user.is_authenticated:
            user_id = current_user.id
            username = current_user.username
        entry = AuditLog(
            user_id=user_id,
            username=username or 'system',
            action=action,
            target=target,
            details=details,
            ip_address=getattr(request, 'remote_addr', None),
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        pass
