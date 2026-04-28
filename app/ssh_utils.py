"""Shared SSH utilities with security hardening.

Consolidates SSH patterns used across the codebase:
- WarningPolicy instead of AutoAddPolicy (MITM defense)
- shlex.quote for all dynamic values in shell commands
- Centralized validation for env vars and cluster object names
"""

import logging
import os
import re
import shlex

import paramiko

logger = logging.getLogger(__name__)

_K8S_NAME_RE = re.compile(r'^[a-z0-9][-a-z0-9.]{0,251}[a-z0-9]?$')
_ENV_KEY_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def create_ssh_client(host=None, username=None, key_filename=None,
                      password=None, timeout=10):
    """Create a Paramiko SSH client with secure defaults.

    Falls back to RH_LAB_HOST / RH_LAB_USER / SSH_KEY_PATH env vars when
    explicit arguments are not provided.  Uses WarningPolicy instead of
    AutoAddPolicy to log unrecognised host keys.
    """
    host = host or os.getenv('RH_LAB_HOST')
    username = username or os.getenv('RH_LAB_USER', 'root')
    key_filename = key_filename or os.getenv('SSH_KEY_PATH')

    if not host:
        raise ValueError(
            "SSH host not configured. Set RH_LAB_HOST or pass host=."
        )

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.WarningPolicy())

    kwargs = {'hostname': host, 'username': username, 'timeout': timeout}
    if key_filename:
        kwargs['key_filename'] = os.path.expanduser(key_filename)
    if password:
        kwargs['password'] = password

    client.connect(**kwargs)
    return client


def ssh_exec(client, command, kubeconfig=None, timeout=30):
    """Execute a command on a remote host, optionally exporting KUBECONFIG.

    Returns (stdout_str, stderr_str).  Both the kubeconfig path and
    the command are passed through without additional quoting -- callers
    must pre-quote any dynamic values with :func:`quote`.
    """
    if kubeconfig:
        full_cmd = f"export KUBECONFIG={shlex.quote(kubeconfig)} && {command}"
    else:
        full_cmd = command

    _stdin, stdout, stderr = client.exec_command(full_cmd, timeout=timeout)
    return stdout.read().decode().strip(), stderr.read().decode().strip()


def quote(value):
    """Shell-quote a value for safe interpolation into a remote command."""
    return shlex.quote(str(value))


def build_pubkey_install_cmd(pub_key_str):
    """Return a single shell command that idempotently installs *pub_key_str*
    into ``~/.ssh/authorized_keys``."""
    q = shlex.quote(pub_key_str.strip())
    return (
        f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
        f"grep -qF {q} ~/.ssh/authorized_keys 2>/dev/null || "
        f"echo {q} >> ~/.ssh/authorized_keys && "
        f"chmod 600 ~/.ssh/authorized_keys"
    )


def validate_env_pair(pair):
    """Return True when *pair* looks like ``KEY=VALUE`` with a safe key name.

    The key must match ``[A-Za-z_][A-Za-z0-9_]*`` so that it is safe for
    ``export KEY=VALUE`` without further quoting of the key part.
    """
    if '=' not in pair:
        return False
    key = pair.split('=', 1)[0]
    return bool(_ENV_KEY_RE.match(key))


def validate_cluster_name(name):
    """Return True when *name* conforms to Kubernetes naming rules.

    Kubernetes names match ``[a-z0-9][-a-z0-9.]*[a-z0-9]`` with a 253-char
    maximum, making them safe for unquoted shell interpolation.
    """
    if not name or len(name) > 253:
        return False
    return bool(_K8S_NAME_RE.match(name))


ALLOWED_CMD_PREFIXES = (
    'oc ', 'kubectl ', 'virtctl ', 'echo ', 'cat ', 'grep ',
    'ls ', 'test ', 'wc ', 'head ', 'tail ', 'sort ', 'uniq ',
)


def is_allowed_command(cmd):
    """Return True when *cmd* starts with a known-safe prefix.

    Used to gate user-defined custom-check commands before remote execution.
    """
    stripped = cmd.strip()
    return any(stripped.startswith(p) for p in ALLOWED_CMD_PREFIXES)
