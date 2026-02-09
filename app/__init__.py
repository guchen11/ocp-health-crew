"""
CNV Health Dashboard - Flask Application Factory
"""

from flask import Flask
import os


def create_app(config_object=None):
    """Application factory for creating Flask app instances."""
    
    app = Flask(__name__,
                template_folder='templates',
                static_folder='static')
    
    # Load configuration
    if config_object:
        app.config.from_object(config_object)
    else:
        # Default configuration
        app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
        app.config['DEBUG'] = os.environ.get('FLASK_DEBUG', False)
    
    # Register blueprints
    from app.routes import dashboard_bp
    app.register_blueprint(dashboard_bp)
    
    # Start background scheduler (only in main process to avoid duplicate schedulers in reloader)
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        from app.scheduler import start_scheduler
        start_scheduler(app)
    
    return app
