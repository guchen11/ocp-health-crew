"""
CNV Health Dashboard - Flask Routes

Multi-user with concurrent builds, role-based access, and audit logging.
"""

import os
import sys
import json
import glob
import subprocess
import threading
import time
import signal
from datetime import datetime
from flask import Blueprint, render_template, jsonify, request, send_from_directory, redirect, url_for
from flask_login import login_required, current_user
from functools import wraps
from app.models import db, Host

# Import configuration
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import Config, AVAILABLE_CHECKS, CATEGORY_ICONS, CNV_SCENARIOS, CNV_SCENARIO_CATEGORIES, CNV_CATEGORY_ORDER, CNV_GLOBAL_VARIABLES

# Create Blueprint
dashboard_bp = Blueprint('dashboard', __name__)

# Configuration
BASE_DIR = Config.BASE_DIR
REPORTS_DIR = Config.REPORTS_DIR
SCRIPT_PATH = os.path.join(BASE_DIR, "healthchecks", "hybrid_health_check.py")
CNV_SCRIPT_PATH = os.path.join(BASE_DIR, "healthchecks", "cnv_scenarios.py")
BUILDS_FILE = Config.BUILDS_FILE
SCHEDULES_FILE = os.path.join(BASE_DIR, "schedules.json")
SETTINGS_FILE = os.path.join(BASE_DIR, ".settings.json")

# ── Concurrent build queue ──────────────────────────────────────────────────
MAX_CONCURRENT = Config.MAX_CONCURRENT_BUILDS
running_jobs = {}          # job_id -> job dict
queued_jobs = []           # list of (job_id, checks, options, user_id) waiting
_jobs_lock = threading.Lock()

# Legacy JSON storage (still used for settings; builds migrated to DB)
builds = []
schedules = []

# Default thresholds
DEFAULT_THRESHOLDS = {
    'cpu_warning': 85,
    'memory_warning': 80,
    'disk_latency': 100,
    'etcd_latency': 100,
    'pod_density': 50,
    'restart_count': 5,
    'virt_handler_memory': 500
}

# Available AI Agents (from CrewAI)
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

# Default CNV Scenarios settings (built from config)
_DEFAULT_CNV_SETTINGS = {
    'cnv_path': '/home/kni/git/cnv-scenarios',
    'mode': 'sanity',
    'parallel': False,
    'kb_log_level': '',
    'kb_timeout': '',
    'global_vars': {var: info['default'] for var, info in CNV_GLOBAL_VARIABLES.items()},
    'scenario_vars': {},
}

# Default settings
DEFAULT_SETTINGS = {
    'thresholds': DEFAULT_THRESHOLDS,
    'ssh': {'host': '', 'user': 'root'},
    'ai': {'model': 'ollama/llama3.2:3b', 'url': 'http://localhost:11434'},
    'jira': {'projects': ['CNV', 'OCPBUGS', 'ODF'], 'scan_days': 30, 'bug_limit': 50},
    'cnv': _DEFAULT_CNV_SETTINGS,
}


# ── Role decorators ─────────────────────────────────────────────────────────
def operator_required(f):
    """Route requires operator or admin role."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_operator:
            return "Access denied. Operator role required.", 403
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Route requires admin role."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            return "Access denied. Admin role required.", 403
        return f(*args, **kwargs)
    return decorated


# ── Audit helper ─────────────────────────────────────────────────────────────
def log_audit(action, target=None, details=None, user_id=None, username=None):
    """Record an audit log entry."""
    from app.models import db, AuditLog
    try:
        if user_id is None and current_user and current_user.is_authenticated:
            user_id = current_user.id
            username = current_user.username
        entry = AuditLog(
            user_id=user_id,
            username=username or 'system',
            action=action,
            target=target,
            details=details,
            ip_address=request.remote_addr if request else None,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        pass  # Audit should never break the app


# ── Settings helpers ─────────────────────────────────────────────────────────
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
        except:
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


def _send_cnv_email_report(recipient, build_num, build_name, status, status_text,
                            duration, checks, options, output):
    """Send a CNV scenario results email."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    smtp_server = os.getenv('SMTP_SERVER', 'smtp.corp.redhat.com')
    smtp_port = int(os.getenv('SMTP_PORT', '25'))
    email_from = os.getenv('EMAIL_FROM', 'cnv-healthcrew@redhat.com')

    mode = options.get('scenario_mode', 'sanity')
    tests = checks if isinstance(checks, list) else []
    test_count = len(tests)

    status_colors = {
        'success': '#73BF69',
        'unstable': '#FF9830',
        'failed': '#F2495C',
    }
    status_emoji = {'success': '✅', 'unstable': '⚠️', 'failed': '❌'}.get(status, '🔵')
    color = status_colors.get(status, '#5794F2')

    # Extract result lines from the output (last ~60 lines usually contain summary)
    output_lines = output.strip().split('\n')
    # Find summary section
    summary_start = None
    for i, line in enumerate(output_lines):
        if any(k in line for k in ['Results:', 'SUMMARY', 'Summary:', 'scenarios complete', 'PASS', 'FAIL']):
            if summary_start is None or i < summary_start:
                summary_start = max(0, i - 2)
    if summary_start is not None:
        summary_lines = output_lines[summary_start:]
    else:
        summary_lines = output_lines[-40:]

    # Strip ANSI codes for plain text
    import re
    ansi_re = re.compile(r'\x1b\[[0-9;]*m')

    def strip_ansi(s):
        return ansi_re.sub('', s)

    plain_summary = '\n'.join(strip_ansi(l) for l in summary_lines)
    html_summary = '<br>'.join(
        strip_ansi(l).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        for l in summary_lines
    )

    subject = f'{status_emoji} CNV Scenarios #{build_num} — {status_text}'
    if build_name:
        subject += f' ({build_name})'

    # Build a nice HTML email
    html = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0d1117;color:#c9d1d9;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0d1117;padding:20px 0;">
<tr><td align="center">
<table width="640" cellpadding="0" cellspacing="0" style="background:#161b22;border-radius:12px;overflow:hidden;border:1px solid #30363d;">

<!-- Header -->
<tr><td style="background:linear-gradient(135deg,#1a1a2e,#16213e);padding:28px 32px;">
<table width="100%"><tr>
<td><span style="font-size:28px;">🔥</span></td>
<td style="padding-left:14px;">
<div style="font-size:22px;font-weight:700;color:#e6edf3;">CNV Scenarios Report</div>
<div style="font-size:13px;color:#8b949e;margin-top:4px;">Build #{build_num} · {duration}</div>
</td>
<td align="right">
<div style="display:inline-block;padding:8px 20px;border-radius:20px;background:{color}22;border:1px solid {color}44;">
<span style="font-size:16px;font-weight:700;color:{color};">{status_emoji} {status_text}</span>
</div>
</td>
</tr></table>
</td></tr>

<!-- Summary Stats -->
<tr><td style="padding:24px 32px;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr>
<td width="33%" style="padding:12px;background:#0d111788;border-radius:8px;text-align:center;border:1px solid #30363d;">
<div style="font-size:24px;font-weight:700;color:{color};">{status_text}</div>
<div style="font-size:11px;color:#8b949e;margin-top:4px;">STATUS</div>
</td>
<td width="8"></td>
<td width="33%" style="padding:12px;background:#0d111788;border-radius:8px;text-align:center;border:1px solid #30363d;">
<div style="font-size:24px;font-weight:700;color:#e6edf3;">{test_count}</div>
<div style="font-size:11px;color:#8b949e;margin-top:4px;">SCENARIOS</div>
</td>
<td width="8"></td>
<td width="33%" style="padding:12px;background:#0d111788;border-radius:8px;text-align:center;border:1px solid #30363d;">
<div style="font-size:24px;font-weight:700;color:#e6edf3;">{mode.upper()}</div>
<div style="font-size:11px;color:#8b949e;margin-top:4px;">MODE</div>
</td>
</tr>
</table>
</td></tr>

<!-- Scenarios List -->
<tr><td style="padding:0 32px 20px;">
<div style="font-size:13px;font-weight:600;color:#8b949e;margin-bottom:10px;">SCENARIOS EXECUTED</div>
<div style="background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:14px 18px;font-family:monospace;font-size:13px;color:#c9d1d9;">
{'  ·  '.join(tests)}
</div>
</td></tr>

<!-- Output Summary -->
<tr><td style="padding:0 32px 24px;">
<div style="font-size:13px;font-weight:600;color:#8b949e;margin-bottom:10px;">OUTPUT SUMMARY</div>
<div style="background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:16px 18px;font-family:monospace;font-size:12px;line-height:1.6;color:#c9d1d9;max-height:400px;overflow:auto;">
{html_summary}
</div>
</td></tr>

<!-- Footer -->
<tr><td style="padding:20px 32px;background:#0d111788;border-top:1px solid #30363d;text-align:center;">
<span style="font-size:12px;color:#8b949e;">
🔥 CNV HealthCrew · Automated scenario report · <a href="#" style="color:#58a6ff;">View full output in dashboard</a>
</span>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>'''

    plain = f"""CNV Scenarios Report — Build #{build_num}
Status: {status_text}
Duration: {duration}
Mode: {mode}
Scenarios: {', '.join(tests)}

--- Output Summary ---
{plain_summary}
"""

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = email_from
    msg['To'] = recipient
    msg.attach(MIMEText(plain, 'plain'))
    msg.attach(MIMEText(html, 'html'))

    with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
        server.sendmail(email_from, [recipient], msg.as_string())


def get_thresholds():
    """Get current threshold settings"""
    settings = load_settings()
    return settings.get('thresholds', DEFAULT_THRESHOLDS)


def get_hosts_for_user(user, **_kwargs):
    """Get all hosts — everyone can see all hosts."""
    return Host.query.order_by(Host.created_at).all()


def _setup_passwordless_ssh(host, user, password):
    """Setup passwordless SSH to a host. Returns (success, message)."""
    import paramiko
    home = os.path.expanduser("~")
    ssh_dir = os.path.join(home, ".ssh")
    key_path = os.path.join(ssh_dir, "id_ed25519")
    pub_path = key_path + ".pub"

    try:
        os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
        if not os.path.exists(key_path):
            key = paramiko.Ed25519Key.generate()
            key.write_private_key_file(key_path)
            os.chmod(key_path, 0o600)
            pub_key_str = f"{key.get_name()} {key.get_base64()} cnv-healthcrew"
            with open(pub_path, 'w') as f:
                f.write(pub_key_str + "\n")
            os.chmod(pub_path, 0o644)
        else:
            key = paramiko.Ed25519Key(filename=key_path)
            pub_key_str = f"{key.get_name()} {key.get_base64()} cnv-healthcrew"

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, username=user, password=password, timeout=15)

        commands = (
            "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
            f"grep -qxF '{pub_key_str}' ~/.ssh/authorized_keys 2>/dev/null || "
            f"echo '{pub_key_str}' >> ~/.ssh/authorized_keys && "
            "chmod 600 ~/.ssh/authorized_keys"
        )
        stdin, stdout, stderr = client.exec_command(commands)
        exit_status = stdout.channel.recv_exit_status()
        err_output = stderr.read().decode().strip()
        client.close()

        if exit_status != 0:
            return False, f'Failed to install key: {err_output}'

        # Verify key-based login works
        verify_client = paramiko.SSHClient()
        verify_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        verify_client.connect(host, username=user, key_filename=key_path, timeout=15)
        verify_client.close()
        return True, 'OK'
    except Exception as e:
        return False, str(e)


def sync_hosts_from_form(host_ids, host_names, host_addrs, host_users, host_passwords, user):
    """
    Sync the host list from form submission for the current user.
    - Existing hosts (with id) are updated.
    - New hosts (no id) are created.
    - If a password is provided for a new host, passwordless SSH is set up first.
    Returns (first_host, first_user, ssh_messages).
    """
    first_host = ''
    first_user = 'root'
    ssh_messages = []
    submitted_ids = set()

    # First pass: collect IDs of existing hosts still in the form
    for hid in host_ids:
        hid = hid.strip()
        if hid:
            submitted_ids.add(int(hid))

    # Delete hosts that were removed from the form (before adding new ones)
    if user.is_admin:
        all_hosts = Host.query.all()
    else:
        all_hosts = Host.query.filter_by(created_by=user.id).all()
    for h in all_hosts:
        if h.id not in submitted_ids:
            db.session.delete(h)
    db.session.flush()

    # Second pass: update existing and create new hosts
    for hid, name, addr, usr, pwd in zip(host_ids, host_names, host_addrs, host_users, host_passwords):
        addr = addr.strip()
        if not addr:
            continue
        name = name.strip() or addr
        usr = usr.strip() or 'root'
        pwd = pwd.strip() if pwd else ''

        if not first_host:
            first_host = addr
            first_user = usr

        hid = hid.strip()
        if hid:
            # Update existing host
            host_obj = Host.query.get(int(hid))
            if host_obj and (host_obj.created_by == user.id or user.is_admin):
                host_obj.name = name
                host_obj.host = addr
                host_obj.user = usr
        else:
            # New host — setup passwordless SSH if password provided
            if pwd:
                ok, msg = _setup_passwordless_ssh(addr, usr, pwd)
                if ok:
                    ssh_messages.append(f'SSH key installed on {usr}@{addr}')
                else:
                    ssh_messages.append(f'SSH setup failed for {usr}@{addr}: {msg}')
            label = f'{name} [{user.username}]' if not name.endswith(f'[{user.username}]') else name
            host_obj = Host(name=label, host=addr, user=usr, created_by=user.id)
            db.session.add(host_obj)

    db.session.commit()
    return first_host, first_user, ssh_messages


# ── Build helpers (DB-backed) ────────────────────────────────────────────────
def load_builds():
    """Load builds from database, return as list of dicts."""
    global builds
    from app.models import Build
    try:
        db_builds = Build.query.order_by(Build.build_number.desc()).limit(Config.MAX_BUILDS_HISTORY).all()
        builds = [b.to_dict() for b in db_builds]
    except Exception:
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


# ── Schedule helpers (still JSON for now) ────────────────────────────────────
def load_schedules():
    """Load schedules from file"""
    global schedules
    if os.path.exists(SCHEDULES_FILE):
        try:
            with open(SCHEDULES_FILE, 'r') as f:
                schedules = json.load(f)
        except:
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


# Load schedules on startup
load_schedules()


# =============================================================================
# ROUTES
# =============================================================================

@dashboard_bp.route('/help')
@login_required
def help_page():
    """Help and documentation page"""
    categories = sorted(set(c['category'] for c in AVAILABLE_CHECKS.values()))
    return render_template('help.html',
                           active_page='help',
                           checks=AVAILABLE_CHECKS,
                           categories=categories,
                           category_icons=CATEGORY_ICONS)


@dashboard_bp.route('/')
@login_required
def dashboard():
    """Main dashboard"""
    load_builds()

    # Get all running builds
    with _jobs_lock:
        running_list = list(running_jobs.values())

    # Filter for "my builds" if requested
    view = request.args.get('view', 'all')
    display_builds = builds
    if view == 'mine' and current_user.is_authenticated:
        display_builds = [b for b in builds if b.get('triggered_by') == current_user.username]

    # Calculate stats
    stats = {
        'total': len(builds),
        'success': sum(1 for b in builds if b.get('status') == 'success'),
        'unstable': sum(1 for b in builds if b.get('status') == 'unstable'),
        'failed': sum(1 for b in builds if b.get('status') == 'failed')
    }

    return render_template('dashboard.html',
                           builds=display_builds[:10],
                           recent_builds=display_builds[:10],
                           stats=stats,
                           running_builds=running_list,
                           running_build=running_list[0] if running_list else None,
                           queued_count=len(queued_jobs),
                           current_view=view,
                           active_page='dashboard')


@dashboard_bp.route('/job/configure')
@operator_required
def configure():
    """Build configuration page"""
    categories = sorted(set(c['category'] for c in AVAILABLE_CHECKS.values()))
    preset = request.args.get('preset', '')
    settings = load_settings()
    thresholds = settings.get('thresholds', DEFAULT_THRESHOLDS)
    ssh_config = settings.get('ssh', DEFAULT_SETTINGS['ssh'])

    host_objects = get_hosts_for_user(current_user)
    saved_hosts = [h.to_dict() for h in host_objects]

    cnv_config = settings.get('cnv', _DEFAULT_CNV_SETTINGS)

    return render_template('configure.html',
                           checks=AVAILABLE_CHECKS,
                           categories=categories,
                           category_icons=CATEGORY_ICONS,
                           preset=preset,
                           thresholds=thresholds,
                           agents=AVAILABLE_AGENTS,
                           ssh_config=ssh_config,
                           saved_hosts=saved_hosts,
                           server_host=ssh_config.get('host', ''),
                           cnv_scenarios=CNV_SCENARIOS,
                           cnv_categories=CNV_SCENARIO_CATEGORIES,
                           cnv_category_order=CNV_CATEGORY_ORDER,
                           cnv_global_vars=CNV_GLOBAL_VARIABLES,
                           cnv_config=cnv_config,
                           active_page='configure')


@dashboard_bp.route('/job/run', methods=['POST'])
@operator_required
def run_build():
    """Start a new build or schedule one"""
    import uuid

    task_type = request.form.get('task_type', 'health_check')
    run_name = request.form.get('run_name', '').strip()
    server_host = request.form.get('server_host', '').strip()

    # ── CNV Scenarios task ───────────────────────────────────────────────
    if task_type == 'cnv_scenarios':
        selected_tests = request.form.getlist('scenario_tests')
        if not selected_tests:
            selected_tests = [s['remote_name'] for s in CNV_SCENARIOS.values() if s.get('default')]

        scenario_mode = request.form.get('scenario_mode', 'sanity')
        scenario_parallel = 'scenario_parallel' in request.form
        cnv_path = request.form.get('cnv_path', '/home/kni/git/cnv-scenarios').strip()

        # Collect env-var overrides from the form
        env_overrides = []
        for key in request.form:
            if key.startswith('cnv_var_') and request.form[key].strip():
                var_name = key[len('cnv_var_'):]
                env_overrides.append(f"{var_name}={request.form[key].strip()}")

        kb_log_level = request.form.get('kb_log_level', '').strip()
        kb_timeout = request.form.get('kb_timeout', '').strip()

        options = {
            'task_type': 'cnv_scenarios',
            'server_host': server_host,
            'run_name': run_name,
            'scenario_tests': selected_tests,
            'scenario_mode': scenario_mode,
            'scenario_parallel': scenario_parallel,
            'cnv_path': cnv_path,
            'env_vars': ','.join(env_overrides) if env_overrides else '',
            'kb_log_level': kb_log_level,
            'kb_timeout': kb_timeout,
            'email': 'cnv_send_email' in request.form,
            'email_to': request.form.get('cnv_email_to', Config.DEFAULT_EMAIL),
        }

        schedule_type = request.form.get('schedule_type', 'now')
        if schedule_type == 'now':
            user_id = current_user.id if current_user.is_authenticated else None
            build_num = start_build(selected_tests, options, user_id=user_id)
            return redirect(url_for('dashboard.console_output', build_num=build_num))

        # Fall through to scheduling code below (reuses same schedule logic)
        selected_checks = selected_tests

    # ── Health Check task (default) ──────────────────────────────────────
    else:
        selected_checks = request.form.getlist('checks')
        if not selected_checks:
            selected_checks = list(AVAILABLE_CHECKS.keys())

        rca_level = request.form.get('rca_level', 'none')

        current_thresholds = get_thresholds()
        use_custom = 'use_custom_thresholds' in request.form

        thresholds = {
            'cpu_warning': int(request.form.get('cpu_threshold', current_thresholds['cpu_warning'])) if use_custom else current_thresholds['cpu_warning'],
            'memory_warning': int(request.form.get('memory_threshold', current_thresholds['memory_warning'])) if use_custom else current_thresholds['memory_warning'],
            'disk_latency': int(request.form.get('disk_latency_threshold', current_thresholds['disk_latency'])) if use_custom else current_thresholds['disk_latency'],
            'etcd_latency': int(request.form.get('etcd_latency_threshold', current_thresholds['etcd_latency'])) if use_custom else current_thresholds['etcd_latency'],
            'pod_density': int(request.form.get('pod_density_threshold', current_thresholds['pod_density'])) if use_custom else current_thresholds['pod_density'],
            'restart_count': int(request.form.get('restart_threshold', current_thresholds['restart_count'])) if use_custom else current_thresholds['restart_count'],
        }

        selected_agent = request.form.get('agent', 'all')

        options = {
            'task_type': 'health_check',
            'server_host': server_host,
            'rca_level': rca_level,
            'rca_jira': 'rca_jira' in request.form,
            'rca_email': 'rca_email' in request.form,
            'rca_web': 'rca_web' in request.form,
            'jira': 'check_jira' in request.form,
            'email': 'send_email' in request.form,
            'email_to': request.form.get('email_to', Config.DEFAULT_EMAIL),
            'run_name': run_name,
            'thresholds': thresholds,
            'agent': selected_agent
        }

    schedule_type = request.form.get('schedule_type', 'now')

    if schedule_type == 'now':
        user_id = current_user.id if current_user.is_authenticated else None
        build_num = start_build(selected_checks, options, user_id=user_id)
        return redirect(url_for('dashboard.console_output', build_num=build_num))

    elif schedule_type == 'once':
        schedule_date = request.form.get('schedule_date', '')
        schedule_time = request.form.get('schedule_time', '')
        if schedule_date and schedule_time:
            scheduled_time = f"{schedule_date} {schedule_time}"
            schedule = {
                'id': str(uuid.uuid4())[:8],
                'name': f"Scheduled Check ({scheduled_time})",
                'type': 'once',
                'scheduled_time': scheduled_time,
                'checks': selected_checks,
                'checks_count': len(selected_checks),
                'options': options,
                'status': 'active',
                'created': datetime.now().strftime('%Y-%m-%d %H:%M'),
                'created_by': current_user.username if current_user.is_authenticated else 'system',
                'last_run': None
            }
            schedules.append(schedule)
            save_schedules()
            return redirect(url_for('dashboard.schedules_page'))

    elif schedule_type == 'recurring':
        frequency = request.form.get('recurring_frequency', 'daily')
        schedule_name = request.form.get('schedule_name', '').strip() or f"Recurring Health Check ({frequency})"
        recurring_time = request.form.get('recurring_time', '06:00')

        schedule = {
            'id': str(uuid.uuid4())[:8],
            'name': schedule_name,
            'type': 'recurring',
            'frequency': frequency,
            'time': recurring_time,
            'checks': selected_checks,
            'checks_count': len(selected_checks),
            'options': options,
            'status': 'active',
            'created': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'created_by': current_user.username if current_user.is_authenticated else 'system',
            'last_run': None
        }

        if frequency == 'weekly':
            days = request.form.getlist('recurring_days')
            schedule['days'] = days if days else ['mon']
        elif frequency == 'monthly':
            day_of_month = request.form.get('recurring_dayofmonth', '1')
            schedule['day_of_month'] = int(day_of_month) if day_of_month.isdigit() else 1
        elif frequency == 'custom':
            cron_expr = request.form.get('recurring_cron', '0 6 * * *')
            schedule['cron'] = cron_expr

        schedules.append(schedule)
        save_schedules()
        return redirect(url_for('dashboard.schedules_page'))

    user_id = current_user.id if current_user.is_authenticated else None
    build_num = start_build(selected_checks, options, user_id=user_id)
    return redirect(url_for('dashboard.console_output', build_num=build_num))


@dashboard_bp.route('/job/quick-run')
@operator_required
def quick_run():
    """Quick build - redirect to configure with all checks selected"""
    return redirect(url_for('dashboard.configure') + '?preset=all')


@dashboard_bp.route('/job/history')
@login_required
def history():
    """Build history page"""
    load_builds()
    status_filter = request.args.get('status')
    view = request.args.get('view', 'all')

    filtered_builds = builds
    if view == 'mine' and current_user.is_authenticated:
        filtered_builds = [b for b in filtered_builds if b.get('triggered_by') == current_user.username]
    if status_filter:
        filtered_builds = [b for b in filtered_builds if b.get('status') == status_filter]

    return render_template('history.html',
                           builds=filtered_builds,
                           current_view=view,
                           active_page='history')


@dashboard_bp.route('/schedules')
@login_required
def schedules_page():
    """Scheduled tasks page"""
    load_schedules()
    status_filter = request.args.get('status')

    for schedule in schedules:
        schedule['next_run'] = get_next_run_time(schedule)
        schedule['cron_display'] = get_cron_display(schedule)

    filtered_schedules = schedules
    if status_filter:
        filtered_schedules = [s for s in schedules if s.get('status') == status_filter]

    scheduler_status = {
        'active_schedules': sum(1 for s in schedules if s.get('status') == 'active'),
        'runs_today': 0,
        'next_run': min((s.get('next_run') for s in schedules if s.get('status') == 'active' and s.get('next_run')), default=None)
    }

    return render_template('schedules.html',
                           schedules=filtered_schedules,
                           scheduler_status=scheduler_status,
                           active_page='schedules')


@dashboard_bp.route('/job/<int:build_num>')
@login_required
def build_detail(build_num):
    """Build detail page"""
    load_builds()
    build = next((b for b in builds if b.get('number') == build_num), None)

    if not build:
        with _jobs_lock:
            for job_id, job in running_jobs.items():
                if job.get('number') == build_num:
                    build = job
                    break

    if not build:
        return "Build not found", 404

    return render_template('build_detail.html',
                           build=build,
                           checks=AVAILABLE_CHECKS,
                           active_page='history')


@dashboard_bp.route('/job/<int:build_num>/console')
@login_required
def console_output(build_num):
    """Console output page"""
    load_builds()
    build = next((b for b in builds if b.get('number') == build_num), None)

    if not build:
        with _jobs_lock:
            for job_id, job in running_jobs.items():
                if job.get('number') == build_num:
                    build = job
                    break

    if not build:
        return "Build not found", 404

    return render_template('console.html', build=build, active_page='history')


@dashboard_bp.route('/job/rebuild/<int:build_num>')
@operator_required
def rebuild(build_num):
    """Rebuild with same parameters"""
    load_builds()
    build = next((b for b in builds if b.get('number') == build_num), None)

    if build:
        checks = build.get('checks', list(AVAILABLE_CHECKS.keys()))
        options = build.get('options', {'rca_level': 'none', 'jira': False, 'email': False})
        user_id = current_user.id if current_user.is_authenticated else None
        new_build_num = start_build(checks, options, user_id=user_id)
        return redirect(url_for('dashboard.console_output', build_num=new_build_num))

    return redirect(url_for('dashboard.dashboard'))


@dashboard_bp.route('/report/<filename>')
@login_required
def serve_report(filename):
    """Serve report files"""
    return send_from_directory(REPORTS_DIR, filename)


# =============================================================================
# API ENDPOINTS
# =============================================================================

@dashboard_bp.route('/api/status')
@login_required
def api_status():
    """API endpoint for build status - returns all running builds."""
    with _jobs_lock:
        if running_jobs:
            # Return info about all running builds
            all_running = []
            for job_id, job in running_jobs.items():
                all_running.append({
                    'job_id': job_id,
                    'number': job.get('number'),
                    'name': job.get('name', ''),
                    'output': job.get('output', ''),
                    'progress': job.get('progress', 0),
                    'phases': job.get('phases', []),
                    'current_phase': job.get('current_phase', ''),
                    'start_time': job.get('start_time', 0),
                    'triggered_by': job.get('triggered_by', 'system'),
                })

            # For backward compatibility, also return first build's data at top level
            first = all_running[0] if all_running else {}
            return jsonify({
                'running': True,
                'builds': all_running,
                'queued': len(queued_jobs),
                'output': first.get('output', ''),
                'progress': first.get('progress', 0),
                'phases': first.get('phases', []),
                'current_phase': first.get('current_phase', ''),
                'start_time': first.get('start_time', 0),
            })
    return jsonify({'running': False, 'queued': len(queued_jobs)})


@dashboard_bp.route('/api/stop', methods=['POST'])
@operator_required
def api_stop():
    """API endpoint to stop a running build."""
    data = request.get_json(silent=True) or {}
    target_job_id = data.get('job_id')

    with _jobs_lock:
        if not running_jobs:
            return jsonify({'success': False, 'error': 'No running build'})

        # If no specific job_id, stop the first one (backward compat)
        if not target_job_id:
            target_job_id = list(running_jobs.keys())[0]

        job = running_jobs.get(target_job_id)
        if not job:
            return jsonify({'success': False, 'error': 'Build not found'})

        # Only owner or admin can stop
        if not current_user.is_admin and job.get('user_id') != current_user.id:
            return jsonify({'success': False, 'error': 'You can only stop your own builds.'})

    try:
        process = job.get('process')
        if process and process.poll() is None:
            try:
                pgid = os.getpgid(process.pid)
                os.killpg(pgid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(pgid, signal.SIGKILL)
                    process.wait(timeout=2)
            except (ProcessLookupError, OSError):
                pass

        job['output'] += f'\n[{datetime.now().strftime("%H:%M:%S")}] ⛔ Build stopped by {current_user.username}\n'
        job['current_phase'] = f'Stopped by {current_user.username}'

        for phase in job.get('phases', []):
            if phase['status'] == 'running':
                phase['status'] = 'error'

        duration_secs = int(time.time() - job['start_time'])
        duration = f"{duration_secs // 60}m {duration_secs % 60}s"

        build_record = {
            'number': job['number'],
            'name': job.get('name', ''),
            'status': 'failed',
            'status_text': 'Stopped',
            'checks': job.get('checks', []),
            'checks_count': job.get('checks_count', 0),
            'options': job.get('options', {}),
            'timestamp': job['timestamp'],
            'duration': duration,
            'output': job['output'],
            'report_file': None
        }

        save_build_to_db(build_record, user_id=job.get('user_id'))

        with _jobs_lock:
            if target_job_id in running_jobs:
                del running_jobs[target_job_id]

        log_audit('build_stop', target=f'Build #{job["number"]}',
                  details=f'Stopped by {current_user.username}')

        # Start next queued build if any
        _start_next_queued()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/delete/<int:build_num>', methods=['POST'])
@operator_required
def api_delete(build_num):
    """API endpoint to delete a build and its report"""
    from app.models import db, Build
    try:
        build = Build.query.filter_by(build_number=build_num).first()
        if not build:
            return jsonify({'success': False, 'error': 'Build not found'})

        # Only owner or admin can delete
        if not current_user.is_admin and build.triggered_by != current_user.id:
            return jsonify({'success': False, 'error': 'You can only delete your own builds.'})

        report_file = build.report_file
        if report_file:
            report_path = os.path.join(REPORTS_DIR, report_file)
            if os.path.exists(report_path):
                os.remove(report_path)
            md_file = report_file.replace('.html', '.md')
            md_path = os.path.join(REPORTS_DIR, md_file)
            if os.path.exists(md_path):
                os.remove(md_path)

        db.session.delete(build)
        db.session.commit()

        log_audit('build_delete', target=f'Build #{build_num}')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/delete-bulk', methods=['POST'])
@admin_required
def api_delete_bulk():
    """API endpoint to delete multiple builds by status filter"""
    from app.models import db, Build
    try:
        data = request.get_json() or {}
        filter_type = data.get('filter', 'all')

        if filter_type == 'all':
            query = Build.query
        elif filter_type == 'failed':
            query = Build.query.filter_by(status='failed')
        elif filter_type == 'stopped':
            query = Build.query.filter_by(status_text='Stopped')
        else:
            return jsonify({'success': False, 'error': 'Invalid filter type'})

        builds_to_delete = query.all()
        deleted_count = 0

        for build in builds_to_delete:
            report_file = build.report_file
            if report_file:
                report_path = os.path.join(REPORTS_DIR, report_file)
                if os.path.exists(report_path):
                    os.remove(report_path)
                md_file = report_file.replace('.html', '.md')
                md_path = os.path.join(REPORTS_DIR, md_file)
                if os.path.exists(md_path):
                    os.remove(md_path)
            db.session.delete(build)
            deleted_count += 1

        db.session.commit()
        log_audit('build_bulk_delete', details=f'Deleted {deleted_count} builds (filter: {filter_type})')
        return jsonify({'success': True, 'deleted': deleted_count})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# =============================================================================
# SCHEDULE API ENDPOINTS
# =============================================================================

@dashboard_bp.route('/api/schedules')
@login_required
def api_get_schedules():
    """API endpoint to get all schedules"""
    load_schedules()
    for schedule in schedules:
        schedule['next_run'] = get_next_run_time(schedule)
        schedule['cron_display'] = get_cron_display(schedule)
    return jsonify({'success': True, 'schedules': schedules})


@dashboard_bp.route('/api/schedule', methods=['POST'])
@operator_required
def api_create_schedule():
    """API endpoint to create a new schedule"""
    import uuid
    try:
        data = request.get_json() or {}
        schedule = {
            'id': str(uuid.uuid4())[:8],
            'name': data.get('name', 'Unnamed Schedule'),
            'type': data.get('type', 'recurring'),
            'frequency': data.get('frequency', 'daily'),
            'time': data.get('time', '06:00'),
            'checks': data.get('checks', list(AVAILABLE_CHECKS.keys())),
            'checks_count': len(data.get('checks', AVAILABLE_CHECKS)),
            'options': data.get('options', {'rca_level': 'none'}),
            'status': 'active',
            'created': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'created_by': current_user.username if current_user.is_authenticated else 'system',
            'last_run': None
        }
        if schedule['type'] == 'once':
            schedule['scheduled_time'] = data.get('scheduled_time', '')
        elif schedule['frequency'] == 'weekly':
            schedule['days'] = data.get('days', ['mon'])
        elif schedule['frequency'] == 'monthly':
            schedule['day_of_month'] = data.get('day_of_month', 1)
        elif schedule['frequency'] == 'custom':
            schedule['cron'] = data.get('cron', '0 6 * * *')

        schedules.append(schedule)
        save_schedules()
        return jsonify({'success': True, 'schedule': schedule})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/schedule/<schedule_id>/<action>', methods=['POST'])
@operator_required
def api_schedule_action(schedule_id, action):
    """API endpoint to pause/resume a schedule"""
    load_schedules()
    try:
        schedule = next((s for s in schedules if s.get('id') == schedule_id), None)
        if not schedule:
            return jsonify({'success': False, 'error': 'Schedule not found'})
        if action == 'pause':
            schedule['status'] = 'paused'
        elif action == 'resume':
            schedule['status'] = 'active'
        else:
            return jsonify({'success': False, 'error': 'Invalid action'})
        save_schedules()
        return jsonify({'success': True, 'status': schedule['status']})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/schedule/<schedule_id>/run', methods=['POST'])
@operator_required
def api_schedule_run(schedule_id):
    """API endpoint to run a schedule immediately"""
    load_schedules()
    try:
        schedule = next((s for s in schedules if s.get('id') == schedule_id), None)
        if not schedule:
            return jsonify({'success': False, 'error': 'Schedule not found'})

        checks = schedule.get('checks', list(AVAILABLE_CHECKS.keys()))
        options = schedule.get('options', {'rca_level': 'none'})
        options['scheduled'] = True
        options['schedule_id'] = schedule_id
        options['schedule_name'] = schedule.get('name', 'Scheduled')

        user_id = current_user.id if current_user.is_authenticated else None
        start_build(checks, options, user_id=user_id)

        schedule['last_run'] = datetime.now().strftime('%Y-%m-%d %H:%M')
        save_schedules()

        return jsonify({'success': True, 'message': 'Build started'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/schedule/<schedule_id>', methods=['DELETE'])
@operator_required
def api_schedule_delete(schedule_id):
    """API endpoint to delete a schedule"""
    global schedules
    load_schedules()
    try:
        schedule = next((s for s in schedules if s.get('id') == schedule_id), None)
        if not schedule:
            return jsonify({'success': False, 'error': 'Schedule not found'})
        schedules = [s for s in schedules if s.get('id') != schedule_id]
        save_schedules()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# =============================================================================
# JIRA INTEGRATION API ENDPOINTS
# =============================================================================

SUGGESTED_CHECKS_FILE = os.path.join(BASE_DIR, ".suggested_checks.json")
suggested_checks = []


def load_suggested_checks():
    global suggested_checks
    if os.path.exists(SUGGESTED_CHECKS_FILE):
        try:
            with open(SUGGESTED_CHECKS_FILE, 'r') as f:
                suggested_checks = json.load(f)
        except:
            suggested_checks = []
    return suggested_checks


def save_suggested_checks():
    with open(SUGGESTED_CHECKS_FILE, 'w') as f:
        json.dump(suggested_checks, f, indent=2)


@dashboard_bp.route('/api/jira/suggestions')
@login_required
def api_jira_suggestions():
    """API endpoint to get Jira-based test suggestions"""
    try:
        sys.path.insert(0, BASE_DIR)
        from healthchecks.hybrid_health_check import (
            get_known_recent_bugs,
            get_existing_check_names,
            analyze_bugs_for_new_checks,
            search_jira_for_new_bugs
        )
        existing_checks = get_existing_check_names()
        load_suggested_checks()
        accepted_checks = {s['name'] for s in suggested_checks if s.get('status') == 'accepted'}
        existing_checks.extend(list(accepted_checks))

        try:
            bugs = search_jira_for_new_bugs(days=30, limit=50)
        except:
            bugs = None
        if not bugs:
            bugs = get_known_recent_bugs()

        suggestions = analyze_bugs_for_new_checks(bugs, existing_checks)
        rejected_recently = {
            s['name'] for s in suggested_checks
            if s.get('status') == 'rejected' and s.get('rejected_at')
        }
        suggestions = [s for s in suggestions if s['suggested_check'] not in rejected_recently]

        # Enrich suggestions with command info
        from healthchecks.hybrid_health_check import generate_check_code
        for s in suggestions:
            check_code = generate_check_code(s)
            s['command'] = check_code.get('command', '')

        return jsonify({
            'success': True,
            'suggestions': suggestions,
            'count': len(suggestions),
            'bugs_analyzed': len(bugs)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'suggestions': []})


@dashboard_bp.route('/api/jira/accept-check', methods=['POST'])
@operator_required
def api_jira_accept_check():
    global suggested_checks
    load_suggested_checks()
    try:
        data = request.get_json() or {}
        check_name = data.get('name', '')
        jira_key = data.get('jira_key', '')
        description = data.get('description', '')
        category = data.get('category', 'Custom')
        if not check_name:
            return jsonify({'success': False, 'error': 'Check name is required'})

        check_record = {
            'name': check_name, 'jira_key': jira_key, 'description': description,
            'category': category, 'status': 'accepted',
            'accepted_at': datetime.now().strftime('%Y-%m-%d %H:%M')
        }
        existing = next((s for s in suggested_checks if s['name'] == check_name), None)
        if existing:
            existing.update(check_record)
        else:
            suggested_checks.append(check_record)
        save_suggested_checks()

        AVAILABLE_CHECKS[check_name] = {
            'name': check_name.replace('_', ' ').title(),
            'description': description, 'category': category,
            'default': True, 'jira': jira_key, 'custom': True
        }
        return jsonify({'success': True, 'message': f'Check "{check_name}" added successfully', 'check': check_record})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/jira/reject-check', methods=['POST'])
@operator_required
def api_jira_reject_check():
    global suggested_checks
    load_suggested_checks()
    try:
        data = request.get_json() or {}
        check_name = data.get('name', '')
        if not check_name:
            return jsonify({'success': False, 'error': 'Check name is required'})

        check_record = {'name': check_name, 'status': 'rejected', 'rejected_at': datetime.now().strftime('%Y-%m-%d %H:%M')}
        existing = next((s for s in suggested_checks if s['name'] == check_name), None)
        if existing:
            existing.update(check_record)
        else:
            suggested_checks.append(check_record)
        save_suggested_checks()
        return jsonify({'success': True, 'message': f'Check "{check_name}" rejected'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/jira/accepted-checks')
@login_required
def api_jira_accepted_checks():
    load_suggested_checks()
    accepted = [s for s in suggested_checks if s.get('status') == 'accepted']
    return jsonify({'success': True, 'checks': accepted, 'count': len(accepted)})


# =============================================================================
# LEARNING & PATTERNS API ENDPOINTS
# =============================================================================

@dashboard_bp.route('/api/learning/stats')
@login_required
def api_learning_stats():
    try:
        from app.learning import get_learning_stats, get_issue_trends, get_recurring_issues
        stats = get_learning_stats()
        trends = get_issue_trends(days=7)
        recurring = get_recurring_issues(min_count=2)
        return jsonify({'success': True, 'stats': stats, 'trends': trends, 'recurring_count': len(recurring)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/learning/patterns')
@login_required
def api_learning_patterns():
    try:
        from app.learning import get_learned_patterns
        patterns = get_learned_patterns()
        return jsonify({'success': True, 'patterns': patterns, 'count': len(patterns)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/learning/recurring')
@login_required
def api_learning_recurring():
    try:
        from app.learning import get_recurring_issues
        min_count = request.args.get('min_count', 2, type=int)
        recurring = get_recurring_issues(min_count=min_count)
        sorted_recurring = dict(sorted(recurring.items(), key=lambda x: -x[1]['count']))
        return jsonify({'success': True, 'recurring_issues': sorted_recurring, 'count': len(sorted_recurring)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/learning/trends')
@login_required
def api_learning_trends():
    try:
        from app.learning import get_issue_trends
        days = request.args.get('days', 7, type=int)
        trends = get_issue_trends(days=days)
        return jsonify({'success': True, 'trends': trends})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# =============================================================================
# BUILD EXECUTION (with concurrent build support)
# =============================================================================

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


def _start_next_queued():
    """Start the next queued build if a slot is available. Must NOT hold _jobs_lock."""
    with _jobs_lock:
        if len(running_jobs) >= MAX_CONCURRENT or not queued_jobs:
            return
        job_id, checks, options, user_id = queued_jobs.pop(0)

    _execute_build(job_id, checks, options, user_id=user_id)


def start_build(checks, options, user_id=None):
    """Start a new build (or queue it if at capacity)."""
    build_num = get_next_build_number()
    job_id = f"build_{build_num}"

    # Resolve username for display
    username = 'system'
    if user_id:
        from app.models import User
        user = User.query.get(user_id)
        if user:
            username = user.username

    with _jobs_lock:
        if len(running_jobs) >= MAX_CONCURRENT:
            queued_jobs.append((job_id, checks, options, user_id))
            return build_num

    _execute_build(job_id, checks, options, user_id=user_id)
    return build_num


def _execute_build(job_id, checks, options, user_id=None):
    """Actually run the build in a background thread."""
    build_num = int(job_id.split('_')[1])

    # Resolve username
    username = 'system'
    if user_id:
        try:
            from app.models import User
            user = User.query.get(user_id)
            if user:
                username = user.username
        except Exception:
            pass

    is_cnv = options.get('task_type') == 'cnv_scenarios'

    # ── Build the command and phase list based on task type ───────────────
    if is_cnv:
        cmd = [sys.executable, CNV_SCRIPT_PATH]
        server_host = options.get('server_host', '')
        if server_host:
            cmd.extend(['--server', server_host])
            host_obj = Host.query.filter_by(host=server_host).first()
            if host_obj and host_obj.name:
                import re
                clean_name = re.sub(r'\s*\[.*?\]\s*$', '', host_obj.name).strip() or host_obj.host
                cmd.extend(['--lab-name', clean_name])

        scenario_tests = options.get('scenario_tests', [])
        tests_str = ','.join(scenario_tests) if scenario_tests else 'all'
        cmd.extend(['--tests', tests_str])
        cmd.extend(['--mode', options.get('scenario_mode', 'sanity')])
        if options.get('scenario_parallel'):
            cmd.append('--parallel')
        if options.get('cnv_path'):
            cmd.extend(['--cnv-path', options['cnv_path']])
        if options.get('env_vars'):
            cmd.extend(['--env-vars', options['env_vars']])
        if options.get('kb_log_level'):
            cmd.extend(['--log-level', options['kb_log_level']])
        if options.get('kb_timeout'):
            cmd.extend(['--timeout', options['kb_timeout']])

        phases = [
            {'name': 'Initialize', 'status': 'pending', 'start_time': None, 'duration': None},
            {'name': 'Connect', 'status': 'pending', 'start_time': None, 'duration': None},
            {'name': 'Verify Setup', 'status': 'pending', 'start_time': None, 'duration': None},
            {'name': 'Run Scenarios', 'status': 'pending', 'start_time': None, 'duration': None},
            {'name': 'Collect Results', 'status': 'pending', 'start_time': None, 'duration': None},
            {'name': 'Summary', 'status': 'pending', 'start_time': None, 'duration': None},
        ]

        if options.get('email'):
            phases.append({'name': 'Send Email', 'status': 'pending', 'start_time': None, 'duration': None})

    else:
        cmd = [sys.executable, SCRIPT_PATH]

        server_host = options.get('server_host', '')
        if server_host:
            cmd.extend(['--server', server_host])
            host_obj = Host.query.filter_by(host=server_host).first()
            if host_obj and host_obj.name:
                import re
                clean_name = re.sub(r'\s*\[.*?\]\s*$', '', host_obj.name).strip() or host_obj.host
                cmd.extend(['--lab-name', clean_name])

        rca_level = options.get('rca_level', 'none')
        if rca_level == 'bugs':
            cmd.append('--rca-bugs')
        elif rca_level == 'full':
            cmd.append('--ai')

        if options.get('rca_jira'):
            cmd.append('--rca-jira')
        if options.get('rca_email'):
            cmd.append('--rca-email')
        if options.get('jira'):
            cmd.append('--check-jira')
        if options.get('email'):
            cmd.append('--email')
            if options.get('email_to'):
                cmd.extend(['--email-to', options.get('email_to')])

        phases = [
            {'name': 'Initialize', 'status': 'pending', 'start_time': None, 'duration': None},
        ]
        if options.get('jira'):
            phases.append({'name': 'Scan Jira', 'status': 'pending', 'start_time': None, 'duration': None})

        phases.extend([
            {'name': 'Connect', 'status': 'pending', 'start_time': None, 'duration': None},
            {'name': 'Collect Data', 'status': 'pending', 'start_time': None, 'duration': None},
            {'name': 'Console Report', 'status': 'pending', 'start_time': None, 'duration': None},
            {'name': 'Analyze', 'status': 'pending', 'start_time': None, 'duration': None},
            {'name': 'Generate Report', 'status': 'pending', 'start_time': None, 'duration': None},
        ])

        rca_phase_idx = len(phases) - 1
        if rca_level != 'none':
            if options.get('rca_jira') or rca_level == 'full':
                phases.insert(rca_phase_idx, {'name': 'Search Jira', 'status': 'pending', 'start_time': None, 'duration': None})
                rca_phase_idx += 1
            if options.get('rca_email') or rca_level == 'full':
                phases.insert(rca_phase_idx, {'name': 'Search Email', 'status': 'pending', 'start_time': None, 'duration': None})
                rca_phase_idx += 1
            if options.get('rca_web'):
                phases.insert(rca_phase_idx, {'name': 'Search Web', 'status': 'pending', 'start_time': None, 'duration': None})
                rca_phase_idx += 1
            if rca_level == 'full':
                phases.insert(rca_phase_idx, {'name': 'Deep RCA', 'status': 'pending', 'start_time': None, 'duration': None})

        if options.get('email'):
            phases.append({'name': 'Send Email', 'status': 'pending', 'start_time': None, 'duration': None})

    run_name = options.get('run_name', '')
    # Include lab name (jumphost label) in the build name
    server_host = options.get('server_host', '')
    lab_name = ''
    if server_host:
        host_obj = Host.query.filter_by(host=server_host).first()
        if host_obj and host_obj.name:
            import re
            lab_name = re.sub(r'\s*\[.*?\]\s*$', '', host_obj.name).strip()
    if run_name and lab_name:
        display_name = f'{run_name} ({lab_name})'
    elif lab_name:
        display_name = lab_name
    else:
        display_name = run_name

    job = {
        'number': build_num,
        'name': display_name,
        'status': 'running',
        'status_text': 'Running',
        'output': f'[{datetime.now().strftime("%H:%M:%S")}] Starting build #{build_num}' + (f' "{run_name}"' if run_name else '') + f' (by {username})...\n',
        'checks': checks,
        'checks_count': len(checks),
        'options': options,
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M"),
        'start_time': time.time(),
        'progress': 5,
        'phases': phases,
        'current_phase': 'Initializing...',
        'triggered_by': username,
        'user_id': user_id,
    }

    with _jobs_lock:
        running_jobs[job_id] = job

    def set_phase(job, index, status, phase_name=None):
        if index < len(job['phases']):
            phase = job['phases'][index]
            now = time.time()
            if status == 'running' and phase['start_time'] is None:
                phase['start_time'] = now
            elif status == 'done' and phase['start_time'] is not None:
                phase['duration'] = round(now - phase['start_time'], 1)
            phase['status'] = status
        if phase_name:
            job['current_phase'] = phase_name
            job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] ▶ {phase_name}\n'

    def run_job():
        from app import create_app
        app = create_app()
        report_file = None

        try:
            set_phase(job, 0, 'running', 'Initializing build environment...')
            if is_cnv:
                tests_list = options.get('scenario_tests', [])
                job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] Task: CNV Scenarios ({options.get("scenario_mode", "sanity")} mode)\n'
                job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] Tests: {len(tests_list)} selected\n'
            else:
                job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] Options: RCA={options.get("rca_level")}, Jira={options.get("jira")}, Email={options.get("email")}\n'
                job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] Checks: {len(checks)} selected\n'
            job['output'] += '-' * 60 + '\n'
            job['progress'] = 5
            set_phase(job, 0, 'done')

            set_phase(job, 1, 'running', 'Connecting to cluster...')
            job['progress'] = 10

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                cwd=BASE_DIR,
                bufsize=1,
                start_new_session=True
            )

            job['process'] = process

            stdout_lines = []
            current_phase_idx = 1

            def find_phase_idx(name):
                for i, p in enumerate(job['phases']):
                    if p['name'] == name:
                        return i
                return -1

            # ── Build phase keyword map based on task type ───────────────
            if is_cnv:
                connect_idx = find_phase_idx('Connect')
                verify_idx = find_phase_idx('Verify Setup')
                run_idx = find_phase_idx('Run Scenarios')
                results_idx = find_phase_idx('Collect Results')
                summary_idx = find_phase_idx('Summary')

                phase_keywords = {
                    'Connecting to': (connect_idx, 'Connecting to jump host...', 10),
                    'Connected to': (connect_idx, 'Connected to jump host', 15),
                    'SSH connection established': (connect_idx, 'Connected to jump host', 15),
                    'Verifying cnv-scenarios': (verify_idx, 'Verifying cnv-scenarios setup...', 20),
                    'KUBECONFIG': (verify_idx, 'Setting up environment...', 22),
                    'kubeconfig': (verify_idx, 'Setting up environment...', 22),
                    'Running command': (run_idx, 'Running workload scenarios...', 30),
                    'run-workloads.sh': (run_idx, 'Running workload scenarios...', 30),
                    'Running test': (run_idx, 'Running test scenarios...', 35),
                    'RUNNING': (run_idx, 'Running scenarios...', 40),
                    'kube-burner': (run_idx, 'Running kube-burner workloads...', 50),
                    'Waiting for': (run_idx, 'Waiting for workloads...', 55),
                    'PASS': (run_idx, 'Tests progressing...', 60),
                    'FAIL': (run_idx, 'Tests progressing...', 60),
                    'Collecting results': (results_idx, 'Collecting results...', 75),
                    'summary.json': (results_idx, 'Parsing summary...', 80),
                    'Results:': (summary_idx, 'Generating summary...', 85),
                    'Summary:': (summary_idx, 'Generating summary...', 85),
                    'SUMMARY': (summary_idx, 'Generating summary...', 85),
                    'scenarios complete': (summary_idx, 'Complete!', 95),
                    'All tests': (summary_idx, 'Complete!', 95),
                    'Done': (summary_idx, 'Complete!', 95),
                }
            else:
                scan_jira_idx = find_phase_idx('Scan Jira')
                connect_idx = find_phase_idx('Connect')
                collect_idx = find_phase_idx('Collect Data')
                console_idx = find_phase_idx('Console Report')
                analyze_idx = find_phase_idx('Analyze')
                jira_rca_idx = find_phase_idx('Search Jira')
                email_rca_idx = find_phase_idx('Search Email')
                web_rca_idx = find_phase_idx('Search Web')
                deep_rca_idx = find_phase_idx('Deep RCA')
                report_idx = find_phase_idx('Generate Report')
                email_idx = find_phase_idx('Send Email')

                phase_keywords = {
                    'Checking Jira for new test suggestions': (scan_jira_idx, 'Scanning Jira for new tests...', 3),
                    'Checking Jira for recent bugs': (scan_jira_idx, 'Checking Jira for bugs...', 4),
                    'Analyzed': (scan_jira_idx, 'Analyzing Jira bugs...', 5),
                    'new checks will be included': (scan_jira_idx, 'Jira scan complete', 6),
                    'HealthCrew AI Starting': (connect_idx, 'Initializing...', 8),
                    'Connecting to cluster': (connect_idx, 'Connecting to cluster...', 10),
                    'Connected to': (connect_idx, 'Connected to cluster', 15),
                    'Collecting cluster data': (collect_idx, 'Collecting cluster data...', 18),
                    'Checking nodes': (collect_idx, 'Checking nodes...', 22),
                    'Checking node resources': (collect_idx, 'Checking node resources...', 25),
                    'Getting cluster version': (collect_idx, 'Getting cluster version...', 28),
                    'Checking etcd': (collect_idx, 'Checking etcd health...', 30),
                    'Checking certificates': (collect_idx, 'Checking certificates...', 32),
                    'Checking PVC': (collect_idx, 'Checking PVC status...', 35),
                    'Checking VM migrations': (collect_idx, 'Checking VM migrations...', 38),
                    'Checking alerts': (collect_idx, 'Checking alerts...', 40),
                    'Checking CSI': (collect_idx, 'Checking CSI drivers...', 42),
                    'Checking OOM': (collect_idx, 'Checking OOM events...', 44),
                    'Checking virt-handler': (collect_idx, 'Checking virt-handler pods...', 46),
                    'Checking virt-launcher': (collect_idx, 'Checking virt-launcher pods...', 48),
                    'Checking DataVolumes': (collect_idx, 'Checking DataVolumes...', 50),
                    'Checking HyperConverged': (collect_idx, 'Checking HyperConverged...', 52),
                    'Data collection complete': (collect_idx, 'Data collection complete', 54),
                    'Generating console report': (console_idx, 'Generating console report...', 56),
                    'HEALTH REPORT': (console_idx, 'Displaying health report...', 58),
                    'Starting Root Cause Analysis': (analyze_idx, 'Starting root cause analysis...', 60),
                    '🔬 Starting Root Cause Analysis': (analyze_idx, 'Starting root cause analysis...', 60),
                    'Matching failures to known issues': (analyze_idx, 'Matching failures to known issues...', 62),
                    'issue(s) to analyze': (analyze_idx, 'Analyzing issues...', 64),
                    '→ Searching Jira': (jira_rca_idx, 'Searching Jira for bugs...', 66),
                    'Searching Jira for related bugs': (jira_rca_idx, 'Searching Jira for bugs...', 66),
                    '→ Searching emails': (email_rca_idx, 'Searching emails...', 70),
                    'Searching emails for related': (email_rca_idx, 'Searching emails...', 70),
                    '→ Searching web': (web_rca_idx, 'Searching web docs...', 74),
                    'Running deep investigation': (deep_rca_idx, 'Running deep investigation...', 78),
                    'Deep investigation complete': (deep_rca_idx, 'Deep investigation complete', 82),
                    'Saving HTML report': (report_idx, 'Saving HTML report...', 85),
                    'Saved:': (report_idx, 'Report saved', 88),
                    'Reports saved': (report_idx, 'Reports saved', 90),
                    'Health check complete': (report_idx, 'Complete!', 95),
                    'Sending email report': (email_idx, 'Sending email...', 96),
                    'Email sent successfully': (email_idx, 'Email sent!', 99),
                }

            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    stdout_lines.append(line)
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    job['output'] += f'[{timestamp}] {line}'

                    for keyword, (phase_idx, phase_msg, progress) in phase_keywords.items():
                        if keyword in line and phase_idx >= 0:
                            if phase_idx > current_phase_idx:
                                set_phase(job, current_phase_idx, 'done')
                                for skip_idx in range(current_phase_idx + 1, phase_idx):
                                    if job['phases'][skip_idx]['status'] == 'pending':
                                        job['phases'][skip_idx]['status'] = 'skipped'
                                current_phase_idx = phase_idx
                                set_phase(job, phase_idx, 'running', phase_msg)
                            job['progress'] = progress
                            job['current_phase'] = phase_msg
                            break

                    if not is_cnv and ('Report saved' in line or 'health_report_' in line):
                        import re
                        match = re.search(r'(health_report_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.html)', line)
                        if match:
                            report_file = match.group(1)

            return_code = process.wait()

            for i in range(current_phase_idx, len(phases)):
                set_phase(job, i, 'done')

            job['progress'] = 100

            duration_secs = int(time.time() - job['start_time'])
            duration = f"{duration_secs // 60}m {duration_secs % 60}s"

            full_output = ''.join(stdout_lines)

            if is_cnv:
                # CNV scenario status detection
                has_fail = 'FAIL' in full_output or 'failed' in full_output.lower()
                has_pass = 'PASS' in full_output
                if return_code != 0 or (has_fail and not has_pass):
                    status = 'failed'
                    status_text = 'Failed'
                elif has_fail:
                    status = 'unstable'
                    status_text = 'Partial Pass'
                else:
                    status = 'success'
                    status_text = 'All Passed'
            else:
                has_issues = 'WARNING' in full_output or 'Issues:' in full_output or 'ISSUES' in full_output or '⚠️' in full_output
                has_errors = 'ERROR' in full_output or 'CRITICAL' in full_output or '❌' in full_output
                if return_code != 0 or has_errors:
                    status = 'failed'
                    status_text = 'Failed'
                elif has_issues:
                    status = 'unstable'
                    status_text = 'Issues Found'
                else:
                    status = 'success'
                    status_text = 'Healthy'

            build_record = {
                'number': build_num,
                'name': job.get('name', run_name),
                'status': status,
                'status_text': status_text,
                'checks': checks,
                'checks_count': len(checks),
                'options': options,
                'timestamp': job['timestamp'],
                'duration': duration,
                'output': job['output'],
                'report_file': report_file
            }

            with app.app_context():
                save_build_to_db(build_record, user_id=user_id)

                # Record issues for learning (health checks only)
                if not is_cnv:
                    try:
                        from app.learning import record_health_check_run
                        detected_issues = extract_issues_from_output(full_output)
                        if detected_issues:
                            record_health_check_run(detected_issues)
                    except Exception:
                        pass

                # Send email report if requested
                if options.get('email') and options.get('email_to'):
                    email_phase_idx = find_phase_idx('Send Email')
                    if email_phase_idx is not None:
                        set_phase(job, email_phase_idx, 'running', 'Sending email report...')
                    try:
                        _send_cnv_email_report(
                            recipient=options['email_to'],
                            build_num=build_num,
                            build_name=job.get('name', run_name),
                            status=status,
                            status_text=status_text,
                            duration=duration,
                            checks=checks,
                            options=options,
                            output=full_output,
                        )
                        job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] ✅ Email sent to {options["email_to"]}\n'
                        if email_phase_idx is not None:
                            set_phase(job, email_phase_idx, 'done', 'Email sent!')
                    except Exception as e:
                        job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] ⚠️ Email failed: {e}\n'
                        if email_phase_idx is not None:
                            set_phase(job, email_phase_idx, 'done', f'Email failed: {e}')

        except Exception as e:
            job['output'] += f'\n[{datetime.now().strftime("%H:%M:%S")}] ❌ Error: {str(e)}\n'
            duration_secs = int(time.time() - job['start_time'])
            duration = f"{duration_secs // 60}m {duration_secs % 60}s"

            build_record = {
                'number': build_num,
                'name': run_name,
                'status': 'failed',
                'status_text': 'Error',
                'checks': checks,
                'checks_count': len(checks),
                'options': options,
                'timestamp': job['timestamp'],
                'duration': duration,
                'output': job['output'],
                'report_file': None
            }
            with app.app_context():
                save_build_to_db(build_record, user_id=user_id)

        finally:
            with _jobs_lock:
                if job_id in running_jobs:
                    del running_jobs[job_id]
            # Start next queued build
            _start_next_queued()

    thread = threading.Thread(target=run_job)
    thread.daemon = True
    thread.start()


# =============================================================================
# Settings Routes
# =============================================================================

@dashboard_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings_page():
    """Settings page for configuring defaults"""
    message = None

    # Only admin and operator can change settings
    if request.method == 'POST':
        if not current_user.is_operator:
            return "Access denied. Operator role required.", 403

        # Sync hosts to DB (per-user)
        host_ids = request.form.getlist('host_id[]')
        host_names = request.form.getlist('host_name[]')
        host_addrs = request.form.getlist('host_addr[]')
        host_users = request.form.getlist('host_user[]')
        host_passwords = request.form.getlist('host_password[]')
        # Pad passwords list to match hosts (existing hosts don't have password fields)
        while len(host_passwords) < len(host_ids):
            host_passwords.append('')
        first_host, first_user, ssh_messages = sync_hosts_from_form(
            host_ids, host_names, host_addrs, host_users, host_passwords, current_user
        )

        new_settings = {
            'thresholds': {
                'cpu_warning': int(request.form.get('cpu_warning', 85)),
                'memory_warning': int(request.form.get('memory_warning', 80)),
                'disk_latency': int(request.form.get('disk_latency', 100)),
                'etcd_latency': int(request.form.get('etcd_latency', 100)),
                'pod_density': int(request.form.get('pod_density', 50)),
                'restart_count': int(request.form.get('restart_count', 5)),
                'virt_handler_memory': int(request.form.get('virt_handler_memory', 500))
            },
            'ssh': {
                'host': first_host,
                'user': first_user,
            },
            'ai': {
                'model': request.form.get('ollama_model', 'ollama/llama3.2:3b').strip(),
                'url': request.form.get('ollama_url', 'http://localhost:11434').strip()
            },
            'jira': {
                'projects': [p.strip() for p in request.form.get('jira_projects', 'CNV, OCPBUGS, ODF').split(',')],
                'scan_days': int(request.form.get('jira_scan_days', 30)),
                'bug_limit': int(request.form.get('jira_bug_limit', 50))
            },
            'cnv': {
                'cnv_path': request.form.get('cnv_path', '/home/kni/git/cnv-scenarios').strip(),
                'mode': request.form.get('cnv_mode', 'sanity').strip(),
                'parallel': 'cnv_parallel' in request.form,
                'kb_log_level': request.form.get('cnv_kb_log_level', '').strip(),
                'kb_timeout': request.form.get('cnv_kb_timeout', '').strip(),
                'global_vars': {
                    'storageClassName': request.form.get('cnv_default_storageClassName', '').strip(),
                    'nodeSelector': request.form.get('cnv_default_nodeSelector', '').strip(),
                    'maxWaitTimeout': request.form.get('cnv_default_maxWaitTimeout', '').strip(),
                    'jobPause': request.form.get('cnv_default_jobPause', '').strip(),
                },
                'scenario_vars': _collect_scenario_var_defaults(request.form),
            }
        }

        save_settings(new_settings)

        if first_host:
            _update_env_var('RH_LAB_HOST', first_host)
            _update_env_var('RH_LAB_USER', first_user)

        log_audit('settings_update', details='Settings updated')
        message = "Your settings have been saved successfully."
        if ssh_messages:
            message += " " + " | ".join(ssh_messages)

    settings = load_settings()
    ssh_config = settings.get('ssh', {'host': '', 'user': 'root'})

    # Load hosts from DB (user's own + admin sees all)
    host_objects = get_hosts_for_user(current_user)
    saved_hosts = [h.to_dict() for h in host_objects]

    cnv_config = settings.get('cnv', _DEFAULT_CNV_SETTINGS)

    return render_template('settings.html',
                           thresholds=settings.get('thresholds', DEFAULT_THRESHOLDS),
                           ssh_config=ssh_config,
                           saved_hosts=saved_hosts,
                           ai_config=settings.get('ai', {'model': 'ollama/llama3.2:3b', 'url': 'http://localhost:11434'}),
                           jira_config=settings.get('jira', {'projects': ['CNV', 'OCPBUGS', 'ODF'], 'scan_days': 30, 'bug_limit': 50}),
                           cnv_config=cnv_config,
                           cnv_global_vars=CNV_GLOBAL_VARIABLES,
                           cnv_scenarios=CNV_SCENARIOS,
                           message=message,
                           active_page='settings')


@dashboard_bp.route('/api/settings', methods=['GET'])
@login_required
def api_get_settings():
    return jsonify(load_settings())


@dashboard_bp.route('/api/settings/thresholds', methods=['GET'])
@login_required
def api_get_thresholds():
    return jsonify(get_thresholds())


# =============================================================================
# Host Management API Routes
# =============================================================================

@dashboard_bp.route('/api/hosts', methods=['POST'])
@operator_required
def api_add_host():
    """Add a new jump host (persisted to DB immediately)."""
    data = request.get_json(force=True)
    addr = data.get('host', '').strip()
    name = data.get('name', '').strip() or addr
    user = data.get('user', '').strip() or 'root'

    if not addr:
        return jsonify({'success': False, 'error': 'Host address is required.'})

    label = f'{name} [{current_user.username}]' if not name.endswith(f'[{current_user.username}]') else name
    host_obj = Host(name=label, host=addr, user=user, created_by=current_user.id)
    db.session.add(host_obj)
    db.session.commit()
    log_audit('host_add', target=f'{user}@{addr}', details=f'Added host {label}')
    return jsonify({'success': True, 'host': host_obj.to_dict()})


@dashboard_bp.route('/api/hosts/<int:host_id>', methods=['DELETE'])
@operator_required
def api_delete_host(host_id):
    """Delete a jump host from the DB."""
    host_obj = Host.query.get(host_id)
    if not host_obj:
        return jsonify({'success': False, 'error': 'Host not found.'}), 404
    # Only owner or admin can delete
    if host_obj.created_by != current_user.id and not current_user.is_admin:
        return jsonify({'success': False, 'error': 'Permission denied.'}), 403
    log_audit('host_delete', target=f'{host_obj.user}@{host_obj.host}', details=f'Deleted host {host_obj.name}')
    db.session.delete(host_obj)
    db.session.commit()
    return jsonify({'success': True})


# =============================================================================
# SSH Setup Routes
# =============================================================================

@dashboard_bp.route('/api/ssh/setup', methods=['POST'])
@operator_required
def api_ssh_setup():
    import paramiko
    data = request.get_json(force=True)
    host = data.get('host', '').strip()
    user = data.get('user', '').strip()
    password = data.get('password', '')

    if not host or not user or not password:
        return jsonify({'success': False, 'error': 'Host, user, and password are all required.'})

    home = os.path.expanduser("~")
    ssh_dir = os.path.join(home, ".ssh")
    key_path = os.path.join(ssh_dir, "id_ed25519")
    pub_path = key_path + ".pub"

    try:
        os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
        if not os.path.exists(key_path):
            key = paramiko.Ed25519Key.generate()
            key.write_private_key_file(key_path)
            os.chmod(key_path, 0o600)
            pub_key_str = f"{key.get_name()} {key.get_base64()} cnv-healthcrew"
            with open(pub_path, 'w') as f:
                f.write(pub_key_str + "\n")
            os.chmod(pub_path, 0o644)
        else:
            key = paramiko.Ed25519Key(filename=key_path)
            pub_key_str = f"{key.get_name()} {key.get_base64()} cnv-healthcrew"

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(host, username=user, password=password, timeout=15)

        commands = (
            "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
            f"grep -qxF '{pub_key_str}' ~/.ssh/authorized_keys 2>/dev/null || "
            f"echo '{pub_key_str}' >> ~/.ssh/authorized_keys && "
            "chmod 600 ~/.ssh/authorized_keys"
        )
        stdin, stdout, stderr = client.exec_command(commands)
        exit_status = stdout.channel.recv_exit_status()
        err_output = stderr.read().decode().strip()
        client.close()

        if exit_status != 0:
            return jsonify({'success': False, 'error': f'Failed to install public key: {err_output}'})

        verify_client = paramiko.SSHClient()
        verify_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        verify_client.connect(host, username=user, key_filename=key_path, timeout=15)
        verify_client.close()

        settings = load_settings()
        settings.setdefault('ssh', {})
        settings['ssh']['host'] = host
        settings['ssh']['user'] = user
        save_settings(settings)

        _update_env_var('RH_LAB_HOST', host)
        _update_env_var('RH_LAB_USER', user)
        _update_env_var('SSH_KEY_PATH', key_path)

        # Also save the host to DB if requested (from the combined add-host flow)
        save_host = data.get('save_host', False)
        host_dict = None
        if save_host:
            host_name = data.get('name', '').strip() or host
            label = f'{host_name} [{current_user.username}]' if not host_name.endswith(f'[{current_user.username}]') else host_name
            host_obj = Host(name=label, host=host, user=user, created_by=current_user.id)
            db.session.add(host_obj)
            db.session.commit()
            host_dict = host_obj.to_dict()

        log_audit('ssh_setup', target=f'{user}@{host}', details='SSH key setup completed')

        result = {'success': True, 'message': f'Passwordless SSH to {user}@{host} is now configured.', 'key_path': key_path}
        if host_dict:
            result['host'] = host_dict
        return jsonify(result)

    except paramiko.AuthenticationException:
        return jsonify({'success': False, 'error': 'Authentication failed — wrong password or user.'})
    except paramiko.SSHException as e:
        return jsonify({'success': False, 'error': f'SSH error: {str(e)}'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Unexpected error: {str(e)}'})




def _update_env_var(key, value):
    from pathlib import Path
    installed_cfg = Path.home() / ".config" / "cnv-healthcrew" / "config.env"
    if installed_cfg.exists():
        env_file = str(installed_cfg)
    else:
        env_file = os.path.join(BASE_DIR, ".env")

    lines = []
    found = False
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                if line.strip().startswith(f'{key}='):
                    lines.append(f'{key}={value}\n')
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f'{key}={value}\n')
    with open(env_file, 'w') as f:
        f.writelines(lines)
