"""CNV Health Dashboard - Flask Routes package.

Multi-user with concurrent builds, role-based access, and audit logging.
"""

import os
import sys
import json
import threading
from datetime import datetime

from flask import Blueprint

from app.models import Host

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import Config, AVAILABLE_CHECKS, CNV_SCENARIOS

dashboard_bp = Blueprint('dashboard', __name__)

BASE_DIR = Config.BASE_DIR
REPORTS_DIR = Config.REPORTS_DIR
SCRIPT_PATH = os.path.join(BASE_DIR, "healthchecks", "hybrid_health_check.py")
CNV_SCRIPT_PATH = os.path.join(BASE_DIR, "healthchecks", "cnv_scenarios.py")
SCHEDULES_FILE = os.path.join(BASE_DIR, "schedules.json")
SETTINGS_FILE = os.path.join(BASE_DIR, ".settings.json")

MAX_CONCURRENT = Config.MAX_CONCURRENT_BUILDS
running_jobs = {}
queued_jobs = []
_jobs_lock = threading.Lock()

builds = []
schedules = []

DEFAULT_THRESHOLDS = {
    'cpu_warning': 85,
    'memory_warning': 80,
    'disk_latency': 100,
    'etcd_latency': 100,
    'pod_density': 50,
    'restart_count': 5,
    'virt_handler_memory': 500
}

AVAILABLE_AGENTS = {
    'infra_agent': {
        'name': 'Infrastructure SRE',
        'icon': '🏗️',
        'description': 'Verifies node health and ClusterOperator status',
        'category': 'Infrastructure',
    },
    'cnv_agent': {
        'name': 'Virtualization Specialist',
        'icon': '💻',
        'description': 'Audits CNV/KubeVirt subsystem, checks VMs and operators',
        'category': 'Virtualization',
    },
    'perf_agent': {
        'name': 'Performance Auditor',
        'icon': '📈',
        'description': 'Identifies CPU/RAM bottlenecks via oc adm top',
        'category': 'Performance',
    },
    'storage_agent': {
        'name': 'Storage Inspector',
        'icon': '💿',
        'description': 'Checks ODF, Ceph, PVCs, CSI drivers and volume health',
        'category': 'Storage',
    },
    'network_agent': {
        'name': 'Network Analyst',
        'icon': '🌐',
        'description': 'Inspects network policies, multus, and connectivity',
        'category': 'Network',
    },
    'security_agent': {
        'name': 'Security Auditor',
        'icon': '🔒',
        'description': 'Checks certificates, RBAC, and security configurations',
        'category': 'Security',
    },
}

_DEFAULT_CNV_SETTINGS = {
    'cnv_path': '/home/kni/git/cnv-scenarios',
    'mode': 'sanity',
    'parallel': False,
    'kb_log_level': '',
    'kb_timeout': '',
    'grafana_url': 'http://rhev-gw.rdu2.scalelab.redhat.com:3002/dashboards/f/d86573a6-d3fa-44ee-a217-550851f3e818/cnv',
    'global_vars': {},
    'scenario_vars': {},
}

DEFAULT_SETTINGS = {
    'thresholds': DEFAULT_THRESHOLDS,
    'ssh': {'host': '', 'user': 'root'},
    'ai': {'model': 'ollama/llama3.2:3b', 'url': 'http://localhost:11434'},
    'jira': {'projects': ['CNV', 'OCPBUGS', 'ODF'], 'scan_days': 30, 'bug_limit': 50},
    'cnv': _DEFAULT_CNV_SETTINGS,
}


def _safe_remove_report(report_file):
    """Remove a report file and its .md sibling, verifying the path stays
    inside REPORTS_DIR to prevent path-traversal."""
    base = os.path.basename(report_file)
    for name in (base, base.replace('.html', '.md')):
        full = os.path.realpath(os.path.join(REPORTS_DIR, name))
        if full.startswith(os.path.realpath(REPORTS_DIR)) and os.path.exists(full):
            os.remove(full)


def load_settings():
    """Load user settings from file"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                merged = DEFAULT_SETTINGS.copy()
                for key in settings:
                    if isinstance(settings[key], dict):
                        merged[key] = {**DEFAULT_SETTINGS.get(key, {}), **settings[key]}
                    else:
                        merged[key] = settings[key]
                return merged
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    """Save user settings to file"""
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)


def _collect_scenario_var_defaults(form):
    """Collect per-scenario variable defaults from a settings form POST."""
    result = {}
    for sid, scenario in CNV_SCENARIOS.items():
        svars = scenario.get('variables', {})
        if not svars:
            continue
        saved = {}
        for var_name, var_info in svars.items():
            key = f'cnv_var_{sid}_{var_name}'
            if var_info['type'] == 'bool':
                saved[var_name] = form.get(key) == 'on'
            elif var_info['type'] == 'int':
                try:
                    saved[var_name] = int(form.get(key, var_info.get('default', 0)))
                except (ValueError, TypeError):
                    saved[var_name] = var_info.get('default', 0)
            else:
                saved[var_name] = form.get(key, str(var_info.get('default', ''))).strip()
        result[sid] = saved
    return result


def get_thresholds():
    """Get current threshold settings"""
    settings = load_settings()
    return settings.get('thresholds', DEFAULT_THRESHOLDS)


def get_hosts_for_user(user, **_kwargs):
    """Get all hosts — everyone can see all hosts."""
    return Host.query.order_by(Host.created_at).all()


def load_builds():
    """Load builds from database, return as list of dicts."""
    global builds
    from app.models import Build
    import logging
    try:
        db_builds = Build.query.order_by(Build.build_number.desc()).limit(Config.MAX_BUILDS_HISTORY).all()
        builds = [b.to_dict() for b in db_builds]
    except Exception as exc:
        logging.getLogger(__name__).error("load_builds failed: %s", exc, exc_info=True)
        builds = []
    return builds


def save_build_to_db(build_record, user_id=None):
    """Save a build record to the database."""
    from app.models import db, Build
    build = Build(
        build_number=build_record['number'],
        name=build_record.get('name', ''),
        triggered_by=user_id,
        status=build_record['status'],
        status_text=build_record['status_text'],
        checks=build_record.get('checks', []),
        checks_count=build_record.get('checks_count', 0),
        options=build_record.get('options', {}),
        output=build_record.get('output', ''),
        report_file=build_record.get('report_file'),
        duration=build_record.get('duration', ''),
        scheduled=build_record.get('options', {}).get('scheduled', False),
    )
    db.session.add(build)
    db.session.commit()
    return build


def get_next_build_number():
    """Get next build number from DB."""
    from app.models import Build
    try:
        last = Build.query.order_by(Build.build_number.desc()).first()
        return (last.build_number + 1) if last else 1
    except Exception:
        return 1


def load_schedules():
    """Load schedules from file"""
    global schedules
    if os.path.exists(SCHEDULES_FILE):
        try:
            with open(SCHEDULES_FILE, 'r') as f:
                schedules = json.load(f)
        except (json.JSONDecodeError, OSError, ValueError):
            schedules = []
    return schedules


def save_schedules():
    """Save schedules to file"""
    with open(SCHEDULES_FILE, 'w') as f:
        json.dump(schedules, f, indent=2)


def get_next_run_time(schedule):
    """Calculate the next run time for a schedule"""
    from datetime import timedelta
    now = datetime.now()

    if schedule['type'] == 'once':
        scheduled_time = datetime.strptime(schedule['scheduled_time'], '%Y-%m-%d %H:%M')
        if scheduled_time > now:
            return scheduled_time.strftime('%Y-%m-%d %H:%M')
        return None

    frequency = schedule.get('frequency', 'daily')
    time_str = schedule.get('time', '06:00')

    if frequency == 'hourly':
        from datetime import timedelta
        next_run = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return next_run.strftime('%Y-%m-%d %H:%M')

    hour, minute = map(int, time_str.split(':'))

    if frequency == 'daily':
        from datetime import timedelta
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        return next_run.strftime('%Y-%m-%d %H:%M')

    if frequency == 'weekly':
        from datetime import timedelta
        days = schedule.get('days', ['mon'])
        day_map = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6}
        target_days = [day_map.get(d, 0) for d in days]
        for i in range(7):
            check_date = now + timedelta(days=i)
            if check_date.weekday() in target_days:
                next_run = check_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if next_run > now:
                    return next_run.strftime('%Y-%m-%d %H:%M')
        return None

    if frequency == 'monthly':
        day_of_month = schedule.get('day_of_month', 1)
        next_run = now.replace(day=day_of_month, hour=hour, minute=minute, second=0, microsecond=0)
        if next_run <= now:
            if now.month == 12:
                next_run = next_run.replace(year=now.year + 1, month=1)
            else:
                next_run = next_run.replace(month=now.month + 1)
        return next_run.strftime('%Y-%m-%d %H:%M')

    return None


def get_cron_display(schedule):
    """Get human-readable cron display"""
    if schedule['type'] == 'once':
        return schedule.get('scheduled_time', 'N/A')

    frequency = schedule.get('frequency', 'daily')
    time_str = schedule.get('time', '06:00')

    if frequency == 'hourly':
        return 'Every hour'
    elif frequency == 'daily':
        return f'Daily at {time_str}'
    elif frequency == 'weekly':
        days = schedule.get('days', ['mon'])
        day_names = {'mon': 'Mon', 'tue': 'Tue', 'wed': 'Wed', 'thu': 'Thu', 'fri': 'Fri', 'sat': 'Sat', 'sun': 'Sun'}
        day_list = ', '.join(day_names.get(d, d) for d in days)
        return f'{day_list} at {time_str}'
    elif frequency == 'monthly':
        day_of_month = schedule.get('day_of_month', 1)
        return f'Day {day_of_month} at {time_str}'
    elif frequency == 'custom':
        return schedule.get('cron', '* * * * *')
    return 'Unknown'


load_schedules()

SUGGESTED_CHECKS_FILE = os.path.join(BASE_DIR, ".suggested_checks.json")
suggested_checks = []


def load_suggested_checks():
    global suggested_checks
    if os.path.exists(SUGGESTED_CHECKS_FILE):
        try:
            with open(SUGGESTED_CHECKS_FILE, 'r') as f:
                suggested_checks = json.load(f)
        except Exception:
            suggested_checks = []
    return suggested_checks


def _restore_accepted_checks():
    """Re-add previously accepted Jira suggestions to AVAILABLE_CHECKS.

    Called once at import time so accepted checks survive server restarts.
    """
    checks = load_suggested_checks()
    restored = 0
    for sc in checks:
        if sc.get('status') != 'accepted':
            continue
        name = sc.get('name', '')
        if not name or name in AVAILABLE_CHECKS:
            continue
        AVAILABLE_CHECKS[name] = {
            'name': name.replace('_', ' ').title(),
            'description': sc.get('description', ''),
            'category': sc.get('category', 'Custom'),
            'default': True,
            'jira': sc.get('jira_key', ''),
            'custom': True,
        }
        restored += 1
    if restored:
        print(f"  [Knowledge] Restored {restored} accepted Jira check(s) into AVAILABLE_CHECKS")


_restore_accepted_checks()


def save_suggested_checks():
    with open(SUGGESTED_CHECKS_FILE, 'w') as f:
        json.dump(suggested_checks, f, indent=2)


def extract_issues_from_output(output):
    """Extract detected issues from health check output for learning."""
    import re
    issues = []
    pod_pattern = r'[❌⚠️]\s*(\S+)/(\S+)\s+(\S+.*?)(?:\n|$)'
    for match in re.finditer(pod_pattern, output):
        issues.append({'type': 'pod', 'namespace': match.group(1), 'name': match.group(2), 'status': match.group(3).strip()})
    operator_pattern = r'[❌⚠️]\s*([\w-]+)\s+(Degraded|Unavailable|Not Available)'
    for match in re.finditer(operator_pattern, output, re.IGNORECASE):
        issues.append({'type': 'operator', 'name': match.group(1), 'status': match.group(2)})
    migration_pattern = r'migration.*?(failed|stuck|error)'
    for match in re.finditer(migration_pattern, output, re.IGNORECASE):
        issues.append({'type': 'migration', 'name': 'vm-migration', 'status': match.group(1)})
    storage_pattern = r'(pvc|volume|storage|odf).*?(pending|failed|error|not ready)'
    for match in re.finditer(storage_pattern, output, re.IGNORECASE):
        issues.append({'type': 'storage', 'name': match.group(1), 'status': match.group(2)})
    node_pattern = r'node[s]?\s+(\S+)\s+(NotReady|SchedulingDisabled)'
    for match in re.finditer(node_pattern, output, re.IGNORECASE):
        issues.append({'type': 'node', 'name': match.group(1), 'status': match.group(2)})
    if 'OOMKilled' in output or 'oom' in output.lower():
        issues.append({'type': 'resource', 'name': 'oom-event', 'status': 'OOMKilled'})

    seen = set()
    unique_issues = []
    for issue in issues:
        key = (issue['type'], issue.get('name', ''), issue.get('namespace', ''))
        if key not in seen:
            seen.add(key)
            unique_issues.append(issue)
    return unique_issues


from . import views  # noqa: F401
from . import build_api  # noqa: F401
from . import build_executor  # noqa: F401
from . import api  # noqa: F401
from . import schedules_api  # noqa: F401
from . import templates_api  # noqa: F401
from . import settings_routes  # noqa: F401
from . import custom_checks  # noqa: F401
from . import learning_api  # noqa: F401

from .build_executor import start_build
