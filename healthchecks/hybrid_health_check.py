#!/usr/bin/env python3
"""
CNV HealthCrew AI - Professional Edition
- Fast single SSH connection
- Beautiful HTML reports
- Email notifications
- Optional AI analysis
- Jira bug status checking
- Automatic new check suggestions from Jira
"""

import os
import sys
import traceback

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from datetime import datetime

from healthchecks import hybrid_flags
import healthchecks.ssh_client as ssh_mod
from healthchecks.data_collector import (
    collect_data,
    generate_error_report_html,
    has_issues,
)
from healthchecks.email_sender import send_email_report
from healthchecks.jira_integration import (
    analyze_bugs_for_new_checks,
    check_jira_for_new_tests,
    generate_check_code,
    get_existing_check_names,
    get_known_recent_bugs,
    search_jira_for_new_bugs,
)
from healthchecks.rca_engine import (
    check_jira_bugs,
    determine_root_cause,
    get_known_bug_info,
)
from healthchecks.report_generator import analyze_failures, run_deep_investigation
from healthchecks.report_rca_html import generate_rca_html
from healthchecks.report_html import generate_html_report
from healthchecks.report_console import print_console_report
from healthchecks.ssh_client import SSHConnectionError, get_ssh_client, ssh_command

if hybrid_flags.SERVER_HOST:
    ssh_mod.HOST = hybrid_flags.SERVER_HOST

# Re-export flag constants expected by legacy imports of this module
USE_AI = hybrid_flags.USE_AI
AI_RCA = hybrid_flags.AI_RCA
RCA_BUGS = hybrid_flags.RCA_BUGS
RCA_JIRA = hybrid_flags.RCA_JIRA
RCA_EMAIL = hybrid_flags.RCA_EMAIL
SEND_EMAIL = hybrid_flags.SEND_EMAIL
CHECK_JIRA_NEW = hybrid_flags.CHECK_JIRA_NEW
SERVER_HOST = hybrid_flags.SERVER_HOST
LAB_NAME = hybrid_flags.LAB_NAME
EMAIL_TO = hybrid_flags.EMAIL_TO
HOST = ssh_mod.HOST
USER = ssh_mod.USER
KEY_PATH = ssh_mod.KEY_PATH


def __getattr__(name):
    if name == "ssh_client":
        return ssh_mod.ssh_client
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main():
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"

    print(f"\n{'='*60}")
    print(f"  {BLUE}🔍 CNV HealthCrew AI Starting...{RESET}")
    print(f"{'='*60}\n")

    print(f"  {YELLOW}⚙️  Configuration:{RESET}")
    if hybrid_flags.SERVER_HOST:
        print(f"     Server: {hybrid_flags.SERVER_HOST}")
    else:
        print(f"     Server: Using environment (RH_LAB_HOST)")
    if hybrid_flags.LAB_NAME:
        print(f"     Lab: {hybrid_flags.LAB_NAME}")
    print(f"     RCA Level: {'Full' if hybrid_flags.USE_AI else 'Bug Match' if hybrid_flags.RCA_BUGS else 'None'}")
    print(f"     AI RCA: {'Yes' if hybrid_flags.AI_RCA else 'No'}")
    print(f"     Jira RCA: {'Yes' if hybrid_flags.RCA_JIRA else 'No'}")
    print(f"     Email RCA: {'Yes' if hybrid_flags.RCA_EMAIL else 'No'}")
    print(f"     Send Email: {'Yes' if hybrid_flags.SEND_EMAIL else 'No'}")
    print()

    if hybrid_flags.CHECK_JIRA_NEW:
        print(f"  {YELLOW}🔍 Checking Jira for new test suggestions...{RESET}")
        new_checks = check_jira_for_new_tests()
        if new_checks:
            print(f"  💡 {len(new_checks)} new checks will be included in this run.\n")

    print(f"  {BLUE}📡 Connecting to cluster...{RESET}")
    print(f"     Host: {ssh_mod.HOST or '(not set)'}")
    print(f"     User: {ssh_mod.USER}")
    print(f"     Key:  {ssh_mod.KEY_PATH or '(not set)'}")
    print()

    try:
        print(f"\n  {BLUE}📊 Collecting cluster data...{RESET}")
        data = collect_data()

        print(f"\n  {BLUE}📋 Generating console report...{RESET}", flush=True)
        print_console_report(data)

        if hybrid_flags.USE_AI:
            rca_level = "full"
        elif hybrid_flags.RCA_BUGS:
            rca_level = "bugs"
        else:
            rca_level = "none"

        print(f"\n  {BLUE}📄 Generating HTML report...{RESET}", flush=True)
        if rca_level != "none":
            print(f"     RCA Level: {rca_level}", flush=True)

        html = generate_html_report(data, rca_level=rca_level, ai_rca=hybrid_flags.AI_RCA)
        timestamp = data["timestamp"].strftime("%Y-%m-%d_%H-%M-%S")

        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        reports_dir = os.path.join(project_dir, "reports")
        os.makedirs(reports_dir, exist_ok=True)

        html_file = f"health_report_{timestamp}.html"
        md_file = f"health_report_{timestamp}.md"
        html_path = os.path.join(reports_dir, html_file)
        md_path = os.path.join(reports_dir, md_file)

        print(f"  {YELLOW}💾 Saving HTML report...{RESET}")
        with open(html_path, "w") as f:
            f.write(html)
        print(f"     ✅ Saved: {html_file}")

        print(f"  {YELLOW}💾 Saving Markdown report...{RESET}")
        md_content = f"""# CNV HealthCrew AI Report
**Cluster:** {data['cluster']}  
**Date:** {data['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}  
**Version:** {data['version']}

## Summary
- **Nodes:** {len(data['nodes']['healthy'])}/{len(data['nodes']['healthy'])+len(data['nodes']['unhealthy'])} Ready
- **Operators:** {len(data['operators']['healthy'])}/{len(data['operators']['healthy'])+len(data['operators']['degraded'])+len(data['operators']['unavailable'])} Available  
- **Pods:** {data['pods']['healthy']} Running, {len(data['pods']['unhealthy'])} Unhealthy
- **VMs:** {data['kubevirt']['vms_running']} Running

## {'⚠️ Issues' if has_issues(data) else '✅ No Issues'}
"""
        if data["pods"]["unhealthy"]:
            by_ns = {}
            for p in data["pods"]["unhealthy"]:
                by_ns.setdefault(p["ns"], []).append(p)
            md_content += "\n### Unhealthy Pods\n"
            for ns in sorted(by_ns.keys()):
                md_content += f"\n**{ns}/**\n"
                for pod in by_ns[ns]:
                    md_content += f"- `{pod['name']}`: {pod['status']}\n"

        with open(md_path, "w") as f:
            f.write(md_content)
        print(f"     ✅ Saved: {md_file}")

        print(f"\n  {GREEN}{'='*50}{RESET}")
        print(f"  {GREEN}✅ Health check complete!{RESET}")
        print(f"  {GREEN}{'='*50}{RESET}")
        print(f"\n  📄 Reports saved:")
        print(f"     • {html_file}")
        print(f"     • {md_file}")

        if hybrid_flags.SEND_EMAIL:
            print(f"\n  📧 Sending email report to {hybrid_flags.EMAIL_TO}...", flush=True)
            cluster_name = data.get("version", "Unknown Cluster")
            issue_count = (
                len(data.get("nodes", {}).get("unhealthy", []))
                + len(data.get("operators", {}).get("degraded", []))
                + len(data.get("operators", {}).get("unavailable", []))
                + len(data.get("pods", {}).get("unhealthy", []))
                + len(data.get("kubevirt", {}).get("failed_vmis", []))
            )
            send_email_report(
                html_path,
                hybrid_flags.EMAIL_TO,
                cluster_name=cluster_name,
                issue_count=issue_count,
                report_data=data,
            )

        if has_issues(data):
            if hybrid_flags.USE_AI:
                print(f"\n  🔍 Full Root Cause Analysis included in report")
            elif hybrid_flags.RCA_BUGS:
                print(f"\n  🐛 Bug matching included in report (use --ai for full investigation)")
            else:
                print(f"\n  💡 Tip: Run with --rca-bugs for bug matching or --ai for full RCA")
            if hybrid_flags.AI_RCA:
                print(f"\n  🤖 AI Root Cause Analysis included in report")
            elif not hybrid_flags.AI_RCA:
                print(f"  💡 Tip: Run with --ai-rca for Gemini-powered AI analysis")

        print()

    except SSHConnectionError as e:
        RED = "\033[91m"
        print(f"\n  {RED}{'='*60}{RESET}")
        print(f"  {RED}❌ CONNECTION ERROR{RESET}")
        print(f"  {RED}{'='*60}{RESET}")
        print(f"\n  {RED}{e}{RESET}\n")
        print(f"  {YELLOW}Connection details:{RESET}")
        print(f"     Host:  {e.host or '(not set)'}")
        print(f"     User:  {e.user or '(not set)'}")
        print(f"     Key:   {e.key_path or '(not set)'}")
        if e.original_error:
            print(f"     Error:  {type(e.original_error).__name__}: {e.original_error}")
        print()
        print(f"  {YELLOW}Troubleshooting:{RESET}")
        print(f"     1. Verify the host is reachable: ssh {e.user or 'root'}@{e.host or '<host>'}")
        print(f"     2. Check SSH key exists and has correct permissions")
        print(f"     3. Ensure RH_LAB_HOST and SSH_KEY_PATH are set correctly")
        print(f"     4. If using --server, verify the hostname is correct")
        print()

        try:
            project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            reports_dir = os.path.join(project_dir, "reports")
            os.makedirs(reports_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            html_file = f"health_report_{timestamp}.html"
            html_path = os.path.join(reports_dir, html_file)
            error_html = generate_error_report_html(e)
            with open(html_path, "w") as f:
                f.write(error_html)
            print(f"  {YELLOW}📄 Error report saved: {html_file}{RESET}")
        except Exception:
            pass

        print()
        sys.exit(1)

    except Exception as e:
        print(f"\n  ❌ Error: {e}\n")
        traceback.print_exc()
    finally:
        if ssh_mod.ssh_client:
            ssh_mod.ssh_client.close()


if __name__ == "__main__":
    main()
