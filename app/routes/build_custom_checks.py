"""Remote custom check execution for build jobs (SSH on jump host)."""
import os
import re
import uuid as _uuid

import paramiko

from app.models import CustomCheck, Host
from app.ssh_utils import is_allowed_command


def run_custom_checks(job, options, check_ids, label='Custom Checks'):
    """Execute custom health checks remotely and return results list.

    Supports both single-command and script-upload checks.
    Each result: {name, command, check_type, expected, match_type, actual, passed, error}
    """
    from datetime import datetime

    results = []
    if not check_ids:
        return results

    checks_list = CustomCheck.query.filter(CustomCheck.id.in_(check_ids)).all()
    if not checks_list:
        return results

    ts = datetime.now().strftime('%H:%M:%S')
    job['output'] += f'\n[{ts}] {"─"*50}\n'
    job['output'] += f'[{ts}] Running {label} ({len(checks_list)} checks)\n'
    job['output'] += f'[{ts}] {"─"*50}\n'

    server_host = options.get('server_host', '')
    if not server_host:
        job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] ⚠ No jump host configured - skipping custom checks\n'
        return results

    ssh_key_path = os.path.expanduser('~/.ssh/id_rsa')
    host_obj = Host.query.filter_by(host=server_host).first()
    ssh_user = host_obj.user if host_obj and host_obj.user else 'root'

    try:
        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
        ssh.connect(server_host, username=ssh_user, key_filename=ssh_key_path, timeout=15)
    except Exception as e:
        ts = datetime.now().strftime('%H:%M:%S')
        job['output'] += f'[{ts}] ✗ SSH connection failed to {ssh_user}@{server_host}\n'
        job['output'] += f'[{ts}]   Error: {e}\n'
        job['output'] += f'[{ts}]   Key: {ssh_key_path}\n'
        job['output'] += f'[{ts}]   Verify: ssh {ssh_user}@{server_host}\n'
        return results

    kubeconfig_prefix = 'export KUBECONFIG=/home/kni/clusterconfigs/auth/kubeconfig 2>/dev/null; '

    for cc in checks_list:
        is_script = (cc.check_type == 'script' and cc.script_content)
        result = {
            'name': cc.name,
            'command': cc.command if not is_script else (cc.script_filename or 'script.sh'),
            'check_type': cc.check_type or 'command',
            'expected': cc.expected_value,
            'match_type': cc.match_type,
            'actual': '',
            'passed': False,
            'error': None,
        }
        try:
            if is_script:
                remote_script = f'/tmp/healthcrew_custom_{_uuid.uuid4().hex[:8]}.sh'
                ts = datetime.now().strftime('%H:%M:%S')
                job['output'] += f'[{ts}] ▸ {cc.name}: 📜 uploading script → {remote_script}\n'

                sftp = ssh.open_sftp()
                with sftp.file(remote_script, 'w') as rf:
                    rf.write(cc.script_content)
                sftp.close()

                wrapped_cmd = (
                    f'{kubeconfig_prefix}chmod +x {remote_script} && {remote_script}; '
                    f'_ec=$?; rm -f {remote_script}; exit $_ec'
                )
                _stdin, stdout, stderr = ssh.exec_command(wrapped_cmd, timeout=300)
                exit_code = stdout.channel.recv_exit_status()
                actual_output = stdout.read().decode('utf-8', errors='replace').strip()
                error_output = stderr.read().decode('utf-8', errors='replace').strip()
            else:
                ts = datetime.now().strftime('%H:%M:%S')
                job['output'] += f'[{ts}] ▸ {cc.name}: {cc.command}\n'
                if not is_allowed_command(cc.command):
                    result['error'] = f'Command blocked by allowlist: {cc.command.split()[0]}'
                    job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}]   ✗ Command not in allowlist\n'
                    results.append(result)
                    continue
                wrapped_cmd = f'{kubeconfig_prefix}{cc.command}'
                _stdin, stdout, stderr = ssh.exec_command(wrapped_cmd, timeout=120)
                exit_code = stdout.channel.recv_exit_status()
                actual_output = stdout.read().decode('utf-8', errors='replace').strip()
                error_output = stderr.read().decode('utf-8', errors='replace').strip()

            result['actual'] = actual_output

            if cc.match_type == 'exit_code':
                expected_ec = int(cc.expected_value) if cc.expected_value else 0
                result['passed'] = (exit_code == expected_ec)
            elif cc.match_type == 'exact':
                result['passed'] = (actual_output == cc.expected_value)
            elif cc.match_type == 'regex':
                result['passed'] = bool(re.search(cc.expected_value, actual_output))
            else:
                if cc.expected_value:
                    result['passed'] = (cc.expected_value in actual_output)
                else:
                    result['passed'] = (exit_code == 0)

            status_icon = '✓' if result['passed'] else '✗'
            status_color = 'PASS' if result['passed'] else 'FAIL'
            ts = datetime.now().strftime('%H:%M:%S')
            job['output'] += f'[{ts}]   {status_icon} [{status_color}] '
            if actual_output:
                first_line = actual_output.split('\n')[0][:120]
                job['output'] += f'{first_line}\n'
            else:
                job['output'] += f'exit_code={exit_code}\n'
            if error_output and not result['passed']:
                job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}]   stderr: {error_output[:200]}\n'

        except Exception as e:
            result['error'] = str(e)
            job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}]   ✗ Error: {e}\n'

        results.append(result)

    try:
        ssh.close()
    except Exception:
        pass

    passed = sum(1 for r in results if r['passed'])
    total = len(results)
    job['output'] += f'[{datetime.now().strftime("%H:%M:%S")}] Custom Checks: {passed}/{total} passed\n'
    return results
