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

_startup_recovery_done = False


@login_manager.user_loader
def load_user(user_id):
    from app.models import User
    return db.session.get(User, int(user_id))


from config.builtin_templates import BUILTIN_TEMPLATES  # noqa: F401


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


BUILTIN_DEPLOYER_CONFIGS = [
    {
        'name': 'Enable HyperShift in MCE',
        'description': 'Patches MCE to enable HyperShift component and waits for operator pod',
        'file': 'deployer-configs/hcp-enable-hypershift.yaml',
    },
    {
        'name': 'Install hcp CLI',
        'description': 'Extracts hcp CLI from hypershift operator pod to /usr/local/bin',
        'file': 'deployer-configs/hcp-install-cli.yaml',
    },
    {
        'name': 'HCP Sanity - Create Cluster (5 VMs)',
        'description': 'Create 1 hosted cluster with 5 kubevirt workers, validate VMs running',
        'file': 'deployer-configs/hcp-sanity-create.yaml',
    },
]


def _seed_deployer_configs():
    """Create built-in deployer configs if they don't exist yet."""
    from app.models import User
    from app.models_operators import DeployerConfig
    admin = User.query.filter_by(role='admin').first()
    if not admin:
        return
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for bc in BUILTIN_DEPLOYER_CONFIGS:
        exists = DeployerConfig.query.filter_by(name=bc['name']).first()
        if exists:
            continue
        yaml_path = os.path.join(base_dir, bc['file'])
        if not os.path.exists(yaml_path):
            continue
        with open(yaml_path, 'r') as f:
            yaml_content = f.read()
        cfg = DeployerConfig(
            name=bc['name'],
            description=bc['description'],
            config_yaml=yaml_content,
            created_by=admin.id,
        )
        db.session.add(cfg)
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
        from app.models import User, Build, Schedule, Host, AuditLog, CustomCheck, Template, TestSuite, SuiteRun, UpgradePolicy, UpgradeRun  # noqa: F811
        from app.models_operators import OperatorInstall, DeployerConfig, DeployerRun  # noqa: F401
        db.create_all()

        # Seed built-in shared templates (idempotent)
        _seed_builtin_templates()

        # Seed built-in deployer configs (idempotent)
        _seed_deployer_configs()

        global _startup_recovery_done
        if not _startup_recovery_done:
            _startup_recovery_done = True

            from app.routes.suite_executor import recover_stale_runs
            recover_stale_runs(app)

            from app.routes.upgrade_executor import recover_stale_upgrade_runs
            recover_stale_upgrade_runs(app)
    
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

        if not os.environ.get('SKIP_UPGRADE_SCANNER'):
            from app.routes.upgrade_scanner import start_upgrade_scanner
            start_upgrade_scanner(app)
    
    return app
