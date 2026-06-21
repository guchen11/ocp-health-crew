"""Live test: run upgrade pipeline with full health validation."""
import time
import logging
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

from app import create_app
from app.models import UpgradePolicy, UpgradeRun, db
from app.routes.upgrade_executor import execute_pipeline
from app.routes.upgrade_scanner import run_scan

app = create_app()
with app.app_context():
    print("Scanning for upgrades...")
    scan = run_scan()
    olm = scan.get("olm", [])
    print(f"Pending OLM upgrades: {len(olm)}")
    for op in olm[:5]:
        print(f"  {op['name']} ({op['namespace']}) -> {op['current_csv']}")

    if not olm:
        print("No pending upgrades to test")
        sys.exit(0)

    target = olm[0]
    tname = target["name"]
    tns = target["namespace"]
    print(f"\nUpgrading: {tname} in {tns}")

    policy = UpgradePolicy(
        name="Live Test", enabled=True, auto_approve=False,
        steps=[{
            "type": "upgrade_olm", "target": tname,
            "namespace": tns, "enabled": True,
            "label": "Upgrade " + tname,
        }],
        scan_interval_minutes=9999, created_by=1,
    )
    db.session.add(policy)
    db.session.commit()

    run = UpgradeRun(
        policy_id=policy.id, upgrade_type="pipeline",
        operator_name=tname,
        from_version=target.get("installed_csv", ""),
        to_version=target.get("current_csv", ""),
        status="pending", created_by=1,
    )
    run.append_log("Live test trigger")
    db.session.add(run)
    db.session.commit()
    print(f"Created run #{run.id}")

    execute_pipeline(run.id, app)
    print("Pipeline started, polling...\n")

    for i in range(180):
        time.sleep(5)
        fresh = UpgradeRun.query.get(run.id)
        lines = (fresh.log or "").strip().split("\n")
        last = lines[-1] if lines else ""
        elapsed = i * 5
        print(f"  [{elapsed:>4}s] {fresh.status}: {last[:120]}")
        if fresh.status in ("completed", "failed", "blocked"):
            print(f"\n{'='*60}")
            print(f"RESULT: {fresh.status}")
            print(f"{'='*60}")
            print(fresh.log)
            break
    else:
        print("\nTimed out (15 min)")
        fresh = UpgradeRun.query.get(run.id)
        print(fresh.log)
