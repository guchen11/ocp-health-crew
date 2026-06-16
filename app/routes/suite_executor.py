"""Suite executor - runs suite items sequentially via start_build()."""
import logging
import threading
import time
from datetime import datetime, timezone

from app.routes import running_jobs, _jobs_lock

log = logging.getLogger(__name__)

_suite_runs_lock = threading.Lock()
_active_suite_runs = {}


def run_suite(suite_run_id, user_id):
    """Spawn a background thread to execute a suite run sequentially."""
    thread = threading.Thread(
        target=_execute_suite,
        args=(suite_run_id, user_id),
        daemon=True,
    )
    with _suite_runs_lock:
        _active_suite_runs[suite_run_id] = thread
    thread.start()


def is_suite_run_active(suite_run_id):
    with _suite_runs_lock:
        return suite_run_id in _active_suite_runs


def _wait_for_build(build_num, timeout_seconds=172800):
    """Poll until a build number leaves running_jobs and appears in DB."""
    start = time.time()
    while time.time() - start < timeout_seconds:
        with _jobs_lock:
            is_running = any(
                j.get('number') == build_num for j in running_jobs.values()
            )
        if not is_running:
            return _get_build_status(build_num)
        time.sleep(2)
    return 'timeout'


def _get_build_status(build_num, retries=5):
    """Read final build status from DB, with retries for commit lag."""
    from app.models import Build
    for _ in range(retries):
        build = Build.query.filter_by(build_number=build_num).first()
        if build:
            return build.status
        time.sleep(1)
    return 'unknown'


def _execute_suite(suite_run_id, user_id):
    """Iterate over suite items, calling start_build() for each."""
    from app import create_app
    from app.routes.build_executor import start_build

    app = create_app()
    with app.app_context():
        from app.models import SuiteRun, db

        suite_run = SuiteRun.query.get(suite_run_id)
        if not suite_run:
            log.error("SuiteRun %s not found", suite_run_id)
            return

        suite_run.status = 'running'
        suite_run.started_at = datetime.now(timezone.utc)
        db.session.commit()

        items = list(suite_run.items or [])
        stop_on_failure = suite_run.stop_on_failure

        for idx, item in enumerate(items):
            sr = SuiteRun.query.get(suite_run_id)
            if not sr or sr.status == 'aborted':
                break

            sr.current_item_index = idx
            items[idx]['item_status'] = 'running'
            sr.items = items
            db.session.commit()

            config = item.get('config', {})
            checks = config.get('scenario_tests', [])
            if not checks and config.get('task_type') != 'cnv_scenarios':
                checks = config.get('_checks', config.get('checks', []))

            options = dict(config)
            options.pop('_checks', None)
            options.pop('checks', None)

            try:
                build_num = start_build(checks, options, user_id=user_id)
            except Exception as exc:
                log.error("Suite item %d start_build failed: %s", idx, exc)
                items[idx]['item_status'] = 'failed'
                items[idx]['error'] = str(exc)
                sr.items = items
                sr.completed_items = (sr.completed_items or 0) + 1
                db.session.commit()
                if stop_on_failure:
                    break
                continue

            items[idx]['build_number'] = build_num
            sr.items = items
            db.session.commit()

            final_status = _wait_for_build(build_num)
            items[idx]['item_status'] = final_status
            sr.completed_items = (sr.completed_items or 0) + 1
            sr.items = items
            db.session.commit()

            if final_status in ('failed', 'timeout') and stop_on_failure:
                for remaining_idx in range(idx + 1, len(items)):
                    items[remaining_idx]['item_status'] = 'skipped'
                sr.items = items
                db.session.commit()
                break

        sr = SuiteRun.query.get(suite_run_id)
        if sr:
            if sr.status == 'aborted':
                pass
            elif any(i.get('item_status') == 'failed' for i in items):
                sr.status = 'failed'
            elif all(
                i.get('item_status') in ('success', 'unstable')
                for i in items
            ):
                sr.status = 'completed'
            else:
                sr.status = 'completed'
            sr.items = items
            sr.finished_at = datetime.now(timezone.utc)
            db.session.commit()

    with _suite_runs_lock:
        _active_suite_runs.pop(suite_run_id, None)


def recover_stale_runs(app):
    """Mark SuiteRuns stuck in 'running' as 'aborted' (SEC-005).

    Only recovers runs older than 30 minutes to avoid killing runs
    that are legitimately still in progress.
    """
    with app.app_context():
        from app.models import SuiteRun, db
        cutoff = datetime.now(timezone.utc) - __import__('datetime').timedelta(minutes=30)
        stale = SuiteRun.query.filter(
            SuiteRun.status == 'running',
            SuiteRun.started_at < cutoff,
        ).all()
        for sr in stale:
            log.warning("Recovering stale SuiteRun %s (%s)", sr.id, sr.name)
            sr.status = 'aborted'
            items = list(sr.items or [])
            for item in items:
                if item.get('item_status') == 'running':
                    item['item_status'] = 'aborted'
            sr.items = items
            sr.finished_at = datetime.now(timezone.utc)
        if stale:
            db.session.commit()
            log.info("Recovered %d stale suite run(s)", len(stale))
