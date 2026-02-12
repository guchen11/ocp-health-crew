#!/usr/bin/env python3
"""
One-time migration script: Import existing .builds.json and schedules.json
into the new SQLite database.

Usage:
    python scripts/migrate_json_to_db.py
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.models import db, Build
from config.settings import Config


def migrate():
    app = create_app()

    with app.app_context():
        # ── Migrate builds ────────────────────────────────────────────
        builds_file = Config.BUILDS_FILE
        if os.path.exists(builds_file):
            print(f"Found builds file: {builds_file}")
            with open(builds_file, 'r') as f:
                builds = json.load(f)

            imported = 0
            skipped = 0
            for b in builds:
                build_num = b.get('number')
                if not build_num:
                    skipped += 1
                    continue

                # Check if already imported
                existing = Build.query.filter_by(build_number=build_num).first()
                if existing:
                    skipped += 1
                    continue

                build = Build(
                    build_number=build_num,
                    name=b.get('name', ''),
                    triggered_by=None,  # No user mapping for legacy builds
                    status=b.get('status', 'unknown'),
                    status_text=b.get('status_text', ''),
                    checks=b.get('checks', []),
                    checks_count=b.get('checks_count', 0),
                    options=b.get('options', {}),
                    output=b.get('output', ''),
                    report_file=b.get('report_file'),
                    duration=b.get('duration', ''),
                    scheduled=b.get('options', {}).get('scheduled', False),
                )
                db.session.add(build)
                imported += 1

            db.session.commit()
            print(f"Builds: imported {imported}, skipped {skipped}")

            # Rename the old file as backup
            backup = builds_file + '.migrated'
            os.rename(builds_file, backup)
            print(f"Old builds file moved to {backup}")
        else:
            print("No builds file found, nothing to migrate.")

        # ── Schedules stay in JSON for now ────────────────────────────
        schedules_file = os.path.join(Config.BASE_DIR, "schedules.json")
        if os.path.exists(schedules_file):
            print(f"Schedules file exists at {schedules_file} (keeping as JSON)")
        else:
            print("No schedules file found.")

    print("\nMigration complete!")


if __name__ == '__main__':
    migrate()
