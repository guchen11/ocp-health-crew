"""Settings page and host / SSH API routes."""
import os
from datetime import datetime

from flask import jsonify, render_template, request
from flask_login import current_user, login_required

from config.settings import CNV_GLOBAL_VARIABLES, CNV_SCENARIOS, Config
from healthchecks.cnv_report import generate_cnv_email_html, parse_cnv_results

from app.decorators import log_audit, operator_required

from app.models import Host, db

from app.routes import (
    dashboard_bp,
    DEFAULT_SETTINGS,
    DEFAULT_THRESHOLDS,
    _DEFAULT_CNV_SETTINGS,
    BASE_DIR,
    _collect_scenario_var_defaults,
    get_hosts_for_user,
    get_thresholds,
    load_settings,
    save_settings,
)

def _send_cnv_email_report(recipient, build_num, build_name, status, status_text,
                            duration, checks, options, output, cnv_results=None,
                            cluster_info=None):
    """Send a CNV scenario results email with per-test pass/fail details."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    smtp_server = os.getenv('SMTP_SERVER', 'smtp.corp.redhat.com')
    smtp_port = int(os.getenv('SMTP_PORT', '25'))
    email_from = os.getenv('EMAIL_FROM', 'cnv-healthcrew@redhat.com')

    mode = options.get('scenario_mode', 'sanity')

    # Parse results from output if not provided
    if cnv_results is None:
        cnv_results = parse_cnv_results(output)

    dashboard_base_url = os.getenv('DASHBOARD_BASE_URL', Config.DASHBOARD_BASE_URL)

    subject, html = generate_cnv_email_html(
        results=cnv_results,
        build_num=build_num,
        build_name=build_name,
        status=status,
        status_text=status_text,
        duration=duration,
        mode=mode,
        checks=checks,
        output=output,
        cluster_info=cluster_info,
        dashboard_base_url=dashboard_base_url,
    )

    # Plain text fallback
    from healthchecks.cnv_report import strip_ansi
    tests = cnv_results.get("tests", [])
    passed = cnv_results.get("passed", 0)
    failed = cnv_results.get("failed", 0)

    test_lines = []
    for t in tests:
        test_lines.append(f"  {'PASS' if t['status'] == 'PASS' else 'FAIL'}  {t['name']:<25}  {t.get('duration_str', 'N/A')}")

    report_link = f"{dashboard_base_url}/job/{build_num}" if dashboard_base_url else ""

    plain = f"""CNV Scenarios Report - Build #{build_num}
Status: {status_text}
Duration: {duration}
Mode: {mode}
Passed: {passed} | Failed: {failed} | Total: {len(tests)}

--- Scenario Results ---
{chr(10).join(test_lines)}
{f'{chr(10)}Full report: {report_link}' if report_link else ''}
"""

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = email_from
    msg['To'] = recipient
    msg.attach(MIMEText(plain, 'plain'))
    msg.attach(MIMEText(html, 'html'))

    with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
        server.sendmail(email_from, [recipient], msg.as_string())


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
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        client.connect(host, username=user, password=password, timeout=15)

        from app.ssh_utils import build_pubkey_install_cmd
        commands = build_pubkey_install_cmd(pub_key_str)
        stdin, stdout, stderr = client.exec_command(commands)
        exit_status = stdout.channel.recv_exit_status()
        err_output = stderr.read().decode().strip()
        client.close()

        if exit_status != 0:
            return False, f'Failed to install key: {err_output}'

        verify_client = paramiko.SSHClient()
        verify_client.load_system_host_keys()
        verify_client.set_missing_host_key_policy(paramiko.WarningPolicy())
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
                'grafana_url': request.form.get('cnv_grafana_url', '').strip(),
                'global_vars': {
                    'storageClassName': request.form.get('cnv_default_storageClassName', '').strip(),
                    'nodeSelector': request.form.get('cnv_default_nodeSelector', '').strip(),
                    'maxWaitTimeout': request.form.get('cnv_default_maxWaitTimeout', '').strip(),
                    'jobPause': request.form.get('cnv_default_jobPause', '').strip(),
                    'esServer': request.form.get('cnv_default_esServer', '').strip(),
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

    # Load custom checks for this user
    from app.models import CustomCheck
    custom_checks = [c.to_dict() for c in
                     CustomCheck.query.filter_by(created_by=current_user.id).order_by(CustomCheck.created_at.desc()).all()]

    return render_template('settings.html',
                           thresholds=settings.get('thresholds', DEFAULT_THRESHOLDS),
                           ssh_config=ssh_config,
                           saved_hosts=saved_hosts,
                           ai_config=settings.get('ai', {'model': 'ollama/llama3.2:3b', 'url': 'http://localhost:11434'}),
                           jira_config=settings.get('jira', {'projects': ['CNV', 'OCPBUGS', 'ODF'], 'scan_days': 30, 'bug_limit': 50}),
                           cnv_config=cnv_config,
                           cnv_global_vars=CNV_GLOBAL_VARIABLES,
                           cnv_scenarios=CNV_SCENARIOS,
                           custom_checks=custom_checks,
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
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        client.connect(host, username=user, password=password, timeout=15)

        from app.ssh_utils import build_pubkey_install_cmd
        commands = build_pubkey_install_cmd(pub_key_str)
        stdin, stdout, stderr = client.exec_command(commands)
        exit_status = stdout.channel.recv_exit_status()
        err_output = stderr.read().decode().strip()
        client.close()

        if exit_status != 0:
            return jsonify({'success': False, 'error': f'Failed to install public key: {err_output}'})

        verify_client = paramiko.SSHClient()
        verify_client.load_system_host_keys()
        verify_client.set_missing_host_key_policy(paramiko.WarningPolicy())
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
