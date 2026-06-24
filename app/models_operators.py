"""Operator and Deployer models.

Separated from app/models.py to respect the 500-line file limit (REQ-3).
Models here support the OCP Deployer and Operator Management frontend.
"""

from datetime import datetime, timezone

from app.models import db


class OperatorInstall(db.Model):
    """Tracks an operator install or removal action."""

    __tablename__ = 'operator_installs'

    id = db.Column(db.Integer, primary_key=True)
    operator_key = db.Column(db.String(80), nullable=False, index=True)
    display_name = db.Column(db.String(200), nullable=False)
    namespace = db.Column(db.String(200), nullable=False)
    version = db.Column(db.String(100), default='')
    status = db.Column(db.String(20), default='pending')
    log = db.Column(db.Text, default='')
    installed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = db.Column(db.DateTime, nullable=True)

    owner = db.relationship('User', backref='operator_installs',
                            foreign_keys=[installed_by])

    VALID_STATUSES = ('pending', 'installing', 'ready', 'removing',
                      'removed', 'failed')

    def append_log(self, msg, level='info'):
        ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
        prefix = {
            'phase': f'[{ts}] >>> ',
            'ok': f'[{ts}] OK  ',
            'fail': f'[{ts}] ERR ',
            'wait': f'[{ts}] ... ',
            'info': f'[{ts}]     ',
        }.get(level, f'[{ts}]     ')
        self.log = (self.log or '') + f'{prefix}{msg}\n'

    def to_dict(self):
        return {
            'id': self.id,
            'operator_key': self.operator_key,
            'display_name': self.display_name,
            'namespace': self.namespace,
            'version': self.version,
            'status': self.status,
            'log': self.log or '',
            'installed_by': self.owner.username if self.owner else 'system',
            'started_at': (self.started_at.strftime('%Y-%m-%d %H:%M')
                           if self.started_at else ''),
            'finished_at': (self.finished_at.strftime('%Y-%m-%d %H:%M')
                            if self.finished_at else ''),
        }

    def __repr__(self):
        return f'<OperatorInstall {self.display_name} ({self.status})>'


class DeployerConfig(db.Model):
    """A saved deployer YAML configuration."""

    __tablename__ = 'deployer_configs'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default='')
    config_yaml = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    owner = db.relationship('User', backref='deployer_configs',
                            foreign_keys=[created_by])

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description or '',
            'config_yaml': self.config_yaml,
            'created_by': self.owner.username if self.owner else 'unknown',
            'created_at': (self.created_at.strftime('%Y-%m-%d %H:%M')
                           if self.created_at else ''),
            'updated_at': (self.updated_at.strftime('%Y-%m-%d %H:%M')
                           if self.updated_at else ''),
        }


class DeployerRun(db.Model):
    """Tracks a deployer execution."""

    __tablename__ = 'deployer_runs'

    id = db.Column(db.Integer, primary_key=True)
    config_id = db.Column(db.Integer, db.ForeignKey('deployer_configs.id'),
                          nullable=True)
    config_name = db.Column(db.String(200), default='')
    phase = db.Column(db.String(50), default='post_deploy')
    status = db.Column(db.String(20), default='running')
    log = db.Column(db.Text, default='')
    triggered_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = db.Column(db.DateTime, nullable=True)

    owner = db.relationship('User', backref='deployer_runs',
                            foreign_keys=[triggered_by])

    def append_log(self, line):
        self.log = (self.log or '') + line + '\n'

    def to_dict(self):
        return {
            'id': self.id,
            'config_id': self.config_id,
            'config_name': self.config_name,
            'phase': self.phase,
            'status': self.status,
            'log': self.log or '',
            'triggered_by': self.owner.username if self.owner else 'system',
            'started_at': (self.started_at.strftime('%Y-%m-%d %H:%M')
                           if self.started_at else ''),
            'finished_at': (self.finished_at.strftime('%Y-%m-%d %H:%M')
                            if self.finished_at else ''),
        }
