"""Trigger the upgrade pipeline policy and monitor progress."""
import os
import sys
import time
import logging
import functools

logging.basicConfig(level=logging.INFO, format='%(message)s')
print = functools.partial(print, flush=True)

os.environ['SKIP_UPGRADE_SCANNER'] = '1'

from app import create_app
from app.models import UpgradePolicy, UpgradeRun, db
from app.routes.upgrade_executor import execute_pipeline

app = create_app()
with app.app_context():
    policy = UpgradePolicy.query.first()
    if not policy:
        print("No policies found")
        sys.exit(1)

    steps = policy.steps or []
    enabled = [s for s in steps if s.get('enabled', True)]
    print(f"Policy: {policy.name} ({len(enabled)} enabled steps)")
    for i, s in enumerate(enabled):
        label = s.get('label', s['type'])
        print(f"  {i+1}. {label}")

    run = UpgradeRun(
        policy_id=policy.id,
        upgrade_type='pipeline',
        operator_name=policy.name,
        status='pending',
        created_by=policy.created_by,
    )
    run.append_log("Console test trigger")
    db.session.add(run)
    db.session.commit()
    print(f"\nCreated run #{run.id}")

    execute_pipeline(run.id, app)
    print("Pipeline started, monitoring...\n")

    for i in range(360):
        time.sleep(5)
        db.session.expire_all()
        fresh = UpgradeRun.query.get(run.id)
        lines = (fresh.log or '').strip().split('\n')
        last = lines[-1] if lines else ''
        elapsed = i * 5
        print(f"[{elapsed:>5}s] {fresh.status}: {last[:140]}")

        if fresh.status in ('completed', 'failed', 'blocked'):
            print(f"\n{'='*60}")
            print(f"RESULT: {fresh.status} (test: {fresh.test_status})")
            print(f"Report: {fresh.report_file or 'none'}")
            print(f"{'='*60}")
            print("\nFull log:")
            print(fresh.log)
            break
    else:
        print("\nTimed out (30 min)")
        fresh = UpgradeRun.query.get(run.id)
        print(fresh.log)
