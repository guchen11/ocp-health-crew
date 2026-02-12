#!/usr/bin/env python3
"""
CNV Scenarios Runner - SSH Wrapper for kube-burner test suite

Connects to a jump host via SSH and runs cnv-scenarios/run-workloads.sh,
streaming output back in real time for the HealthCrew dashboard console.

Usage:
    python healthchecks/cnv_scenarios.py --server HOST --tests cpu-limits,disk-hotplug --mode sanity
    python healthchecks/cnv_scenarios.py --server HOST --tests all --mode full --parallel
"""

import os
import sys
import json
import argparse
import time
from datetime import datetime

import paramiko
from dotenv import load_dotenv

load_dotenv()

# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_HOST = os.getenv("RH_LAB_HOST")
DEFAULT_USER = os.getenv("RH_LAB_USER", "root")
DEFAULT_KEY_PATH = os.getenv("SSH_KEY_PATH")
DEFAULT_KUBECONFIG = "/home/kni/clusterconfigs/auth/kubeconfig"
DEFAULT_CNV_PATH = "/home/kni/git/cnv-scenarios"

# ── ANSI colours (for console output) ────────────────────────────────────────
BOLD = "\033[1m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"


def log(msg):
    """Print a timestamped log line."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def parse_args():
    parser = argparse.ArgumentParser(description="Run cnv-scenarios on a remote jump host via SSH")
    parser.add_argument("--server", default=DEFAULT_HOST, help="Jump host address")
    parser.add_argument("--user", default=DEFAULT_USER, help="SSH user")
    parser.add_argument("--key", default=DEFAULT_KEY_PATH, help="SSH private key path")
    parser.add_argument("--kubeconfig", default=DEFAULT_KUBECONFIG, help="KUBECONFIG path on the remote host")
    parser.add_argument("--cnv-path", default=DEFAULT_CNV_PATH, help="Path to cnv-scenarios on the remote host")
    parser.add_argument("--tests", required=True, help="Comma-separated test names or 'all'")
    parser.add_argument("--mode", default="sanity", choices=["sanity", "full"], help="Test mode")
    parser.add_argument("--parallel", action="store_true", help="Run tests in parallel")
    parser.add_argument("--env-vars", default="", help="Comma-separated key=value env var overrides")
    parser.add_argument("--lab-name", default="", help="Lab name for display")
    parser.add_argument("--log-level", default="", help="kube-burner log level (debug, info, warn, error)")
    parser.add_argument("--timeout", default="", help="kube-burner timeout (e.g. 1h, 2h)")
    return parser.parse_args()


def connect_ssh(host, user, key_path):
    """Create and return an SSH client connected to the host."""
    log(f"Connecting to {user}@{host} ...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs = {"hostname": host, "username": user, "timeout": 30}
    if key_path and os.path.exists(key_path):
        connect_kwargs["key_filename"] = key_path
    # Fallback: paramiko will try default keys from ~/.ssh/

    client.connect(**connect_kwargs)
    log(f"{GREEN}Connected to {user}@{host}{RESET}")
    return client


def build_remote_command(args):
    """Build the shell command to run on the remote host."""
    parts = []

    # Environment setup
    parts.append(f"export KUBECONFIG={args.kubeconfig}")

    # Env var overrides (e.g. cpuCores=8,memorySize=64Gi)
    if args.env_vars:
        for pair in args.env_vars.split(","):
            pair = pair.strip()
            if "=" in pair:
                parts.append(f"export {pair}")

    # cd into the cnv-scenarios directory
    parts.append(f"cd {args.cnv_path}")

    # Build run-workloads.sh command
    runner = "./run-workloads.sh"
    if args.tests.lower() == "all":
        runner += " --all"
    else:
        tests = " ".join(t.strip() for t in args.tests.split(",") if t.strip())
        runner += f" {tests}"

    runner += f" --mode {args.mode}"

    if args.parallel:
        runner += " --parallel"

    # kube-burner passthrough options
    if args.log_level:
        runner += f" --log-level={args.log_level}"
    if args.timeout:
        runner += f" --timeout={args.timeout}"

    parts.append(runner)

    return " && ".join(parts)


def stream_ssh_output(client, command, timeout=7200):
    """
    Execute command on the SSH client and stream stdout line by line.
    Returns (exit_code, full_output).
    """
    transport = client.get_transport()
    channel = transport.open_session()
    channel.set_combine_stderr(True)
    channel.settimeout(timeout)
    channel.exec_command(command)

    output_lines = []
    buf = ""

    while True:
        # Check if channel has data
        if channel.recv_ready():
            chunk = channel.recv(4096).decode("utf-8", errors="replace")
            buf += chunk
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                output_lines.append(line)
                # Print each line with timestamp for the console
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"[{ts}] {line}", flush=True)
        elif channel.exit_status_ready():
            # Drain remaining data
            while channel.recv_ready():
                chunk = channel.recv(4096).decode("utf-8", errors="replace")
                buf += chunk
            if buf.strip():
                for line in buf.split("\n"):
                    if line:
                        output_lines.append(line)
                        ts = datetime.now().strftime("%H:%M:%S")
                        print(f"[{ts}] {line}", flush=True)
            break
        else:
            time.sleep(0.1)

    exit_code = channel.recv_exit_status()
    channel.close()
    return exit_code, "\n".join(output_lines)


def fetch_results_summary(client, cnv_path, tests, mode):
    """
    Fetch summary.json files from the remote host and print a parsed summary.
    """
    log(f"{CYAN}Collecting results from remote host...{RESET}")

    results_base = "/tmp/kube-burner-results"
    test_list = tests if isinstance(tests, list) else [t.strip() for t in tests.split(",")]

    summaries = []
    for test_name in test_list:
        if test_name.lower() == "all":
            continue
        cmd = f"ls -td {results_base}/{test_name}/run-* 2>/dev/null | head -1"
        stdin, stdout, stderr = client.exec_command(cmd)
        latest_dir = stdout.read().decode().strip()
        if not latest_dir:
            continue

        # Try to read summary.json
        cmd = f"cat {latest_dir}/summary.json 2>/dev/null"
        stdin, stdout, stderr = client.exec_command(cmd)
        raw = stdout.read().decode().strip()
        if raw:
            try:
                summary = json.loads(raw)
                summaries.append(summary)
            except json.JSONDecodeError:
                pass

    if summaries:
        log(f"\n{'='*70}")
        log(f"{BOLD}CNV Scenarios — Results Summary{RESET}")
        log(f"{'='*70}")
        log(f"{'Test':<30} {'Status':<12} {'Validation':<12} {'Duration'}")
        log(f"{'-'*70}")
        for s in summaries:
            name = s.get("test", "unknown")
            ec = s.get("exit_code", -1)
            status = f"{GREEN}PASS{RESET}" if ec == 0 else f"{RED}FAIL{RESET}"
            validation = s.get("validation_status", "N/A")
            dur = s.get("duration_seconds", 0)
            dur_str = f"{dur // 60}m {dur % 60}s" if dur else "N/A"
            log(f"  {name:<28} {status:<20} {validation:<12} {dur_str}")
        log(f"{'='*70}")

    return summaries


def main():
    args = parse_args()

    if not args.server:
        print(f"{RED}ERROR: No server specified. Use --server HOST or set RH_LAB_HOST env var.{RESET}", flush=True)
        sys.exit(1)

    # ── Print header ─────────────────────────────────────────────────────
    print(flush=True)
    log(f"{BOLD}{'='*60}{RESET}")
    log(f"{BOLD}  CNV Scenarios — kube-burner Test Suite{RESET}")
    log(f"{BOLD}{'='*60}{RESET}")
    log(f"  CNV Scenarios Starting")
    log(f"  Server:    {args.server}")
    log(f"  Tests:     {args.tests}")
    log(f"  Mode:      {args.mode}")
    log(f"  Parallel:  {args.parallel}")
    if args.lab_name:
        log(f"  Lab:       {args.lab_name}")
    if args.log_level:
        log(f"  Log Level: {args.log_level}")
    if args.timeout:
        log(f"  Timeout:   {args.timeout}")
    if args.env_vars:
        log(f"  Overrides: {args.env_vars}")
    log(f"{'='*60}")
    print(flush=True)

    # ── Connect ──────────────────────────────────────────────────────────
    start_time = time.time()
    try:
        client = connect_ssh(args.server, args.user, args.key)
    except Exception as e:
        log(f"{RED}SSH connection failed: {e}{RESET}")
        sys.exit(1)

    # ── Verify cnv-scenarios exists ──────────────────────────────────────
    log("Verifying cnv-scenarios installation...")
    stdin, stdout, stderr = client.exec_command(f"test -f {args.cnv_path}/run-workloads.sh && echo OK")
    if stdout.read().decode().strip() != "OK":
        log(f"{RED}ERROR: run-workloads.sh not found at {args.cnv_path}{RESET}")
        log(f"  Ensure cnv-scenarios is cloned at {args.cnv_path} on {args.server}")
        client.close()
        sys.exit(1)
    log(f"{GREEN}cnv-scenarios found at {args.cnv_path}{RESET}")

    # ── Build and run command ────────────────────────────────────────────
    remote_cmd = build_remote_command(args)
    log(f"{CYAN}Running: {remote_cmd}{RESET}")
    print(flush=True)
    log("─" * 60)
    log(f"Running test: {args.tests}")
    log("─" * 60)
    print(flush=True)

    exit_code, full_output = stream_ssh_output(client, remote_cmd)

    print(flush=True)
    log("─" * 60)

    # ── Collect results ──────────────────────────────────────────────────
    test_names = args.tests
    if test_names.lower() != "all":
        test_list = [t.strip() for t in test_names.split(",")]
    else:
        test_list = [
            "cpu-limits", "memory-limits", "disk-limits",
            "disk-hotplug", "nic-hotplug",
            "minimal-resources", "large-disk", "high-memory",
            "per-host-density", "virt-capacity-benchmark",
        ]

    summaries = fetch_results_summary(client, args.cnv_path, test_list, args.mode)
    client.close()

    # ── Final status ─────────────────────────────────────────────────────
    elapsed = int(time.time() - start_time)
    elapsed_str = f"{elapsed // 60}m {elapsed % 60}s"

    print(flush=True)
    if exit_code == 0:
        log(f"{GREEN}{BOLD}CNV Scenarios complete — ALL PASSED ({elapsed_str}){RESET}")
    else:
        log(f"{RED}{BOLD}CNV Scenarios complete — FAILURES DETECTED ({elapsed_str}){RESET}")

    # Print the final status line that routes.py looks for
    passed = sum(1 for s in summaries if s.get("exit_code", -1) == 0) if summaries else (1 if exit_code == 0 else 0)
    failed = (len(summaries) - passed) if summaries else (0 if exit_code == 0 else 1)
    total = len(summaries) if summaries else 1
    log(f"PASSED: {passed} | FAILED: {failed} | TOTAL: {total}")
    log(f"CNV Scenarios finished")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
