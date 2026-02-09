"""
CNV Health Dashboard - Authentication Blueprint

Handles login, logout, registration, and profile management.
First registered user becomes admin automatically.
"""

from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from app.models import db, User, AuditLog

auth_bp = Blueprint('auth', __name__)


def log_audit(action, target=None, details=None):
    """Record an audit log entry."""
    entry = AuditLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        username=current_user.username if current_user.is_authenticated else 'anonymous',
        action=action,
        target=target,
        details=details,
        ip_address=request.remote_addr,
    )
    db.session.add(entry)
    db.session.commit()


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Login page."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.dashboard'))

    # Check if any users exist - if not, redirect to register (first-time setup)
    if User.query.count() == 0:
        return redirect(url_for('auth.register'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter(
            (User.username == username) | (User.email == username)
        ).first()

        if user and user.check_password(password):
            login_user(user, remember='remember' in request.form)
            user.last_login = datetime.now(timezone.utc)
            db.session.commit()
            log_audit('login', target=f'User {user.username}')

            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard.dashboard'))
        else:
            error = 'Invalid username or password.'

    return render_template('login.html', error=error)


@auth_bp.route('/logout')
@login_required
def logout():
    """Logout and redirect to login."""
    log_audit('logout', target=f'User {current_user.username}')
    logout_user()
    return redirect(url_for('auth.login'))


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """
    Registration page.
    - If no users exist, first user becomes admin (open registration).
    - Otherwise, only admins can create new users (via admin panel).
    """
    user_count = User.query.count()
    is_first_user = user_count == 0

    # If users already exist and nobody is logged in as admin, deny access
    if not is_first_user and (not current_user.is_authenticated or not current_user.is_admin):
        return redirect(url_for('auth.login'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Validation
        if not username or not email or not password:
            error = 'All fields are required.'
        elif len(username) < 3:
            error = 'Username must be at least 3 characters.'
        elif len(password) < 6:
            error = 'Password must be at least 6 characters.'
        elif password != confirm_password:
            error = 'Passwords do not match.'
        elif User.query.filter_by(username=username).first():
            error = 'Username already taken.'
        elif User.query.filter_by(email=email).first():
            error = 'Email already registered.'
        else:
            role = 'admin' if is_first_user else request.form.get('role', 'operator')
            user = User(username=username, email=email, role=role)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()

            if is_first_user:
                # Auto-login the first user
                login_user(user)
                user.last_login = datetime.now(timezone.utc)
                db.session.commit()
                log_audit('register', target=f'User {username}',
                          details='First user registration (auto-admin)')
                return redirect(url_for('dashboard.dashboard'))
            else:
                log_audit('user_create', target=f'User {username}',
                          details=f'Role: {role}')
                return redirect(url_for('admin.users'))

    return render_template('register.html',
                           is_first_user=is_first_user,
                           error=error)


@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """User profile - change password."""
    message = None
    error = None

    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not current_user.check_password(current_password):
            error = 'Current password is incorrect.'
        elif len(new_password) < 6:
            error = 'New password must be at least 6 characters.'
        elif new_password != confirm_password:
            error = 'New passwords do not match.'
        else:
            current_user.set_password(new_password)
            db.session.commit()
            log_audit('password_change', target=f'User {current_user.username}')
            message = 'Password updated successfully.'

    return render_template('profile.html', message=message, error=error,
                           active_page='profile')
