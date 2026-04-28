"""CNV and health-check subprocess phase orchestration."""
import os
import re
import subprocess
import sys
import time
from datetime import datetime

from app.models import Host

from config.settings import Config
from healthchecks.cnv_report import (
    generate_combined_report_html,
    parse_cluster_info,
    parse_cnv_results,
)

BASE_DIR = Config.BASE_DIR
REPORTS_DIR = Config.REPORTS_DIR
SCRIPT_PATH = os.path.join(BASE_DIR, 'healthchecks', 'hybrid_health_check.py')


def find_phase_idx(phases, name):
    for i, p in enumerate(phases):
        if p['name'] == name:
            return i
    return -1


def stream_subprocess(job, set_phase, sub_cmd, sub_keywords, phase_idx_box):
    """Stream subprocess stdout; phase_idx_box[0] tracks current phase index. Returns (rc, lines)."""
    current_phase_idx = phase_idx_box[0]
    sub_process = subprocess.Popen(
        sub_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE,
        text=True,
        cwd=BASE_DIR,
        bufsize=1,
        start_new_session=True,
    )
    job['process'] = sub_process
    _re_test_start = re.compile(r'\[(\S+)\]\s+Starting test')
    _re_test_complete = re.compile(r'\[(\S+)\]\s+Completed:\s+exit_code=(\d+),\s+duration=(.*)')
    _re_test_queued = re.compile(r'\[(\S+)\]\s+Queued for')

    sub_lines = []
    while True:
        line = sub_process.stdout.readline()
        if not line and sub_process.poll() is not None:
            break
        if line:
            sub_lines.append(line)
            timestamp = datetime.now().strftime('%H:%M:%S')
            job['output'] += f'[{timestamp}] {line}'

            m_queued = _re_test_queued.search(line)
            if m_queued:
                tname = m_queued.group(1)
                if tname not in job['test_progress']:
                    job['test_progress'][tname] = {
                        'status': 'queued',
                        'start_time': None,
                        'duration': None,
                        'exit_code': None,
                    }

            m_start = _re_test_start.search(line)
            if m_start:
                tname = m_start.group(1)
                job['test_progress'][tname] = {
                    'status': 'running',
                    'start_time': time.time(),
                    'duration': None,
                    'exit_code': None,
                }

            m_done = _re_test_complete.search(line)
            if m_done:
                tname = m_done.group(1)
                ec = int(m_done.group(2))
                dur_str = m_done.group(3).strip()
                tp = job['test_progress'].get(tname, {})
                tp['status'] = 'passed' if ec == 0 else 'failed'
                tp['exit_code'] = ec
                tp['duration'] = dur_str
                job['test_progress'][tname] = tp

            for keyword, (phase_idx, phase_msg, progress) in sub_keywords.items():
                if keyword in line and phase_idx >= 0:
                    if phase_idx > current_phase_idx:
                        set_phase(job, current_phase_idx, 'done')
                        for skip_idx in range(current_phase_idx + 1, phase_idx):
                            if job['phases'][skip_idx]['status'] == 'pending':
                                job['phases'][skip_idx]['status'] = 'skipped'
                        current_phase_idx = phase_idx
                        phase_idx_box[0] = current_phase_idx
                        set_phase(job, phase_idx, 'running', phase_msg)
                    job['progress'] = progress
                    job['current_phase'] = phase_msg
                    break
    rc = sub_process.wait()
    phase_idx_box[0] = current_phase_idx
    return rc, sub_lines


def build_cnv_scenario_keywords(job, is_combined):
    phases = job['phases']
    connect_idx = find_phase_idx(phases, 'Connect')
    verify_idx = find_phase_idx(phases, 'Verify Setup')
    run_idx = find_phase_idx(phases, 'Run Scenarios')
    results_idx = find_phase_idx(phases, 'Collect Results')
    summary_idx = find_phase_idx(phases, 'Scenario Summary' if is_combined else 'Summary')
    pr = 60 if not is_combined else 30
    colp, sump, smzp, donp = (
        (75, 80, 85, 95) if not is_combined else (35, 38, 40, 42)
    )
    return {
        'Connecting to': (connect_idx, 'Connecting to jump host...', 10),
        'Connected to': (connect_idx, 'Connected to jump host', 15),
        'SSH connection established': (connect_idx, 'Connected to jump host', 15),
        'CONNECTION ERROR': (connect_idx, '❌ Connection failed!', 15),
        'SSH connection failed': (connect_idx, '❌ Connection failed!', 15),
        'Connection refused': (connect_idx, '❌ Connection refused!', 15),
        'Verifying cnv-scenarios': (verify_idx, 'Verifying cnv-scenarios setup...', 20),
        'KUBECONFIG': (verify_idx, 'Setting up environment...', 22),
        'kubeconfig': (verify_idx, 'Setting up environment...', 22),
        'Running command': (run_idx, 'Running workload scenarios...', 30),
        'run-workloads.sh': (run_idx, 'Running workload scenarios...', 30),
        'Running test': (run_idx, 'Running test scenarios...', 35),
        'RUNNING': (run_idx, 'Running scenarios...', 40),
        'kube-burner': (run_idx, 'Running kube-burner workloads...', 50),
        'Waiting for': (run_idx, 'Waiting for workloads...', 55),
        'PASS': (run_idx, 'Tests progressing...', pr),
        'FAIL': (run_idx, 'Tests progressing...', pr),
        'Collecting results': (results_idx, 'Collecting results...', colp),
        'summary.json': (results_idx, 'Parsing summary...', sump),
        'Results:': (summary_idx, 'Generating summary...', smzp),
        'Summary:': (summary_idx, 'Generating summary...', smzp),
        'SUMMARY': (summary_idx, 'Generating summary...', smzp),
        'scenarios complete': (summary_idx, 'Scenarios done!', donp),
        'All tests': (summary_idx, 'Scenarios done!', donp),
        'CNV Scenarios finished': (summary_idx, 'Scenarios done!', donp),
    }


def build_health_check_keywords(job):
    phases = job['phases']
    scan_jira_idx = find_phase_idx(phases, 'Scan Jira')
    connect_idx = find_phase_idx(phases, 'Connect')
    collect_idx = find_phase_idx(phases, 'Collect Data')
    console_idx = find_phase_idx(phases, 'Console Report')
    analyze_idx = find_phase_idx(phases, 'Analyze')
    jira_rca_idx = find_phase_idx(phases, 'Search Jira')
    email_rca_idx = find_phase_idx(phases, 'Search Email')
    web_rca_idx = find_phase_idx(phases, 'Search Web')
    deep_rca_idx = find_phase_idx(phases, 'Deep RCA')
    report_idx = find_phase_idx(phases, 'Generate Report')
    email_idx = find_phase_idx(phases, 'Send Email')

    return {
        'Checking Jira for new test suggestions': (scan_jira_idx, 'Scanning Jira for new tests...', 3),
        'Checking Jira for recent bugs': (scan_jira_idx, 'Checking Jira for bugs...', 4),
        'Analyzed': (scan_jira_idx, 'Analyzing Jira bugs...', 5),
        'new checks will be included': (scan_jira_idx, 'Jira scan complete', 6),
        'HealthCrew AI Starting': (connect_idx, 'Initializing...', 8),
        'Connecting to cluster': (connect_idx, 'Connecting to cluster...', 10),
        'Connected to': (connect_idx, 'Connected to cluster', 15),
        'CONNECTION ERROR': (connect_idx, '❌ Connection failed!', 15),
        'SSH connection failed': (connect_idx, '❌ Connection failed!', 15),
        'host unreachable': (connect_idx, '❌ Host unreachable!', 15),
        'Authentication failed': (connect_idx, '❌ Authentication failed!', 15),
        'oc.*not responding': (connect_idx, '❌ oc CLI not configured!', 15),
        'cluster is not configured': (connect_idx, '❌ Cluster not configured!', 15),
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


def run_primary_phases(
    *,
    job,
    set_phase,
    cmd,
    options,
    checks,
    build_num,
    run_name,
    is_cnv,
    is_combined,
    phases,
    phase_idx_box,
):
    """Run subprocess pipeline for CNV-only, health-only, or combined tasks; returns result dict."""
    if is_cnv or is_combined:
        cnv_scenario_keywords = build_cnv_scenario_keywords(job, is_combined)
    else:
        cnv_scenario_keywords = {}

    if not is_cnv and not is_combined:
        health_check_keywords = build_health_check_keywords(job)
    else:
        health_check_keywords = {}

    report_file = None

    if is_combined:
        # Step 1: scenarios (cleanup=false)
        job['output'] += f'\n[{datetime.now().strftime("%H:%M:%S")}] {"="*60}\n'
        job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] PHASE 1: Running CNV Scenarios (cleanup=false)\n'
        job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] {"="*60}\n'

        scenario_rc, scenario_lines = stream_subprocess(
            job, set_phase, cmd, cnv_scenario_keywords, phase_idx_box
        )
        scenario_output = ''.join(scenario_lines)

        s_summary_idx = find_phase_idx(phases, 'Scenario Summary')
        if s_summary_idx >= 0:
            set_phase(job, s_summary_idx, 'done')

        cnv_results = None
        try:
            cnv_results = parse_cnv_results(scenario_output)
        except Exception:
            pass

        # Step 2: health check
        hc_phase_idx = find_phase_idx(phases, 'Health Check')
        hr_phase_idx = find_phase_idx(phases, 'Health Report')
        set_phase(job, hc_phase_idx, 'running', 'Running health check...')
        current_phase_idx = hc_phase_idx
        phase_idx_box[0] = current_phase_idx
        job['progress'] = 50

        job['output'] += f'\n[{datetime.now().strftime("%H:%M:%S")}] {"="*60}\n'
        job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] PHASE 2: Running Health Check\n'
        job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] {"="*60}\n'

        hc_cmd = [sys.executable, SCRIPT_PATH]
        server_host = options.get('server_host', '')
        if server_host:
            hc_cmd.extend(['--server', server_host])
            host_obj = Host.query.filter_by(host=server_host).first()
            if host_obj and host_obj.name:
                clean_name = re.sub(r'\s*\[.*?\]\s*$', '', host_obj.name).strip() or host_obj.host
                hc_cmd.extend(['--lab-name', clean_name])

        rca_level = options.get('rca_level', 'none')
        if rca_level == 'bugs':
            hc_cmd.append('--rca-bugs')
        elif rca_level == 'full':
            hc_cmd.append('--ai')
        if options.get('rca_jira'):
            hc_cmd.append('--rca-jira')
        if options.get('rca_email'):
            hc_cmd.append('--rca-email')
        if options.get('jira'):
            hc_cmd.append('--check-jira')
        if options.get('email'):
            hc_cmd.append('--email')
            if options.get('email_to'):
                hc_cmd.extend(['--email-to', options.get('email_to')])

        hc_keywords = {
            'HealthCrew AI Starting': (hc_phase_idx, 'Health check initializing...', 52),
            'Connecting to cluster': (hc_phase_idx, 'Health check connecting...', 54),
            'Connected to': (hc_phase_idx, 'Health check connected', 55),
            'Collecting cluster data': (hc_phase_idx, 'Collecting cluster data...', 58),
            'Checking nodes': (hc_phase_idx, 'Checking nodes...', 60),
            'Checking node resources': (hc_phase_idx, 'Checking resources...', 62),
            'Data collection complete': (hc_phase_idx, 'Data collection done', 65),
            'Generating console report': (hc_phase_idx, 'Generating console report...', 67),
            'HEALTH REPORT': (hc_phase_idx, 'Displaying health report...', 70),
            'Saving HTML report': (hr_phase_idx, 'Saving health report...', 72),
            'Saved:': (hr_phase_idx, 'Health report saved', 74),
            'Reports saved': (hr_phase_idx, 'Health reports saved', 75),
            'Health check complete': (hr_phase_idx, 'Health check done!', 78),
        }

        rca_level = options.get('rca_level', 'none')
        if rca_level != 'none':
            jira_rca_idx = find_phase_idx(phases, 'Search Jira')
            email_rca_idx = find_phase_idx(phases, 'Search Email')
            web_rca_idx = find_phase_idx(phases, 'Search Web')
            deep_rca_idx = find_phase_idx(phases, 'Deep RCA')

            hc_keywords.update({
                'Starting Root Cause Analysis': (hr_phase_idx, 'Starting root cause analysis...', 73),
                '🔬 Starting Root Cause Analysis': (hr_phase_idx, 'Starting root cause analysis...', 73),
                'Matching failures to known issues': (hr_phase_idx, 'Matching failures...', 74),
                'issue(s) to analyze': (hr_phase_idx, 'Analyzing issues...', 75),
                '→ Searching Jira': (jira_rca_idx, 'Searching Jira for bugs...', 76),
                'Searching Jira for related bugs': (jira_rca_idx, 'Searching Jira for bugs...', 76),
                '→ Searching emails': (email_rca_idx, 'Searching emails...', 77),
                'Searching emails for related': (email_rca_idx, 'Searching emails...', 77),
                '→ Searching web': (web_rca_idx, 'Searching web docs...', 78),
                'Running deep investigation': (deep_rca_idx, 'Running deep investigation...', 79),
                'Deep investigation complete': (deep_rca_idx, 'Deep investigation complete', 80),
            })

        hc_rc, hc_lines = stream_subprocess(job, set_phase, hc_cmd, hc_keywords, phase_idx_box)
        health_output = ''.join(hc_lines)
        set_phase(job, hr_phase_idx, 'done')

        for rca_name in ('Search Jira', 'Search Email', 'Search Web', 'Deep RCA'):
            rca_idx = find_phase_idx(phases, rca_name)
            if rca_idx >= 0:
                set_phase(job, rca_idx, 'done')

        health_report_file = None
        for hl in hc_lines:
            match = re.search(r'(health_report_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.html)', hl)
            if match:
                health_report_file = match.group(1)

        cleanup_rc = 0
        cleanup_output = ''
        if options.get('combined_cleanup'):
            cleanup_phase_idx = find_phase_idx(phases, 'Cleanup')
            set_phase(job, cleanup_phase_idx, 'running', 'Cleaning up test resources...')
            current_phase_idx = cleanup_phase_idx
            phase_idx_box[0] = current_phase_idx
            job['progress'] = 80

            job['output'] += f'\n[{datetime.now().strftime("%H:%M:%S")}] {"="*60}\n'
            job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] PHASE 3: Cleanup (cleanup=true)\n'
            job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] {"="*60}\n'

            cleanup_cmd = list(cmd) + ['--cleanup-only']
            cleanup_keywords = {
                'Cleanup Starting': (cleanup_phase_idx, 'Cleanup running...', 82),
                'Connecting to': (cleanup_phase_idx, 'Cleanup connecting...', 83),
                'Connected to': (cleanup_phase_idx, 'Cleanup connected', 84),
                'Running': (cleanup_phase_idx, 'Cleanup in progress...', 86),
                'kube-burner': (cleanup_phase_idx, 'Cleanup running kube-burner...', 88),
                'CLEANUP COMPLETE': (cleanup_phase_idx, 'Cleanup done!', 90),
                'CLEANUP FAILED': (cleanup_phase_idx, 'Cleanup failed!', 90),
            }

            cleanup_rc, cleanup_lines = stream_subprocess(
                job, set_phase, cleanup_cmd, cleanup_keywords, phase_idx_box
            )
            cleanup_output = ''.join(cleanup_lines)
            set_phase(job, cleanup_phase_idx, 'done')

        gen_phase_idx = find_phase_idx(phases, 'Generate Report')
        set_phase(job, gen_phase_idx, 'running', 'Generating combined report...')
        current_phase_idx = gen_phase_idx
        phase_idx_box[0] = current_phase_idx
        job['progress'] = 92

        full_output = scenario_output + '\n' + health_output + '\n' + cleanup_output

        has_scenario_fail = scenario_rc != 0 or ('FAIL' in scenario_output and 'PASS' not in scenario_output)
        has_scenario_partial = 'FAIL' in scenario_output and 'PASS' in scenario_output
        has_hc_issues = 'WARNING' in health_output or 'Issues:' in health_output or '⚠️' in health_output
        has_hc_errors = 'ERROR' in health_output or 'CRITICAL' in health_output or '❌' in health_output

        if scenario_rc != 0 and hc_rc != 0:
            status = 'failed'
            status_text = 'Failed'
        elif has_scenario_fail or has_hc_errors:
            status = 'failed'
            status_text = 'Failed'
        elif has_scenario_partial or has_hc_issues:
            status = 'unstable'
            status_text = 'Issues Found'
        else:
            status = 'success'
            status_text = 'All Passed'

        combined_cluster_info = None
        try:
            ts_str = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            report_filename = f'combined_report_{ts_str}.html'

            duration_secs = int(time.time() - job['start_time'])
            duration = f'{duration_secs // 60}m {duration_secs % 60}s'

            combined_cluster_info = parse_cluster_info(scenario_output)
            report_html = generate_combined_report_html(
                cnv_results=cnv_results,
                health_output=health_output,
                health_report_file=health_report_file,
                cleanup_status='success'
                if cleanup_rc == 0 and options.get('combined_cleanup')
                else ('failed' if cleanup_rc != 0 else 'skipped'),
                build_num=build_num,
                build_name=job.get('name', run_name),
                status=status,
                status_text=status_text,
                duration=duration,
                mode=options.get('scenario_mode', 'sanity'),
                server=options.get('server_host', ''),
                checks=checks,
                scenario_output=scenario_output,
                health_check_output=health_output,
                cleanup_output=cleanup_output,
                cluster_info=combined_cluster_info,
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

        set_phase(job, gen_phase_idx, 'done')
        job['progress'] = 95

        duration_feats = int(time.time() - job['start_time'])
        duration = f'{duration_feats // 60}m {duration_feats % 60}s'
        return_code = max(scenario_rc, hc_rc, cleanup_rc)

        return {
            'return_code': return_code,
            'full_output': full_output,
            'report_file': report_file,
            'current_phase_idx': phase_idx_box[0],
            'status': status,
            'status_text': status_text,
            'duration': duration,
            'scenario_cnv_results': cnv_results,
            'combined_cluster_info': combined_cluster_info,
        }

    # Single task: CNV only or health only
    active_keywords = cnv_scenario_keywords if is_cnv else health_check_keywords
    return_code, stdout_lines = stream_subprocess(
        job, set_phase, cmd, active_keywords, phase_idx_box
    )
    current_phase_idx = phase_idx_box[0]
    report_file = None

    if not is_cnv:
        for sl in stdout_lines:
            if 'Report saved' in sl or 'health_report_' in sl:
                match = re.search(r'(health_report_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.html)', sl)
                if match:
                    report_file = match.group(1)

    for i in range(current_phase_idx, len(phases)):
        set_phase(job, i, 'done')

    job['progress'] = 100

    duration_secs = int(time.time() - job['start_time'])
    duration = f'{duration_secs // 60}m {duration_secs % 60}s'
    full_output = ''.join(stdout_lines)

    return {
        'return_code': return_code,
        'full_output': full_output,
        'report_file': report_file,
        'current_phase_idx': phase_idx_box[0],
        'duration': duration,
    }
