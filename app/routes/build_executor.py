"""Build queue and background execution (_execute_build)."""
import os
import re
import sys
import threading
import time
from datetime import datetime

from app.models import Host

from healthchecks.cnv_report import (
    generate_cnv_report_html,
    parse_cluster_info,
    parse_cnv_results,
)

from app.routes import (
    CNV_SCRIPT_PATH,
    MAX_CONCURRENT,
    REPORTS_DIR,
    SCRIPT_PATH,
    extract_issues_from_output,
    get_next_build_number,
    queued_jobs,
    running_jobs,
    _jobs_lock,
    save_build_to_db,
)

from app.routes.build_custom_checks import run_custom_checks
from app.routes.build_phases import find_phase_idx, run_primary_phases


def _pending_phase(name):
    return {'name': name, 'status': 'pending', 'start_time': None, 'duration': None}


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
    job_id = f'build_{build_num}'

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
    is_combined = options.get('task_type') == 'cnv_combined'

    if is_cnv or is_combined:
        cmd = [sys.executable, CNV_SCRIPT_PATH]
        server_host = options.get('server_host', '')
        if server_host:
            cmd.extend(['--server', server_host])
            host_obj = Host.query.filter_by(host=server_host).first()
            if host_obj and host_obj.name:
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

        if is_combined:
            rca_level = options.get('rca_level', 'none')
            phases = [
                _pending_phase('Initialize'), _pending_phase('Connect'), _pending_phase('Verify Setup'),
                _pending_phase('Run Scenarios'), _pending_phase('Collect Results'),
                _pending_phase('Scenario Summary'), _pending_phase('Health Check'), _pending_phase('Health Report'),
            ]
            if rca_level != 'none':
                if options.get('rca_jira') or rca_level == 'full':
                    phases.append(_pending_phase('Search Jira'))
                if options.get('rca_email') or rca_level == 'full':
                    phases.append(_pending_phase('Search Email'))
                if options.get('rca_web'):
                    phases.append(_pending_phase('Search Web'))
                if rca_level == 'full':
                    phases.append(_pending_phase('Deep RCA'))
            if options.get('combined_cleanup'):
                phases.append(_pending_phase('Cleanup'))
            phases.append(_pending_phase('Generate Report'))
            if options.get('email'):
                phases.append(_pending_phase('Send Email'))
        else:
            phases = [
                _pending_phase('Initialize'), _pending_phase('Connect'), _pending_phase('Verify Setup'),
                _pending_phase('Run Scenarios'), _pending_phase('Collect Results'), _pending_phase('Summary'),
            ]
            if options.get('email'):
                phases.append(_pending_phase('Send Email'))

    else:
        cmd = [sys.executable, SCRIPT_PATH]

        server_host = options.get('server_host', '')
        if server_host:
            cmd.extend(['--server', server_host])
            host_obj = Host.query.filter_by(host=server_host).first()
            if host_obj and host_obj.name:
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

        phases = [_pending_phase('Initialize')]
        if options.get('jira'):
            phases.append(_pending_phase('Scan Jira'))

        phases.extend([
            _pending_phase('Connect'), _pending_phase('Collect Data'), _pending_phase('Console Report'),
            _pending_phase('Analyze'), _pending_phase('Generate Report'),
        ])

        rca_phase_idx = len(phases) - 1
        if rca_level != 'none':
            if options.get('rca_jira') or rca_level == 'full':
                phases.insert(rca_phase_idx, _pending_phase('Search Jira'))
                rca_phase_idx += 1
            if options.get('rca_email') or rca_level == 'full':
                phases.insert(rca_phase_idx, _pending_phase('Search Email'))
                rca_phase_idx += 1
            if options.get('rca_web'):
                phases.insert(rca_phase_idx, _pending_phase('Search Web'))
                rca_phase_idx += 1
            if rca_level == 'full':
                phases.insert(rca_phase_idx, _pending_phase('Deep RCA'))

        if options.get('email'):
            phases.append(_pending_phase('Send Email'))

    run_name = options.get('run_name', '')
    server_host = options.get('server_host', '')
    lab_name = ''
    if server_host:
        host_obj = Host.query.filter_by(host=server_host).first()
        if host_obj and host_obj.name:
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
        'output': f'[{datetime.now().strftime("%H:%M:%S")}] Starting build #{build_num}'
        + (f' "{run_name}"' if run_name else '')
        + f' (by {username})...\n',
        'checks': checks,
        'checks_count': len(checks),
        'options': options,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'started_at_iso': datetime.utcnow().isoformat() + 'Z',
        'start_time': time.time(),
        'progress': 5,
        'phases': phases,
        'current_phase': 'Initializing...',
        'triggered_by': username,
        'user_id': user_id,
        'test_progress': {},
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
            if is_cnv or is_combined:
                tests_list = options.get('scenario_tests', [])
                task_label = 'CNV Combined' if is_combined else 'CNV Scenarios'
                job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] Task: {task_label} ({options.get("scenario_mode", "sanity")} mode)\n'
                job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] Tests: {len(tests_list)} selected\n'
                if is_combined:
                    job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] Pipeline: Scenarios → Health Check → {"Cleanup" if options.get("combined_cleanup") else "No Cleanup"}\n'
            else:
                job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] Options: RCA={options.get("rca_level")}, Jira={options.get("jira")}, Email={options.get("email")}\n'
                job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] Checks: {len(checks)} selected\n'
            job['output'] += '-' * 60 + '\n'
            job['progress'] = 5
            set_phase(job, 0, 'done')

            set_phase(job, 1, 'running', 'Connecting to cluster...')
            job['progress'] = 10
            phase_idx_box = [1]
            outcome = run_primary_phases(
                job=job,
                set_phase=set_phase,
                cmd=cmd,
                options=options,
                checks=checks,
                build_num=build_num,
                run_name=run_name,
                is_cnv=is_cnv,
                is_combined=is_combined,
                phases=phases,
                phase_idx_box=phase_idx_box,
            )
            return_code = outcome['return_code']
            full_output = outcome['full_output']
            report_file = outcome.get('report_file')
            current_phase_idx = outcome['current_phase_idx']
            duration = outcome['duration']

            if is_combined:
                status = outcome['status']
                status_text = outcome['status_text']
                cnv_results = outcome['scenario_cnv_results']
                combined_cluster_info = outcome['combined_cluster_info']
                cnv_results_final = None
                cnv_cluster_info = None
            else:
                cnv_results = None
                combined_cluster_info = None
                cnv_results_final = None
                cnv_cluster_info = None

            if is_cnv:
                summary_lines = [
                    l
                    for l in full_output.split('\n')
                    if 'PASSED:' in l and 'FAILED:' in l and 'TOTAL:' in l
                ]
                if summary_lines:
                    import re as _re

                    m = _re.search(
                        r'PASSED:\s*(\d+)\s*\|\s*FAILED:\s*(\d+)\s*\|\s*TOTAL:\s*(\d+)',
                        summary_lines[-1],
                    )
                    if m:
                        n_passed, n_failed = int(m.group(1)), int(m.group(2))
                        if return_code != 0 and n_passed == 0:
                            status, status_text = 'failed', 'Failed'
                        elif n_failed > 0 and n_passed > 0:
                            status, status_text = 'unstable', 'Partial Pass'
                        elif n_failed > 0:
                            status, status_text = 'failed', 'Failed'
                        else:
                            status, status_text = 'success', 'All Passed'
                    else:
                        status = 'failed' if return_code != 0 else 'success'
                        status_text = 'Failed' if return_code != 0 else 'All Passed'
                else:
                    status = 'failed' if return_code != 0 else 'success'
                    status_text = 'Failed' if return_code != 0 else 'All Passed'

                try:
                    cnv_results_final = parse_cnv_results(full_output)
                    cnv_cluster_info = parse_cluster_info(full_output)
                    ts_str = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
                    report_filename = f'cnv_report_{ts_str}.html'
                    report_html = generate_cnv_report_html(
                        results=cnv_results_final,
                        build_num=build_num,
                        build_name=job.get('name', run_name),
                        status=status,
                        status_text=status_text,
                        duration=duration,
                        mode=options.get('scenario_mode', 'sanity'),
                        server=options.get('server_host', ''),
                        checks=checks,
                        output=full_output,
                        cluster_info=cnv_cluster_info,
                        run_config=options,
                    )
                    os.makedirs(REPORTS_DIR, exist_ok=True)
                    report_path = os.path.join(REPORTS_DIR, report_filename)
                    with open(report_path, 'w', encoding='utf-8') as f:
                        f.write(report_html)
                    report_file = report_filename
                    job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] Reports saved: {report_filename}\n'
                except Exception as e:
                    job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] Report generation failed: {e}\n'

            elif not is_combined:
                has_issues = (
                    'WARNING' in full_output
                    or 'Issues:' in full_output
                    or 'ISSUES' in full_output
                    or '⚠️' in full_output
                )
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

            custom_check_results = []
            try:
                if is_cnv:
                    cc_ids = options.get('scenario_custom_checks', [])
                elif is_combined:
                    cc_ids = list(
                        set(
                            options.get('hc_custom_checks', [])
                            + options.get('scenario_custom_checks', [])
                        )
                    )
                else:
                    cc_ids = options.get('custom_checks', [])

                if cc_ids:
                    custom_check_results = run_custom_checks(
                        job, options, cc_ids, label='Custom Health Checks'
                    )
                    cc_failed = [r for r in custom_check_results if not r['passed']]
                    if cc_failed and status == 'success':
                        status = 'unstable'
                        status_text = status_text + ' (custom check issues)'
            except Exception as e:
                job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] Custom check execution error: {e}\n'

            for i in range(current_phase_idx, len(phases)):
                set_phase(job, i, 'done')
            job['progress'] = 100

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
                'report_file': report_file,
                'custom_check_results': custom_check_results,
            }

            with app.app_context():
                save_build_to_db(build_record, user_id=user_id)

                if not is_cnv and not is_combined:
                    try:
                        from app.learning import record_health_check_run

                        detected_issues = extract_issues_from_output(full_output)
                        if detected_issues:
                            record_health_check_run(detected_issues)
                    except Exception:
                        pass

                if (is_cnv or is_combined) and options.get('email') and options.get('email_to'):
                    email_phase_idx = find_phase_idx(phases, 'Send Email')
                    if email_phase_idx is not None and email_phase_idx >= 0:
                        set_phase(job, email_phase_idx, 'running', 'Sending email report...')
                    try:
                        from app.routes.settings_routes import _send_cnv_email_report

                        _email_cluster_info = (
                            cnv_cluster_info
                            if is_cnv
                            else (combined_cluster_info if is_combined else None)
                        )
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
                            cnv_results=cnv_results_final
                            if is_cnv
                            else (cnv_results if is_combined else None),
                            cluster_info=_email_cluster_info,
                        )
                        job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] Email sent to {options["email_to"]}\n'
                        if email_phase_idx is not None and email_phase_idx >= 0:
                            set_phase(job, email_phase_idx, 'done', 'Email sent!')
                    except Exception as e:
                        job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] Email failed: {e}\n'
                        if email_phase_idx is not None and email_phase_idx >= 0:
                            set_phase(job, email_phase_idx, 'done', f'Email failed: {e}')

        except Exception as e:
            job['output'] += f'\n[{datetime.now().strftime("%H:%M:%S")}] ❌ Error: {str(e)}\n'
            duration_secs = int(time.time() - job['start_time'])
            duration = f'{duration_secs // 60}m {duration_secs % 60}s'

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
                'report_file': None,
            }
            with app.app_context():
                save_build_to_db(build_record, user_id=user_id)

        finally:
            with _jobs_lock:
                if job_id in running_jobs:
                    del running_jobs[job_id]
            _start_next_queued()

    thread = threading.Thread(target=run_job)
    thread.daemon = True
    thread.start()
