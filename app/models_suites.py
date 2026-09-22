"""Test suite models.

Separated from app/models.py to respect the 500-line file limit (REQ-3).
"""

from datetime import datetime, timezone

from app.models import db

MAX_SUITE_ITEMS = 50


class TestSuite(db.Model):
    """A saved collection of test templates to run sequentially."""

    __tablename__ = 'test_suites'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    icon = db.Column(db.String(10), default='📦')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    shared = db.Column(db.Boolean, default=False)
    stop_on_failure = db.Column(db.Boolean, default=True)
    server_host = db.Column(db.String(200), default='')
    items = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    owner = db.relationship('User', backref='test_suites')
    runs = db.relationship('SuiteRun', backref='suite', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description or '',
            'icon': self.icon or '📦',
            'shared': self.shared,
            'stop_on_failure': self.stop_on_failure,
            'server_host': self.server_host or '',
            'items': self.items or [],
            'item_count': len(self.items or []),
            'created_by': self.owner.username if self.owner else 'unknown',
            'created_by_id': self.created_by,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else '',
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M') if self.updated_at else '',
        }

    def __repr__(self):
        return f'<TestSuite {self.name} ({len(self.items or [])} items)>'


class SuiteRun(db.Model):
    """A single execution of a test suite."""

    __tablename__ = 'suite_runs'

    id = db.Column(db.Integer, primary_key=True)
    suite_id = db.Column(db.Integer, db.ForeignKey('test_suites.id'), nullable=True)
    name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    stop_on_failure = db.Column(db.Boolean, default=True)
    items = db.Column(db.JSON, nullable=False, default=list)
    total_items = db.Column(db.Integer, default=0)
    completed_items = db.Column(db.Integer, default=0)
    current_item_index = db.Column(db.Integer, default=-1)
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = db.Column(db.DateTime, nullable=True)

    owner = db.relationship('User', backref='suite_runs',
                            foreign_keys=[created_by])

    def to_dict(self):
        return {
            'id': self.id,
            'suite_id': self.suite_id,
            'name': self.name,
            'status': self.status,
            'stop_on_failure': self.stop_on_failure,
            'items': self.items or [],
            'total_items': self.total_items,
            'completed_items': self.completed_items,
            'current_item_index': self.current_item_index,
            'created_by': self.owner.username if self.owner else 'unknown',
            'created_by_id': self.created_by,
            'started_at': self.started_at.strftime('%Y-%m-%d %H:%M') if self.started_at else '',
            'finished_at': self.finished_at.strftime('%Y-%m-%d %H:%M') if self.finished_at else '',
        }

    def __repr__(self):
        return f'<SuiteRun {self.name} ({self.status})>'
