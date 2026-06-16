"""Upgrade executor - applies upgrades and triggers post-upgrade tests."""
import logging
import threading
import time
from datetime import datetime, timezone

from config.settings import Config

log = logging.getLogger(__name__)


def recover_stale_upgrade_runs(app):
    """Mark UpgradeRuns stuck in active state as aborted on startup.

    Only recovers runs older than 30 minutes to avoid killing runs that
    are legitimately still in progress from a concurrent process.
    """
    with app.app_context():
        from app.models import UpgradeRun, db
        cutoff = datetime.now(timezone.utc) - __import__('datetime').timedelta(minutes=30)
        stale = UpgradeRun.query.filter(
            UpgradeRun.status.in_(['pending', 'upgrading', 'waiting', 'testing']),
            UpgradeRun.created_at < cutoff,
        ).all()
        for r in stale:
            log.warning("Recovering stale UpgradeRun %s (%s)", r.id, r.operator_name)
            r.status = 'aborted'
            r.upgrade_finished_at = datetime.now(timezone.utc)
            r.append_log("Recovered from stale state on restart", level='warn')
        if stale:
            db.session.commit()
            log.info("Recovered %d stale upgrade run(s)", len(stale))


def execute_pipeline(upgrade_run_id, app):
    """Spawn a background thread to execute a full pipeline of steps."""
    thread = threading.Thread(
        target=_run_pipeline, args=(upgrade_run_id, app), daemon=True
    )
    thread.start()


def _run_pipeline(upgrade_run_id, app):
    """Execute all enabled steps in a policy pipeline."""
    with app.app_context():
        from app.models import UpgradeRun, db
        from app.routes.upgrade_actions import (
            build_upgrade_tag, _run_single_action
        )
        from sqlalchemy.orm.attributes import flag_modified

        run = UpgradeRun.query.get(upgrade_run_id)
        if not run or not run.policy:
            return

        run.status = 'upgrading'
        run.upgrade_started_at = datetime.now(timezone.utc)
        run.report_data = {'steps': [], 'upgrades': []}
        db.session.commit()

        steps = run.policy.steps or []
        enabled = [s for s in steps if s.get('enabled', True)]
        skipped = len(steps) - len(enabled)
        tag = build_upgrade_tag(run)

        run.append_log(f"UPGRADE PIPELINE: {run.policy.name}", level='divider')
        run.append_log(f"Steps: {len(enabled)} enabled, {skipped} disabled")
        for i, s in enumerate(enabled):
            run.append_log(f"  {i+1}. {s.get('label', s['type'])}")
        run.test_status = 'running'
        db.session.commit()

        all_ok = True
        for idx, step in enumerate(enabled):
            step_label = f"Step {idx + 1}/{len(enabled)}"
            stype = step.get('type', '')
            label = step.get('label', stype)
            step_start = time.time()

            run.append_log(f"{label}", level='phase')
            db.session.commit()

            step_data = {
                'index': idx + 1,
                'type': stype,
                'label': label,
                'status': 'running',
                'started_at': datetime.now(timezone.utc).strftime('%H:%M:%S'),
            }

            try:
                result = _run_single_action(run, step, tag, app, step_label)
                step_dur = int(time.time() - step_start)
                step_data['duration_s'] = step_dur
                step_data['duration'] = f"{step_dur // 60}m {step_dur % 60}s"

                no_upgrade = (result == 'skipped')
                ok = bool(result) and result != 'skipped'

                if no_upgrade:
                    step_data['status'] = 'skipped'
                    run.append_log(f"{step_label}: {label} - no upgrades available", level='skip')
                elif ok:
                    step_data['status'] = 'success'
                    run.append_log(f"{step_label}: {label} - done ({step_data['duration']})", level='ok')
                else:
                    all_ok = False
                    step_data['status'] = 'failed'
                    run.append_log(f"{step_label}: {label} - FAILED", level='fail')
                    run.append_log("Pipeline stopped on failure", level='fail')
                db.session.commit()

                rd = dict(run.report_data or {})
                rd.setdefault('steps', []).append(step_data)
                if stype in ('upgrade_olm', 'upgrade_cvo'):
                    upgrade_info = {
                        'operator': run.operator_name,
                        'from_version': run.from_version or '',
                        'to_version': run.to_version or '',
                        'type': stype,
                        'status': step_data['status'],
                        'duration': step_data.get('duration', ''),
                    }
                    rd.setdefault('upgrades', []).append(upgrade_info)
                run.report_data = rd
                flag_modified(run, 'report_data')
                db.session.commit()

                if stype in ('upgrade_olm', 'upgrade_cvo'):
                    actual_upgrades = [u for u in rd.get('upgrades', []) if u.get('namespace')]
                    if actual_upgrades:
                        try:
                            _send_upgrade_step_email(run, step_data, tag, actual_upgrades[-1])
                            run.append_log("Upgrade notification email sent", level='ok')
                            db.session.commit()
                        except Exception as mail_exc:
                            run.append_log(f"Upgrade notification email failed: {mail_exc}", level='warn')
                            db.session.commit()
                            log.error("Upgrade step email failed: %s", mail_exc)

                        try:
                            build_num = _save_upgrade_as_build(
                                run, step_data, actual_upgrades[-1], tag
                            )
                            run.append_log(f"Upgrade build record saved: Build #{build_num}", level='ok')
                            db.session.commit()
                        except Exception as bld_exc:
                            log.error("Upgrade build record failed: %s", bld_exc)
                    else:
                        run.append_log("No upgrade performed, skipping notification email", level='skip')
                        db.session.commit()

                if no_upgrade:
                    run.append_log("No upgrades available, skipping remaining steps", level='skip')
                    db.session.commit()
                    break
                if not ok:
                    break
            except Exception as exc:
                all_ok = False
                step_data['status'] = 'error'
                step_data['error'] = str(exc)
                rd = dict(run.report_data or {})
                rd.setdefault('steps', []).append(step_data)
                run.report_data = rd
                flag_modified(run, 'report_data')
                run.append_log(f"{step_label}: {label} - ERROR: {exc}", level='fail')
                db.session.commit()
                log.error("Pipeline step %d failed: %s", idx, exc)
                break

        run.status = 'completed' if all_ok else 'failed'
        run.test_status = 'success' if all_ok else 'failed'
        run.upgrade_finished_at = datetime.now(timezone.utc)
        try:
            started = run.upgrade_started_at
            finished = run.upgrade_finished_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            if finished.tzinfo is None:
                finished = finished.replace(tzinfo=timezone.utc)
            duration = int((finished - started).total_seconds())
        except Exception:
            duration = 0
        mins, secs = divmod(duration, 60)
        duration_str = f"{mins}m {secs}s"

        rd = dict(run.report_data or {})
        rd['total_duration'] = duration_str
        rd['total_duration_s'] = duration
        rd['status'] = run.status
        rd['pipeline_name'] = run.policy.name if run.policy else run.operator_name
        run.report_data = rd

        run.append_log("PIPELINE RESULT", level='divider')
        if all_ok:
            run.append_log(f"All {len(enabled)} steps completed successfully ({duration_str})", level='ok')
        else:
            run.append_log(f"Failed at step {idx+1}/{len(enabled)} ({duration_str})", level='fail')
        db.session.commit()

        try:
            from app.routes.upgrade_report import generate_upgrade_report
            report_file = generate_upgrade_report(run)
            run.report_file = report_file
            run.append_log(f"Report saved: {report_file}", level='ok')
            db.session.commit()
        except Exception as exc:
            run.append_log(f"Report generation failed: {exc}", level='warn')
            db.session.commit()
            log.error("Report generation failed: %s", exc)

        try:
            _send_pipeline_email(run, enabled, all_ok, duration_str)
            run.append_log("Email report sent", level='ok')
            db.session.commit()
        except Exception as exc:
            run.append_log(f"Email send failed: {exc}", level='warn')
            db.session.commit()
            log.error("Pipeline email failed: %s", exc)


def _send_pipeline_email(run, steps, success, duration):
    """Delegate email sending to the report module."""
    from app.routes.upgrade_report import send_pipeline_email
    send_pipeline_email(run, steps, success, duration)


def _send_upgrade_step_email(run, step_data, tag, upgrade_info=None):
    """Send an email notification after an upgrade step completes."""
    from app.routes.upgrade_report import send_upgrade_step_email
    send_upgrade_step_email(run, step_data, tag, upgrade_info=upgrade_info)


def _save_upgrade_as_build(run, step_data, upgrade_info, tag):
    """Delegate to upgrade_report module."""
    from app.routes.upgrade_report import save_upgrade_as_build
    return save_upgrade_as_build(run, step_data, upgrade_info, tag)
