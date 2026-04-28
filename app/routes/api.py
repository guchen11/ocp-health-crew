"""Status and management API routes."""
import os
import signal
import subprocess
import time
from datetime import datetime

from flask import jsonify, request
from flask_login import current_user, login_required

from app.decorators import admin_required, log_audit, operator_required

from app.routes import (
    dashboard_bp,
    builds,
    load_builds,
    queued_jobs,
    running_jobs,
    _jobs_lock,
    save_build_to_db,
    _safe_remove_report,
)
from app.routes.build_executor import _start_next_queued

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


@dashboard_bp.route('/api/test-progress/<int:build_num>')
@login_required
def api_test_progress(build_num):
    """API endpoint for per-test live progress of a running build."""
    with _jobs_lock:
        for job_id, job in running_jobs.items():
            if job.get('number') == build_num:
                tp = job.get('test_progress', {})
                # For running tests, compute elapsed time
                now = time.time()
                result = {}
                for tname, info in tp.items():
                    entry = dict(info)
                    if entry['status'] == 'running' and entry.get('start_time'):
                        elapsed = int(now - entry['start_time'])
                        entry['elapsed'] = f"{elapsed // 60}m {elapsed % 60}s"
                    result[tname] = entry
                return jsonify({
                    'running': True,
                    'build_num': build_num,
                    'test_progress': result,
                    'current_phase': job.get('current_phase', ''),
                    'progress': job.get('progress', 0),
                })
    # Not running — check completed builds
    load_builds()
    build = next((b for b in builds if b.get('number') == build_num), None)
    if build:
        return jsonify({'running': False, 'build_num': build_num, 'status': build.get('status', 'unknown')})
    return jsonify({'running': False, 'build_num': build_num, 'status': 'not_found'}), 404


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
            _safe_remove_report(report_file)

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
                _safe_remove_report(report_file)
            db.session.delete(build)
            deleted_count += 1

        db.session.commit()
        log_audit('build_bulk_delete', details=f'Deleted {deleted_count} builds (filter: {filter_type})')
        return jsonify({'success': True, 'deleted': deleted_count})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
