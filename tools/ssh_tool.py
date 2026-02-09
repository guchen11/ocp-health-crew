from crewai.tools import BaseTool
import paramiko
import os
from dotenv import load_dotenv

load_dotenv()

class RemoteOCPTool(BaseTool):
    name: str = "Remote OCP Executor"
    description: str = "Executes 'oc' commands on the remote Red Hat lab. Input must be the full command string."

    def _run(self, command: str) -> str:
        host = os.getenv("RH_LAB_HOST")
        user = os.getenv("RH_LAB_USER")
        key_path = os.getenv("SSH_KEY_PATH")

        # 1. Security & Sanity Check
        if not any(command.strip().startswith(cmd) for cmd in ["oc", "kubectl", "echo"]):
             return "Error: You can only run 'oc' or 'kubectl' commands."

        # 2. INJECT AUTH: Prepend the KUBECONFIG export
        # This ensures every command runs as admin
        kube_env = "export KUBECONFIG=/home/kni/clusterconfigs/auth/kubeconfig"
        full_command = f"{kube_env}; {command}"

        # 3. Connect via Paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            # Use the specific key path from .env
            if key_path:
                client.connect(host, username=user, key_filename=os.path.expanduser(key_path), timeout=10)
            else:
                client.connect(host, username=user, timeout=10)

            stdin, stdout, stderr = client.exec_command(full_command)
            
            out_str = stdout.read().decode().strip()
            err_str = stderr.read().decode().strip()
            
            # Paramiko puts warnings in stderr, so only fail if output is completely missing
            if err_str and not out_str:
                return f"CMD FAILED:\n{err_str}"
            
            return f"OUTPUT:\n{out_str}\n(Stderr info: {err_str})"

        except Exception as e:
            return f"SSH CONNECTION FAILED: {str(e)}"
        finally:
            client.close()
