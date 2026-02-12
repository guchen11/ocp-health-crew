#!/usr/bin/env python3
"""
Simple OCP Health Check - No AI Required
Connects to remote cluster and checks health status
"""

import os
import paramiko
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Configuration from .env
HOST = os.getenv("RH_LAB_HOST")
USER = os.getenv("RH_LAB_USER", "root")
KEY_PATH = os.getenv("SSH_KEY_PATH")

def ssh_command(command):
    """Execute command on remote host via SSH"""
    # Set kubeconfig before running oc commands
    full_cmd = f"export KUBECONFIG=/home/kni/clusterconfigs/auth/kubeconfig && {command}"
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(HOST, username=USER, key_filename=KEY_PATH)
        stdin, stdout, stderr = client.exec_command(full_cmd)
        output = stdout.read().decode()
        error = stderr.read().decode()
        client.close()
        return output, error
    except Exception as e:
        return None, str(e)

def check_nodes():
    """Check node status"""
    print("Checking nodes...")
    output, error = ssh_command("oc get nodes --no-headers")
    if error and not output:
        return f"ERROR: {error}"
    
    report = []
    unhealthy = []
    for line in output.strip().split('\n'):
        if line:
            parts = line.split()
            name, status = parts[0], parts[1]
            if status != "Ready":
                unhealthy.append(f"  - {name}: {status}")
    
    if unhealthy:
        report.append("## ⚠️ Unhealthy Nodes")
        report.extend(unhealthy)
    else:
        report.append("## ✅ All Nodes Ready")
    
    return '\n'.join(report)

def check_cluster_operators():
    """Check ClusterOperator status"""
    print("Checking cluster operators...")
    output, error = ssh_command("oc get co --no-headers")
    if error and not output:
        return f"ERROR: {error}"
    
    report = []
    degraded = []
    unavailable = []
    
    for line in output.strip().split('\n'):
        if line:
            parts = line.split()
            name = parts[0]
            # Columns: NAME VERSION AVAILABLE PROGRESSING DEGRADED SINCE MESSAGE
            available = parts[2] if len(parts) > 2 else "Unknown"
            degraded_status = parts[4] if len(parts) > 4 else "Unknown"
            
            if available == "False":
                unavailable.append(f"  - {name}")
            if degraded_status == "True":
                degraded.append(f"  - {name}")
    
    if degraded:
        report.append("## ⚠️ Degraded Operators")
        report.extend(degraded)
    if unavailable:
        report.append("## ⚠️ Unavailable Operators")
        report.extend(unavailable)
    if not degraded and not unavailable:
        report.append("## ✅ All Operators Healthy")
    
    return '\n'.join(report)

def check_kubevirt():
    """Check KubeVirt/CNV status"""
    print("Checking KubeVirt...")
    output, error = ssh_command("oc get kubevirt -A --no-headers 2>/dev/null")
    
    report = []
    if not output or "No resources found" in output:
        report.append("## ℹ️ KubeVirt not installed")
    else:
        for line in output.strip().split('\n'):
            if line:
                parts = line.split()
                namespace, name = parts[0], parts[1]
                phase = parts[-1] if len(parts) > 2 else "Unknown"
                if phase == "Deployed":
                    report.append(f"## ✅ KubeVirt: {phase}")
                else:
                    report.append(f"## ⚠️ KubeVirt: {phase}")
    
    # Check VMIs
    vmi_output, _ = ssh_command("oc get vmi -A --no-headers 2>/dev/null")
    failed_vmis = []
    if vmi_output:
        for line in vmi_output.strip().split('\n'):
            if line:
                parts = line.split()
                if len(parts) >= 4:
                    namespace, name, phase = parts[0], parts[1], parts[3]
                    if phase in ["Failed", "Error", "CrashLoopBackOff"]:
                        failed_vmis.append(f"  - {namespace}/{name}: {phase}")
    
    if failed_vmis:
        report.append("## ⚠️ Failed VMIs")
        report.extend(failed_vmis)
    elif vmi_output:
        report.append("## ✅ All VMIs Healthy")
    
    return '\n'.join(report)

def check_node_resources():
    """Check node resource usage"""
    print("Checking node resources...")
    output, error = ssh_command("oc adm top nodes --no-headers 2>/dev/null")
    
    report = []
    high_usage = []
    
    if output:
        for line in output.strip().split('\n'):
            if line:
                parts = line.split()
                if len(parts) >= 5:
                    name = parts[0]
                    cpu_pct = parts[2].replace('%', '')
                    mem_pct = parts[4].replace('%', '')
                    try:
                        if int(cpu_pct) > 85:
                            high_usage.append(f"  - {name}: CPU {cpu_pct}%")
                        if int(mem_pct) > 85:
                            high_usage.append(f"  - {name}: Memory {mem_pct}%")
                    except ValueError:
                        pass
    
    if high_usage:
        report.append("## ⚠️ High Resource Usage (>85%)")
        report.extend(high_usage)
    elif output:
        report.append("## ✅ Resource Usage Normal")
    else:
        report.append("## ℹ️ Could not get resource metrics")
    
    return '\n'.join(report)

def main():
    print(f"\n🔍 OCP Health Check - {HOST}")
    print("=" * 50)
    
    report_parts = [
        f"# OCP Health Report",
        f"**Cluster:** {HOST}",
        f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        check_nodes(),
        "",
        check_cluster_operators(),
        "",
        check_kubevirt(),
        "",
        check_node_resources(),
    ]
    
    report = '\n'.join(report_parts)
    
    # Save report
    filename = f"health_report_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.md"
    with open(filename, 'w') as f:
        f.write(report)
    
    print("\n" + "=" * 50)
    print(report)
    print("=" * 50)
    print(f"\n📄 Report saved: {filename}")

if __name__ == "__main__":
    main()
