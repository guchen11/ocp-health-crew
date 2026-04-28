"""SSH client and remote command execution for hybrid health check."""

import os
import threading

import paramiko

HOST = os.getenv("RH_LAB_HOST")
USER = os.getenv("RH_LAB_USER", "root")
KEY_PATH = os.getenv("SSH_KEY_PATH")
KUBECONFIG = "/home/kni/clusterconfigs/auth/kubeconfig"

_ssh_lock = threading.Lock()
ssh_client = None


class SSHConnectionError(Exception):
    """Raised when SSH connection to the target host fails."""

    def __init__(self, message, host=None, user=None, key_path=None, original_error=None):
        self.host = host
        self.user = user
        self.key_path = key_path
        self.original_error = original_error
        super().__init__(message)


def get_ssh_client():
    """
    Get or create SSH client.
    Connects directly to the target host that has oc access.
    Raises SSHConnectionError with detailed info on failure.
    Thread-safe: uses lock to prevent duplicate connection setup.
    """
    global ssh_client

    with _ssh_lock:
        if ssh_client is not None:
            transport = ssh_client.get_transport()
            if transport and transport.is_active():
                return ssh_client
            ssh_client = None

        if not HOST:
            raise SSHConnectionError(
                "No target host configured. Set RH_LAB_HOST environment variable or pass --server <host>.",
                host=HOST,
                user=USER,
                key_path=KEY_PATH,
            )
        if not KEY_PATH:
            raise SSHConnectionError(
                "No SSH key path configured. Set SSH_KEY_PATH environment variable.",
                host=HOST,
                user=USER,
                key_path=KEY_PATH,
            )
        if not os.path.isfile(KEY_PATH):
            raise SSHConnectionError(
                f"SSH key file not found: {KEY_PATH}",
                host=HOST,
                user=USER,
                key_path=KEY_PATH,
            )

        ssh_client = paramiko.SSHClient()
        ssh_client.load_system_host_keys()
        ssh_client.set_missing_host_key_policy(paramiko.WarningPolicy())
        try:
            ssh_client.connect(HOST, username=USER, key_filename=KEY_PATH, timeout=10)
        except paramiko.AuthenticationException as e:
            ssh_client = None
            raise SSHConnectionError(
                f"SSH authentication failed for {USER}@{HOST} (key: {KEY_PATH}): {e}",
                host=HOST,
                user=USER,
                key_path=KEY_PATH,
                original_error=e,
            )
        except paramiko.SSHException as e:
            ssh_client = None
            raise SSHConnectionError(
                f"SSH protocol error connecting to {USER}@{HOST}: {e}",
                host=HOST,
                user=USER,
                key_path=KEY_PATH,
                original_error=e,
            )
        except OSError as e:
            ssh_client = None
            raise SSHConnectionError(
                f"Cannot connect to {HOST} -- host unreachable or connection refused: {e}",
                host=HOST,
                user=USER,
                key_path=KEY_PATH,
                original_error=e,
            )
        except Exception as e:
            ssh_client = None
            raise SSHConnectionError(
                f"SSH connection failed to {USER}@{HOST} (key: {KEY_PATH}): {e}",
                host=HOST,
                user=USER,
                key_path=KEY_PATH,
                original_error=e,
            )

        return ssh_client


def ssh_command(command, timeout=30):
    """Execute command via SSH. Raises SSHConnectionError if connection fails."""
    import shlex

    full_cmd = f"export KUBECONFIG={shlex.quote(KUBECONFIG)} && {command}"
    try:
        client = get_ssh_client()
        stdin, stdout, stderr = client.exec_command(full_cmd, timeout=timeout)
        channel = stdout.channel
        channel.settimeout(timeout)
        output = stdout.read().decode().strip()
        return output
    except SSHConnectionError:
        raise
    except Exception:
        return ""
