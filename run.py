#!/usr/bin/env python3
"""
CNV HealthCrew AI - Main Entry Point

Run this script to start the web dashboard:
    python run.py

Or use the start_dashboard.sh script which also opens the browser.
"""

import os
import sys

# Ensure the app directory is in the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from config.settings import Config


def ensure_dirs():
    """Create data directories if they don't exist."""
    os.makedirs(Config.REPORTS_DIR, exist_ok=True)
    data_dir = getattr(Config, 'DATA_DIR', None)
    if data_dir:
        os.makedirs(os.path.join(data_dir, "logs"), exist_ok=True)


def main():
    """Main entry point for CNV HealthCrew AI."""
    ensure_dirs()
    app = create_app()
    
    print(f"""
╔════════════════════════════════════════════════════════════╗
║                  CNV HealthCrew AI                          ║
║                                                              ║
║  Running at: http://{Config.FLASK_HOST}:{Config.FLASK_PORT}
║  Build history: {Config.BUILDS_FILE}
║  Reports: {Config.REPORTS_DIR}
║                                                              ║
║  Press Ctrl+C to stop                                       ║
╚════════════════════════════════════════════════════════════╝
    """)
    
    app.run(
        host=Config.FLASK_HOST,
        port=Config.FLASK_PORT,
        debug=Config.FLASK_DEBUG
    )


if __name__ == '__main__':
    main()
