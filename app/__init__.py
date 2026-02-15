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
        from app.models import User, Build, Schedule, Host, AuditLog, CustomCheck  # noqa: F811
        db.create_all()
    
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
