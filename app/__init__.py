"""
CNV Health Dashboard - Flask Application Factory
"""

from flask import Flask
from flask_login import LoginManager
import os

from app.models import db, bcrypt


login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access the dashboard.'
login_manager.login_message_category = 'info'


@login_manager.user_loader
def load_user(user_id):
    from app.models import User
    return db.session.get(User, int(user_id))


BUILTIN_TEMPLATES = [
    {
        'name': 'Create 10K VMs',
        'description': 'Per-Host Density: 10,000 VMs in 1 namespace, create-only, multi-node, 48h timeout.',
        'icon': '🚀',
        'config': {
            'task_type': 'cnv_scenarios',
            'scenario_mode': 'full',
            'scenario_tests': ['per-host-density'],
            'scenario_parallel': False,
            'kb_timeout': '48h',
            'kb_log_level': '',
            'email': True,
            'env_vars': {
                'per_host_density.vmsPerNamespace': '10000',
                'per_host_density.namespaceCount': '1',
                'per_host_density.scaleMode': 'multi-node',
                'per_host_density.targetNode': '',
                'per_host_density.cleanup': 'false',
                'per_host_density.percentage_of_vms_to_validate': '0',
                'per_host_density.max_ssh_retries': '240',
                'per_host_density.vmMemory': '256Mi',
                'per_host_density.vmCpuCores': '100',
                'per_host_density.vmCpuRequest': '100m',
                'per_host_density.vmCpuLimit': '1000m',
                'per_host_density.sourceStorageSize': '256',
                'per_host_density.vmStorageSize': '256',
                'per_host_density.imageUrl': '',
                'per_host_density.shutdownBatchSize': '50',
                'per_host_density.sleepBetweenPhases': '2m',
                'per_host_density.skipVmShutdown': 'true',
                'per_host_density.skipVmRestart': 'true',
                'per_host_density.qpsCreate': '20',
                'per_host_density.burstCreate': '40',
                'per_host_density.qpsShutdown': '10',
                'per_host_density.burstShutdown': '20',
                'per_host_density.qpsStartup': '30',
                'per_host_density.burstStartup': '60',
                'maxWaitTimeout': '48h',
                'jobPause': '2m',
                'cleanup': 'false',
            },
        },
    },
]


def _seed_builtin_templates():
    """Create built-in shared templates if they don't exist yet."""
    from app.models import Template, User
    admin = User.query.filter_by(role='admin').first()
    if not admin:
        return
    for bt in BUILTIN_TEMPLATES:
        exists = Template.query.filter_by(name=bt['name'], shared=True).first()
        if not exists:
            t = Template(
                name=bt['name'],
                description=bt['description'],
                icon=bt['icon'],
                created_by=admin.id,
                shared=True,
                config=bt['config'],
            )
            db.session.add(t)
    db.session.commit()


def create_app(config_object=None):
    """Application factory for creating Flask app instances."""
    
    app = Flask(__name__,
                template_folder='templates',
                static_folder='static')
    
    # Load configuration
    if config_object:
        app.config.from_object(config_object)
    else:
        from config.settings import Config
        app.config['SECRET_KEY'] = Config.SECRET_KEY
        app.config['DEBUG'] = os.environ.get('FLASK_DEBUG', False)
        app.config['SQLALCHEMY_DATABASE_URI'] = Config.SQLALCHEMY_DATABASE_URI
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = Config.SQLALCHEMY_TRACK_MODIFICATIONS
        app.config['OPEN_REGISTRATION'] = Config.OPEN_REGISTRATION
    
    # Initialize extensions
    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    
    # Create database tables
    with app.app_context():
        from app.models import User, Build, Schedule, Host, AuditLog, CustomCheck, Template  # noqa: F811
        db.create_all()

        # Seed built-in shared templates (idempotent)
        _seed_builtin_templates()
    
    # Register blueprints
    from app.routes import dashboard_bp
    app.register_blueprint(dashboard_bp)
    
    from app.auth import auth_bp
    app.register_blueprint(auth_bp)
    
    from app.admin import admin_bp
    app.register_blueprint(admin_bp)
    
    # Start background scheduler (only in main process to avoid duplicate schedulers in reloader)
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        from app.scheduler import start_scheduler
        start_scheduler(app)
    
    return app
