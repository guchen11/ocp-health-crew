"""
CNV Health Dashboard - Flask Routes
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

# Import configuration
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import Config, AVAILABLE_CHECKS

# Create Blueprint
dashboard_bp = Blueprint('dashboard', __name__)

# Configuration
BASE_DIR = Config.BASE_DIR
REPORTS_DIR = Config.REPORTS_DIR
SCRIPT_PATH = os.path.join(BASE_DIR, "hybrid_health_check.py")
BUILDS_FILE = Config.BUILDS_FILE
SCHEDULES_FILE = os.path.join(BASE_DIR, "schedules.json")
SETTINGS_FILE = os.path.join(BASE_DIR, ".settings.json")

# Store for running jobs
running_jobs = {}
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

# Default settings
DEFAULT_SETTINGS = {
    'thresholds': DEFAULT_THRESHOLDS,
    'ssh': {'host': '', 'user': 'root'},
    'ai': {'model': 'ollama/llama3.2:3b', 'url': 'http://localhost:11434'},
    'jira': {'projects': ['CNV', 'OCPBUGS', 'ODF'], 'scan_days': 30, 'bug_limit': 50}
}


def load_settings():
    """Load user settings from file"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                # Merge with defaults to handle new settings
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


def get_thresholds():
    """Get current threshold settings"""
    settings = load_settings()
    return settings.get('thresholds', DEFAULT_THRESHOLDS)


def load_builds():
    """Load builds from file"""
    global builds
    if os.path.exists(BUILDS_FILE):
        try:
            with open(BUILDS_FILE, 'r') as f:
                builds = json.load(f)
        except:
            builds = []
    return builds


def save_builds():
    """Save builds to file"""
    with open(BUILDS_FILE, 'w') as f:
        json.dump(builds[-Config.MAX_BUILDS_HISTORY:], f)


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
        next_run = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return next_run.strftime('%Y-%m-%d %H:%M')
    
    hour, minute = map(int, time_str.split(':'))
    
    if frequency == 'daily':
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        return next_run.strftime('%Y-%m-%d %H:%M')
    
    if frequency == 'weekly':
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


def get_next_build_number():
    """Get next build number"""
    if not builds:
        return 1
    return max(b.get('number', 0) for b in builds) + 1


# Load builds and schedules on startup
load_builds()
load_schedules()


# =============================================================================
# ROUTES
# =============================================================================

@dashboard_bp.route('/help')
def help_page():
    """Help and documentation page"""
    return render_template('help.html', active_page='help')


@dashboard_bp.route('/')
def dashboard():
    """Main dashboard"""
    load_builds()
    
    # Get running build if any
    running_build = None
    if running_jobs:
        job_id = list(running_jobs.keys())[0]
        running_build = running_jobs[job_id]
    
    # Calculate stats
    stats = {
        'total': len(builds),
        'success': sum(1 for b in builds if b.get('status') == 'success'),
        'unstable': sum(1 for b in builds if b.get('status') == 'unstable'),
        'failed': sum(1 for b in builds if b.get('status') == 'failed')
    }
    
    return render_template('dashboard.html',
                          builds=builds[:10],
                          recent_builds=builds[:10],
                          stats=stats,
                          running_build=running_build,
                          active_page='dashboard')


@dashboard_bp.route('/job/configure')
def configure():
    """Build configuration page"""
    categories = sorted(set(c['category'] for c in AVAILABLE_CHECKS.values()))
    preset = request.args.get('preset', '')
    settings = load_settings()
    thresholds = settings.get('thresholds', DEFAULT_THRESHOLDS)
    return render_template('configure.html',
                          checks=AVAILABLE_CHECKS,
                          categories=categories,
                          preset=preset,
                          thresholds=thresholds,
                          server_host=settings.get('ssh', {}).get('host', ''),
                          active_page='configure')


@dashboard_bp.route('/job/run', methods=['POST'])
def run_build():
    """Start a new build or schedule one"""
    import uuid
    
    selected_checks = request.form.getlist('checks')
    if not selected_checks:
        selected_checks = list(AVAILABLE_CHECKS.keys())
    
    rca_level = request.form.get('rca_level', 'none')
    run_name = request.form.get('run_name', '').strip()
    
    # Get thresholds - either custom or defaults
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
    
    options = {
        'server_host': request.form.get('server_host', '').strip(),
        'rca_level': rca_level,
        'rca_jira': 'rca_jira' in request.form,
        'rca_email': 'rca_email' in request.form,
        'rca_web': 'rca_web' in request.form,
        'jira': 'check_jira' in request.form,
        'email': 'send_email' in request.form,
        'email_to': request.form.get('email_to', Config.DEFAULT_EMAIL),
        'run_name': run_name,
        'thresholds': thresholds
    }
    
    # Handle scheduling
    schedule_type = request.form.get('schedule_type', 'now')
    
    if schedule_type == 'now':
        # Run immediately
        start_build(selected_checks, options)
        return redirect(url_for('dashboard.dashboard'))
    
    elif schedule_type == 'once':
        # Schedule for a specific date/time
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
                'last_run': None
            }
            schedules.append(schedule)
            save_schedules()
            return redirect(url_for('dashboard.schedules_page'))
    
    elif schedule_type == 'recurring':
        # Set up recurring schedule
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
            'last_run': None
        }
        
        # Add frequency-specific details
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
    
    # Fallback - run now
    start_build(selected_checks, options)
    return redirect(url_for('dashboard.dashboard'))


@dashboard_bp.route('/job/quick-run')
def quick_run():
    """Quick build - redirect to configure with all checks selected"""
    return redirect(url_for('dashboard.configure') + '?preset=all')


@dashboard_bp.route('/job/history')
def history():
    """Build history page"""
    load_builds()
    status_filter = request.args.get('status')
    
    filtered_builds = builds
    if status_filter:
        filtered_builds = [b for b in builds if b.get('status') == status_filter]
    
    return render_template('history.html', 
                          builds=filtered_builds,
                          active_page='history')


@dashboard_bp.route('/schedules')
def schedules_page():
    """Scheduled tasks page"""
    load_schedules()
    status_filter = request.args.get('status')
    
    # Update next run times
    for schedule in schedules:
        schedule['next_run'] = get_next_run_time(schedule)
        schedule['cron_display'] = get_cron_display(schedule)
    
    filtered_schedules = schedules
    if status_filter:
        filtered_schedules = [s for s in schedules if s.get('status') == status_filter]
    
    # Calculate scheduler stats
    scheduler_status = {
        'active_schedules': sum(1 for s in schedules if s.get('status') == 'active'),
        'runs_today': sum(1 for b in builds if b.get('timestamp', '').startswith(datetime.now().strftime('%Y-%m-%d')) and b.get('scheduled', False)),
        'next_run': min((s.get('next_run') for s in schedules if s.get('status') == 'active' and s.get('next_run')), default=None)
    }
    
    return render_template('schedules.html',
                          schedules=filtered_schedules,
                          scheduler_status=scheduler_status,
                          active_page='schedules')


@dashboard_bp.route('/job/<int:build_num>')
def build_detail(build_num):
    """Build detail page"""
    load_builds()
    build = next((b for b in builds if b.get('number') == build_num), None)
    
    if not build:
        if running_jobs:
            job_id = list(running_jobs.keys())[0]
            if running_jobs[job_id].get('number') == build_num:
                build = running_jobs[job_id]
    
    if not build:
        return "Build not found", 404
    
    return render_template('build_detail.html', 
                          build=build, 
                          checks=AVAILABLE_CHECKS,
                          active_page='history')


@dashboard_bp.route('/job/<int:build_num>/console')
def console_output(build_num):
    """Console output page"""
    load_builds()
    build = next((b for b in builds if b.get('number') == build_num), None)
    
    if not build and running_jobs:
        job_id = list(running_jobs.keys())[0]
        if running_jobs[job_id].get('number') == build_num:
            build = running_jobs[job_id]
    
    if not build:
        return "Build not found", 404
    
    return render_template('console.html', build=build, active_page='history')


@dashboard_bp.route('/job/rebuild/<int:build_num>')
def rebuild(build_num):
    """Rebuild with same parameters"""
    load_builds()
    build = next((b for b in builds if b.get('number') == build_num), None)
    
    if build:
        checks = build.get('checks', list(AVAILABLE_CHECKS.keys()))
        options = build.get('options', {'rca_level': 'none', 'jira': False, 'email': False})
        start_build(checks, options)
    
    return redirect(url_for('dashboard.dashboard'))


@dashboard_bp.route('/report/<filename>')
def serve_report(filename):
    """Serve report files"""
    return send_from_directory(REPORTS_DIR, filename)


# =============================================================================
# API ENDPOINTS
# =============================================================================

@dashboard_bp.route('/api/status')
def api_status():
    """API endpoint for build status"""
    if running_jobs:
        job_id = list(running_jobs.keys())[0]
        job = running_jobs[job_id]
        return jsonify({
            'running': True,
            'output': job.get('output', ''),
            'progress': job.get('progress', 0),
            'phases': job.get('phases', []),
            'current_phase': job.get('current_phase', ''),
            'start_time': job.get('start_time', 0)
        })
    return jsonify({'running': False})


@dashboard_bp.route('/api/stop', methods=['POST'])
def api_stop():
    """API endpoint to stop running build"""
    global builds
    if running_jobs:
        job_id = list(running_jobs.keys())[0]
        job = running_jobs[job_id]
        
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
            
            job['output'] += f'\n[{datetime.now().strftime("%H:%M:%S")}] ⛔ Build stopped by user\n'
            job['current_phase'] = 'Stopped by user'
            
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
            
            builds.insert(0, build_record)
            save_builds()
            del running_jobs[job_id]
            
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    
    return jsonify({'success': False, 'error': 'No running build'})


@dashboard_bp.route('/api/delete/<int:build_num>', methods=['POST'])
def api_delete(build_num):
    """API endpoint to delete a build and its report"""
    global builds
    load_builds()
    
    try:
        build = next((b for b in builds if b.get('number') == build_num), None)
        
        if not build:
            return jsonify({'success': False, 'error': 'Build not found'})
        
        report_file = build.get('report_file')
        if report_file:
            report_path = os.path.join(REPORTS_DIR, report_file)
            if os.path.exists(report_path):
                os.remove(report_path)
            md_file = report_file.replace('.html', '.md')
            md_path = os.path.join(REPORTS_DIR, md_file)
            if os.path.exists(md_path):
                os.remove(md_path)
        
        builds = [b for b in builds if b.get('number') != build_num]
        save_builds()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/delete-bulk', methods=['POST'])
def api_delete_bulk():
    """API endpoint to delete multiple builds by status filter"""
    global builds
    load_builds()
    
    try:
        data = request.get_json() or {}
        filter_type = data.get('filter', 'all')  # 'all', 'failed', 'stopped'
        
        # Determine which builds to delete
        if filter_type == 'all':
            builds_to_delete = builds[:]
        elif filter_type == 'failed':
            builds_to_delete = [b for b in builds if b.get('status') == 'failed']
        elif filter_type == 'stopped':
            builds_to_delete = [b for b in builds if b.get('status_text') == 'Stopped']
        else:
            return jsonify({'success': False, 'error': 'Invalid filter type'})
        
        deleted_count = 0
        
        # Delete report files for each build
        for build in builds_to_delete:
            report_file = build.get('report_file')
            if report_file:
                report_path = os.path.join(REPORTS_DIR, report_file)
                if os.path.exists(report_path):
                    os.remove(report_path)
                md_file = report_file.replace('.html', '.md')
                md_path = os.path.join(REPORTS_DIR, md_file)
                if os.path.exists(md_path):
                    os.remove(md_path)
            deleted_count += 1
        
        # Remove from builds list
        build_nums_to_delete = {b.get('number') for b in builds_to_delete}
        builds = [b for b in builds if b.get('number') not in build_nums_to_delete]
        save_builds()
        
        return jsonify({'success': True, 'deleted': deleted_count})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# =============================================================================
# SCHEDULE API ENDPOINTS
# =============================================================================

@dashboard_bp.route('/api/schedules')
def api_get_schedules():
    """API endpoint to get all schedules"""
    load_schedules()
    
    # Update next run times
    for schedule in schedules:
        schedule['next_run'] = get_next_run_time(schedule)
        schedule['cron_display'] = get_cron_display(schedule)
    
    return jsonify({'success': True, 'schedules': schedules})


@dashboard_bp.route('/api/schedule', methods=['POST'])
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
def api_schedule_run(schedule_id):
    """API endpoint to run a schedule immediately"""
    load_schedules()
    
    try:
        schedule = next((s for s in schedules if s.get('id') == schedule_id), None)
        
        if not schedule:
            return jsonify({'success': False, 'error': 'Schedule not found'})
        
        # Run the build with the schedule's configuration
        checks = schedule.get('checks', list(AVAILABLE_CHECKS.keys()))
        options = schedule.get('options', {'rca_level': 'none'})
        
        # Mark as scheduled build
        options['scheduled'] = True
        options['schedule_id'] = schedule_id
        options['schedule_name'] = schedule.get('name', 'Scheduled')
        
        start_build(checks, options)
        
        # Update last run time
        schedule['last_run'] = datetime.now().strftime('%Y-%m-%d %H:%M')
        save_schedules()
        
        return jsonify({'success': True, 'message': 'Build started'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/schedule/<schedule_id>', methods=['DELETE'])
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

# Store for suggested checks
SUGGESTED_CHECKS_FILE = os.path.join(BASE_DIR, ".suggested_checks.json")
suggested_checks = []


def load_suggested_checks():
    """Load suggested checks from file"""
    global suggested_checks
    if os.path.exists(SUGGESTED_CHECKS_FILE):
        try:
            with open(SUGGESTED_CHECKS_FILE, 'r') as f:
                suggested_checks = json.load(f)
        except:
            suggested_checks = []
    return suggested_checks


def save_suggested_checks():
    """Save suggested checks to file"""
    with open(SUGGESTED_CHECKS_FILE, 'w') as f:
        json.dump(suggested_checks, f, indent=2)


@dashboard_bp.route('/api/jira/suggestions')
def api_jira_suggestions():
    """API endpoint to get Jira-based test suggestions"""
    try:
        # Import the functions from hybrid_health_check.py
        sys.path.insert(0, BASE_DIR)
        from hybrid_health_check import (
            get_known_recent_bugs, 
            get_existing_check_names,
            analyze_bugs_for_new_checks,
            search_jira_for_new_bugs
        )
        
        # Get existing check names
        existing_checks = get_existing_check_names()
        
        # Load previously suggested checks to exclude accepted ones
        load_suggested_checks()
        accepted_checks = {s['name'] for s in suggested_checks if s.get('status') == 'accepted'}
        existing_checks.extend(list(accepted_checks))
        
        # Search Jira for recent bugs (try real search first, fall back to known bugs)
        try:
            bugs = search_jira_for_new_bugs(days=30, limit=50)
        except:
            bugs = None
        
        if not bugs:
            bugs = get_known_recent_bugs()
        
        # Analyze bugs for potential new checks
        suggestions = analyze_bugs_for_new_checks(bugs, existing_checks)
        
        # Filter out already rejected checks (within last 7 days)
        rejected_recently = {
            s['name'] for s in suggested_checks 
            if s.get('status') == 'rejected' and s.get('rejected_at')
        }
        suggestions = [s for s in suggestions if s['suggested_check'] not in rejected_recently]
        
        return jsonify({
            'success': True, 
            'suggestions': suggestions,
            'count': len(suggestions),
            'bugs_analyzed': len(bugs)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'suggestions': []})


@dashboard_bp.route('/api/jira/accept-check', methods=['POST'])
def api_jira_accept_check():
    """API endpoint to accept a suggested health check"""
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
        
        # Add to suggested checks with accepted status
        check_record = {
            'name': check_name,
            'jira_key': jira_key,
            'description': description,
            'category': category,
            'status': 'accepted',
            'accepted_at': datetime.now().strftime('%Y-%m-%d %H:%M')
        }
        
        # Update or add
        existing = next((s for s in suggested_checks if s['name'] == check_name), None)
        if existing:
            existing.update(check_record)
        else:
            suggested_checks.append(check_record)
        
        save_suggested_checks()
        
        # Also add to AVAILABLE_CHECKS for the session
        AVAILABLE_CHECKS[check_name] = {
            'name': check_name.replace('_', ' ').title(),
            'description': description,
            'category': category,
            'default': True,
            'jira': jira_key,
            'custom': True
        }
        
        return jsonify({
            'success': True, 
            'message': f'Check "{check_name}" added successfully',
            'check': check_record
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/jira/reject-check', methods=['POST'])
def api_jira_reject_check():
    """API endpoint to reject a suggested health check"""
    global suggested_checks
    load_suggested_checks()
    
    try:
        data = request.get_json() or {}
        check_name = data.get('name', '')
        
        if not check_name:
            return jsonify({'success': False, 'error': 'Check name is required'})
        
        # Add to suggested checks with rejected status
        check_record = {
            'name': check_name,
            'status': 'rejected',
            'rejected_at': datetime.now().strftime('%Y-%m-%d %H:%M')
        }
        
        # Update or add
        existing = next((s for s in suggested_checks if s['name'] == check_name), None)
        if existing:
            existing.update(check_record)
        else:
            suggested_checks.append(check_record)
        
        save_suggested_checks()
        
        return jsonify({
            'success': True, 
            'message': f'Check "{check_name}" rejected'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/jira/accepted-checks')
def api_jira_accepted_checks():
    """API endpoint to get list of accepted custom checks"""
    load_suggested_checks()
    
    accepted = [s for s in suggested_checks if s.get('status') == 'accepted']
    return jsonify({
        'success': True,
        'checks': accepted,
        'count': len(accepted)
    })


# =============================================================================
# LEARNING & PATTERNS API ENDPOINTS
# =============================================================================

@dashboard_bp.route('/api/learning/stats')
def api_learning_stats():
    """API endpoint to get learning system statistics"""
    try:
        from app.learning import get_learning_stats, get_issue_trends, get_recurring_issues
        
        stats = get_learning_stats()
        trends = get_issue_trends(days=7)
        recurring = get_recurring_issues(min_count=2)
        
        return jsonify({
            'success': True,
            'stats': stats,
            'trends': trends,
            'recurring_count': len(recurring)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/learning/patterns')
def api_learning_patterns():
    """API endpoint to get discovered patterns"""
    try:
        from app.learning import get_learned_patterns
        
        patterns = get_learned_patterns()
        return jsonify({
            'success': True,
            'patterns': patterns,
            'count': len(patterns)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/learning/recurring')
def api_learning_recurring():
    """API endpoint to get recurring issues"""
    try:
        from app.learning import get_recurring_issues
        
        min_count = request.args.get('min_count', 2, type=int)
        recurring = get_recurring_issues(min_count=min_count)
        
        # Sort by count descending
        sorted_recurring = dict(sorted(recurring.items(), key=lambda x: -x[1]['count']))
        
        return jsonify({
            'success': True,
            'recurring_issues': sorted_recurring,
            'count': len(sorted_recurring)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@dashboard_bp.route('/api/learning/trends')
def api_learning_trends():
    """API endpoint to get issue trends"""
    try:
        from app.learning import get_issue_trends
        
        days = request.args.get('days', 7, type=int)
        trends = get_issue_trends(days=days)
        
        return jsonify({
            'success': True,
            'trends': trends
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# =============================================================================
# BUILD EXECUTION
# =============================================================================

def extract_issues_from_output(output):
    """
    Extract detected issues from health check output for learning.
    Parses the output to find pods, operators, VMs, etc. with issues.
    """
    import re
    issues = []
    
    # Pattern to match unhealthy pods
    # Example: "❌ openshift-cnv/virt-handler-xyz  CrashLoopBackOff"
    pod_pattern = r'[❌⚠️]\s*(\S+)/(\S+)\s+(\S+.*?)(?:\n|$)'
    for match in re.finditer(pod_pattern, output):
        issues.append({
            'type': 'pod',
            'namespace': match.group(1),
            'name': match.group(2),
            'status': match.group(3).strip()
        })
    
    # Pattern to match degraded operators
    # Example: "⚠️ machine-config  Degraded"
    operator_pattern = r'[❌⚠️]\s*([\w-]+)\s+(Degraded|Unavailable|Not Available)'
    for match in re.finditer(operator_pattern, output, re.IGNORECASE):
        issues.append({
            'type': 'operator',
            'name': match.group(1),
            'status': match.group(2)
        })
    
    # Pattern to match failed migrations
    migration_pattern = r'migration.*?(failed|stuck|error)'
    for match in re.finditer(migration_pattern, output, re.IGNORECASE):
        issues.append({
            'type': 'migration',
            'name': 'vm-migration',
            'status': match.group(1)
        })
    
    # Pattern to match storage issues
    storage_pattern = r'(pvc|volume|storage|odf).*?(pending|failed|error|not ready)'
    for match in re.finditer(storage_pattern, output, re.IGNORECASE):
        issues.append({
            'type': 'storage',
            'name': match.group(1),
            'status': match.group(2)
        })
    
    # Pattern to match node issues
    node_pattern = r'node[s]?\s+(\S+)\s+(NotReady|SchedulingDisabled)'
    for match in re.finditer(node_pattern, output, re.IGNORECASE):
        issues.append({
            'type': 'node',
            'name': match.group(1),
            'status': match.group(2)
        })
    
    # Pattern to match OOM events
    if 'OOMKilled' in output or 'oom' in output.lower():
        issues.append({
            'type': 'resource',
            'name': 'oom-event',
            'status': 'OOMKilled'
        })
    
    # Deduplicate by (type, name)
    seen = set()
    unique_issues = []
    for issue in issues:
        key = (issue['type'], issue.get('name', ''), issue.get('namespace', ''))
        if key not in seen:
            seen.add(key)
            unique_issues.append(issue)
    
    return unique_issues


def start_build(checks, options):
    """Start a new build"""
    global builds
    
    if running_jobs:
        return
    
    build_num = get_next_build_number()
    job_id = f"build_{build_num}"
    
    cmd = [sys.executable, SCRIPT_PATH]
    
    server_host = options.get('server_host', '')
    if server_host:
        cmd.extend(['--server', server_host])
    
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
    
    # Add Scan Jira phase if jira integration is enabled (happens before Connect)
    if options.get('jira'):
        phases.append({'name': 'Scan Jira', 'status': 'pending', 'start_time': None, 'duration': None})
    
    phases.extend([
        {'name': 'Connect', 'status': 'pending', 'start_time': None, 'duration': None},
        {'name': 'Collect Data', 'status': 'pending', 'start_time': None, 'duration': None},
        {'name': 'Console Report', 'status': 'pending', 'start_time': None, 'duration': None},
        {'name': 'Analyze', 'status': 'pending', 'start_time': None, 'duration': None},
        {'name': 'Generate Report', 'status': 'pending', 'start_time': None, 'duration': None},
    ])
    
    # Calculate base index for RCA phases (after Analyze)
    rca_phase_idx = len(phases) - 1  # Position before Generate Report
    if rca_level != 'none':
        # Full RCA mode automatically includes Jira and Email search
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
    
    running_jobs[job_id] = {
        'number': build_num,
        'name': run_name,
        'status': 'running',
        'status_text': 'Running',
        'output': f'[{datetime.now().strftime("%H:%M:%S")}] Starting build #{build_num}' + (f' "{run_name}"' if run_name else '') + '...\n',
        'checks': checks,
        'checks_count': len(checks),
        'options': options,
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M"),
        'start_time': time.time(),
        'progress': 5,
        'phases': phases,
        'current_phase': 'Initializing...'
    }
    
    def set_phase(job, index, status, phase_name=None):
        if index < len(job['phases']):
            phase = job['phases'][index]
            now = time.time()
            
            # Track timing
            if status == 'running' and phase['start_time'] is None:
                phase['start_time'] = now
            elif status == 'done' and phase['start_time'] is not None:
                phase['duration'] = round(now - phase['start_time'], 1)
            
            phase['status'] = status
        
        if phase_name:
            job['current_phase'] = phase_name
            job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] ▶ {phase_name}\n'
    
    def run_job():
        job = running_jobs[job_id]
        report_file = None
        
        try:
            set_phase(job, 0, 'running', 'Initializing build environment...')
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
            
            rca_level = options.get('rca_level', 'none')
            
            # Calculate dynamic phase indices based on which phases are enabled
            # Find indices by looking up phase names in the job's phases list
            def find_phase_idx(name):
                for i, p in enumerate(job['phases']):
                    if p['name'] == name:
                        return i
                return -1
            
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
            
            # Debug: Log all phases and indices
            phase_names = [p['name'] for p in job['phases']]
            job['output'] += f'[DEBUG] All phases ({len(phase_names)}): {phase_names}\n'
            job['output'] += f'[DEBUG] Phase indices: Analyze={analyze_idx}, SearchJira={jira_rca_idx}, SearchEmail={email_rca_idx}, SearchWeb={web_rca_idx}, DeepRCA={deep_rca_idx}, Report={report_idx}\n'
            
            # Warn if Search Web is requested but not found in phases
            if web_rca_idx == -1 and options.get('rca_web'):
                job['output'] += f'[DEBUG WARNING] rca_web is True but Search Web phase not found in phases list!\n'
            
            phase_keywords = {
                # Scan Jira phase (if enabled)
                'Checking Jira for new test suggestions': (scan_jira_idx, 'Scanning Jira for new tests...', 3),
                'Checking Jira for recent bugs': (scan_jira_idx, 'Checking Jira for bugs...', 4),
                'Analyzed': (scan_jira_idx, 'Analyzing Jira bugs...', 5),
                'new checks will be included': (scan_jira_idx, 'Jira scan complete', 6),
                
                # Connection phase
                'HealthCrew AI Starting': (connect_idx, 'Initializing...', 8),
                'Connecting to cluster': (connect_idx, 'Connecting to cluster...', 10),
                'Connected to': (connect_idx, 'Connected to cluster', 15),
                
                # Collect Data phase
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
                
                # Console Report phase
                'Generating console report': (console_idx, 'Generating console report...', 56),
                'HEALTH REPORT': (console_idx, 'Displaying health report...', 58),
                
                # Analyze phase
                'Starting Root Cause Analysis': (analyze_idx, 'Starting root cause analysis...', 60),
                '🔬 Starting Root Cause Analysis': (analyze_idx, 'Starting root cause analysis...', 60),
                'Matching failures to known issues': (analyze_idx, 'Matching failures to known issues...', 62),
                'issue(s) to analyze': (analyze_idx, 'Analyzing issues...', 64),
                
                # RCA sub-phases
                '→ Searching Jira': (jira_rca_idx, 'Searching Jira for bugs...', 66),
                'Searching Jira for related bugs': (jira_rca_idx, 'Searching Jira for bugs...', 66),
                '→ Searching emails': (email_rca_idx, 'Searching emails...', 70),
                'Searching emails for related': (email_rca_idx, 'Searching emails...', 70),
                '→ Searching web': (web_rca_idx, 'Searching web docs...', 74),
                'Running deep investigation': (deep_rca_idx, 'Running deep investigation...', 78),
                'Deep investigation complete': (deep_rca_idx, 'Deep investigation complete', 82),
                
                # Generate Report phase - use "Saving" not "Generating" (Generating appears before RCA)
                'Saving HTML report': (report_idx, 'Saving HTML report...', 85),
                'Saved:': (report_idx, 'Report saved', 88),
                'Reports saved': (report_idx, 'Reports saved', 90),
                'Health check complete': (report_idx, 'Complete!', 95),
                
                # Email phase
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
                            # Debug: log every keyword match
                            job['output'] += f'[DEBUG] Keyword matched: "{keyword}" -> phase_idx={phase_idx}, current_phase_idx={current_phase_idx}\n'
                            if phase_idx > current_phase_idx:
                                # Mark current phase as done
                                set_phase(job, current_phase_idx, 'done')
                                # Mark any skipped phases in between as 'skipped'
                                skipped_phases = []
                                for skip_idx in range(current_phase_idx + 1, phase_idx):
                                    phase_name = job['phases'][skip_idx]['name']
                                    phase_status = job['phases'][skip_idx]['status']
                                    if phase_status == 'pending':
                                        job['phases'][skip_idx]['status'] = 'skipped'
                                        skipped_phases.append(f'{skip_idx}:{phase_name}')
                                if skipped_phases:
                                    job['output'] += f'[DEBUG] Skipped phases: {", ".join(skipped_phases)}\n'
                                job['output'] += f'[DEBUG] Transition: phase {current_phase_idx} -> {phase_idx} ({phase_msg})\n'
                                current_phase_idx = phase_idx
                                # Only set to 'running' when transitioning to a NEW phase
                                set_phase(job, phase_idx, 'running', phase_msg)
                            # Update progress and phase message for current phase
                            job['progress'] = progress
                            job['current_phase'] = phase_msg
                            break
                    
                    if 'Report saved' in line or 'health_report_' in line:
                        import re
                        # Match format: health_report_YYYY-MM-DD_HH-MM-SS.html
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
                'name': run_name,
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
            
            builds.insert(0, build_record)
            save_builds()
            
            # Record issues for learning (pattern recognition & "gets smarter")
            try:
                from app.learning import record_health_check_run
                detected_issues = extract_issues_from_output(full_output)
                if detected_issues:
                    record_health_check_run(detected_issues)
                    job['output'] += f'\n[{datetime.now().strftime("%H:%M:%S")}] 🧠 Recorded {len(detected_issues)} issues for learning\n'
            except Exception as learn_err:
                pass  # Learning is optional, don't fail the build
            
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
            
            builds.insert(0, build_record)
            save_builds()
        
        finally:
            if job_id in running_jobs:
                del running_jobs[job_id]
    
    thread = threading.Thread(target=run_job)
    thread.daemon = True
    thread.start()


# =============================================================================
# Settings Routes
# =============================================================================

@dashboard_bp.route('/settings', methods=['GET', 'POST'])
def settings_page():
    """Settings page for configuring defaults"""
    message = None
    
    if request.method == 'POST':
        # Save settings
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
                'host': request.form.get('ssh_host', '').strip(),
                'user': request.form.get('ssh_user', 'root').strip()
            },
            'ai': {
                'model': request.form.get('ollama_model', 'ollama/llama3.2:3b').strip(),
                'url': request.form.get('ollama_url', 'http://localhost:11434').strip()
            },
            'jira': {
                'projects': [p.strip() for p in request.form.get('jira_projects', 'CNV, OCPBUGS, ODF').split(',')],
                'scan_days': int(request.form.get('jira_scan_days', 30)),
                'bug_limit': int(request.form.get('jira_bug_limit', 50))
            }
        }
        
        save_settings(new_settings)
        message = "Your settings have been saved successfully."
    
    # Load current settings
    settings = load_settings()
    
    return render_template('settings.html',
                          thresholds=settings.get('thresholds', DEFAULT_THRESHOLDS),
                          ssh_config=settings.get('ssh', {'host': '', 'user': 'root'}),
                          ai_config=settings.get('ai', {'model': 'ollama/llama3.2:3b', 'url': 'http://localhost:11434'}),
                          jira_config=settings.get('jira', {'projects': ['CNV', 'OCPBUGS', 'ODF'], 'scan_days': 30, 'bug_limit': 50}),
                          message=message,
                          active_page='settings')


@dashboard_bp.route('/api/settings', methods=['GET'])
def api_get_settings():
    """API endpoint to get current settings"""
    return jsonify(load_settings())


@dashboard_bp.route('/api/settings/thresholds', methods=['GET'])
def api_get_thresholds():
    """API endpoint to get current thresholds"""
    return jsonify(get_thresholds())
