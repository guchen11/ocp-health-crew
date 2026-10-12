#!/usr/bin/env python3
"""
CNV HealthCrew AI - Main Entry Point

Run this script to start the web dashboard:
    python run.py

Or use the scripts/start_dashboard.sh script which also opens the browser.
"""

import os
import socket
import sys

# Ensure the app directory is in the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from config.settings import Config


def ensure_dirs():
    """Create data directories if they don't exist."""
    os.makedirs(Config.REPORTS_DIR, exist_ok=True)
    os.makedirs(Config.PERF_REPORTS_DIR, exist_ok=True)
    data_dir = getattr(Config, 'DATA_DIR', None)
    if data_dir:
        os.makedirs(os.path.join(data_dir, "logs"), exist_ok=True)


def _port_is_free(host, port):
    """Return True if we can bind host:port (no other listener)."""
    bind_host = host if host not in ('0.0.0.0', '::', '') else '0.0.0.0'
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((bind_host, int(port)))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _recover_orphans_if_primary(app):
    """Abort DB rows left running only when this process will own the port.

    A duplicate systemd unit crash-looping on Address-already-in-use must not
    mark live suite/upgrade runs as aborted (root cause of suite #68/#69).
    """
    if not _port_is_free(Config.FLASK_HOST, Config.FLASK_PORT):
        print(
            f"Port {Config.FLASK_PORT} already in use; "
            "skipping stale-run recovery (not primary instance).",
            file=sys.stderr,
            flush=True,
        )
        return
    with app.app_context():
        from app.routes.suite_executor import recover_stale_runs
        from app.routes.upgrade_executor import recover_stale_upgrade_runs
        recover_stale_runs(app)
        recover_stale_upgrade_runs(app)


def main():
    """Main entry point for CNV HealthCrew AI."""
    ensure_dirs()
    app = create_app()
    _recover_orphans_if_primary(app)

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
