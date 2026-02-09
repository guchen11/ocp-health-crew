"""
CNV Health Dashboard - Database Models

SQLAlchemy models for multi-user support:
  - User: authentication, roles, profiles
  - Build: health check build records (replaces .builds.json)
  - Schedule: scheduled tasks (replaces schedules.json)
  - AuditLog: audit trail for team accountability
"""

from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from flask_bcrypt import Bcrypt

db = SQLAlchemy()
bcrypt = Bcrypt()


class User(UserMixin, db.Model):
    """User model for authentication and role-based access."""

    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='operator')  # admin, operator, viewer
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_login = db.Column(db.DateTime, nullable=True)

    # Relationships
    builds = db.relationship('Build', backref='triggered_by_user', lazy='dynamic',
                             foreign_keys='Build.triggered_by')
    schedules = db.relationship('Schedule', backref='created_by_user', lazy='dynamic',
                                foreign_keys='Schedule.created_by')

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_operator(self):
        return self.role in ('admin', 'operator')

    @property
    def is_viewer(self):
        return self.role in ('admin', 'operator', 'viewer')

    @property
    def role_display(self):
        return self.role.capitalize()

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'


class Build(db.Model):
    """Build record model - replaces .builds.json storage."""

    __tablename__ = 'builds'

    id = db.Column(db.Integer, primary_key=True)
    build_number = db.Column(db.Integer, unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), default='')
    triggered_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    status = db.Column(db.String(20), default='running')  # running, success, unstable, failed
    status_text = db.Column(db.String(50), default='Running')
    checks = db.Column(db.JSON, default=list)
    checks_count = db.Column(db.Integer, default=0)
    options = db.Column(db.JSON, default=dict)
    output = db.Column(db.Text, default='')
    report_file = db.Column(db.String(200), nullable=True)
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = db.Column(db.DateTime, nullable=True)
    duration = db.Column(db.String(20), default='')
    scheduled = db.Column(db.Boolean, default=False)

    def to_dict(self):
        """Convert to dictionary (for backward compatibility with templates)."""
        return {
            'number': self.build_number,
            'name': self.name or '',
            'status': self.status,
            'status_text': self.status_text,
            'checks': self.checks or [],
            'checks_count': self.checks_count,
            'options': self.options or {},
            'output': self.output or '',
            'report_file': self.report_file,
            'timestamp': self.started_at.strftime('%Y-%m-%d %H:%M') if self.started_at else '',
            'duration': self.duration or '',
            'triggered_by': self.triggered_by_user.username if self.triggered_by_user else 'system',
            'scheduled': self.scheduled,
        }

    def __repr__(self):
        return f'<Build #{self.build_number} ({self.status})>'


class Schedule(db.Model):
    """Schedule model - replaces schedules.json storage."""

    __tablename__ = 'schedules'

    id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.String(8), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), default='Unnamed Schedule')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    schedule_type = db.Column(db.String(20), default='recurring')  # once, recurring
    frequency = db.Column(db.String(20), default='daily')  # hourly, daily, weekly, monthly, custom
    time_of_day = db.Column(db.String(5), default='06:00')
    scheduled_time = db.Column(db.String(20), nullable=True)  # for 'once' type
    days = db.Column(db.JSON, nullable=True)  # for weekly
    day_of_month = db.Column(db.Integer, nullable=True)  # for monthly
    cron = db.Column(db.String(50), nullable=True)  # for custom
    checks = db.Column(db.JSON, default=list)
    checks_count = db.Column(db.Integer, default=0)
    options = db.Column(db.JSON, default=dict)
    status = db.Column(db.String(20), default='active')  # active, paused, completed
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_run = db.Column(db.String(20), nullable=True)

    def to_dict(self):
        """Convert to dictionary (for backward compatibility with templates)."""
        d = {
            'id': self.schedule_id,
            'name': self.name,
            'type': self.schedule_type,
            'frequency': self.frequency,
            'time': self.time_of_day,
            'checks': self.checks or [],
            'checks_count': self.checks_count,
            'options': self.options or {},
            'status': self.status,
            'created': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else '',
            'last_run': self.last_run,
            'created_by': self.created_by_user.username if self.created_by_user else 'system',
        }
        if self.schedule_type == 'once':
            d['scheduled_time'] = self.scheduled_time or ''
        if self.frequency == 'weekly':
            d['days'] = self.days or ['mon']
        if self.frequency == 'monthly':
            d['day_of_month'] = self.day_of_month or 1
        if self.frequency == 'custom':
            d['cron'] = self.cron or '0 6 * * *'
        return d

    def __repr__(self):
        return f'<Schedule {self.name} ({self.status})>'


class AuditLog(db.Model):
    """Audit log for tracking user actions."""

    __tablename__ = 'audit_log'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    username = db.Column(db.String(80), default='system')
    action = db.Column(db.String(50), nullable=False)  # login, logout, build_start, build_stop, etc.
    target = db.Column(db.String(200), nullable=True)  # e.g., "Build #5", "User john"
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    user = db.relationship('User', backref='audit_logs')

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'action': self.action,
            'target': self.target or '',
            'details': self.details or '',
            'ip_address': self.ip_address or '',
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M:%S') if self.timestamp else '',
        }

    def __repr__(self):
        return f'<AuditLog {self.username}: {self.action}>'
