"""Schedule CRUD API routes."""
from datetime import datetime

from flask import jsonify, request
from flask_login import current_user, login_required

from config.settings import AVAILABLE_CHECKS

from app.decorators import operator_required

from app.routes import (
    dashboard_bp,
    load_schedules,
    save_schedules,
    get_next_run_time,
    get_cron_display,
    schedules,
)
from app.routes.build_executor import start_build

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
    load_schedules()
    try:
        schedule = next((s for s in schedules if s.get('id') == schedule_id), None)
        if not schedule:
            return jsonify({'success': False, 'error': 'Schedule not found'})
        schedules[:] = [s for s in schedules if s.get('id') != schedule_id]
        save_schedules()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
