"""Upgrade scanner - periodically detects available CVO and OLM upgrades."""
import json
import logging
import threading
import time
from datetime import datetime, timezone

from config.settings import Config

log = logging.getLogger(__name__)

KUBECONFIG = Config.KUBECONFIG
_scanner_running = False
_scanner_thread = None
SCAN_LOOP_INTERVAL = 60
SCAN_SSH_TIMEOUT = 60
SCAN_SSH_TIMEOUT_LONG = 120
SCAN_SSH_TIMEOUT_SHORT = 15


def _get_ssh_client(server_host=None):
    """Create an SSH client to the configured jump host."""
    from app.ssh_utils import create_ssh_client
    username = None
    if server_host:
        try:
            from app.models import Host
            host_obj = Host.query.filter_by(host=server_host).first()
            if host_obj:
                username = host_obj.user
        except Exception:
            pass
    return create_ssh_client(host=server_host, username=username)


def _ssh_run(client, cmd, timeout=120):
    """Run a command via SSH with KUBECONFIG exported."""
    from app.ssh_utils import ssh_exec
    stdout, stderr = ssh_exec(client, cmd, kubeconfig=KUBECONFIG, timeout=timeout)
    return stdout


def scan_cvo(client):
    """Detect available CVO cluster version updates.

    Returns dict with current_version, available_updates list,
    upgrade_readiness conditions, and raw warnings.
    """
    result = {
        'current_version': '',
        'channel': '',
        'available_updates': [],
        'conditions': {},
        'warnings': [],
        'upgradeable': True,
    }

    cv_json = _ssh_run(client, "oc get clusterversion version -o json", timeout=SCAN_SSH_TIMEOUT)
    if not cv_json:
        return result

    try:
        cv = json.loads(cv_json)
    except (json.JSONDecodeError, ValueError):
        return result

    status = cv.get('status', {})
    spec = cv.get('spec', {})
    result['current_version'] = status.get('desired', {}).get('version', '')
    result['channel'] = spec.get('channel', '')

    for cond in status.get('conditions', []):
        ctype = cond.get('type', '')
        result['conditions'][ctype] = {
            'status': cond.get('status', ''),
            'message': cond.get('message', ''),
        }

    upgradeable_cond = result['conditions'].get('Upgradeable', {})
    if upgradeable_cond.get('status') == 'False':
        result['upgradeable'] = False
        result['warnings'].append(
            f"Upgradeable=False: {upgradeable_cond.get('message', 'unknown reason')}"
        )

    for ctype in ('Failing', 'Degraded'):
        cond = result['conditions'].get(ctype, {})
        if cond.get('status') == 'True':
            result['upgradeable'] = False
            result['warnings'].append(f"{ctype}=True: {cond.get('message', '')}")

    for upd in status.get('availableUpdates', []) or []:
        version = upd.get('version', '')
        if not version:
            continue
        result['available_updates'].append({
            'version': version,
            'image': upd.get('image', ''),
        })

    adm_output = _ssh_run(client, "oc adm upgrade 2>&1", timeout=SCAN_SSH_TIMEOUT)
    if adm_output:
        for line in adm_output.splitlines():
            lower = line.lower()
            if any(w in lower for w in ('cannot update', 'warning', 'degraded', 'error')):
                result['warnings'].append(line.strip())

    return result


def scan_olm(client):
    """Detect OLM operators with pending upgrades.

    Returns list of dicts with subscription name, namespace,
    installed CSV, current (desired) CSV, and pending InstallPlans.
    """
    results = []

    subs_json = _ssh_run(
        client, "oc get subscriptions.operators -A -o json", timeout=SCAN_SSH_TIMEOUT_LONG
    )
    if not subs_json:
        return results

    try:
        subs = json.loads(subs_json)
    except (json.JSONDecodeError, ValueError):
        return results

    for item in subs.get('items', []):
        meta = item.get('metadata', {})
        status = item.get('status', {})
        spec = item.get('spec', {})

        installed = status.get('installedCSV', '')
        current = status.get('currentCSV', '')

        has_pending = installed and current and installed != current
        pending_plans = []

        if has_pending:
            ns = meta.get('namespace', '')
            plans_json = _ssh_run(
                client,
                f"oc get installplan -n {ns} -o json 2>/dev/null",
                timeout=SCAN_SSH_TIMEOUT_SHORT,
            )
            if plans_json:
                try:
                    plans = json.loads(plans_json)
                    for plan in plans.get('items', []):
                        approved = plan.get('spec', {}).get('approved', True)
                        if not approved:
                            pending_plans.append({
                                'name': plan['metadata']['name'],
                                'namespace': ns,
                            })
                except (json.JSONDecodeError, ValueError, KeyError):
                    pass

        if has_pending or pending_plans:
            results.append({
                'name': meta.get('name', ''),
                'namespace': meta.get('namespace', ''),
                'package': spec.get('name', ''),
                'channel': spec.get('channel', ''),
                'installed_csv': installed,
                'current_csv': current,
                'pending_plans': pending_plans,
            })

    return results


def _resolve_host(server_host=None):
    """Resolve SSH host: explicit > env var > first DB host."""
    if server_host:
        return server_host
    import os
    env_host = os.getenv('RH_LAB_HOST')
    if env_host:
        return env_host
    try:
        from app.models import Host
        first = Host.query.first()
        if first:
            return first.host
    except Exception:
        pass
    return None


def run_scan(server_host=None):
    """Run a one-time scan for both CVO and OLM upgrades."""
    host = _resolve_host(server_host)
    if not host:
        return {'cvo': {}, 'olm': [], 'error': 'No SSH host configured'}
    try:
        client = _get_ssh_client(host)
    except Exception as exc:
        log.error("Upgrade scan SSH connect failed: %s", exc)
        return {'cvo': {}, 'olm': [], 'error': str(exc)}

    try:
        cvo = scan_cvo(client)
        olm = scan_olm(client)
        return {'cvo': cvo, 'olm': olm}
    finally:
        client.close()


def _scanner_loop(app):
    """Background loop that checks policies and triggers upgrades."""
    global _scanner_running
    log.info("[UpgradeScanner] Started")

    while _scanner_running:
        try:
            with app.app_context():
                _check_policies(app)
        except Exception as exc:
            log.error("[UpgradeScanner] Error: %s", exc)

        time.sleep(SCAN_LOOP_INTERVAL)

    log.info("[UpgradeScanner] Stopped")


_DAY_MAP = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6}


def _is_schedule_due(policy, now):
    """Return True if a time-of-day scheduled policy should fire now.

    Matches when current UTC time is within 2 minutes after schedule_time
    on the configured days (or any day if schedule_days is empty).
    Uses last_scanned_at to prevent duplicate triggers on the same window.
    """
    try:
        sched_hour, sched_min = int(policy.schedule_time[:2]), int(policy.schedule_time[3:])
    except (ValueError, TypeError):
        return False

    if policy.schedule_days:
        target_days = {_DAY_MAP[d] for d in policy.schedule_days if d in _DAY_MAP}
        if target_days and now.weekday() not in target_days:
            return False

    current_minutes = now.hour * 60 + now.minute
    target_minutes = sched_hour * 60 + sched_min
    diff = current_minutes - target_minutes
    if diff < 0 or diff > 2:
        return False

    if policy.last_scanned_at:
        last = policy.last_scanned_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last.date() == now.date() and (last.hour * 60 + last.minute) >= target_minutes:
            return False

    return True


def _is_interval_due(policy, now):
    """Return True if an interval-based policy should fire now."""
    if not policy.last_scanned_at:
        return True
    last = policy.last_scanned_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    elapsed = (now - last).total_seconds() / 60
    return elapsed >= policy.scan_interval_minutes


def _is_dates_due(policy, now):
    """Return True if a specific-dates policy should fire now.

    Checks schedule_dates list for any entry whose date+time is within
    a 2-minute window of the current UTC time.
    """
    if not policy.schedule_dates:
        return False
    for dt_str in policy.schedule_dates:
        try:
            parts = dt_str.split('T')
            date_part = parts[0]
            time_part = parts[1] if len(parts) > 1 else '03:00'
            y, m, d = int(date_part[:4]), int(date_part[5:7]), int(date_part[8:10])
            hh, mm = int(time_part[:2]), int(time_part[3:5])
            target = datetime(y, m, d, hh, mm, tzinfo=timezone.utc)
        except (ValueError, IndexError):
            continue
        diff_seconds = (now - target).total_seconds()
        if 0 <= diff_seconds <= 120:
            if policy.last_scanned_at:
                last = policy.last_scanned_at
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if last >= target:
                    continue
            return True
    return False


def _check_policies(app):
    """Check all enabled auto-approve policies and trigger pipelines if due.

    Only policies with enabled=True AND auto_approve=True are considered.
    Uses schedule_mode to determine trigger logic:
      - 'daily': triggers at schedule_time on schedule_days
      - 'dates': triggers at specific schedule_dates entries
      - 'interval' (default): triggers every scan_interval_minutes
    """
    from app.models import UpgradePolicy, UpgradeRun, db

    now = datetime.now(timezone.utc)
    policies = UpgradePolicy.query.filter_by(enabled=True, auto_approve=True).all()

    for policy in policies:
        mode = getattr(policy, 'schedule_mode', None) or 'interval'
        if mode == 'daily':
            if not _is_schedule_due(policy, now):
                continue
        elif mode == 'dates':
            if not _is_dates_due(policy, now):
                continue
        else:
            if policy.schedule_time:
                if not _is_schedule_due(policy, now):
                    continue
            else:
                if not _is_interval_due(policy, now):
                    continue

        enabled_steps = [s for s in (policy.steps or []) if s.get('enabled', True)]
        if not enabled_steps:
            continue

        active_run = UpgradeRun.query.filter(
            UpgradeRun.policy_id == policy.id,
            UpgradeRun.status.in_(['pending', 'upgrading', 'waiting', 'testing']),
        ).first()
        if active_run:
            log.info(
                "[UpgradeScanner] Policy '%s' skipped - run #%s still %s",
                policy.name, active_run.id, active_run.status,
            )
            continue

        policy.last_scanned_at = now
        db.session.commit()

        trigger_desc = policy.schedule_time or f'{policy.scan_interval_minutes}m interval'
        log.info(
            "[UpgradeScanner] Auto-triggering policy '%s' (%d steps, schedule=%s)",
            policy.name, len(enabled_steps), trigger_desc,
        )
        _trigger_pipeline(policy, app)


def _trigger_pipeline(policy, app):
    """Create an UpgradeRun and launch the pipeline executor."""
    from app.models import UpgradeRun, db
    from app.routes.upgrade_executor import execute_pipeline

    run = UpgradeRun(
        policy_id=policy.id,
        upgrade_type='pipeline',
        operator_name=policy.name,
        status='pending',
        created_by=policy.created_by,
    )
    run.append_log(f"Auto-triggered by policy '{policy.name}'")
    db.session.add(run)
    db.session.commit()

    execute_pipeline(run.id, app)


def start_upgrade_scanner(app):
    """Start the background upgrade scanner thread."""
    global _scanner_running, _scanner_thread
    if _scanner_running:
        return
    _scanner_running = True
    _scanner_thread = threading.Thread(
        target=_scanner_loop, args=(app,), daemon=True
    )
    _scanner_thread.start()


def stop_upgrade_scanner():
    global _scanner_running
    _scanner_running = False
