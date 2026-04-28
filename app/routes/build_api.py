"""Build-trigger API routes."""
from datetime import datetime

from flask import redirect, request, url_for
from flask_login import current_user

from config.settings import AVAILABLE_CHECKS, CNV_SCENARIOS, Config

from app.decorators import operator_required

from app.routes import dashboard_bp, get_thresholds, schedules, save_schedules
from app.routes.build_executor import start_build

@dashboard_bp.route('/job/run', methods=['POST'])
@operator_required
def run_build():
    """Start a new build or schedule one"""
    import uuid

    task_type = request.form.get('task_type', 'health_check')
    run_name = request.form.get('run_name', '').strip()
    server_host = request.form.get('server_host', '').strip()

    # ── CNV Scenarios task ───────────────────────────────────────────────
    if task_type in ('cnv_scenarios', 'cnv_combined'):
        selected_tests = request.form.getlist('scenario_tests')
        if not selected_tests:
            selected_tests = [s['remote_name'] for s in CNV_SCENARIOS.values() if s.get('default')]

        scenario_mode = request.form.get('scenario_mode', 'sanity')
        scenario_parallel = 'scenario_parallel' in request.form
        cnv_path = request.form.get('cnv_path', '/home/kni/git/cnv-scenarios').strip()

        # Collect env-var overrides from the form
        env_overrides = []
        seen_vars = set()
        for key in request.form:
            if key.startswith('cnv_var_'):
                var_name = key[len('cnv_var_'):]
                if var_name in seen_vars:
                    continue
                seen_vars.add(var_name)
                # For checkboxes (bool), getlist returns ['false','true'] when checked
                values = request.form.getlist(key)
                value = values[-1].strip() if values else ''
                if value:
                    env_overrides.append(f"{var_name}={value}")

        kb_log_level = request.form.get('kb_log_level', '').strip()
        kb_timeout = request.form.get('kb_timeout', '').strip()

        # For combined runs: force cleanup=false in env vars so resources
        # stay on the cluster for the health check, then cleanup later.
        combined_cleanup = False
        if task_type == 'cnv_combined':
            combined_cleanup = 'combined_cleanup' in request.form
            # Strip any existing cleanup override and force false
            env_overrides = [e for e in env_overrides if not e.startswith('cleanup=')]
            env_overrides.append('cleanup=false')

        options = {
            'task_type': task_type,
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
            'scenario_custom_checks': [int(x) for x in request.form.getlist('scenario_custom_checks')],
        }

        if task_type == 'cnv_combined':
            options['combined_cleanup'] = combined_cleanup

            # ── Collect health-check options for the combined run ─────────
            options['rca_level'] = request.form.get('rca_level', 'none')
            options['rca_jira'] = 'rca_jira' in request.form
            options['rca_email'] = 'rca_email' in request.form
            options['rca_web'] = 'rca_web' in request.form
            options['jira'] = 'check_jira' in request.form

            # Health-check email (separate from CNV email)
            if 'send_email' in request.form:
                options['email'] = True
                options['email_to'] = request.form.get('email_to', Config.DEFAULT_EMAIL)

            options['hc_checks'] = request.form.getlist('checks')
            options['hc_custom_checks'] = [int(x) for x in request.form.getlist('custom_checks')]

            # Thresholds
            current_thresholds = get_thresholds()
            use_custom = 'use_custom_thresholds' in request.form
            options['thresholds'] = {
                'cpu_warning': int(request.form.get('cpu_threshold', current_thresholds['cpu_warning'])) if use_custom else current_thresholds['cpu_warning'],
                'memory_warning': int(request.form.get('memory_threshold', current_thresholds['memory_warning'])) if use_custom else current_thresholds['memory_warning'],
                'disk_latency': int(request.form.get('disk_latency_threshold', current_thresholds['disk_latency'])) if use_custom else current_thresholds['disk_latency'],
                'etcd_latency': int(request.form.get('etcd_latency_threshold', current_thresholds['etcd_latency'])) if use_custom else current_thresholds['etcd_latency'],
                'pod_density': int(request.form.get('pod_density_threshold', current_thresholds['pod_density'])) if use_custom else current_thresholds['pod_density'],
                'restart_count': int(request.form.get('restart_threshold', current_thresholds['restart_count'])) if use_custom else current_thresholds['restart_count'],
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
            'agent': selected_agent,
            'custom_checks': [int(x) for x in request.form.getlist('custom_checks')],
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


@dashboard_bp.route('/job/quick-sanity')
@operator_required
def quick_sanity():
    """Quick sanity - redirect to configure with CNV sanity mode pre-selected"""
    return redirect(url_for('dashboard.configure') + '?preset=cnv_sanity')


@dashboard_bp.route('/job/quick-full')
@operator_required
def quick_full():
    """Full CNV scenarios - redirect to configure with full mode pre-selected and 4.21.0 defaults"""
    return redirect(url_for('dashboard.configure') + '?preset=cnv_full')


@dashboard_bp.route('/job/quick-10k')
@operator_required
def quick_10k():
    """Create 10K VMs - per-host density preset optimized for create-only at scale"""
    return redirect(url_for('dashboard.configure') + '?preset=10k_density')
