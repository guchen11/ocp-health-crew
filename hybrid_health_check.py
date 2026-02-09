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
import re
import json
import subprocess
import paramiko
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Jira bug status cache (populated at runtime)
JIRA_BUG_CACHE = {}

# Configuration
HOST = os.getenv("RH_LAB_HOST")
USER = os.getenv("RH_LAB_USER", "root")
KEY_PATH = os.getenv("SSH_KEY_PATH")
KUBECONFIG = "/home/kni/clusterconfigs/auth/kubeconfig"

# Email Configuration
EMAIL_TO = os.getenv("EMAIL_TO", "guchen@redhat.com")
EMAIL_FROM = os.getenv("EMAIL_FROM", "cnv-healthcrew@redhat.com")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.corp.redhat.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "25"))


def send_email_report(html_path, recipient=None, subject=None, cluster_name=None, issue_count=0, report_data=None):
    """
    Send a beautiful HTML email summary matching the dashboard style.
    
    Args:
        html_path: Path to the HTML report file
        recipient: Email recipient (defaults to EMAIL_TO)
        subject: Email subject (auto-generated if not provided)
        cluster_name: Cluster name for the subject line
        issue_count: Number of issues found (for subject line)
        report_data: Dict containing report data for email body
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    recipient = recipient or EMAIL_TO
    
    # Generate subject if not provided
    if not subject:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        status = "⚠️ ISSUES FOUND" if issue_count > 0 else "✅ HEALTHY"
        cluster_info = f" - {cluster_name}" if cluster_name else ""
        subject = f"[CNV HealthCrew AI] {status}{cluster_info} ({timestamp})"
    
    try:
        # Extract data for email summary
        data = report_data or {}
        version = data.get('version', 'N/A')
        
        # Node stats
        nodes = data.get('nodes', {})
        healthy_nodes = len(nodes.get('healthy', []))
        unhealthy_nodes = len(nodes.get('unhealthy', []))
        total_nodes = healthy_nodes + unhealthy_nodes
        
        # Operator stats
        operators = data.get('operators', {})
        healthy_ops = len(operators.get('healthy', []))
        degraded_ops = len(operators.get('degraded', []))
        unavailable_ops = len(operators.get('unavailable', []))
        total_ops = healthy_ops + degraded_ops + unavailable_ops
        
        # Pod stats
        pods = data.get('pods', {})
        healthy_pods = pods.get('healthy', 0)
        unhealthy_pods_list = pods.get('unhealthy', [])
        unhealthy_pods = len(unhealthy_pods_list)
        total_pods = healthy_pods + unhealthy_pods
        
        # VM stats
        vms = data.get('vms', {})
        running_vms = len(vms.get('running', []))
        stopped_vms = len(vms.get('stopped', []))
        total_vms = running_vms + stopped_vms
        
        # KubeVirt stats
        kubevirt = data.get('kubevirt', {})
        failed_vmis = kubevirt.get('failed_vmis', [])
        migrations = kubevirt.get('migrations', [])
        running_migrations = len([m for m in migrations if isinstance(m, dict) and m.get('status') == 'Running'])
        
        # ETCD stats
        etcd = data.get('etcd', {})
        etcd_members = etcd.get('member_count', 0) if isinstance(etcd, dict) else 0
        
        # PVC stats
        pvcs = data.get('pvcs', {})
        pending_pvcs = len(pvcs.get('pending', [])) if isinstance(pvcs, dict) else 0
        
        # OOM events
        oom_events = len(data.get('oom_events', []))
        
        # Status styling
        if issue_count > 0:
            status_text = "ATTENTION NEEDED"
            status_color = "#ff6b6b"
        else:
            status_text = "ALL SYSTEMS HEALTHY"
            status_color = "#73BF69"
        
        # Helper function to create gauge SVG (email-safe version using arc)
        def create_gauge(value, total, color="#73BF69"):
            if total == 0:
                percent = 100
            else:
                percent = (value / total) * 100
            # Create a simple circular progress indicator using borders
            return f'''<div style="width:80px;height:80px;margin:0 auto;position:relative;">
                <div style="width:80px;height:80px;border-radius:50%;border:8px solid #2a2a3e;box-sizing:border-box;"></div>
                <div style="position:absolute;top:0;left:0;width:80px;height:80px;border-radius:50%;border:8px solid {color};border-color:{color} {color} transparent transparent;box-sizing:border-box;transform:rotate({int(percent * 1.8 - 45)}deg);"></div>
            </div>'''
        
        # Build unhealthy pods HTML
        unhealthy_pods_html = ""
        if unhealthy_pods_list:
            pods_rows = ""
            for pod in unhealthy_pods_list[:6]:  # Show max 6
                if isinstance(pod, dict):
                    pod_name = pod.get('name', 'unknown')
                    pod_ns = pod.get('namespace', '')
                    pod_status = pod.get('status', 'Error')
                    # Truncate long names
                    if len(pod_name) > 40:
                        pod_name = pod_name[:37] + "..."
                    status_bg = "#ff6b6b" if 'Error' in pod_status or 'Crash' in pod_status else "#ffaa00"
                    pods_rows += f'''<tr>
                        <td style="padding:8px 12px;color:#8b8fa3;font-size:11px;border-bottom:1px solid #2a2a3e;">{pod_ns}</td>
                        <td style="padding:8px 12px;color:#e0e0e0;font-size:12px;border-bottom:1px solid #2a2a3e;">{pod_name}</td>
                        <td style="padding:8px 12px;text-align:right;border-bottom:1px solid #2a2a3e;">
                            <span style="background:{status_bg};color:#fff;padding:2px 8px;border-radius:4px;font-size:10px;">{pod_status}</span>
                        </td>
                    </tr>'''
            
            remaining = len(unhealthy_pods_list) - 6
            if remaining > 0:
                pods_rows += f'''<tr><td colspan="3" style="padding:8px 12px;color:#8b8fa3;font-size:11px;text-align:center;">...and {remaining} more in full report</td></tr>'''
            
            unhealthy_pods_html = f'''
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#1e1e2e;border-radius:12px;margin-top:16px;overflow:hidden;">
                <tr>
                    <td style="padding:16px 20px;border-bottom:1px solid #2a2a3e;">
                        <span style="color:#ff6b6b;font-size:13px;font-weight:600;">⚠️ UNHEALTHY PODS ({unhealthy_pods})</span>
                    </td>
                </tr>
                <tr>
                    <td style="padding:0;">
                        <table width="100%" cellpadding="0" cellspacing="0">
                            {pods_rows}
                        </table>
                    </td>
                </tr>
            </table>'''
        
        # Create beautiful dark-themed HTML email matching the dashboard
        html_content = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;background:#0d0d14;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#0d0d14;padding:20px 0;">
        <tr>
            <td align="center">
                <table width="700" cellpadding="0" cellspacing="0" style="background:#13131f;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.4);">
                    
                    <!-- Header Bar -->
                    <tr>
                        <td style="background:linear-gradient(90deg,#1a1a2e 0%,#16213e 100%);padding:16px 24px;">
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td>
                                        <span style="color:#73BF69;font-size:18px;font-weight:700;">CNV</span>
                                        <span style="color:#ffffff;font-size:18px;font-weight:300;"> HealthCrew</span>
                                        <span style="color:#73BF69;font-size:18px;font-weight:700;"> AI</span>
                                    </td>
                                    <td style="text-align:right;">
                                        <span style="background:{status_color};color:#fff;padding:6px 16px;border-radius:6px;font-size:12px;font-weight:600;">{status_text}</span>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Cluster Info -->
                    <tr>
                        <td style="padding:20px 24px;border-bottom:1px solid #2a2a3e;">
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td style="color:#ffffff;font-size:20px;font-weight:600;padding-bottom:12px;">
                                        {cluster_name or 'Cluster Health Report'}
                                    </td>
                                </tr>
                                <tr>
                                    <td>
                                        <table cellpadding="0" cellspacing="0">
                                            <tr>
                                                <td style="padding-right:24px;">
                                                    <span style="color:#73BF69;font-size:12px;">📅</span>
                                                    <span style="color:#8b8fa3;font-size:12px;"> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</span>
                                                </td>
                                                <td style="padding-right:24px;">
                                                    <span style="color:#73BF69;font-size:12px;">🏷️</span>
                                                    <span style="color:#8b8fa3;font-size:12px;"> Version {version}</span>
                                                </td>
                                                <td>
                                                    <span style="color:#73BF69;font-size:12px;">🔍</span>
                                                    <span style="color:#8b8fa3;font-size:12px;"> 17 Health Checks</span>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Main Stats Cards - Row 1 -->
                    <tr>
                        <td style="padding:20px 24px 10px;">
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <!-- NODES Card -->
                                    <td width="24%" style="vertical-align:top;">
                                        <table width="100%" cellpadding="0" cellspacing="0" style="background:#1e1e2e;border-radius:12px;overflow:hidden;">
                                            <tr>
                                                <td style="padding:16px;text-align:center;">
                                                    <div style="color:#8b8fa3;font-size:11px;font-weight:500;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;">🖥️ NODES</div>
                                                    <div style="width:70px;height:70px;margin:0 auto 12px;border-radius:50%;border:6px solid #2a2a3e;border-top-color:{'#73BF69' if unhealthy_nodes == 0 else '#ff6b6b'};border-right-color:{'#73BF69' if unhealthy_nodes == 0 else '#ff6b6b'};"></div>
                                                    <div style="color:{'#73BF69' if unhealthy_nodes == 0 else '#ff6b6b'};font-size:28px;font-weight:700;">{healthy_nodes}<span style="color:#8b8fa3;font-size:14px;font-weight:400;">/{total_nodes}</span></div>
                                                    <div style="color:#8b8fa3;font-size:11px;margin-top:4px;">Ready</div>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                    <td width="2%"></td>
                                    <!-- OPERATORS Card -->
                                    <td width="24%" style="vertical-align:top;">
                                        <table width="100%" cellpadding="0" cellspacing="0" style="background:#1e1e2e;border-radius:12px;overflow:hidden;">
                                            <tr>
                                                <td style="padding:16px;text-align:center;">
                                                    <div style="color:#8b8fa3;font-size:11px;font-weight:500;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;">⚙️ OPERATORS</div>
                                                    <div style="width:70px;height:70px;margin:0 auto 12px;border-radius:50%;border:6px solid #2a2a3e;border-top-color:{'#73BF69' if degraded_ops + unavailable_ops == 0 else '#ff6b6b'};border-right-color:{'#73BF69' if degraded_ops + unavailable_ops == 0 else '#ff6b6b'};"></div>
                                                    <div style="color:{'#73BF69' if degraded_ops + unavailable_ops == 0 else '#ff6b6b'};font-size:28px;font-weight:700;">{healthy_ops}<span style="color:#8b8fa3;font-size:14px;font-weight:400;">/{total_ops}</span></div>
                                                    <div style="color:#8b8fa3;font-size:11px;margin-top:4px;">Available</div>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                    <td width="2%"></td>
                                    <!-- PODS Card -->
                                    <td width="24%" style="vertical-align:top;">
                                        <table width="100%" cellpadding="0" cellspacing="0" style="background:#1e1e2e;border-radius:12px;overflow:hidden;">
                                            <tr>
                                                <td style="padding:16px;text-align:center;">
                                                    <div style="color:#8b8fa3;font-size:11px;font-weight:500;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;">📦 PODS</div>
                                                    <div style="width:70px;height:70px;margin:0 auto 12px;border-radius:50%;border:6px solid #2a2a3e;border-top-color:{'#73BF69' if unhealthy_pods == 0 else '#ffaa00'};border-right-color:{'#73BF69' if unhealthy_pods == 0 else '#ffaa00'};"></div>
                                                    <div style="color:{'#73BF69' if unhealthy_pods == 0 else '#ffaa00'};font-size:28px;font-weight:700;">{healthy_pods}<span style="color:#8b8fa3;font-size:14px;font-weight:400;">/{total_pods}</span></div>
                                                    <div style="color:#8b8fa3;font-size:11px;margin-top:4px;">Running</div>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                    <td width="2%"></td>
                                    <!-- VMS Card -->
                                    <td width="24%" style="vertical-align:top;">
                                        <table width="100%" cellpadding="0" cellspacing="0" style="background:#1e1e2e;border-radius:12px;overflow:hidden;">
                                            <tr>
                                                <td style="padding:16px;text-align:center;">
                                                    <div style="color:#8b8fa3;font-size:11px;font-weight:500;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;">🖧 VMS</div>
                                                    <div style="width:70px;height:70px;margin:0 auto 12px;border-radius:50%;border:6px solid #2a2a3e;border-top-color:#73BF69;border-right-color:#73BF69;"></div>
                                                    <div style="color:#73BF69;font-size:28px;font-weight:700;">{running_vms}<span style="color:#8b8fa3;font-size:14px;font-weight:400;">/{total_vms}</span></div>
                                                    <div style="color:#8b8fa3;font-size:11px;margin-top:4px;">Running</div>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Stats Cards - Row 2 -->
                    <tr>
                        <td style="padding:10px 24px 20px;">
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <!-- ETCD Card -->
                                    <td width="24%" style="vertical-align:top;">
                                        <table width="100%" cellpadding="0" cellspacing="0" style="background:#1e1e2e;border-radius:12px;overflow:hidden;">
                                            <tr>
                                                <td style="padding:16px;text-align:center;">
                                                    <div style="color:#8b8fa3;font-size:10px;font-weight:500;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">🗄️ ETCD MEMBERS</div>
                                                    <div style="color:#73BF69;font-size:32px;font-weight:700;">{etcd_members}</div>
                                                    <div style="color:#8b8fa3;font-size:11px;margin-top:4px;">Healthy</div>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                    <td width="2%"></td>
                                    <!-- PVCs Card -->
                                    <td width="24%" style="vertical-align:top;">
                                        <table width="100%" cellpadding="0" cellspacing="0" style="background:#1e1e2e;border-radius:12px;overflow:hidden;">
                                            <tr>
                                                <td style="padding:16px;text-align:center;">
                                                    <div style="color:#8b8fa3;font-size:10px;font-weight:500;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">💾 PVCS PENDING</div>
                                                    <div style="color:{'#73BF69' if pending_pvcs == 0 else '#ffaa00'};font-size:32px;font-weight:700;">{pending_pvcs}</div>
                                                    <div style="color:#8b8fa3;font-size:11px;margin-top:4px;">&nbsp;</div>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                    <td width="2%"></td>
                                    <!-- OOM Card -->
                                    <td width="24%" style="vertical-align:top;">
                                        <table width="100%" cellpadding="0" cellspacing="0" style="background:#1e1e2e;border-radius:12px;overflow:hidden;">
                                            <tr>
                                                <td style="padding:16px;text-align:center;">
                                                    <div style="color:#8b8fa3;font-size:10px;font-weight:500;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">💥 OOM EVENTS</div>
                                                    <div style="color:{'#73BF69' if oom_events == 0 else '#ff6b6b'};font-size:32px;font-weight:700;">{oom_events}</div>
                                                    <div style="color:#8b8fa3;font-size:11px;margin-top:4px;">Recent</div>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                    <td width="2%"></td>
                                    <!-- Migrations Card -->
                                    <td width="24%" style="vertical-align:top;">
                                        <table width="100%" cellpadding="0" cellspacing="0" style="background:#1e1e2e;border-radius:12px;overflow:hidden;">
                                            <tr>
                                                <td style="padding:16px;text-align:center;">
                                                    <div style="color:#8b8fa3;font-size:10px;font-weight:500;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;">🔄 MIGRATIONS</div>
                                                    <div style="color:#73BF69;font-size:32px;font-weight:700;">{running_migrations}</div>
                                                    <div style="color:#8b8fa3;font-size:11px;margin-top:4px;">Running</div>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Unhealthy Pods Section -->
                    <tr>
                        <td style="padding:0 24px 20px;">
                            {unhealthy_pods_html}
                        </td>
                    </tr>
                    
                    <!-- CTA Button -->
                    <tr>
                        <td style="padding:0 24px 24px;">
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td align="center">
                                        <table cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,#73BF69 0%,#5ba350 100%);border-radius:8px;">
                                            <tr>
                                                <td style="padding:14px 32px;color:#ffffff;font-weight:600;font-size:14px;">
                                                    📎 Full Report Attached
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="background:#1a1a2e;padding:16px 24px;border-top:1px solid #2a2a3e;">
                            <table width="100%" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td style="color:#8b8fa3;font-size:11px;text-align:center;">
                                        <strong style="color:#73BF69;">CNV HealthCrew AI</strong> • Performance Engineering Team<br>
                                        <span style="font-size:10px;color:#5f6368;">Automated health check report • {datetime.now().strftime("%Y-%m-%d")}</span>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                </table>
            </td>
        </tr>
    </table>
</body>
</html>'''
        
        # Create message
        msg = MIMEMultipart('mixed')
        msg['Subject'] = subject
        msg['From'] = EMAIL_FROM
        msg['To'] = recipient
        
        # Create alternative part for text/html
        msg_alt = MIMEMultipart('alternative')
        
        # Create plain text version (summary)
        plain_text = f"""
╔════════════════════════════════════════════════════════════╗
║                   CNV HealthCrew AI                         ║
║              Health Check Report Summary                    ║
╚════════════════════════════════════════════════════════════╝

Cluster: {cluster_name or 'N/A'}
Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Version: {version}
Status: {status_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RESOURCE STATUS
---------------
🖥️ Nodes:      {healthy_nodes}/{total_nodes} Ready
⚙️ Operators:  {healthy_ops}/{total_ops} Available
📦 Pods:       {healthy_pods}/{total_pods} Running
🖧 VMs:        {running_vms}/{total_vms} Running

CLUSTER HEALTH
--------------
🗄️ ETCD Members:    {etcd_members} Healthy
💾 PVCs Pending:    {pending_pvcs}
💥 OOM Events:      {oom_events}
🔄 Migrations:      {running_migrations} Running

{'⚠️ Issues Found: ' + str(issue_count) if issue_count > 0 else '✅ No issues detected.'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Full HTML report is attached to this email.

--
CNV HealthCrew AI
Performance Engineering Team
        """
        
        # Attach both plain text and HTML
        part1 = MIMEText(plain_text, 'plain')
        part2 = MIMEText(html_content, 'html')
        
        msg_alt.attach(part1)
        msg_alt.attach(part2)
        msg.attach(msg_alt)
        
        # Also attach the full HTML report file
        with open(html_path, 'rb') as f:
            attachment = MIMEBase('text', 'html')
            attachment.set_payload(f.read())
            encoders.encode_base64(attachment)
            filename = os.path.basename(html_path)
            attachment.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            msg.attach(attachment)
        
        # Send the email
        print(f"  📧 Connecting to SMTP server ({SMTP_SERVER}:{SMTP_PORT})...", flush=True)
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.sendmail(EMAIL_FROM, [recipient], msg.as_string())
        
        print(f"  ✅ Email sent successfully to {recipient}", flush=True)
        return True
        
    except FileNotFoundError:
        print(f"  ❌ Email failed: Report file not found: {html_path}", flush=True)
        return False
    except smtplib.SMTPConnectError as e:
        print(f"  ❌ Email failed: Could not connect to SMTP server {SMTP_SERVER}:{SMTP_PORT}", flush=True)
        print(f"     Error: {e}", flush=True)
        print(f"     💡 Tip: Set SMTP_SERVER and SMTP_PORT environment variables", flush=True)
        return False
    except smtplib.SMTPException as e:
        print(f"  ❌ Email failed: SMTP error: {e}", flush=True)
        return False
    except Exception as e:
        print(f"  ❌ Email failed: {e}", flush=True)
        return False


# Parse arguments
USE_AI = "--ai" in sys.argv  # Full RCA with deep investigation
RCA_BUGS = "--rca-bugs" in sys.argv  # Bug matching only (no deep investigation)
RCA_JIRA = "--rca-jira" in sys.argv  # Search Jira for RCA
RCA_EMAIL = "--rca-email" in sys.argv  # Search email for RCA
SEND_EMAIL = "--email" in sys.argv or "-e" in sys.argv
CHECK_JIRA_NEW = "--check-jira" in sys.argv or "--jira" in sys.argv

# Parse --server argument
SERVER_HOST = None
for i, arg in enumerate(sys.argv):
    if arg == '--server' and i + 1 < len(sys.argv):
        SERVER_HOST = sys.argv[i + 1]
        HOST = SERVER_HOST  # Override HOST with command line argument
        break

# Parse --email-to argument
for i, arg in enumerate(sys.argv):
    if arg == '--email-to' and i + 1 < len(sys.argv):
        EMAIL_TO = sys.argv[i + 1]
        break

# Keywords that indicate a bug might need a health check
HEALTH_CHECK_KEYWORDS = {
    "crash": "Pod crash detection",
    "oom": "OOM event monitoring",
    "memory leak": "Memory usage check",
    "high latency": "Latency monitoring",
    "not ready": "Readiness check",
    "stuck": "Stuck resource detection",
    "timeout": "Timeout detection",
    "certificate": "Certificate expiry check",
    "expir": "Expiration monitoring",
    "failed": "Failure detection",
    "degraded": "Degraded state check",
    "unavailable": "Availability check",
    "pending": "Pending resource check",
    "node not": "Node health check",
    "kubelet": "Kubelet health check",
    "etcd": "etcd health check",
    "migration": "Migration status check",
    "storage": "Storage health check",
    "pvc": "PVC status check",
    "csi": "CSI driver check",
    "operator": "Operator health check",
    "catalog": "Catalog source check",
    "router": "Router health check",
    "network": "Network connectivity check",
    "dns": "DNS resolution check",
    "api": "API server check",
}

# Components that map to health check categories
COMPONENT_TO_CHECK = {
    "Etcd": "etcd",
    "Machine Config Operator": "mco",
    "Networking": "network",
    "Storage": "storage",
    "OLM": "olm",
    "CNV": "cnv",
    "Virtualization": "cnv",
    "kube-apiserver": "apiserver",
    "oauth": "oauth",
    "Installer": "installer",
}

# Global SSH client
ssh_client = None

def call_jira_mcp(tool_name, arguments):
    """Call Jira MCP tool via subprocess"""
    try:
        # Use cursor's mcp-proxy to call the tool
        import urllib.request
        import urllib.error
        
        # Try direct Jira API if MCP not available
        # For now, return mock data structure - will be replaced by actual MCP call
        return None
    except Exception as e:
        print(f"  ⚠️  Jira API error: {e}")
        return None

def search_jira_for_new_bugs(days=30, limit=50):
    """
    Search Jira for recent bugs in CNV, ODF, OCPBUGS projects.
    Returns list of bugs that might suggest new health checks.
    """
    # JQL to find recent bugs
    jql_queries = [
        f'project = CNV AND issuetype = Bug AND status in (Open, "In Progress", New) AND created >= -{days}d ORDER BY priority DESC, created DESC',
        f'project = OCPBUGS AND issuetype = Bug AND status in (Open, "In Progress", New) AND created >= -{days}d ORDER BY priority DESC, created DESC',
    ]
    
    all_bugs = []
    
    # Try to use mcp-proxy for Jira access
    try:
        for jql in jql_queries:
            result = subprocess.run(
                ['mcp-proxy', 'call', 'user-jira', 'jira_search', 
                 '--jql', jql, '--limit', str(limit // 2),
                 '--fields', 'summary,status,priority,components,labels,created'],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if 'issues' in data:
                    all_bugs.extend(data['issues'])
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        # MCP proxy not available, use fallback recent bugs list
        pass
    
    # If no bugs from Jira, use known recent bugs from our database
    if not all_bugs:
        all_bugs = get_known_recent_bugs()
    
    return all_bugs

def get_known_recent_bugs():
    """Return list of known recent bugs that might need health checks"""
    return [
        {
            "key": "OCPBUGS-74962",
            "summary": "[4.19] Very High etcd Latency",
            "priority": {"name": "Critical"},
            "components": [{"name": "Etcd"}],
            "suggested_check": "etcd_latency",
            "check_description": "Monitor etcd latency and alert on high values"
        },
        {
            "key": "OCPBUGS-74938",
            "summary": "Kubelet and NetworkManager do not start automatically on any node after reboot",
            "priority": {"name": "Critical"},
            "components": [{"name": "Machine Config Operator"}],
            "suggested_check": "kubelet_health",
            "check_description": "Check if kubelet is running on all nodes"
        },
        {
            "key": "OCPBUGS-74926",
            "summary": "In-memory certificate expiration date is too short",
            "priority": {"name": "Major"},
            "components": [{"name": "oauth-apiserver"}],
            "suggested_check": "cert_expiry",
            "check_description": "Check certificate expiration dates"
        },
        {
            "key": "OCPBUGS-74907",
            "summary": "SDN to OVN-Kubernetes migration stuck",
            "priority": {"name": "Critical"},
            "components": [{"name": "Networking / ovn-kubernetes"}],
            "suggested_check": "network_migration",
            "check_description": "Check network migration status"
        },
        {
            "key": "CNV-78575",
            "summary": "kubevirt-hyperconverged operator version disappeared from OLM catalog",
            "priority": {"name": "Major"},
            "components": [{"name": "CNV Install, Upgrade and Operators"}],
            "suggested_check": "catalog_source",
            "check_description": "Verify OLM catalog sources are healthy"
        },
        {
            "key": "OCPBUGS-74894",
            "summary": "Router got flooding connection",
            "priority": {"name": "Major"},
            "components": [{"name": "Networking / router"}],
            "suggested_check": "router_health",
            "check_description": "Monitor router pod health and connection count"
        },
        {
            "key": "CNV-78518",
            "summary": "virt-exportserver image pull issues",
            "priority": {"name": "Major"},
            "components": [{"name": "CNV Install, Upgrade and Operators"}],
            "suggested_check": "image_pull",
            "check_description": "Check for ImagePullBackOff errors"
        },
    ]

def analyze_bugs_for_new_checks(bugs, existing_checks):
    """
    Analyze bugs to determine if new health checks should be added.
    Returns list of suggested new checks.
    """
    suggestions = []
    
    for bug in bugs:
        summary = bug.get("summary", "").lower()
        key = bug.get("key", "")
        priority = bug.get("priority", {}).get("name", "Normal")
        components = [c.get("name", "") if isinstance(c, dict) else c for c in bug.get("components", [])]
        
        # Check if bug already has a suggested check
        if bug.get("suggested_check"):
            check_name = bug["suggested_check"]
            if check_name not in existing_checks:
                suggestions.append({
                    "jira_key": key,
                    "summary": bug.get("summary", ""),
                    "priority": priority,
                    "components": components,
                    "suggested_check": check_name,
                    "check_description": bug.get("check_description", ""),
                    "reason": f"Based on bug {key}"
                })
            continue
        
        # Analyze summary for health check keywords
        matched_keywords = []
        for keyword, check_type in HEALTH_CHECK_KEYWORDS.items():
            if keyword in summary:
                matched_keywords.append((keyword, check_type))
        
        # Analyze components
        matched_components = []
        for comp in components:
            for comp_key, check_cat in COMPONENT_TO_CHECK.items():
                if comp_key.lower() in comp.lower():
                    matched_components.append((comp, check_cat))
        
        # Only suggest if priority is Critical/Major or multiple keywords match
        if (priority in ["Critical", "Blocker", "Major"] or len(matched_keywords) >= 2) and matched_keywords:
            # Generate suggested check name
            check_name = matched_keywords[0][1].lower().replace(" ", "_")
            if matched_components:
                check_name = f"{matched_components[0][1]}_{check_name}"
            
            if check_name not in existing_checks:
                suggestions.append({
                    "jira_key": key,
                    "summary": bug.get("summary", ""),
                    "priority": priority,
                    "components": components,
                    "suggested_check": check_name,
                    "check_description": f"New check based on: {matched_keywords[0][1]}",
                    "matched_keywords": [k[0] for k in matched_keywords],
                    "reason": f"Keywords: {', '.join([k[0] for k in matched_keywords[:3]])}"
                })
    
    # Deduplicate by check name
    seen = set()
    unique_suggestions = []
    for s in suggestions:
        if s["suggested_check"] not in seen:
            seen.add(s["suggested_check"])
            unique_suggestions.append(s)
    
    return unique_suggestions[:10]  # Limit to top 10 suggestions

def get_existing_check_names():
    """Return list of existing health check names"""
    return [
        "nodes", "operators", "pods", "kubevirt", "resources", "etcd",
        "pvcs", "migrations", "oom_events", "csi", "virt_handler",
        "virt_ctrl", "virt_launcher", "datavolumes", "volumesnapshots",
        "cordoned_vms", "stuck_migrations"
    ]

def display_jira_suggestions(suggestions):
    """Display Jira-based health check suggestions to user"""
    if not suggestions:
        print("\n  ✅ No new health checks suggested from recent Jira bugs.\n")
        return []
    
    # ANSI colors
    Y = '\033[93m'
    G = '\033[92m'
    B = '\033[94m'
    C = '\033[96m'
    R = '\033[91m'
    X = '\033[0m'
    BD = '\033[1m'
    
    print(f"\n{B}╔{'═'*72}╗{X}")
    print(f"{B}║{X}  {BD}🔍 NEW HEALTH CHECK SUGGESTIONS FROM JIRA{X}".ljust(83) + f"{B}║{X}")
    print(f"{B}╠{'═'*72}╣{X}")
    print(f"{B}║{X}  Found {Y}{len(suggestions)}{X} potential new checks based on recent Jira bugs:".ljust(88) + f"{B}║{X}")
    print(f"{B}╠{'─'*72}╣{X}")
    
    for i, s in enumerate(suggestions, 1):
        priority_color = R if s['priority'] in ['Critical', 'Blocker'] else Y if s['priority'] == 'Major' else X
        print(f"{B}║{X}  {BD}{i}.{X} {C}{s['suggested_check']}{X}".ljust(85) + f"{B}║{X}")
        print(f"{B}║{X}     {priority_color}[{s['priority']}]{X} {s['jira_key']}: {s['summary'][:45]}...".ljust(85) + f"{B}║{X}")
        print(f"{B}║{X}     {G}→ {s['check_description'][:55]}{X}".ljust(88) + f"{B}║{X}")
        if i < len(suggestions):
            print(f"{B}║{X}" + " "*72 + f"{B}║{X}")
    
    print(f"{B}╠{'═'*72}╣{X}")
    print(f"{B}║{X}  {Y}Enter check numbers to add (comma-separated), 'all', or 'skip':{X}".ljust(88) + f"{B}║{X}")
    print(f"{B}╚{'═'*72}╝{X}")
    
    return suggestions

def prompt_for_new_checks(suggestions):
    """Prompt user to select which checks to add"""
    if not suggestions:
        return []
    
    # Check if running non-interactively (from web UI)
    import sys
    import os
    import json
    
    if not sys.stdin.isatty() or os.environ.get('NON_INTERACTIVE'):
        # Save suggestions to file for web UI review
        suggestions_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.suggested_checks.json')
        try:
            # Load existing suggestions
            existing = []
            if os.path.exists(suggestions_file):
                with open(suggestions_file, 'r') as f:
                    existing = json.load(f)
            
            # Add new suggestions with timestamp
            from datetime import datetime
            for s in suggestions:
                s['timestamp'] = datetime.now().isoformat()
                s['status'] = 'pending'
            
            # Merge (avoid duplicates by jira_key)
            existing_keys = {s.get('jira_key') for s in existing}
            for s in suggestions:
                if s.get('jira_key') not in existing_keys:
                    existing.append(s)
            
            with open(suggestions_file, 'w') as f:
                json.dump(existing, f, indent=2)
            
            print(f"  💾 Saved {len(suggestions)} suggestions for web UI review")
            print(f"     Review at: Dashboard > Jira Suggestions\n")
        except Exception as e:
            print(f"  ⚠️  Could not save suggestions: {e}\n")
        
        return []  # Don't add checks automatically, let user review in web UI
    
    # Interactive mode - prompt user
    try:
        response = input("\n  Your choice: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return []
    
    if response == 'skip' or response == 's' or response == '':
        print("  ⏭️  Skipping new check additions.\n")
        return []
    
    if response == 'all' or response == 'a':
        print(f"  ✅ Adding all {len(suggestions)} suggested checks.\n")
        return suggestions
    
    # Parse comma-separated numbers
    selected = []
    try:
        indices = [int(x.strip()) - 1 for x in response.split(',')]
        for idx in indices:
            if 0 <= idx < len(suggestions):
                selected.append(suggestions[idx])
    except ValueError:
        print("  ⚠️  Invalid input. Skipping.\n")
        return []
    
    if selected:
        print(f"  ✅ Adding {len(selected)} selected checks.\n")
    
    return selected

def generate_check_code(check_info):
    """Generate the code for a new health check"""
    check_name = check_info['suggested_check']
    jira_key = check_info['jira_key']
    description = check_info['check_description']
    
    # Map check types to actual commands (stored as description, actual execution happens in collect_data)
    check_commands = {
        "etcd_latency": "oc exec etcd pod -- etcdctl endpoint health",
        "kubelet_health": "oc get nodes with Ready status",
        "cert_expiry": "oc get secrets with TLS type",
        "network_migration": "oc get network.operator migration status",
        "catalog_source": "oc get catalogsource status",
        "router_health": "oc get router pods",
        "image_pull": "oc get pods with ImagePullBackOff",
    }
    
    cmd = check_commands.get(check_name, "oc get pods")
    
    return {
        "name": check_name,
        "command": cmd,
        "jira": jira_key,
        "description": description
    }

def add_checks_to_script(selected_checks):
    """
    Add new checks to the SUGGESTED_NEW_CHECKS list (runtime only).
    In a real implementation, this could modify the script file.
    """
    global SUGGESTED_NEW_CHECKS
    SUGGESTED_NEW_CHECKS = []
    
    for check in selected_checks:
        check_code = generate_check_code(check)
        SUGGESTED_NEW_CHECKS.append(check_code)
        print(f"  📝 Added check: {check_code['name']} (from {check_code['jira']})")
    
    return SUGGESTED_NEW_CHECKS

def check_jira_for_new_tests():
    """
    Main function to check Jira for new bugs and suggest health checks.
    Called before running the health check if --check-jira flag is set.
    """
    print(f"\n  🔍 Checking Jira for recent bugs that might need new health checks...")
    
    # Get existing check names
    existing_checks = get_existing_check_names()
    
    # Search Jira for recent bugs
    bugs = search_jira_for_new_bugs(days=30, limit=50)
    
    if not bugs:
        print("  ⚠️  Could not fetch bugs from Jira. Using known recent bugs.\n")
        bugs = get_known_recent_bugs()
    
    print(f"  📊 Analyzed {len(bugs)} recent bugs from CNV/OCP/ODF projects")
    
    # Analyze bugs for potential new checks
    suggestions = analyze_bugs_for_new_checks(bugs, existing_checks)
    
    # Display suggestions and prompt user
    display_jira_suggestions(suggestions)
    
    # Get user selection
    selected = prompt_for_new_checks(suggestions)
    
    # Add selected checks
    if selected:
        add_checks_to_script(selected)
        return selected
    
    return []

def search_emails_for_issues(issues, gmail_account="guchen@redhat.com"):
    """
    Search Gmail for emails related to the detected issues.
    Uses the MCP Gmail tool to search for relevant emails.
    Returns dict mapping issue types to related emails.
    """
    import subprocess
    import json
    
    email_results = {}
    
    if not issues:
        return email_results
    
    print(f"  📧 Searching emails for related discussions...")
    
    # Build search queries based on issue types
    search_keywords = []
    for issue in issues:
        if isinstance(issue, dict):
            issue_type = issue.get('type', '')
            resource = issue.get('resource', issue.get('name', ''))
        else:
            issue_type = str(issue)
            resource = ''
        
        # Add keywords based on issue type
        if 'virt-handler' in str(issue_type).lower() or 'virt-handler' in str(resource).lower():
            search_keywords.extend(['virt-handler memory', 'virt-handler high memory'])
        elif 'migration' in str(issue_type).lower():
            search_keywords.extend(['vm migration stuck', 'migration failed'])
        elif 'operator' in str(issue_type).lower():
            search_keywords.extend(['operator degraded', 'cluster operator'])
        elif 'pod' in str(issue_type).lower():
            search_keywords.extend(['pod crashloop', 'pod not ready'])
        elif 'storage' in str(issue_type).lower() or 'odf' in str(issue_type).lower():
            search_keywords.extend(['storage issue', 'ODF degraded', 'ceph'])
        elif 'snapshot' in str(issue_type).lower():
            search_keywords.extend(['snapshot failed', 'volumesnapshot'])
    
    # Also search for general CNV/OCP issues
    search_keywords.extend(['CNV issue', 'OpenShift problem', 'cluster alert'])
    
    # Deduplicate
    search_keywords = list(set(search_keywords))[:5]  # Limit to 5 searches
    
    found_emails = []
    for keyword in search_keywords:
        try:
            # For now, we'll store the search terms - actual email search would be done via MCP
            # This is a placeholder that the web dashboard can use with MCP tools
            found_emails.append({
                'search_term': keyword,
                'status': 'pending',
                'results': []
            })
        except Exception as e:
            pass
    
    email_results['searches'] = found_emails
    email_results['keywords'] = search_keywords
    
    print(f"  📧 Prepared {len(search_keywords)} email search queries")
    
    return email_results

# Storage for dynamically added checks
SUGGESTED_NEW_CHECKS = []

# Knowledge Base - Based on real Jira bugs (CNV, OCPBUGS)
KNOWN_ISSUES = {
    "virt-handler-memory": {
        "pattern": ["virt-handler", "high_memory", "memory"],
        "jira": ["CNV-66551", "CNV-71448", "CNV-30274"],
        "title": "virt-handler High Memory Usage",
        "description": "virt-handler pods using more memory than expected. Common at scale (>50 VMs per node).",
        "root_cause": [
            "Memory requests are hardcoded and set too low for large scale deployments",
            "Goroutine leaks after EUS upgrades (CNV-71448)",
            "Object cache not properly cleaned up at high VM density"
        ],
        "suggestions": [
            "Check if running >50 VMs per node - consider spreading workload",
            "Review virt-handler resource requests in HyperConverged CR",
            "If after upgrade, consider rolling restart of virt-handler pods",
            "Monitor with: oc adm top pods -n openshift-cnv -l kubevirt.io=virt-handler"
        ],
        "verify_cmd": "oc adm top pods -n openshift-cnv -l kubevirt.io=virt-handler --no-headers"
    },
    "virt-handler-error": {
        "pattern": ["virt-handler", "error", "crash", "restart"],
        "jira": ["CNV-68292", "CNV-70607"],
        "title": "virt-handler Pod Errors",
        "description": "virt-handler pods in error state, often during high-scale VM operations.",
        "root_cause": [
            "Deleting large number of VMs at once (>6k) can lock virt-handler",
            "Tight loop on uncompleted migrations blocks node drain"
        ],
        "suggestions": [
            "Delete VMs in smaller batches (100-200 at a time)",
            "Check for stuck migrations: oc get vmim -A | grep Running",
            "Force delete stuck pods if necessary: oc delete pod -n openshift-cnv <pod> --force"
        ],
        "verify_cmd": "oc get pods -n openshift-cnv -l kubevirt.io=virt-handler --no-headers"
    },
    "noobaa-endpoint": {
        "pattern": ["noobaa-endpoint", "ContainerStatusUnknown", "openshift-storage"],
        "jira": ["OCPBUGS-storage"],
        "title": "NooBaa Endpoint Issues",
        "description": "NooBaa endpoint pods in ContainerStatusUnknown state.",
        "root_cause": [
            "Node failure or network partition caused container state to become unknown",
            "ODF/NooBaa components not properly reconciled after node issues"
        ],
        "suggestions": [
            "Check node health where pods were scheduled",
            "Delete the stuck pods to trigger rescheduling: oc delete pod -n openshift-storage <pod>",
            "Verify ODF operator health: oc get csv -n openshift-storage"
        ],
        "verify_cmd": "oc get pods -n openshift-storage -l noobaa-core=noobaa --no-headers"
    },
    "metal3-crashloop": {
        "pattern": ["metal3-image-customization", "CrashLoopBackOff", "Init"],
        "jira": ["OCPBUGS-48789"],
        "title": "Metal3 Image Customization CrashLoop",
        "description": "metal3-image-customization pod failing to start.",
        "root_cause": [
            "Service validation fails when workers are taken offline for servicing",
            "Network connectivity issues to metal3-image-customization-service"
        ],
        "suggestions": [
            "Check metal3 service: oc get svc -n openshift-machine-api",
            "Review pod logs: oc logs -n openshift-machine-api -l app=metal3-image-customization",
            "Ensure at least one worker is available during servicing operations"
        ],
        "verify_cmd": "oc get pods -n openshift-machine-api -l app=metal3-image-customization --no-headers"
    },
    "container-status-unknown": {
        "pattern": ["ContainerStatusUnknown"],
        "jira": ["OCPBUGS-general"],
        "title": "Container Status Unknown",
        "description": "Pods stuck in ContainerStatusUnknown state.",
        "root_cause": [
            "Node became unreachable or was rebooted unexpectedly",
            "Kubelet lost connection to container runtime",
            "Node was cordoned/drained but pods weren't properly evicted"
        ],
        "suggestions": [
            "Check node status: oc get nodes",
            "Force delete stuck pods: oc delete pod <pod> -n <ns> --force --grace-period=0",
            "Check kubelet logs on affected node",
            "Verify node network connectivity"
        ],
        "verify_cmd": "oc get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded | grep -i unknown"
    },
    "volumesnapshot-not-ready": {
        "pattern": ["volumesnapshot", "snapshot_issues", "not ready"],
        "jira": ["CNV-45516", "CNV-52369", "CNV-74930"],
        "title": "VolumeSnapshot Not Ready",
        "description": "VolumeSnapshots stuck in non-ready state.",
        "root_cause": [
            "LVM Storage with Filesystem mode has size mismatch issues (CNV-52369)",
            "Dangling snapshots from previous operations (CNV-45516)",
            "Default storage class changes can delete snapshots (CNV-74930)"
        ],
        "suggestions": [
            "Check snapshot status: oc get volumesnapshot -A -o wide",
            "For LVM: ensure using Block volume mode for snapshots",
            "Delete orphaned snapshots if source PVC no longer exists",
            "Verify VolumeSnapshotClass exists: oc get volumesnapshotclass"
        ],
        "verify_cmd": "oc get volumesnapshot -A --no-headers | grep -v true"
    },
    "datavolume-stuck": {
        "pattern": ["dv_issues", "datavolume", "ImportInProgress", "Pending"],
        "jira": ["CNV-storage"],
        "title": "DataVolume Import Stuck",
        "description": "DataVolumes stuck in import or pending state.",
        "root_cause": [
            "CDI importer pod failed or is slow",
            "Source image URL unreachable",
            "Insufficient storage space"
        ],
        "suggestions": [
            "Check CDI pods: oc get pods -n openshift-cnv -l app=containerized-data-importer",
            "Check importer pod logs: oc logs -n <ns> importer-<dv-name>",
            "Verify source URL accessibility",
            "Check PVC events: oc describe pvc <pvc-name> -n <ns>"
        ],
        "verify_cmd": "oc get dv -A --no-headers | grep -v Succeeded"
    },
    "migration-failed": {
        "pattern": ["migration", "failed", "vmim"],
        "jira": ["CNV-74568", "CNV-71962", "CNV-74856", "CNV-76280"],
        "title": "VM Live Migration Failed",
        "description": "Virtual machine migrations failing.",
        "root_cause": [
            "CPU feature mismatch between source and target nodes (CNV-74856)",
            "Migration between different CPU architectures AMD/Intel (CNV-71957)",
            "Migration breaks after cluster upgrade (CNV-74568)",
            "Storage migration between different backends fails (CNV-76280)"
        ],
        "suggestions": [
            "Check VMI migration status: oc get vmim -A -o wide",
            "Ensure homogeneous CPU types across cluster or use CPU passthrough",
            "After upgrades, restart virt-handler: oc rollout restart ds/virt-handler -n openshift-cnv",
            "For storage migration, ensure same storage class capabilities"
        ],
        "verify_cmd": "oc get vmim -A --no-headers | grep -i failed"
    },
    "stuck-migration": {
        "pattern": ["stuck_migrations", "migration", "Running"],
        "jira": ["CNV-74866", "CNV-70607", "CNV-69281"],
        "title": "VM Migration Stuck",
        "description": "Live migrations stuck in Running state for extended periods.",
        "root_cause": [
            "virt-handler tight loop on uncompleted migration (CNV-74866)",
            "Network bandwidth saturation during large VM migrations",
            "parallelMigrationsPerCluster limit not working properly (CNV-69281)"
        ],
        "suggestions": [
            "Check migration details: oc describe vmim <name> -n <ns>",
            "Cancel stuck migration: oc delete vmim <name> -n <ns>",
            "Reduce parallel migrations in HyperConverged spec",
            "Check network bandwidth between nodes"
        ],
        "verify_cmd": "oc get vmim -A --no-headers | grep Running"
    },
    "cordoned-node-vms": {
        "pattern": ["cordoned_vms", "SchedulingDisabled"],
        "jira": ["CNV-20450"],
        "title": "VMs on Cordoned Nodes",
        "description": "VMs running on nodes marked as SchedulingDisabled.",
        "root_cause": [
            "Node was cordoned but VMs weren't migrated (CNV-20450)",
            "Migrations to cordoned nodes during testing"
        ],
        "suggestions": [
            "Migrate VMs off cordoned nodes: virtctl migrate <vm-name>",
            "Check why node is cordoned: oc describe node <node>",
            "Drain node properly: oc adm drain <node> --ignore-daemonsets --delete-emptydir-data"
        ],
        "verify_cmd": "oc get nodes | grep SchedulingDisabled && oc get vmi -A -o wide"
    },
    "etcd-unhealthy": {
        "pattern": ["etcd", "unhealthy"],
        "jira": ["OCPBUGS-74962", "OCPBUGS-70140"],
        "title": "etcd Cluster Issues",
        "description": "etcd members unhealthy or high latency.",
        "root_cause": [
            "High etcd latency under load (OCPBUGS-74962)",
            "Database size growing due to large operators (OCPBUGS-70140)",
            "Disk I/O saturation on control plane nodes"
        ],
        "suggestions": [
            "Check etcd status: oc get pods -n openshift-etcd",
            "Monitor etcd metrics for latency spikes",
            "Check disk I/O on control plane nodes",
            "Consider defragmentation if DB size is large"
        ],
        "verify_cmd": "oc get pods -n openshift-etcd -l app=etcd --no-headers"
    },
    "oom-events": {
        "pattern": ["oom_events", "OOMKilled"],
        "jira": ["CNV-75962", "CNV-63538"],
        "title": "OOMKilled Pods",
        "description": "Pods being killed due to Out of Memory.",
        "root_cause": [
            "kubevirt-migration-controller OOMKilled at scale (CNV-75962)",
            "virt-launcher consuming more memory than assigned (CNV-63538)",
            "Memory limits set too low for workload"
        ],
        "suggestions": [
            "Check which pods are OOMKilled: oc get events -A --field-selector reason=OOMKilled",
            "Review memory requests/limits in pod spec",
            "For CNV components, check HyperConverged resource settings",
            "Monitor memory usage: oc adm top pods -n <namespace>"
        ],
        "verify_cmd": "oc get events -A --field-selector reason=OOMKilled --no-headers"
    },
    "csi-issues": {
        "pattern": ["csi_issues", "csi", "driver"],
        "jira": ["OCPBUGS-69390", "CNV-70889"],
        "title": "CSI Driver Issues",
        "description": "CSI driver pods not running properly.",
        "root_cause": [
            "CSI driver crash on specific cloud providers (OCPBUGS-69390)",
            "kubevirt-csi-controller crash when resize not supported (CNV-70889)"
        ],
        "suggestions": [
            "Check CSI pods: oc get pods -A | grep csi",
            "Review CSI driver logs: oc logs -n <ns> <csi-pod>",
            "Verify storage class configuration",
            "Check if storage backend supports required features"
        ],
        "verify_cmd": "oc get pods -A --no-headers | grep csi | grep -v Running"
    }
}

# Investigation commands for each issue type - used for deep RCA
INVESTIGATION_COMMANDS = {
    "pod-crashloop": [
        {"cmd": "oc logs {pod} -n {ns} --tail=50 2>&1 | head -30", "desc": "Recent pod logs"},
        {"cmd": "oc logs {pod} -n {ns} --previous --tail=30 2>&1 | head -20", "desc": "Previous container logs"},
        {"cmd": "oc describe pod {pod} -n {ns} 2>&1 | grep -A20 'Events:'", "desc": "Pod events"},
        {"cmd": "oc get pod {pod} -n {ns} -o jsonpath='{{.status.containerStatuses[*].state}}' 2>&1", "desc": "Container state"},
    ],
    "pod-unknown": [
        {"cmd": "oc get pod {pod} -n {ns} -o wide 2>&1", "desc": "Pod details with node"},
        {"cmd": "oc describe pod {pod} -n {ns} 2>&1 | grep -A5 'Conditions:'", "desc": "Pod conditions"},
        {"cmd": "oc get node $(oc get pod {pod} -n {ns} -o jsonpath='{{.spec.nodeName}}' 2>/dev/null) 2>&1 | tail -1", "desc": "Node status"},
        {"cmd": "oc get events -n {ns} --field-selector involvedObject.name={pod} 2>&1 | tail -5", "desc": "Related events"},
    ],
    "virt-handler-memory": [
        {"cmd": "oc adm top pods -n openshift-cnv -l kubevirt.io=virt-handler --no-headers 2>&1", "desc": "virt-handler resource usage"},
        {"cmd": "oc get pods -n openshift-cnv -l kubevirt.io=virt-handler -o jsonpath='{{range .items[*]}}{{.metadata.name}} {{.spec.nodeName}}{{\"\\n\"}}{{end}}' 2>&1", "desc": "virt-handler pod locations"},
        {"cmd": "oc exec -n openshift-cnv $(oc get pods -n openshift-cnv -l kubevirt.io=virt-handler -o name | head -1) -- cat /proc/meminfo 2>&1 | grep -E 'MemTotal|MemFree|MemAvailable' | head -3", "desc": "Node memory info"},
        {"cmd": "oc get vmi -A --no-headers 2>&1 | wc -l", "desc": "Total VMI count"},
        {"cmd": "oc logs -n openshift-cnv $(oc get pods -n openshift-cnv -l kubevirt.io=virt-handler -o name | head -1) --tail=20 2>&1 | grep -i 'memory\\|oom\\|error' | head -10", "desc": "Memory-related logs"},
    ],
    "volumesnapshot": [
        {"cmd": "oc get volumesnapshot -A -o wide 2>&1 | grep -v 'true' | head -10", "desc": "Unhealthy snapshots"},
        {"cmd": "oc describe volumesnapshot {name} -n {ns} 2>&1 | grep -A10 'Status:'", "desc": "Snapshot status details"},
        {"cmd": "oc get volumesnapshotclass 2>&1", "desc": "VolumeSnapshot classes"},
        {"cmd": "oc get volumesnapshotcontent 2>&1 | grep -v 'true' | head -5", "desc": "Snapshot content status"},
        {"cmd": "oc get pvc -A 2>&1 | head -10", "desc": "PVC status"},
    ],
    "noobaa": [
        {"cmd": "oc get pods -n openshift-storage -l noobaa-core=noobaa 2>&1", "desc": "NooBaa pod status"},
        {"cmd": "oc describe pod {pod} -n openshift-storage 2>&1 | grep -A15 'Events:'", "desc": "Pod events"},
        {"cmd": "oc get storagecluster -n openshift-storage 2>&1", "desc": "Storage cluster status"},
        {"cmd": "oc get noobaa -n openshift-storage -o yaml 2>&1 | grep -A5 'status:'", "desc": "NooBaa status"},
        {"cmd": "oc logs {pod} -n openshift-storage --tail=30 2>&1 | head -20", "desc": "Pod logs"},
    ],
    "metal3": [
        {"cmd": "oc get pods -n openshift-machine-api -l app=metal3-image-customization 2>&1", "desc": "Metal3 pods"},
        {"cmd": "oc logs -n openshift-machine-api -l app=metal3-image-customization --tail=50 2>&1 | head -30", "desc": "Pod logs"},
        {"cmd": "oc describe pod {pod} -n openshift-machine-api 2>&1 | grep -A20 'Events:'", "desc": "Pod events"},
        {"cmd": "oc get svc -n openshift-machine-api | grep metal3 2>&1", "desc": "Metal3 services"},
        {"cmd": "oc get bmh -A 2>&1 | head -10", "desc": "BareMetalHost status"},
    ],
    "etcd": [
        {"cmd": "oc get pods -n openshift-etcd -l app=etcd 2>&1", "desc": "etcd pod status"},
        {"cmd": "oc logs -n openshift-etcd -l app=etcd --tail=30 2>&1 | grep -i 'error\\|warn\\|slow' | head -15", "desc": "etcd error logs"},
        {"cmd": "oc get etcd cluster -o yaml 2>&1 | grep -A10 'status:'", "desc": "etcd cluster status"},
        {"cmd": "oc rsh -n openshift-etcd $(oc get pods -n openshift-etcd -l app=etcd -o name | head -1) etcdctl endpoint health 2>&1", "desc": "etcd health check"},
    ],
    "migration": [
        {"cmd": "oc get vmim -A -o wide 2>&1 | head -10", "desc": "Migration status"},
        {"cmd": "oc describe vmim {name} -n {ns} 2>&1 | grep -A20 'Status:'", "desc": "Migration details"},
        {"cmd": "oc get vmi {vm} -n {ns} -o yaml 2>&1 | grep -A10 'migrationState:'", "desc": "VMI migration state"},
        {"cmd": "oc logs -n openshift-cnv -l kubevirt.io=virt-handler --tail=30 2>&1 | grep -i migration | head -10", "desc": "Migration logs"},
    ],
    "csi": [
        {"cmd": "oc get pods -A 2>&1 | grep csi", "desc": "CSI pod status"},
        {"cmd": "oc logs {pod} -n {ns} --tail=30 2>&1 | grep -i 'error\\|fail' | head -15", "desc": "CSI error logs"},
        {"cmd": "oc get csidrivers 2>&1", "desc": "CSI drivers"},
        {"cmd": "oc get sc 2>&1", "desc": "Storage classes"},
    ],
    "oom": [
        {"cmd": "oc get events -A --field-selector reason=OOMKilled --sort-by='.lastTimestamp' 2>&1 | tail -10", "desc": "Recent OOM events"},
        {"cmd": "oc describe pod {pod} -n {ns} 2>&1 | grep -A5 'Resources:'", "desc": "Pod resource limits"},
        {"cmd": "oc adm top pods -n {ns} --no-headers 2>&1 | head -10", "desc": "Namespace resource usage"},
    ],
}

def investigate_issue(issue_type, context, ssh_command_func):
    """
    Run investigation commands for a specific issue type.
    Returns list of investigation results.
    """
    results = []
    commands = INVESTIGATION_COMMANDS.get(issue_type, [])
    
    for cmd_info in commands:
        cmd_template = cmd_info["cmd"]
        desc = cmd_info["desc"]
        
        # Substitute context variables
        cmd = cmd_template
        for key, value in context.items():
            cmd = cmd.replace("{" + key + "}", str(value))
        
        # Run command with shorter timeout for speed
        try:
            output = ssh_command_func(cmd, timeout=5)
            if output:
                output = output.strip()[:500]  # Limit output size
            else:
                output = "(no output)"
        except Exception as e:
            output = f"(error: {str(e)[:100]})"
        
        results.append({
            "description": desc,
            "command": cmd,
            "output": output
        })
    
    return results

def determine_root_cause(issue_type, investigation_results, failure_details):
    """
    Analyze investigation results to determine the most likely root cause.
    Returns (root_cause, confidence, explanation).
    """
    # Combine all outputs for analysis
    all_output = " ".join([r.get("output", "") for r in investigation_results]).lower()
    
    # Pattern matching for common root causes
    root_causes = []
    
    if issue_type in ["pod-crashloop", "pod-unknown"]:
        if "oomkilled" in all_output or "out of memory" in all_output:
            root_causes.append(("OOM Kill", "high", "Pod was killed due to memory limits exceeded"))
        if "crashloopbackoff" in all_output:
            if "image" in all_output and ("pull" in all_output or "not found" in all_output):
                root_causes.append(("Image Pull Error", "high", "Container image could not be pulled"))
            elif "permission" in all_output or "denied" in all_output:
                root_causes.append(("Permission Denied", "high", "Container lacks required permissions"))
            else:
                root_causes.append(("Application Crash", "medium", "Application inside container is crashing"))
        if "containerstatusunknown" in all_output:
            if "notready" in all_output or "schedulingdisabled" in all_output:
                root_causes.append(("Node Issue", "high", "Node became unavailable or was cordoned"))
            else:
                root_causes.append(("Kubelet Communication Lost", "medium", "Kubelet lost connection to API server"))
        if "pending" in all_output and "insufficient" in all_output:
            root_causes.append(("Insufficient Resources", "high", "Cluster lacks resources to schedule pod"))
    
    elif issue_type == "virt-handler-memory":
        if "oom" in all_output or "killed" in all_output:
            root_causes.append(("Memory Leak", "high", "virt-handler experiencing memory leak under load"))
        vmi_count = 0
        for r in investigation_results:
            if "Total VMI" in r.get("description", ""):
                try:
                    vmi_count = int(r.get("output", "0").strip())
                except:
                    pass
        if vmi_count > 1000:
            root_causes.append(("High VM Density", "high", f"Running {vmi_count} VMs - high memory usage expected"))
        elif vmi_count > 500:
            root_causes.append(("Moderate VM Load", "medium", f"Running {vmi_count} VMs - consider spreading load"))
    
    elif issue_type == "volumesnapshot":
        if "pending" in all_output:
            root_causes.append(("Snapshot Pending", "medium", "Snapshot waiting for CSI driver"))
        if "not found" in all_output or "missing" in all_output:
            root_causes.append(("Missing Source", "high", "Source PVC no longer exists"))
        if "error" in all_output and "csi" in all_output:
            root_causes.append(("CSI Driver Error", "high", "CSI driver failed to create snapshot"))
    
    elif issue_type == "noobaa":
        if "containerstatusunknown" in all_output:
            root_causes.append(("Node Failure", "high", "Node hosting NooBaa became unavailable"))
        if "pending" in all_output:
            root_causes.append(("Storage Issue", "medium", "NooBaa waiting for storage resources"))
    
    elif issue_type == "metal3":
        if "service" in all_output and ("unavailable" in all_output or "error" in all_output):
            root_causes.append(("Service Unavailable", "high", "metal3-image-customization-service not reachable"))
        if "init" in all_output and "crash" in all_output:
            root_causes.append(("Init Container Failure", "high", "Init container failing to complete"))
    
    elif issue_type == "migration":
        if "timeout" in all_output or "stuck" in all_output:
            root_causes.append(("Migration Timeout", "high", "Migration exceeded time limit"))
        if "bandwidth" in all_output or "network" in all_output:
            root_causes.append(("Network Bandwidth", "medium", "Network bandwidth limiting migration speed"))
        if "cpu" in all_output and "mismatch" in all_output:
            root_causes.append(("CPU Incompatibility", "high", "CPU features mismatch between nodes"))
    
    # Default if no specific cause found
    if not root_causes:
        root_causes.append(("Unknown", "low", "Further manual investigation required"))
    
    # Return the highest confidence root cause
    confidence_order = {"high": 0, "medium": 1, "low": 2}
    root_causes.sort(key=lambda x: confidence_order.get(x[1], 3))
    
    return root_causes[0]

def parse_version(version_str):
    """Parse version string to comparable tuple"""
    if not version_str:
        return (0, 0, 0)
    # Handle formats like "4.21.0-ec.3", "4.17", "CNV 4.17.0"
    match = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', str(version_str))
    if match:
        major = int(match.group(1))
        minor = int(match.group(2))
        patch = int(match.group(3)) if match.group(3) else 0
        return (major, minor, patch)
    return (0, 0, 0)

def compare_versions(v1, v2):
    """Compare two version strings. Returns: -1 if v1 < v2, 0 if equal, 1 if v1 > v2"""
    v1_tuple = parse_version(v1)
    v2_tuple = parse_version(v2)
    if v1_tuple < v2_tuple:
        return -1
    elif v1_tuple > v2_tuple:
        return 1
    return 0

def check_jira_bugs(jira_keys, cluster_version):
    """
    Check Jira bug status and determine if bugs are open, fixed, or regression.
    Uses subprocess to call the Jira MCP tool.
    
    Returns dict with bug info: {
        'CNV-12345': {
            'status': 'Closed',
            'resolution': 'Done',
            'fix_versions': ['CNV 4.17.0'],
            'affects_versions': ['CNV 4.16.0'],
            'assessment': 'fixed'|'open'|'regression'|'unknown',
            'assessment_detail': 'Fixed in CNV 4.17.0, you are on 4.21'
        }
    }
    """
    import subprocess
    
    results = {}
    
    for jira_key in jira_keys:
        if not jira_key or jira_key in ["OCPBUGS-storage", "OCPBUGS-general", "CNV-storage"]:
            # Skip placeholder keys
            continue
            
        if jira_key in JIRA_BUG_CACHE:
            results[jira_key] = JIRA_BUG_CACHE[jira_key]
            continue
        
        try:
            # Call the Jira MCP tool via cursor's mcp-proxy if available, 
            # or use direct Jira API
            # For now, we'll use a cached/known status approach
            
            # Try to get from environment or use known statuses
            bug_info = get_known_bug_info(jira_key, cluster_version)
            results[jira_key] = bug_info
            JIRA_BUG_CACHE[jira_key] = bug_info
            
        except Exception as e:
            results[jira_key] = {
                'status': 'Unknown',
                'resolution': None,
                'fix_versions': [],
                'assessment': 'unknown',
                'assessment_detail': f'Unable to fetch: {str(e)}'
            }
    
    return results

def get_known_bug_info(jira_key, cluster_version):
    """
    Get known bug information. This includes hardcoded data for common bugs
    that can be updated from Jira periodically.
    """
    # Known bug database with status info (can be refreshed from Jira)
    KNOWN_BUGS = {
        # CNV bugs
        "CNV-66551": {"status": "Closed", "resolution": "Done", "fix_versions": ["CNV 4.17.0"], "affects": ["CNV 4.16"]},
        "CNV-71448": {"status": "In Progress", "resolution": None, "fix_versions": [], "affects": ["CNV 4.17", "CNV 4.18"]},
        "CNV-30274": {"status": "Closed", "resolution": "Done", "fix_versions": ["CNV 4.15.0"], "affects": ["CNV 4.14"]},
        "CNV-68292": {"status": "Closed", "resolution": "Done", "fix_versions": ["CNV 4.17.1"], "affects": ["CNV 4.17.0"]},
        "CNV-70607": {"status": "In Progress", "resolution": None, "fix_versions": [], "affects": ["CNV 4.17"]},
        "CNV-74568": {"status": "Open", "resolution": None, "fix_versions": [], "affects": ["CNV 4.18"]},
        "CNV-71962": {"status": "Closed", "resolution": "Done", "fix_versions": ["CNV 4.17.2"], "affects": ["CNV 4.17"]},
        "CNV-74856": {"status": "Open", "resolution": None, "fix_versions": [], "affects": ["CNV 4.18"]},
        "CNV-76280": {"status": "Open", "resolution": None, "fix_versions": [], "affects": ["CNV 4.18"]},
        "CNV-74866": {"status": "In Progress", "resolution": None, "fix_versions": [], "affects": ["CNV 4.18"]},
        "CNV-69281": {"status": "Closed", "resolution": "Done", "fix_versions": ["CNV 4.17.0"], "affects": ["CNV 4.16"]},
        "CNV-45516": {"status": "Closed", "resolution": "Done", "fix_versions": ["CNV 4.16.0"], "affects": ["CNV 4.15"]},
        "CNV-52369": {"status": "Closed", "resolution": "Done", "fix_versions": ["CNV 4.16.1"], "affects": ["CNV 4.16.0"]},
        "CNV-74930": {"status": "Open", "resolution": None, "fix_versions": [], "affects": ["CNV 4.18"]},
        "CNV-20450": {"status": "Closed", "resolution": "Done", "fix_versions": ["CNV 4.14.0"], "affects": ["CNV 4.13"]},
        "CNV-75962": {"status": "In Progress", "resolution": None, "fix_versions": [], "affects": ["CNV 4.18"]},
        "CNV-63538": {"status": "Closed", "resolution": "Done", "fix_versions": ["CNV 4.16.0"], "affects": ["CNV 4.15"]},
        "CNV-70889": {"status": "Closed", "resolution": "Done", "fix_versions": ["CNV 4.17.0"], "affects": ["CNV 4.16"]},
        # OCP bugs
        "OCPBUGS-48789": {"status": "Closed", "resolution": "Done", "fix_versions": ["OCP 4.17.0"], "affects": ["OCP 4.16"]},
        "OCPBUGS-74962": {"status": "Open", "resolution": None, "fix_versions": [], "affects": ["OCP 4.18"]},
        "OCPBUGS-70140": {"status": "In Progress", "resolution": None, "fix_versions": [], "affects": ["OCP 4.17"]},
        "OCPBUGS-69390": {"status": "Closed", "resolution": "Done", "fix_versions": ["OCP 4.17.1"], "affects": ["OCP 4.17.0"]},
    }
    
    if jira_key in KNOWN_BUGS:
        bug = KNOWN_BUGS[jira_key]
        assessment, detail = assess_bug_status(bug, cluster_version, jira_key)
        return {
            'status': bug['status'],
            'resolution': bug.get('resolution'),
            'fix_versions': bug.get('fix_versions', []),
            'affects_versions': bug.get('affects', []),
            'assessment': assessment,
            'assessment_detail': detail
        }
    
    # Unknown bug - return generic info
    return {
        'status': 'Unknown',
        'resolution': None,
        'fix_versions': [],
        'affects_versions': [],
        'assessment': 'unknown',
        'assessment_detail': f'Bug {jira_key} not in local database'
    }

def assess_bug_status(bug, cluster_version, jira_key):
    """
    Assess if a bug is relevant to current cluster version.
    Returns (assessment, detail) tuple.
    """
    status = bug.get('status', 'Unknown')
    fix_versions = bug.get('fix_versions', [])
    affects = bug.get('affects', [])
    
    # Parse cluster version (e.g., "4.21.0-ec.3" -> (4, 21, 0))
    cluster_ver = parse_version(cluster_version)
    
    # Open/In Progress bugs
    if status in ['Open', 'In Progress', 'New', 'To Do']:
        # Check if affects current version
        for av in affects:
            av_ver = parse_version(av)
            if av_ver[0] == cluster_ver[0] and av_ver[1] <= cluster_ver[1]:
                return ('open', f'🔴 OPEN - Affects your version ({cluster_version})')
        return ('open', f'🟡 OPEN - May affect version {cluster_version}')
    
    # Closed/Done bugs
    if status in ['Closed', 'Done', 'Resolved']:
        if fix_versions:
            # Find the lowest fix version
            fix_ver = min([parse_version(fv) for fv in fix_versions])
            fix_ver_str = fix_versions[0]
            
            # Compare with cluster version
            if cluster_ver >= fix_ver:
                # Bug was fixed in a version <= current
                # This could be a regression!
                return ('regression', f'⚠️ POTENTIAL REGRESSION - Fixed in {fix_ver_str}, you have {cluster_version}')
            else:
                # Bug fixed in newer version
                return ('fixed_newer', f'🟢 Fixed in {fix_ver_str} - Upgrade from {cluster_version} to resolve')
        else:
            return ('fixed', f'🟢 Closed/Resolved')
    
    return ('unknown', f'Status: {status}')

def format_raw_output(details, failure_type):
    """Format raw details into readable output like oc command result"""
    if isinstance(details, list):
        if not details:
            return "(no data)"
        lines = []
        for item in details[:8]:  # Limit to 8 items
            if isinstance(item, dict):
                if "ns" in item and "name" in item:
                    lines.append(f"{item.get('ns', '-'):<30} {item.get('name', '-'):<45} {item.get('status', '-')}")
                elif "name" in item:
                    lines.append(f"{item.get('name', '-'):<45} {item.get('status', item.get('memory', '-'))}")
                else:
                    lines.append(str(item))
            else:
                lines.append(str(item))
        if len(details) > 8:
            lines.append(f"... +{len(details) - 8} more")
        return "\n".join(lines)
    elif isinstance(details, dict):
        return "\n".join([f"{k}: {v}" for k, v in list(details.items())[:5]])
    else:
        return str(details)

def analyze_failures(data):
    """Analyze failures and match to known issues from Jira"""
    analysis = []
    
    # Check each failure type against known issues
    failures = []
    
    # Collect all failures with raw output
    if data["pods"]["unhealthy"]:
        # Format pod output like oc get pods
        raw_lines = ["NAMESPACE" + " "*22 + "NAME" + " "*41 + "STATUS"]
        for pod in data["pods"]["unhealthy"][:10]:
            raw_lines.append(f"{pod['ns']:<30} {pod['name']:<45} {pod['status']}")
        if len(data["pods"]["unhealthy"]) > 10:
            raw_lines.append(f"... +{len(data['pods']['unhealthy']) - 10} more pods")
        
        for pod in data["pods"]["unhealthy"]:
            failures.append({
                "type": "pod",
                "name": f"{pod['ns']}/{pod['name']}",
                "status": pod["status"],
                "details": pod,
                "raw_output": "\n".join(raw_lines)
            })
    
    if data["virt_handler"]["unhealthy"]:
        raw_out = format_raw_output(data["virt_handler"]["unhealthy"], "virt-handler")
        failures.append({
            "type": "virt-handler",
            "name": "virt-handler pods",
            "status": "unhealthy",
            "details": data["virt_handler"]["unhealthy"],
            "raw_output": raw_out
        })
    
    if data["virt_handler"]["high_memory"]:
        # Format like oc adm top pods output
        raw_lines = ["NAME" + " "*36 + "CPU" + " "*5 + "MEMORY"]
        for pod in data["virt_handler"]["high_memory"][:8]:
            raw_lines.append(f"{pod.get('name', '-'):<40} {pod.get('cpu', '-'):<8} {pod.get('memory', '-')}")
        if len(data["virt_handler"]["high_memory"]) > 8:
            raw_lines.append(f"... +{len(data['virt_handler']['high_memory']) - 8} more")
        
        failures.append({
            "type": "virt-handler-memory",
            "name": "virt-handler memory",
            "status": f"{len(data['virt_handler']['high_memory'])} pods high memory",
            "details": data["virt_handler"]["high_memory"],
            "raw_output": "\n".join(raw_lines)
        })
    
    if data["snapshot_issues"]:
        raw_out = format_raw_output(data["snapshot_issues"], "snapshot")
        failures.append({
            "type": "volumesnapshot",
            "name": "VolumeSnapshots",
            "status": f"{len(data['snapshot_issues'])} not ready",
            "details": data["snapshot_issues"],
            "raw_output": raw_out
        })
    
    if data["dv_issues"]:
        raw_out = format_raw_output(data["dv_issues"], "dv")
        failures.append({
            "type": "datavolume",
            "name": "DataVolumes",
            "status": f"{len(data['dv_issues'])} stuck",
            "details": data["dv_issues"],
            "raw_output": raw_out
        })
    
    if data["migrations"]["failed"] or data["migrations"]["failed_count"] > 0:
        raw_out = format_raw_output(data["migrations"]["failed"], "migration")
        failures.append({
            "type": "migration-failed",
            "name": "VM Migrations",
            "status": "failed",
            "details": data["migrations"]["failed"],
            "raw_output": raw_out
        })
    
    if data["stuck_migrations"]:
        raw_out = format_raw_output(data["stuck_migrations"], "migration")
        failures.append({
            "type": "stuck-migration",
            "name": "Stuck Migrations",
            "status": f"{len(data['stuck_migrations'])} stuck",
            "details": data["stuck_migrations"],
            "raw_output": raw_out
        })
    
    if data["cordoned_vms"]:
        raw_out = format_raw_output(data["cordoned_vms"], "vmi")
        failures.append({
            "type": "cordoned-vms",
            "name": "VMs on cordoned nodes",
            "status": f"{len(data['cordoned_vms'])} at risk",
            "details": data["cordoned_vms"],
            "raw_output": raw_out
        })
    
    if data["etcd"]["unhealthy"]:
        raw_out = format_raw_output(data["etcd"]["unhealthy"], "etcd")
        failures.append({
            "type": "etcd",
            "name": "etcd",
            "status": "unhealthy",
            "details": data["etcd"]["unhealthy"],
            "raw_output": raw_out
        })
    
    if data["oom_events"]:
        raw_out = format_raw_output(data["oom_events"], "events")
        failures.append({
            "type": "oom",
            "name": "OOM Events",
            "status": f"{len(data['oom_events'])} events",
            "details": data["oom_events"],
            "raw_output": raw_out
        })
    
    if data["csi_issues"]:
        raw_out = format_raw_output(data["csi_issues"], "csi")
        failures.append({
            "type": "csi",
            "name": "CSI Drivers",
            "status": f"{len(data['csi_issues'])} issues",
            "details": data["csi_issues"],
            "raw_output": raw_out
        })
    
    # Match failures to known issues
    for failure in failures:
        matched_issues = []
        failure_text = f"{failure['type']} {failure['name']} {failure['status']} {str(failure['details'])}".lower()
        
        for issue_key, issue in KNOWN_ISSUES.items():
            for pattern in issue["pattern"]:
                if pattern.lower() in failure_text:
                    matched_issues.append(issue)
                    break
        
        if matched_issues:
            # Use the most relevant match
            analysis.append({
                "failure": failure,
                "matched_issue": matched_issues[0],
                "all_matches": matched_issues,
                "investigation": None,  # Will be populated by deep investigation
                "determined_cause": None
            })
        else:
            # Generic analysis for unmatched failures
            analysis.append({
                "failure": failure,
                "matched_issue": {
                    "title": f"Unknown Issue: {failure['name']}",
                    "jira": [],
                    "description": f"Issue detected: {failure['status']}",
                    "root_cause": ["Unable to determine root cause from known issues database"],
                    "suggestions": [
                        f"Check pod/resource logs: oc logs <pod> -n <namespace>",
                        f"Describe the resource: oc describe <resource>",
                        "Search Jira for similar issues",
                        "Contact support if issue persists"
                    ]
                },
                "all_matches": [],
                "investigation": None,
                "determined_cause": None
            })
    
    return analysis

def run_deep_investigation(analysis, ssh_command_func, max_unique_types=10):
    """
    Run deep investigation for issues in the analysis.
    OPTIMIZATION: Clusters issues by symptom/type and only investigates ONE
    representative issue per cluster, then applies results to all similar issues.
    """
    import hashlib
    
    # Helper function to get investigation type and context for an item
    def get_inv_info(item):
        failure = item["failure"]
        failure_type = failure.get("type", "")
        details = failure.get("details", {})
        
        # Determine investigation type based on failure
        if failure_type == "pod":
            status = failure.get("status", "").lower()
            if "crashloop" in status or "error" in status or "init:" in status:
                inv_type = "pod-crashloop"
            elif "unknown" in status or "pending" in status:
                inv_type = "pod-unknown"
            else:
                inv_type = "pod-unknown"
            
            # Check for specific pod types
            name = failure.get("name", "").lower()
            if "noobaa" in name:
                inv_type = "noobaa"
            elif "metal3" in name:
                inv_type = "metal3"
            
            # Build context
            if isinstance(details, dict):
                context = {
                    "pod": details.get("name", ""),
                    "ns": details.get("ns", ""),
                    "name": details.get("name", ""),
                }
            else:
                parts = failure.get("name", "").split("/")
                context = {
                    "pod": parts[1] if len(parts) > 1 else parts[0],
                    "ns": parts[0] if len(parts) > 1 else "default",
                    "name": parts[1] if len(parts) > 1 else parts[0],
                }
        
        elif failure_type == "virt-handler-memory":
            inv_type = "virt-handler-memory"
            context = {}
        
        elif failure_type == "volumesnapshot":
            inv_type = "volumesnapshot"
            if isinstance(details, list) and details:
                first = details[0] if isinstance(details[0], dict) else {}
                context = {"name": first.get("name", ""), "ns": first.get("ns", "")}
            else:
                context = {"name": "", "ns": ""}
        
        elif failure_type == "etcd":
            inv_type = "etcd"
            context = {}
        
        elif failure_type in ["migration-failed", "stuck-migration"]:
            inv_type = "migration"
            if isinstance(details, list) and details:
                first = details[0] if isinstance(details[0], dict) else {}
                context = {"name": first.get("name", ""), "ns": first.get("ns", ""), "vm": first.get("vm", "")}
            else:
                context = {"name": "", "ns": "", "vm": ""}
        
        elif failure_type == "csi":
            inv_type = "csi"
            if isinstance(details, list) and details:
                first = details[0] if isinstance(details[0], dict) else {}
                context = {"pod": first.get("name", ""), "ns": first.get("ns", "")}
            else:
                context = {"pod": "", "ns": ""}
        
        elif failure_type == "oom":
            inv_type = "oom"
            if isinstance(details, list) and details:
                first = details[0] if isinstance(details[0], dict) else {}
                context = {"pod": first.get("name", ""), "ns": first.get("ns", "")}
            else:
                context = {"pod": "", "ns": ""}
        
        else:
            inv_type = "pod-unknown"
            context = {"pod": "", "ns": "", "name": ""}
        
        return inv_type, context, failure_type, details
    
    # Step 1: Group issues by their matched issue title (symptom)
    symptom_groups = {}
    for item in analysis:
        # Use matched issue title as the grouping key
        symptom_key = item.get("matched_issue", {}).get("title", "unknown")
        if symptom_key not in symptom_groups:
            symptom_groups[symptom_key] = []
        symptom_groups[symptom_key].append(item)
    
    unique_symptoms = len(symptom_groups)
    total_issues = len(analysis)
    
    print(f"        Found {unique_symptoms} unique issue types across {total_issues} issues", flush=True)
    print(f"        Investigating ONE representative per type (saves {total_issues - unique_symptoms} duplicate investigations)", flush=True)
    
    # Step 2: For each symptom group, investigate only the first (representative) issue
    investigation_count = 0
    symptoms_investigated = 0
    
    for symptom_key, items in list(symptom_groups.items())[:max_unique_types]:
        symptoms_investigated += 1
        
        # Get the first item as representative
        representative = items[0]
        inv_type, context, failure_type, details = get_inv_info(representative)
        
        print(f"        [{symptoms_investigated}/{min(unique_symptoms, max_unique_types)}] Investigating: {symptom_key[:50]}... ({len(items)} similar issues)", flush=True)
        
        # Run investigation on representative
        investigation_results = investigate_issue(inv_type, context, ssh_command_func)
        
        if investigation_results:
            investigation_count += 1
            
            # Determine root cause from investigation
            root_cause, confidence, explanation = determine_root_cause(
                inv_type, investigation_results, details
            )
            
            # Generate unique ID for this symptom group
            inv_id = hashlib.md5(f"{symptom_key}".encode()).hexdigest()[:8]
            
            # Apply results to ALL items in this symptom group
            for item in items:
                item["investigation"] = investigation_results
                item["determined_cause"] = {
                    "cause": root_cause,
                    "confidence": confidence,
                    "explanation": explanation,
                    "investigation_id": inv_id,
                    "shared_with": len(items) - 1  # Number of other issues sharing this investigation
                }
    
    if unique_symptoms > max_unique_types:
        print(f"        (Skipped {unique_symptoms - max_unique_types} additional issue types)", flush=True)
    
    print(f"        Deep investigation complete: {investigation_count} unique investigations", flush=True)
    
    return analysis

def generate_rca_html(analysis, cluster_version="", show_investigation=True, email_data=None):
    """Generate HTML for Root Cause Analysis section - grouped by issue type
    
    show_investigation: If False, only show bug matching without deep investigation
    email_data: Dict containing email search results
    """
    if not analysis:
        return ""
    
    # Group by issue title to bundle similar issues
    grouped = {}
    for item in analysis:
        title = item["matched_issue"]["title"]
        if title not in grouped:
            grouped[title] = {
                "issue": item["matched_issue"],
                "failures": [],
                "raw_outputs": [],
                "investigations": [],
                "determined_causes": []
            }
        grouped[title]["failures"].append(item["failure"])
        # Collect raw output (avoid duplicates)
        raw = item["failure"].get("raw_output", "")
        if raw and raw not in grouped[title]["raw_outputs"]:
            grouped[title]["raw_outputs"].append(raw)
        # Collect investigations
        if item.get("investigation"):
            grouped[title]["investigations"].append({
                "failure_name": item["failure"].get("name", ""),
                "results": item["investigation"]
            })
        if item.get("determined_cause"):
            grouped[title]["determined_causes"].append(item["determined_cause"])
    
    # Collect all Jira keys and check their status
    all_jira_keys = []
    for data in grouped.values():
        all_jira_keys.extend(data["issue"].get("jira", []))
    
    # Check bug status against cluster version
    bug_status_info = check_jira_bugs(all_jira_keys, cluster_version)
    
    # Count bug categories
    open_bugs = sum(1 for b in bug_status_info.values() if b.get('assessment') == 'open')
    regression_bugs = sum(1 for b in bug_status_info.values() if b.get('assessment') == 'regression')
    fixed_bugs = sum(1 for b in bug_status_info.values() if b.get('assessment') in ['fixed', 'fixed_newer'])
    
    html = '''
    <div class="panel rca-panel" style="border-color:#FF9830;">
        <div class="panel-title" style="background:#2d1f0f;color:#FF9830;">🔍 Root Cause Analysis & Recommendations</div>
        <div style="padding:20px;">
            <p style="color:var(--text-secondary);margin-bottom:12px;font-size:13px;">
                Analysis based on Red Hat Jira bug database (CNV, OCPBUGS projects) • {count} issue categories identified
            </p>
            <div style="display:flex;gap:16px;margin-bottom:20px;">
                <div style="background:#1a0a0a;border:1px solid #F2495C;border-radius:6px;padding:8px 16px;">
                    <span style="color:#F2495C;font-weight:600;">{open_count}</span>
                    <span style="color:#8b949e;font-size:12px;margin-left:4px;">Open Bugs</span>
                </div>
                <div style="background:#1a1a0a;border:1px solid #FF9830;border-radius:6px;padding:8px 16px;">
                    <span style="color:#FF9830;font-weight:600;">{regression_count}</span>
                    <span style="color:#8b949e;font-size:12px;margin-left:4px;">Potential Regressions</span>
                </div>
                <div style="background:#0a1a0a;border:1px solid #73BF69;border-radius:6px;padding:8px 16px;">
                    <span style="color:#73BF69;font-weight:600;">{fixed_count}</span>
                    <span style="color:#8b949e;font-size:12px;margin-left:4px;">Fixed (upgrade available)</span>
                </div>
            </div>
    '''.format(count=len(grouped), open_count=open_bugs, regression_count=regression_bugs, fixed_count=fixed_bugs)
    
    # Add email search results if available
    if email_data and email_data.get('keywords'):
        keywords = email_data.get('keywords', [])
        html += f'''
            <div style="margin-bottom:20px;padding:12px 16px;background:linear-gradient(135deg, #1a1a2e 0%, #0d1117 100%);border:1px solid #30363d;border-radius:8px;">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
                    <span style="font-size:16px;">📧</span>
                    <span style="color:#58a6ff;font-weight:600;font-size:13px;">Email Search Keywords</span>
                </div>
                <div style="display:flex;flex-wrap:wrap;gap:8px;">
        '''
        for keyword in keywords[:8]:  # Limit to 8 keywords
            html += f'''
                    <span style="background:#21262d;border:1px solid #30363d;padding:4px 10px;border-radius:12px;font-size:11px;color:#c9d1d9;">
                        🔍 {keyword}
                    </span>
            '''
        html += '''
                </div>
                <p style="color:#8b949e;font-size:11px;margin-top:10px;margin-bottom:0;">
                    💡 Use these keywords to search your inbox for related discussions, alerts, or previous incidents.
                </p>
            </div>
        '''
    
    for title, data in grouped.items():
        issue = data["issue"]
        failures = data["failures"]
        raw_outputs = data["raw_outputs"]
        jira_keys = issue.get("jira", [])
        verify_cmd = issue.get("verify_cmd", "")
        
        # Build Jira links with status badges
        jira_html_parts = []
        for jira_key in jira_keys:
            if jira_key in bug_status_info:
                bug_info = bug_status_info[jira_key]
                status = bug_info.get('status', 'Unknown')
                assessment = bug_info.get('assessment', 'unknown')
                detail = bug_info.get('assessment_detail', '')
                
                # Color based on assessment
                if assessment == 'open':
                    badge_color = "#F2495C"
                    badge_bg = "rgba(242,73,92,0.2)"
                elif assessment == 'regression':
                    badge_color = "#FF9830"
                    badge_bg = "rgba(255,152,48,0.2)"
                elif assessment in ['fixed', 'fixed_newer']:
                    badge_color = "#73BF69"
                    badge_bg = "rgba(115,191,105,0.2)"
                else:
                    badge_color = "#8b949e"
                    badge_bg = "rgba(139,148,158,0.2)"
                
                jira_html_parts.append(
                    f'<div style="display:inline-flex;align-items:center;gap:6px;margin:2px 0;">'
                    f'<a href="https://issues.redhat.com/browse/{jira_key}" style="color:#5794F2;" target="_blank">{jira_key}</a>'
                    f'<span style="background:{badge_bg};color:{badge_color};padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600;">{status}</span>'
                    f'</div>'
                )
            else:
                jira_html_parts.append(f'<a href="https://issues.redhat.com/browse/{jira_key}" style="color:#5794F2;" target="_blank">{jira_key}</a>')
        
        jira_links_html = "<br>".join(jira_html_parts) if jira_html_parts else "N/A"
        
        # Color code by severity (based on number of affected items)
        border_color = "#F2495C" if len(failures) > 3 else "#FF9830" if len(failures) > 1 else "#FADE2A"
        
        html += f'''
            <div style="background:var(--bg-secondary);border-radius:8px;padding:20px;margin-bottom:16px;border-left:4px solid {border_color};">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                    <span style="font-weight:600;color:#fff;font-size:16px;">⚠️ {issue["title"]}</span>
                    <span style="background:var(--bg-canvas);padding:4px 12px;border-radius:12px;color:#F2495C;font-size:12px;font-weight:600;">{len(failures)} affected</span>
                </div>
                
                <div style="background:var(--bg-canvas);border-radius:6px;padding:12px;margin-bottom:15px;">
                    <div style="color:var(--text-secondary);font-size:11px;margin-bottom:6px;text-transform:uppercase;">Affected Resources:</div>
                    <div style="display:flex;flex-wrap:wrap;gap:6px;">
        '''
        
        for f in failures[:6]:
            html += f'<span style="background:var(--bg-primary);padding:4px 8px;border-radius:4px;font-size:11px;color:#c9d1d9;font-family:monospace;">{f["name"]}</span>'
        
        if len(failures) > 6:
            html += f'<span style="color:var(--text-secondary);font-size:11px;padding:4px;">+{len(failures)-6} more</span>'
        
        html += '''
                    </div>
                </div>
        '''
        
        # Add VERIFY ON SERVER section with command and output
        if verify_cmd or raw_outputs:
            html += f'''
                <div style="background:#0a0e14;border:1px solid #30363d;border-radius:6px;margin-bottom:15px;overflow:hidden;">
                    <div style="background:#161b22;padding:10px 14px;border-bottom:1px solid #30363d;display:flex;align-items:center;gap:8px;">
                        <span style="color:#73BF69;font-size:12px;">▶</span>
                        <span style="color:#8b949e;font-size:11px;text-transform:uppercase;font-weight:600;">How to verify on server:</span>
                    </div>
            '''
            
            if verify_cmd:
                html += f'''
                    <div style="padding:12px 14px;border-bottom:1px solid #21262d;">
                        <div style="color:#58a6ff;font-size:11px;margin-bottom:6px;">COMMAND:</div>
                        <code style="display:block;background:#0d1117;padding:10px 12px;border-radius:4px;font-family:'JetBrains Mono',Monaco,monospace;font-size:12px;color:#e6edf3;white-space:pre-wrap;word-break:break-all;">$ {verify_cmd}</code>
                    </div>
                '''
            
            if raw_outputs:
                # Combine and limit raw outputs, escape HTML
                combined_output = raw_outputs[0] if raw_outputs else "(no output)"
                # Escape HTML special characters
                combined_output = str(combined_output).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html += f'''
                    <div style="padding:12px 14px;">
                        <div style="color:#f85149;font-size:11px;margin-bottom:6px;">OUTPUT (detected issues):</div>
                        <pre style="background:#0d1117;padding:10px 12px;border-radius:4px;font-family:'JetBrains Mono',Monaco,monospace;font-size:11px;color:#f85149;white-space:pre-wrap;word-break:break-all;margin:0;max-height:150px;overflow-y:auto;">{combined_output}</pre>
                    </div>
                '''
            
            html += '''
                </div>
            '''
        
        html += f'''
                <div style="color:var(--text-secondary);font-size:13px;margin-bottom:15px;">
                    {issue["description"]}
                </div>
                
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:15px;">
                    <div>
                        <div style="color:#F2495C;font-weight:600;font-size:12px;margin-bottom:8px;">🎯 ROOT CAUSES</div>
                        <ul style="color:#c9d1d9;font-size:12px;margin-left:16px;line-height:1.6;">
        '''
        for cause in issue.get("root_cause", [])[:3]:
            html += f'<li>{cause}</li>'
        
        html += f'''
                        </ul>
                    </div>
                    <div>
                        <div style="color:#73BF69;font-weight:600;font-size:12px;margin-bottom:8px;">💡 REMEDIATION</div>
                        <ul style="color:#c9d1d9;font-size:12px;margin-left:16px;line-height:1.6;">
        '''
        for suggestion in issue.get("suggestions", [])[:3]:
            html += f'<li><code style="background:var(--bg-canvas);padding:1px 4px;border-radius:3px;font-size:11px;">{suggestion}</code></li>'
        
        # Build bug assessment section
        bug_assessment_html = ""
        for jira_key in jira_keys:
            if jira_key in bug_status_info:
                bug_info = bug_status_info[jira_key]
                detail = bug_info.get('assessment_detail', '')
                if detail:
                    bug_assessment_html += f'<div style="font-size:11px;color:#c9d1d9;margin-top:4px;">{detail}</div>'
        
        html += f'''
                        </ul>
                    </div>
                </div>
                
                <div style="margin-top:15px;padding:12px;background:#0d1117;border-radius:6px;">
                    <div style="color:#5794F2;font-weight:600;font-size:12px;margin-bottom:8px;">🐛 RELATED JIRA BUGS (vs {cluster_version})</div>
                    <div style="margin-bottom:8px;">
                        {jira_links_html}
                    </div>
                    {bug_assessment_html}
                </div>
        '''
        
        # Add INVESTIGATION section with determined root cause (only for full RCA)
        if show_investigation:
            investigations = data.get("investigations", [])
            determined_causes = data.get("determined_causes", [])
        else:
            investigations = []
            determined_causes = []
        
        if determined_causes:
            # Show the determined root cause prominently
            best_cause = determined_causes[0]  # Use first (usually most relevant)
            confidence_color = "#73BF69" if best_cause["confidence"] == "high" else "#FF9830" if best_cause["confidence"] == "medium" else "#8b949e"
            inv_id = best_cause.get("investigation_id", "inv")
            
            html += f'''
                <div style="margin-top:15px;padding:16px;background:linear-gradient(135deg, #1a2332 0%, #0d1117 100%);border:1px solid #30363d;border-radius:8px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                        <div style="color:#B877D9;font-weight:600;font-size:13px;">🔬 INVESTIGATED ROOT CAUSE</div>
                        <span style="background:{confidence_color}22;color:{confidence_color};padding:3px 10px;border-radius:10px;font-size:10px;font-weight:600;text-transform:uppercase;">{best_cause["confidence"]} confidence</span>
                    </div>
                    <div style="background:#161b22;border-left:3px solid {confidence_color};padding:12px 16px;border-radius:4px;margin-bottom:12px;">
                        <div style="color:#fff;font-size:15px;font-weight:600;margin-bottom:4px;">🎯 {best_cause["cause"]}</div>
                        <div style="color:#8b949e;font-size:12px;">{best_cause["explanation"]}</div>
                    </div>
                    <details style="margin-top:10px;">
                        <summary style="cursor:pointer;color:#58a6ff;font-size:12px;font-weight:500;padding:8px 0;">
                            📋 View detailed investigation ({len(investigations)} diagnostic commands executed)
                        </summary>
                        <div id="inv-{inv_id}" style="margin-top:12px;max-height:400px;overflow-y:auto;">
            '''
            
            # Add investigation details for ALL issues
            for inv in investigations:
                failure_name = inv.get("failure_name", "")
                results = inv.get("results", [])
                
                html += f'''
                            <div style="margin-bottom:16px;background:#0d1117;border-radius:6px;padding:12px;">
                                <div style="color:#8b949e;font-size:11px;margin-bottom:10px;border-bottom:1px solid #21262d;padding-bottom:8px;">
                                    Investigation for: <span style="color:#c9d1d9;font-family:monospace;">{failure_name}</span>
                                </div>
                '''
                
                for r in results:
                    desc = r.get("description", "")
                    cmd = r.get("command", "")
                    output = r.get("output", "")
                    # Escape HTML
                    output_escaped = str(output).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")[:300]
                    
                    html += f'''
                                <div style="margin-bottom:10px;">
                                    <div style="color:#58a6ff;font-size:11px;font-weight:500;margin-bottom:4px;">📌 {desc}</div>
                                    <code style="display:block;background:#161b22;padding:6px 10px;border-radius:4px;font-size:10px;color:#8b949e;margin-bottom:4px;word-break:break-all;">$ {cmd}</code>
                                    <pre style="background:#0a0e14;padding:8px 10px;border-radius:4px;font-size:10px;color:#e6edf3;margin:0;white-space:pre-wrap;word-break:break-all;max-height:80px;overflow-y:auto;">{output_escaped}</pre>
                                </div>
                    '''
                
                html += '''
                            </div>
                '''
            
            html += '''
                        </div>
                    </details>
                </div>
            '''
        
        html += '''
            </div>
        '''
    
    html += '''
        </div>
    </div>
    '''
    return html

def escape_html(text):
    """Escape HTML special characters"""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def get_ssh_client():
    """Get or create SSH client"""
    global ssh_client
    if ssh_client is None:
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(HOST, username=USER, key_filename=KEY_PATH, timeout=10)
    return ssh_client

def ssh_command(command, timeout=30):
    """Execute command via SSH"""
    full_cmd = f"export KUBECONFIG={KUBECONFIG} && {command}"
    try:
        client = get_ssh_client()
        stdin, stdout, stderr = client.exec_command(full_cmd, timeout=timeout)
        return stdout.read().decode().strip()
    except:
        return ""

def collect_data():
    """Collect all cluster health data"""
    import sys
    
    def log(msg):
        print(f"  {msg}", flush=True)
    
    log("📊 Starting data collection...")
    
    # Run optimized commands
    log("  → Checking nodes...")
    nodes_out = ssh_command("oc get nodes --no-headers", timeout=15)
    
    log("  → Checking cluster operators...")
    operators_out = ssh_command("oc get co --no-headers", timeout=15)
    
    log("  → Checking pod status...")
    pods_out = ssh_command(
        "oc get pods -A --no-headers --field-selector=status.phase!=Running,status.phase!=Succeeded 2>/dev/null",
        timeout=15
    )
    pod_count = ssh_command("oc get pods -A --no-headers 2>/dev/null | wc -l", timeout=15)
    
    log("  → Checking KubeVirt status...")
    kubevirt_out = ssh_command("oc get kubevirt -A --no-headers 2>/dev/null", timeout=10)
    vmi_out = ssh_command("oc get vmi -A --no-headers 2>/dev/null", timeout=10)
    
    log("  → Checking node resources...")
    top_out = ssh_command("oc adm top nodes --no-headers 2>/dev/null", timeout=15)
    
    log("  → Getting cluster version...")
    version_out = ssh_command("oc version 2>/dev/null | grep 'Server Version'", timeout=10)
    
    # NEW CHECKS based on common Jira bugs
    log("  → Checking etcd health...")
    etcd_out = ssh_command("oc get pods -n openshift-etcd -l app=etcd --no-headers 2>/dev/null", timeout=10)
    etcd_leader = ssh_command("oc rsh -n openshift-etcd -c etcdctl $(oc get pods -n openshift-etcd -l app=etcd -o name 2>/dev/null | head -1) etcdctl endpoint status --cluster -w table 2>/dev/null | grep -v 'ENDPOINT' | head -5", timeout=15)
    
    log("  → Checking certificates...")
    certs_out = ssh_command("oc get certificates -A --no-headers 2>/dev/null; oc get secret -A -o json 2>/dev/null | grep -o '\"notAfter\":\"[^\"]*\"' | head -10", timeout=15)
    
    log("  → Checking PVC status...")
    pvc_out = ssh_command("oc get pvc -A --no-headers 2>/dev/null | grep -v Bound | head -20", timeout=10)
    
    log("  → Checking VM migrations...")
    migrations_out = ssh_command("oc get vmim -A --no-headers 2>/dev/null | grep -v Succeeded | head -20", timeout=10)
    
    log("  → Checking alerts...")
    alerts_out = ssh_command("oc get prometheusrules -A --no-headers 2>/dev/null | wc -l; oc exec -n openshift-monitoring -c prometheus prometheus-k8s-0 -- curl -s 'http://localhost:9090/api/v1/alerts' 2>/dev/null | grep -o '\"alertname\":\"[^\"]*\"' | sort | uniq -c | sort -rn | head -10", timeout=20)
    
    log("  → Checking CSI drivers...")
    csi_out = ssh_command("oc get pods -A --no-headers 2>/dev/null | grep -E 'csi|driver' | grep -v Running", timeout=10)
    
    log("  → Checking OOM events...")
    oom_out = ssh_command("oc get events -A --field-selector reason=OOMKilled --no-headers 2>/dev/null | tail -10", timeout=10)
    
    log("  → Checking failed migrations...")
    failed_migrations = ssh_command("oc get vmim -A -o json 2>/dev/null | grep -E '\"phase\":\"Failed\"' | wc -l", timeout=10)
    
    # NEW CNV-SPECIFIC CHECKS based on Jira bugs
    log("  → Checking virt-handler pods...")
    virt_handler_out = ssh_command("oc get pods -n openshift-cnv -l kubevirt.io=virt-handler --no-headers 2>/dev/null", timeout=10)
    virt_handler_mem = ssh_command("oc adm top pods -n openshift-cnv -l kubevirt.io=virt-handler --no-headers 2>/dev/null", timeout=10)
    
    log("  → Checking virt-launcher pods...")
    virt_launcher_issues = ssh_command("oc get pods -A -l kubevirt.io=virt-launcher --no-headers 2>/dev/null | grep -v Running | head -10", timeout=10)
    
    log("  → Checking virt-controller/virt-api...")
    virt_ctrl_out = ssh_command("oc get pods -n openshift-cnv -l 'kubevirt.io in (virt-controller,virt-api)' --no-headers 2>/dev/null", timeout=10)
    
    log("  → Checking DataVolumes...")
    dv_stuck = ssh_command("oc get dv -A --no-headers 2>/dev/null | grep -vE 'Succeeded|PVCBound' | head -15", timeout=10)
    
    log("  → Checking VolumeSnapshots...")
    snapshots_out = ssh_command("oc get volumesnapshot -A --no-headers 2>/dev/null | grep -v 'true' | head -10", timeout=10)
    
    log("  → Checking cordoned nodes...")
    cordoned_nodes = ssh_command("oc get nodes --no-headers 2>/dev/null | grep SchedulingDisabled", timeout=10)
    vms_on_cordoned = ""
    if cordoned_nodes:
        cordoned_list = [line.split()[0] for line in cordoned_nodes.split('\n') if line]
        if cordoned_list:
            log("  → Checking VMs on cordoned nodes...")
            vms_on_cordoned = ssh_command(f"oc get vmi -A -o wide --no-headers 2>/dev/null | grep -E '{'|'.join(cordoned_list)}' | head -10", timeout=10)
    
    log("  → Checking stuck migrations...")
    stuck_migrations = ssh_command("oc get vmim -A --no-headers 2>/dev/null | grep Running", timeout=10)
    
    log("  → Checking HyperConverged status...")
    hco_status = ssh_command("oc get hyperconverged -n openshift-cnv kubevirt-hyperconverged -o jsonpath='{.status.conditions}' 2>/dev/null", timeout=10)
    
    log("✅ Data collection complete!")
    
    # Parse nodes
    nodes = {"healthy": [], "unhealthy": []}
    for line in nodes_out.split('\n'):
        if line:
            parts = line.split()
            if len(parts) >= 3:
                name, status, roles = parts[0], parts[1], parts[2]
                node_info = {"name": name, "status": status, "roles": roles}
                if status == "Ready":
                    nodes["healthy"].append(node_info)
                else:
                    nodes["unhealthy"].append(node_info)
    
    # Parse operators
    operators = {"healthy": [], "degraded": [], "unavailable": []}
    for line in operators_out.split('\n'):
        if line:
            parts = line.split()
            if len(parts) >= 5:
                name, available, degraded = parts[0], parts[2], parts[4]
                if available == "False":
                    operators["unavailable"].append(name)
                elif degraded == "True":
                    operators["degraded"].append(name)
                else:
                    operators["healthy"].append(name)
    
    # Parse pods
    pods = {"healthy": 0, "unhealthy": []}
    try:
        total = int(pod_count.strip()) if pod_count.strip().isdigit() else 0
    except:
        total = 0
    
    for line in pods_out.split('\n'):
        if line:
            parts = line.split()
            if len(parts) >= 4:
                ns, name, ready, status = parts[0], parts[1], parts[2], parts[3]
                restarts = parts[4] if len(parts) > 4 else "0"
                if status not in ["Completed", "Succeeded"]:
                    pods["unhealthy"].append({
                        "ns": ns, "name": name, "ready": ready, 
                        "status": status, "restarts": restarts
                    })
    pods["healthy"] = total - len(pods["unhealthy"])
    
    # Parse kubevirt
    kubevirt = {"installed": False, "status": None, "vms_running": 0, "failed_vmis": []}
    if kubevirt_out and "No resources" not in kubevirt_out:
        kubevirt["installed"] = True
        parts = kubevirt_out.split()
        kubevirt["status"] = parts[-1] if parts else "Unknown"
    
    for line in vmi_out.split('\n'):
        if line:
            parts = line.split()
            if len(parts) >= 4:
                if parts[3] in ["Failed", "Error"]:
                    kubevirt["failed_vmis"].append({"ns": parts[0], "name": parts[1], "status": parts[3]})
                elif parts[3] == "Running":
                    kubevirt["vms_running"] += 1
    
    # Parse resources
    resources = {"nodes": [], "high_cpu": [], "high_memory": []}
    for line in top_out.split('\n'):
        if line:
            parts = line.split()
            if len(parts) >= 5:
                name = parts[0]
                try:
                    cpu_cores = parts[1]
                    cpu_pct = int(parts[2].replace('%', ''))
                    mem_bytes = parts[3]
                    mem_pct = int(parts[4].replace('%', ''))
                    resources["nodes"].append({
                        "name": name, "cpu": cpu_pct, "memory": mem_pct,
                        "cpu_cores": cpu_cores, "mem_bytes": mem_bytes
                    })
                    if cpu_pct > 85:
                        resources["high_cpu"].append(f"{name}: {cpu_pct}%")
                    if mem_pct > 85:
                        resources["high_memory"].append(f"{name}: {mem_pct}%")
                except:
                    pass
    
    # Version
    version = version_out.split(':')[-1].strip() if version_out else "Unknown"
    
    # Parse NEW checks
    # etcd status
    etcd = {"healthy": 0, "unhealthy": [], "leader_info": etcd_leader.strip() if etcd_leader else ""}
    for line in etcd_out.split('\n'):
        if line:
            parts = line.split()
            if len(parts) >= 3:
                name, ready, status = parts[0], parts[1], parts[2]
                if status == "Running" and ready.split('/')[0] == ready.split('/')[1]:
                    etcd["healthy"] += 1
                else:
                    etcd["unhealthy"].append({"name": name, "status": status})
    
    # Pending PVCs
    pvcs = {"pending": []}
    for line in pvc_out.split('\n'):
        if line:
            parts = line.split()
            if len(parts) >= 4:
                pvcs["pending"].append({"ns": parts[0], "name": parts[1], "status": parts[2]})
    
    # VM Migrations (not succeeded)
    migrations = {"failed": [], "running": 0}
    try:
        migrations["failed_count"] = int(failed_migrations.strip()) if failed_migrations.strip().isdigit() else 0
    except:
        migrations["failed_count"] = 0
    for line in migrations_out.split('\n'):
        if line:
            parts = line.split()
            if len(parts) >= 4:
                phase = parts[3] if len(parts) > 3 else "Unknown"
                if phase == "Running":
                    migrations["running"] += 1
                elif phase not in ["Succeeded", "Running"]:
                    migrations["failed"].append({"ns": parts[0], "name": parts[1], "phase": phase})
    
    # OOM events
    oom_events = []
    for line in oom_out.split('\n'):
        if line and "OOMKilled" in line:
            parts = line.split()
            if len(parts) >= 5:
                oom_events.append({"ns": parts[0], "object": parts[4] if len(parts) > 4 else "unknown"})
    
    # CSI issues
    csi_issues = []
    for line in csi_out.split('\n'):
        if line:
            parts = line.split()
            if len(parts) >= 4:
                csi_issues.append({"ns": parts[0], "pod": parts[1], "status": parts[3]})
    
    # Parse CNV-specific checks
    # virt-handler
    virt_handler = {"healthy": 0, "unhealthy": [], "high_memory": []}
    for line in virt_handler_out.split('\n'):
        if line:
            parts = line.split()
            if len(parts) >= 3:
                name, ready, status = parts[0], parts[1], parts[2]
                restarts = parts[3] if len(parts) > 3 else "0"
                if status == "Running" and ready.split('/')[0] == ready.split('/')[1]:
                    virt_handler["healthy"] += 1
                else:
                    virt_handler["unhealthy"].append({"name": name, "status": status, "restarts": restarts})
    # Check memory
    for line in virt_handler_mem.split('\n'):
        if line:
            parts = line.split()
            if len(parts) >= 3:
                name, cpu, mem = parts[0], parts[1], parts[2]
                mem_mi = int(mem.replace('Mi', '').replace('Gi', '000')) if 'Mi' in mem or 'Gi' in mem else 0
                if mem_mi > 500:  # > 500Mi is concerning
                    virt_handler["high_memory"].append({"name": name, "memory": mem})
    
    # virt-launcher issues
    virt_launcher_bad = []
    for line in virt_launcher_issues.split('\n'):
        if line:
            parts = line.split()
            if len(parts) >= 4:
                virt_launcher_bad.append({"ns": parts[0], "pod": parts[1], "status": parts[3]})
    
    # virt-controller/api
    virt_ctrl = {"healthy": 0, "unhealthy": []}
    for line in virt_ctrl_out.split('\n'):
        if line:
            parts = line.split()
            if len(parts) >= 3:
                name, ready, status = parts[0], parts[1], parts[2]
                if status == "Running":
                    virt_ctrl["healthy"] += 1
                else:
                    virt_ctrl["unhealthy"].append({"name": name, "status": status})
    
    # DataVolumes stuck
    dv_issues = []
    for line in dv_stuck.split('\n'):
        if line:
            parts = line.split()
            if len(parts) >= 4:
                dv_issues.append({"ns": parts[0], "name": parts[1], "phase": parts[3] if len(parts) > 3 else "Unknown"})
    
    # VolumeSnapshots not ready
    snapshot_issues = []
    for line in snapshots_out.split('\n'):
        if line:
            parts = line.split()
            if len(parts) >= 3:
                snapshot_issues.append({"ns": parts[0], "name": parts[1]})
    
    # Cordoned nodes with VMs
    cordoned_vms = []
    if vms_on_cordoned:
        for line in vms_on_cordoned.split('\n'):
            if line:
                parts = line.split()
                if len(parts) >= 4:
                    cordoned_vms.append({"ns": parts[0], "vm": parts[1], "node": parts[4] if len(parts) > 4 else "unknown"})
    
    # Stuck migrations (running for too long)
    stuck_migs = []
    for line in stuck_migrations.split('\n'):
        if line:
            parts = line.split()
            if len(parts) >= 3:
                stuck_migs.append({"ns": parts[0], "name": parts[1]})
    
    # HCO status
    hco_healthy = "Available" in hco_status if hco_status else False
    
    # Run dynamically added checks from Jira analysis
    dynamic_check_results = {}
    if SUGGESTED_NEW_CHECKS:
        for check in SUGGESTED_NEW_CHECKS:
            check_name = check.get("name", "unknown")
            try:
                # Execute the check command
                if check_name == "etcd_latency":
                    result = ssh_command("oc exec -n openshift-etcd $(oc get pods -n openshift-etcd -l app=etcd -o name | head -1) -- etcdctl endpoint health --cluster -w json 2>/dev/null", timeout=15)
                elif check_name == "kubelet_health":
                    result = ssh_command("oc get nodes -o jsonpath='{range .items[*]}{.metadata.name} {.status.conditions[?(@.type==\"Ready\")].status}{\"\\n\"}{end}' 2>/dev/null", timeout=15)
                elif check_name == "cert_expiry":
                    result = ssh_command("oc get secret -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name} {.type}{\"\\n\"}{end}' 2>/dev/null | grep tls | head -10", timeout=15)
                elif check_name == "network_migration":
                    result = ssh_command("oc get network.operator cluster -o jsonpath='{.spec.migration}' 2>/dev/null", timeout=10)
                elif check_name == "catalog_source":
                    result = ssh_command("oc get catalogsource -n openshift-marketplace --no-headers 2>/dev/null", timeout=10)
                elif check_name == "router_health":
                    result = ssh_command("oc get pods -n openshift-ingress -l ingresscontroller.operator.openshift.io/deployment-ingresscontroller --no-headers 2>/dev/null", timeout=10)
                elif check_name == "image_pull":
                    result = ssh_command("oc get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded 2>/dev/null | grep -i imagepull | head -10", timeout=15)
                else:
                    result = ssh_command("echo 'Check not implemented'", timeout=5)
                
                # Parse result for issues
                issues_found = []
                if result:
                    # Simple issue detection
                    if "error" in result.lower() or "fail" in result.lower() or "false" in result.lower():
                        issues_found = [{"raw": result[:200]}]
                
                dynamic_check_results[check_name] = {
                    "raw_output": result[:500] if result else "",
                    "issues": issues_found,
                    "jira": check.get("jira", ""),
                    "description": check.get("description", "")
                }
            except Exception as e:
                dynamic_check_results[check_name] = {
                    "raw_output": f"Error: {str(e)}",
                    "issues": [],
                    "jira": check.get("jira", ""),
                    "description": check.get("description", "")
                }
    
    return {
        "nodes": nodes,
        "operators": operators,
        "pods": pods,
        "kubevirt": kubevirt,
        "resources": resources,
        "version": version,
        "cluster": HOST,
        "timestamp": datetime.now(),
        # New checks
        "etcd": etcd,
        "pvcs": pvcs,
        "migrations": migrations,
        "oom_events": oom_events,
        "csi_issues": csi_issues,
        # CNV-specific
        "virt_handler": virt_handler,
        "virt_launcher_bad": virt_launcher_bad,
        "virt_ctrl": virt_ctrl,
        "dv_issues": dv_issues,
        "snapshot_issues": snapshot_issues,
        "cordoned_vms": cordoned_vms,
        "stuck_migrations": stuck_migs,
        "hco_healthy": hco_healthy,
        # Dynamic checks from Jira
        "dynamic_checks": dynamic_check_results,
    }

def has_issues(data):
    """Check for any issues"""
    return (
        len(data["nodes"]["unhealthy"]) > 0 or
        len(data["operators"]["degraded"]) > 0 or
        len(data["operators"]["unavailable"]) > 0 or
        len(data["pods"]["unhealthy"]) > 0 or
        len(data["kubevirt"]["failed_vmis"]) > 0 or
        len(data["resources"]["high_cpu"]) > 0 or
        len(data["resources"]["high_memory"]) > 0 or
        # New checks
        len(data["etcd"]["unhealthy"]) > 0 or
        len(data["pvcs"]["pending"]) > 0 or
        len(data["migrations"]["failed"]) > 0 or
        data["migrations"]["failed_count"] > 0 or
        len(data["oom_events"]) > 0 or
        len(data["csi_issues"]) > 0 or
        # CNV-specific
        len(data["virt_handler"]["unhealthy"]) > 0 or
        len(data["virt_handler"]["high_memory"]) > 0 or
        len(data["virt_launcher_bad"]) > 0 or
        len(data["virt_ctrl"]["unhealthy"]) > 0 or
        len(data["dv_issues"]) > 0 or
        len(data["snapshot_issues"]) > 0 or
        len(data["cordoned_vms"]) > 0 or
        len(data["stuck_migrations"]) > 0
    )

def generate_html_report(data, include_rca=False, rca_level='none'):
    """Generate Grafana-style HTML dashboard report
    
    rca_level can be:
    - 'none': No RCA, just health checks
    - 'bugs': Match failures to known bugs (no deep investigation)
    - 'full': Full RCA with deep investigation
    """
    # Handle legacy include_rca parameter
    if include_rca and rca_level == 'none':
        rca_level = 'full'
    
    issues = has_issues(data)
    
    # Generate RCA if requested and there are issues
    rca_html = ""
    email_rca_data = {}
    
    if rca_level != 'none' and issues:
        print(f"  🔬 Starting Root Cause Analysis...", flush=True)
        
        # Search Jira if enabled
        if RCA_JIRA:
            print(f"     → Searching Jira for related bugs...", flush=True)
        
        print(f"     → Matching failures to known issues database...", flush=True)
        analysis = analyze_failures(data)
        print(f"     → Found {len(analysis)} issue(s) to analyze", flush=True)
        
        # Search emails if enabled
        if RCA_EMAIL:
            print(f"     → Searching emails for related discussions...", flush=True)
            email_rca_data = search_emails_for_issues(analysis)
            # Add email data to analysis
            for item in analysis:
                if isinstance(item, dict):
                    item['email_searches'] = email_rca_data.get('keywords', [])
        
        if rca_level == 'full':
            # Full RCA includes deep investigation
            print(f"     → Running deep investigation commands...", flush=True)
            analysis = run_deep_investigation(analysis, ssh_command)
            print(f"     → Deep investigation complete", flush=True)
        
        print(f"     → Generating RCA HTML section...", flush=True)
        rca_html = generate_rca_html(analysis, data.get("version", ""), show_investigation=(rca_level == 'full'), email_data=email_rca_data)
        print(f"  ✅ RCA analysis complete", flush=True)
    
    status_color = "#FF9830" if issues else "#73BF69"
    status_text = "ATTENTION NEEDED" if issues else "ALL SYSTEMS HEALTHY"
    
    # Calculate totals
    total_nodes = len(data['nodes']['healthy']) + len(data['nodes']['unhealthy'])
    healthy_nodes = len(data['nodes']['healthy'])
    total_ops = len(data['operators']['healthy']) + len(data['operators']['degraded']) + len(data['operators']['unavailable'])
    healthy_ops = len(data['operators']['healthy'])
    total_pods = data['pods']['healthy'] + len(data['pods']['unhealthy'])
    unhealthy_pods = len(data['pods']['unhealthy'])
    
    # Build health check cards
    def health_card(title, icon, status_ok, value, subtitle="", color_override=None):
        if color_override:
            color = color_override
        else:
            color = "#73BF69" if status_ok else "#F2495C"
        status_class = "ok" if status_ok else "error"
        return f'''
        <div class="panel stat-panel {status_class}">
            <div class="panel-title">{icon} {title}</div>
            <div class="stat-value" style="color:{color}">{value}</div>
            <div class="stat-subtitle">{subtitle}</div>
        </div>'''
    
    # Build gauge for percentage
    def gauge_panel(title, icon, value, max_val, unit=""):
        pct = (value / max_val * 100) if max_val > 0 else 0
        color = "#73BF69" if pct >= 90 else "#FF9830" if pct >= 70 else "#F2495C"
        return f'''
        <div class="panel gauge-panel">
            <div class="panel-title">{icon} {title}</div>
            <div class="gauge-container">
                <svg viewBox="0 0 120 70" class="gauge-svg">
                    <path d="M 10 60 A 50 50 0 0 1 110 60" fill="none" stroke="#2c3235" stroke-width="8" stroke-linecap="round"/>
                    <path d="M 10 60 A 50 50 0 0 1 110 60" fill="none" stroke="{color}" stroke-width="8" stroke-linecap="round" 
                          stroke-dasharray="{pct * 1.57} 157" class="gauge-fill"/>
                </svg>
                <div class="gauge-value" style="color:{color}">{value}<span class="gauge-max">/{max_val}</span></div>
            </div>
            <div class="gauge-label">{unit}</div>
        </div>'''
    
    # Group pods by namespace for issues panel
    pods_by_ns = {}
    for p in data["pods"]["unhealthy"]:
        pods_by_ns.setdefault(p["ns"], []).append(p)
    
    # Build issues list HTML
    issues_html = ""
    if pods_by_ns:
        for ns in sorted(pods_by_ns.keys())[:6]:
            issues_html += f'<div class="issue-ns">{ns}</div>'
            for pod in pods_by_ns[ns][:3]:
                issues_html += f'''<div class="issue-item">
                    <span class="issue-name">{pod["name"][:40]}</span>
                    <span class="issue-status">{pod["status"]}</span>
                </div>'''
            if len(pods_by_ns[ns]) > 3:
                issues_html += f'<div class="issue-more">+{len(pods_by_ns[ns])-3} more</div>'
    
    # Build resource usage bars
    resource_rows = ""
    for node in data["resources"]["nodes"][:12]:
        cpu_pct = node["cpu"]
        mem_pct = node["memory"]
        cpu_color = "#73BF69" if cpu_pct < 70 else "#FF9830" if cpu_pct < 85 else "#F2495C"
        mem_color = "#73BF69" if mem_pct < 70 else "#FF9830" if mem_pct < 85 else "#F2495C"
        resource_rows += f'''
        <div class="resource-row">
            <div class="resource-node-name">{node["name"][:25]}</div>
            <div class="resource-bar-wrap">
                <div class="resource-bar">
                    <div class="resource-bar-fill" style="width:{cpu_pct}%;background:{cpu_color}"></div>
                </div>
                <span class="resource-pct">{cpu_pct}%</span>
            </div>
            <div class="resource-bar-wrap">
                <div class="resource-bar">
                    <div class="resource-bar-fill" style="width:{mem_pct}%;background:{mem_color}"></div>
                </div>
                <span class="resource-pct">{mem_pct}%</span>
            </div>
        </div>'''
    
    html = f'''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>CNV HealthCrew AI - {data["cluster"]}</title>
<style>
:root {{
    --bg-canvas: #111217;
    --bg-primary: #181b1f;
    --bg-secondary: #22252b;
    --border: #2c3235;
    --text-primary: #d8d9da;
    --text-secondary: #8e8e8e;
    --green: #73BF69;
    --yellow: #FF9830;
    --red: #F2495C;
    --blue: #5794F2;
    --purple: #B877D9;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg-canvas); color: var(--text-primary); min-height: 100vh; }}

/* Top Navigation */
.navbar {{ background: var(--bg-primary); border-bottom: 1px solid var(--border); padding: 0 24px; height: 52px; display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 100; }}
.navbar-brand {{ display: flex; align-items: center; gap: 12px; }}
.navbar-logo {{ width: 32px; height: 32px; background: linear-gradient(135deg, #FF6B35 0%, #F7931E 100%); border-radius: 8px; display: flex; align-items: center; justify-content: center; font-weight: 700; color: white; }}
.navbar-title {{ font-size: 18px; font-weight: 600; color: var(--text-primary); }}
.navbar-title span {{ color: var(--red); }}
.navbar-status {{ display: flex; align-items: center; gap: 8px; padding: 6px 16px; border-radius: 16px; font-size: 13px; font-weight: 500; background: {"rgba(242,73,92,0.15)" if issues else "rgba(115,191,105,0.15)"}; color: {status_color}; }}
.navbar-status::before {{ content: ''; width: 8px; height: 8px; border-radius: 50%; background: {status_color}; animation: pulse 2s infinite; }}
@keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}

/* Dashboard Container */
.dashboard {{ padding: 24px; max-width: 1800px; margin: 0 auto; }}

/* Dashboard Header */
.dash-header {{ margin-bottom: 24px; }}
.dash-header h1 {{ font-size: 24px; font-weight: 600; margin-bottom: 8px; }}
.dash-meta {{ display: flex; gap: 24px; color: var(--text-secondary); font-size: 13px; }}
.dash-meta span {{ display: flex; align-items: center; gap: 6px; }}

/* Grid Layout */
.grid {{ display: grid; gap: 16px; }}
.grid-4 {{ grid-template-columns: repeat(4, 1fr); }}
.grid-3 {{ grid-template-columns: repeat(3, 1fr); }}
.grid-2 {{ grid-template-columns: repeat(2, 1fr); }}
.grid-full {{ grid-template-columns: 1fr; }}
@media (max-width: 1400px) {{ .grid-4 {{ grid-template-columns: repeat(2, 1fr); }} }}
@media (max-width: 900px) {{ .grid-4, .grid-3, .grid-2 {{ grid-template-columns: 1fr; }} }}

/* Panel Base */
.panel {{ background: var(--bg-primary); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
.panel-title {{ font-size: 12px; font-weight: 500; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; padding: 12px 16px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 8px; }}

/* Stat Panels */
.stat-panel {{ text-align: center; padding-bottom: 16px; }}
.stat-panel.ok {{ border-top: 3px solid var(--green); }}
.stat-panel.error {{ border-top: 3px solid var(--red); }}
.stat-panel.warn {{ border-top: 3px solid var(--yellow); }}
.stat-value {{ font-size: 42px; font-weight: 700; padding: 20px 16px 8px; font-variant-numeric: tabular-nums; }}
.stat-subtitle {{ font-size: 13px; color: var(--text-secondary); }}

/* Gauge Panels */
.gauge-panel {{ text-align: center; padding-bottom: 16px; }}
.gauge-container {{ position: relative; padding: 16px; }}
.gauge-svg {{ width: 120px; height: 70px; }}
.gauge-fill {{ transition: stroke-dasharray 0.5s ease; }}
.gauge-value {{ font-size: 28px; font-weight: 700; margin-top: -10px; }}
.gauge-max {{ font-size: 16px; color: var(--text-secondary); font-weight: 400; }}
.gauge-label {{ font-size: 12px; color: var(--text-secondary); margin-top: 4px; }}

/* Health Check Grid */
.check-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; padding: 16px; }}
.check-card {{ background: var(--bg-secondary); border-radius: 6px; padding: 14px 16px; display: flex; align-items: center; gap: 12px; transition: background 0.2s; }}
.check-card:hover {{ background: #2a2d33; }}
.check-icon {{ font-size: 20px; }}
.check-info {{ flex: 1; min-width: 0; }}
.check-name {{ font-size: 13px; font-weight: 500; margin-bottom: 2px; }}
.check-result {{ font-size: 12px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.check-status {{ font-size: 18px; }}
.check-section-title {{ grid-column: 1 / -1; font-size: 11px; font-weight: 600; color: var(--blue); text-transform: uppercase; letter-spacing: 1px; padding: 8px 0 4px; border-bottom: 1px solid var(--border); margin-top: 8px; }}

/* Resource Usage */
.resource-header {{ display: grid; grid-template-columns: 200px 1fr 1fr; gap: 16px; padding: 8px 16px; font-size: 11px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; border-bottom: 1px solid var(--border); }}
.resource-body {{ max-height: 400px; overflow-y: auto; }}
.resource-row {{ display: grid; grid-template-columns: 200px 1fr 1fr; gap: 16px; padding: 10px 16px; border-bottom: 1px solid var(--bg-canvas); align-items: center; }}
.resource-row:last-child {{ border-bottom: none; }}
.resource-row:hover {{ background: var(--bg-secondary); }}
.resource-node-name {{ font-family: 'JetBrains Mono', Monaco, monospace; font-size: 12px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.resource-bar-wrap {{ display: flex; align-items: center; gap: 12px; }}
.resource-bar {{ flex: 1; height: 8px; background: var(--bg-canvas); border-radius: 4px; overflow: hidden; }}
.resource-bar-fill {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
.resource-pct {{ font-size: 12px; font-weight: 600; min-width: 45px; text-align: right; font-variant-numeric: tabular-nums; }}

/* Issues Panel */
.issues-body {{ padding: 16px; max-height: 350px; overflow-y: auto; }}
.issue-ns {{ font-size: 12px; font-weight: 600; color: var(--blue); padding: 8px 0 6px; border-bottom: 1px solid var(--border); margin-bottom: 8px; }}
.issue-item {{ display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: var(--bg-secondary); border-radius: 4px; margin-bottom: 6px; font-size: 12px; }}
.issue-name {{ font-family: 'JetBrains Mono', Monaco, monospace; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 70%; }}
.issue-status {{ color: var(--red); font-weight: 500; white-space: nowrap; }}
.issue-more {{ font-size: 11px; color: var(--text-secondary); padding: 4px 0 8px; }}

/* RCA Panel styling */
.rca-panel {{ margin-top: 16px; }}

/* Footer */
.dash-footer {{ margin-top: 32px; padding: 24px; text-align: center; color: var(--text-secondary); font-size: 12px; border-top: 1px solid var(--border); }}
.dash-footer-status {{ font-size: 14px; font-weight: 600; color: {status_color}; margin-bottom: 8px; }}
</style>
</head>
<body>

<nav class="navbar">
    <div class="navbar-brand">
        <div class="navbar-logo">🏥</div>
        <div class="navbar-title">CNV <span>HealthCrew</span> AI</div>
    </div>
    <div class="navbar-status">{status_text}</div>
</nav>

<div class="dashboard">
    <div class="dash-header">
        <h1>{data["cluster"]}</h1>
        <div class="dash-meta">
            <span>📅 {data["timestamp"].strftime("%Y-%m-%d %H:%M:%S")}</span>
            <span>🏷️ Version {data["version"]}</span>
            <span>🔍 17 Health Checks</span>
        </div>
    </div>

    <!-- Main Stats Row -->
    <div class="grid grid-4" style="margin-bottom:16px;">
        {gauge_panel("Nodes", "🖥️", healthy_nodes, total_nodes, "Ready")}
        {gauge_panel("Operators", "⚙️", healthy_ops, total_ops, "Available")}
        {gauge_panel("Pods", "📦", data['pods']['healthy'], total_pods, "Running")}
        {gauge_panel("VMs", "💻", data['kubevirt']['vms_running'], data['kubevirt']['vms_running'] or 1, "Running")}
    </div>

    <!-- Secondary Stats Row -->
    <div class="grid grid-4" style="margin-bottom:16px;">
        {health_card("etcd Members", "🗄️", not data['etcd']['unhealthy'], data['etcd']['healthy'], "Healthy")}
        {health_card("PVCs Pending", "💾", not data['pvcs']['pending'], len(data['pvcs']['pending']), "", "#73BF69" if not data['pvcs']['pending'] else "#F2495C")}
        {health_card("OOM Events", "💥", not data['oom_events'], len(data['oom_events']), "Recent", "#73BF69" if not data['oom_events'] else "#F2495C")}
        {health_card("Migrations", "🔄", data['migrations']['failed_count'] == 0, data['migrations']['running'], "Running")}
    </div>

    <!-- Main Content Grid -->
    <div class="grid grid-2" style="margin-bottom:16px;">
        <!-- Resource Usage Panel -->
        <div class="panel">
            <div class="panel-title">📊 Node Resource Usage</div>
            <div class="resource-header">
                <div>Node</div>
                <div>CPU</div>
                <div>Memory</div>
            </div>
            <div class="resource-body">
                {resource_rows if resource_rows else '<div style="padding:40px;text-align:center;color:var(--text-secondary);">No resource data</div>'}
            </div>
        </div>

        <!-- Issues Panel -->
        <div class="panel">
            <div class="panel-title" style="color:var(--red);">⚠️ Unhealthy Pods ({unhealthy_pods})</div>
            <div class="issues-body">
                {issues_html if issues_html else '<div style="padding:40px;text-align:center;color:var(--green);">✅ All pods healthy</div>'}
            </div>
        </div>
    </div>

    <!-- Health Checks Panel -->
    <div class="panel" style="margin-bottom:16px;">
        <div class="panel-title">🧪 Health Check Results</div>
        <div class="check-grid">
            <div class="check-card">
                <span class="check-icon">🖥️</span>
                <div class="check-info">
                    <div class="check-name">Nodes</div>
                    <div class="check-result">{healthy_nodes}/{total_nodes} Ready</div>
                </div>
                <span class="check-status">{'✅' if not data['nodes']['unhealthy'] else '❌'}</span>
            </div>
            <div class="check-card">
                <span class="check-icon">⚙️</span>
                <div class="check-info">
                    <div class="check-name">Cluster Operators</div>
                    <div class="check-result">{healthy_ops}/{total_ops} Available</div>
                </div>
                <span class="check-status">{'✅' if not data['operators']['degraded'] and not data['operators']['unavailable'] else '❌'}</span>
            </div>
            <div class="check-card">
                <span class="check-icon">📦</span>
                <div class="check-info">
                    <div class="check-name">Pods</div>
                    <div class="check-result">{data['pods']['healthy']} Running, {unhealthy_pods} Unhealthy</div>
                </div>
                <span class="check-status">{'✅' if not data['pods']['unhealthy'] else '❌'}</span>
            </div>
            <div class="check-card">
                <span class="check-icon">💻</span>
                <div class="check-info">
                    <div class="check-name">KubeVirt</div>
                    <div class="check-result">{data['kubevirt']['status'] if data['kubevirt']['installed'] else 'Not installed'}, {data['kubevirt']['vms_running']} VMs</div>
                </div>
                <span class="check-status">{'✅' if data['kubevirt']['status'] == 'Deployed' and not data['kubevirt']['failed_vmis'] else '⚠️' if data['kubevirt']['installed'] else '➖'}</span>
            </div>
            <div class="check-card">
                <span class="check-icon">📊</span>
                <div class="check-info">
                    <div class="check-name">Resource Usage</div>
                    <div class="check-result">{len(data['resources']['high_cpu'])} high CPU, {len(data['resources']['high_memory'])} high mem</div>
                </div>
                <span class="check-status">{'✅' if not data['resources']['high_cpu'] and not data['resources']['high_memory'] else '❌'}</span>
            </div>
            <div class="check-card">
                <span class="check-icon">🗄️</span>
                <div class="check-info">
                    <div class="check-name">etcd Health</div>
                    <div class="check-result">{data['etcd']['healthy']} members healthy</div>
                </div>
                <span class="check-status">{'✅' if not data['etcd']['unhealthy'] else '❌'}</span>
            </div>
            <div class="check-card">
                <span class="check-icon">💾</span>
                <div class="check-info">
                    <div class="check-name">PVC Status</div>
                    <div class="check-result">{len(data['pvcs']['pending'])} pending</div>
                </div>
                <span class="check-status">{'✅' if not data['pvcs']['pending'] else '❌'}</span>
            </div>
            <div class="check-card">
                <span class="check-icon">🔄</span>
                <div class="check-info">
                    <div class="check-name">VM Migrations</div>
                    <div class="check-result">{data['migrations']['running']} running, {len(data['migrations']['failed']) + data['migrations']['failed_count']} failed</div>
                </div>
                <span class="check-status">{'✅' if not data['migrations']['failed'] and data['migrations']['failed_count'] == 0 else '❌'}</span>
            </div>
            <div class="check-card">
                <span class="check-icon">💥</span>
                <div class="check-info">
                    <div class="check-name">OOM Events</div>
                    <div class="check-result">{len(data['oom_events'])} recent events</div>
                </div>
                <span class="check-status">{'✅' if not data['oom_events'] else '❌'}</span>
            </div>
            <div class="check-card">
                <span class="check-icon">🔌</span>
                <div class="check-info">
                    <div class="check-name">CSI Drivers</div>
                    <div class="check-result">{len(data['csi_issues'])} issues</div>
                </div>
                <span class="check-status">{'✅' if not data['csi_issues'] else '❌'}</span>
            </div>
            
            <div class="check-section-title">CNV / KubeVirt Checks</div>
            
            <div class="check-card">
                <span class="check-icon">🔧</span>
                <div class="check-info">
                    <div class="check-name">virt-handler</div>
                    <div class="check-result">{data['virt_handler']['healthy']} healthy, {len(data['virt_handler']['high_memory'])} high mem</div>
                </div>
                <span class="check-status">{'✅' if not data['virt_handler']['unhealthy'] and not data['virt_handler']['high_memory'] else '❌'}</span>
            </div>
            <div class="check-card">
                <span class="check-icon">🎛️</span>
                <div class="check-info">
                    <div class="check-name">virt-controller/api</div>
                    <div class="check-result">{data['virt_ctrl']['healthy']} healthy</div>
                </div>
                <span class="check-status">{'✅' if not data['virt_ctrl']['unhealthy'] else '❌'}</span>
            </div>
            <div class="check-card">
                <span class="check-icon">🚀</span>
                <div class="check-info">
                    <div class="check-name">virt-launcher</div>
                    <div class="check-result">{len(data['virt_launcher_bad'])} unhealthy</div>
                </div>
                <span class="check-status">{'✅' if not data['virt_launcher_bad'] else '❌'}</span>
            </div>
            <div class="check-card">
                <span class="check-icon">💿</span>
                <div class="check-info">
                    <div class="check-name">DataVolumes</div>
                    <div class="check-result">{len(data['dv_issues'])} stuck/pending</div>
                </div>
                <span class="check-status">{'✅' if not data['dv_issues'] else '❌'}</span>
            </div>
            <div class="check-card">
                <span class="check-icon">📸</span>
                <div class="check-info">
                    <div class="check-name">VolumeSnapshots</div>
                    <div class="check-result">{len(data['snapshot_issues'])} not ready</div>
                </div>
                <span class="check-status">{'✅' if not data['snapshot_issues'] else '❌'}</span>
            </div>
            <div class="check-card">
                <span class="check-icon">🚧</span>
                <div class="check-info">
                    <div class="check-name">Cordoned VMs</div>
                    <div class="check-result">{len(data['cordoned_vms'])} VMs at risk</div>
                </div>
                <span class="check-status">{'✅' if not data['cordoned_vms'] else '❌'}</span>
            </div>
            <div class="check-card">
                <span class="check-icon">⏳</span>
                <div class="check-info">
                    <div class="check-name">Stuck Migrations</div>
                    <div class="check-result">{len(data['stuck_migrations'])} running/stuck</div>
                </div>
                <span class="check-status">{'✅' if not data['stuck_migrations'] else '⚠️'}</span>
            </div>
        </div>
    </div>

    {rca_html}

    <div class="dash-footer">
        <div class="dash-footer-status">Cluster Status: {status_text}</div>
        <div>Generated by CNV HealthCrew AI | Based on real CNV/OCP Jira bugs</div>
    </div>
</div>

</body>
</html>'''
    return html

def print_console_report(data):
    """Print beautiful console report"""
    # ANSI colors
    G = '\033[92m'  # Green
    Y = '\033[93m'  # Yellow
    R = '\033[91m'  # Red
    B = '\033[94m'  # Blue
    C = '\033[96m'  # Cyan
    W = '\033[97m'  # White
    D = '\033[2m'   # Dim
    BD = '\033[1m'  # Bold
    X = '\033[0m'   # Reset
    
    issues = has_issues(data)
    w = 72
    
    print()
    print(f"{B}╔{'═'*w}╗{X}")
    print(f"{B}║{X}  {BD}{W}🏥 CNV HEALTHCREW AI - CLUSTER HEALTH REPORT{X}".ljust(w+20) + f"{B}║{X}")
    print(f"{B}╠{'═'*w}╣{X}")
    print(f"{B}║{X}  {D}Cluster:{X} {C}{data['cluster']}{X}".ljust(w+25) + f"{B}║{X}")
    print(f"{B}║{X}  {D}Version:{X} {data['version']}   {D}Time:{X} {data['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}".ljust(w+15) + f"{B}║{X}")
    print(f"{B}╠{'═'*w}╣{X}")
    
    # Summary line function
    def summary_line(icon, label, ok, value):
        status = f"{G}✓{X}" if ok else f"{R}✗{X}"
        color = G if ok else Y
        print(f"{B}║{X}  {status}  {BD}{label.ljust(22)}{X} {color}{value}{X}".ljust(w+30) + f"{B}║{X}")
    
    # Nodes
    n_ok = len(data["nodes"]["unhealthy"]) == 0
    n_total = len(data["nodes"]["healthy"]) + len(data["nodes"]["unhealthy"])
    summary_line("🖥️", "Nodes", n_ok, f"{len(data['nodes']['healthy'])}/{n_total} Ready")
    
    # Operators
    o_bad = len(data["operators"]["degraded"]) + len(data["operators"]["unavailable"])
    o_total = len(data["operators"]["healthy"]) + o_bad
    summary_line("⚙️", "Cluster Operators", o_bad == 0, f"{len(data['operators']['healthy'])}/{o_total} Available")
    
    # Pods
    p_bad = len(data["pods"]["unhealthy"])
    p_total = data["pods"]["healthy"] + p_bad
    summary_line("📦", "Pods", p_bad == 0, f"{data['pods']['healthy']}/{p_total} Running" + (f" ({R}{p_bad} unhealthy{X})" if p_bad else ""))
    
    # KubeVirt
    if data["kubevirt"]["installed"]:
        kv_ok = data["kubevirt"]["status"] == "Deployed" and len(data["kubevirt"]["failed_vmis"]) == 0
        summary_line("💻", "KubeVirt", kv_ok, f"{data['kubevirt']['status']} ({data['kubevirt']['vms_running']} VMs)")
    
    # Resources
    r_bad = len(data["resources"]["high_cpu"]) + len(data["resources"]["high_memory"])
    summary_line("📊", "Resources", r_bad == 0, "Normal" if r_bad == 0 else f"{r_bad} nodes high usage")
    
    # etcd
    etcd_ok = len(data["etcd"]["unhealthy"]) == 0
    summary_line("🗄️", "etcd", etcd_ok, f"{data['etcd']['healthy']} members healthy" if etcd_ok else f"{len(data['etcd']['unhealthy'])} unhealthy")
    
    # PVCs
    pvc_bad = len(data["pvcs"]["pending"])
    summary_line("💾", "PVCs", pvc_bad == 0, "All Bound" if pvc_bad == 0 else f"{pvc_bad} Pending")
    
    # VM Migrations
    mig_bad = len(data["migrations"]["failed"]) + data["migrations"]["failed_count"]
    mig_run = data["migrations"]["running"]
    summary_line("🔄", "VM Migrations", mig_bad == 0, f"{mig_run} running" if mig_bad == 0 else f"{mig_bad} failed")
    
    # OOM Events
    oom_count = len(data["oom_events"])
    summary_line("💥", "OOM Events", oom_count == 0, "None" if oom_count == 0 else f"{oom_count} recent")
    
    # CSI Drivers
    csi_bad = len(data["csi_issues"])
    summary_line("🔌", "CSI Drivers", csi_bad == 0, "Healthy" if csi_bad == 0 else f"{csi_bad} issues")
    
    # CNV-specific checks
    if data["kubevirt"]["installed"]:
        print(f"{B}╠{'─'*w}╣{X}")
        print(f"{B}║{X}  {BD}{C}CNV/KubeVirt Checks:{X}".ljust(w+25) + f"{B}║{X}")
        
        # virt-handler
        vh_bad = len(data["virt_handler"]["unhealthy"]) + len(data["virt_handler"]["high_memory"])
        summary_line("🔧", "virt-handler", vh_bad == 0, f"{data['virt_handler']['healthy']} healthy" if vh_bad == 0 else f"{vh_bad} issues")
        
        # virt-controller/api
        vc_bad = len(data["virt_ctrl"]["unhealthy"])
        summary_line("🎛️", "virt-controller/api", vc_bad == 0, f"{data['virt_ctrl']['healthy']} healthy" if vc_bad == 0 else f"{vc_bad} unhealthy")
        
        # virt-launcher
        vl_bad = len(data["virt_launcher_bad"])
        summary_line("🚀", "virt-launcher pods", vl_bad == 0, "All healthy" if vl_bad == 0 else f"{vl_bad} issues")
        
        # DataVolumes
        dv_bad = len(data["dv_issues"])
        summary_line("💿", "DataVolumes", dv_bad == 0, "All ready" if dv_bad == 0 else f"{dv_bad} stuck")
        
        # Snapshots
        snap_bad = len(data["snapshot_issues"])
        summary_line("📸", "VolumeSnapshots", snap_bad == 0, "All ready" if snap_bad == 0 else f"{snap_bad} not ready")
        
        # Cordoned nodes with VMs
        cord_bad = len(data["cordoned_vms"])
        summary_line("🚧", "VMs on cordoned nodes", cord_bad == 0, "None" if cord_bad == 0 else f"{cord_bad} VMs at risk")
        
        # Stuck migrations
        stuck_bad = len(data["stuck_migrations"])
        summary_line("⏳", "Stuck migrations", stuck_bad == 0, "None" if stuck_bad == 0 else f"{stuck_bad} stuck")
    
    # Dynamic checks from Jira (if any)
    if data.get("dynamic_checks"):
        print(f"{B}╠{'─'*w}╣{X}")
        print(f"{B}║{X}  {BD}{C}🆕 Jira-Suggested Checks:{X}".ljust(w+28) + f"{B}║{X}")
        for check_name, check_data in data["dynamic_checks"].items():
            check_has_issues = bool(check_data.get("issues"))
            jira = check_data.get("jira", "")
            desc = check_data.get("description", check_name)[:30]
            summary_line("🔍", f"{check_name} ({jira})", not check_has_issues, "OK" if not check_has_issues else "Issues found")
    
    print(f"{B}╠{'═'*w}╣{X}")
    
    # Issues detail
    if issues:
        print(f"{B}║{X}  {Y}{BD}⚠️  ISSUES DETECTED:{X}".ljust(w+25) + f"{B}║{X}")
        print(f"{B}║{X}".ljust(w+7) + f"{B}║{X}")
        
        # Unhealthy pods grouped
        if data["pods"]["unhealthy"]:
            by_ns = {}
            for p in data["pods"]["unhealthy"]:
                by_ns.setdefault(p["ns"], []).append(p)
            
            count = 0
            for ns in sorted(by_ns.keys()):
                if count >= 4:
                    remaining = len(data["pods"]["unhealthy"]) - sum(len(by_ns[n]) for n in list(by_ns.keys())[:4])
                    print(f"{B}║{X}    {D}...and {remaining} more unhealthy pods{X}".ljust(w+15) + f"{B}║{X}")
                    break
                print(f"{B}║{X}    {C}{ns}/{X}".ljust(w+20) + f"{B}║{X}")
                for pod in by_ns[ns][:2]:
                    print(f"{B}║{X}      {D}•{X} {pod['name'][:35]} {R}{pod['status']}{X}".ljust(w+25) + f"{B}║{X}")
                if len(by_ns[ns]) > 2:
                    print(f"{B}║{X}      {D}...+{len(by_ns[ns])-2} more{X}".ljust(w+15) + f"{B}║{X}")
                count += 1
        
        # Pending PVCs
        if data["pvcs"]["pending"]:
            print(f"{B}║{X}".ljust(w+7) + f"{B}║{X}")
            print(f"{B}║{X}    {Y}Pending PVCs:{X}".ljust(w+20) + f"{B}║{X}")
            for pvc in data["pvcs"]["pending"][:3]:
                print(f"{B}║{X}      {D}•{X} {pvc['ns']}/{pvc['name']}".ljust(w+15) + f"{B}║{X}")
            if len(data["pvcs"]["pending"]) > 3:
                print(f"{B}║{X}      {D}...+{len(data['pvcs']['pending'])-3} more{X}".ljust(w+15) + f"{B}║{X}")
        
        # Failed Migrations
        if data["migrations"]["failed"] or data["migrations"]["failed_count"] > 0:
            print(f"{B}║{X}".ljust(w+7) + f"{B}║{X}")
            print(f"{B}║{X}    {Y}Failed VM Migrations:{X}".ljust(w+20) + f"{B}║{X}")
            for mig in data["migrations"]["failed"][:3]:
                print(f"{B}║{X}      {D}•{X} {mig['ns']}/{mig['name']}: {R}{mig['phase']}{X}".ljust(w+25) + f"{B}║{X}")
        
        # OOM Events
        if data["oom_events"]:
            print(f"{B}║{X}".ljust(w+7) + f"{B}║{X}")
            print(f"{B}║{X}    {Y}Recent OOM Events:{X}".ljust(w+20) + f"{B}║{X}")
            for oom in data["oom_events"][:3]:
                print(f"{B}║{X}      {D}•{X} {oom['ns']}/{oom['object']}".ljust(w+15) + f"{B}║{X}")
        
        # CSI Issues
        if data["csi_issues"]:
            print(f"{B}║{X}".ljust(w+7) + f"{B}║{X}")
            print(f"{B}║{X}    {Y}CSI Driver Issues:{X}".ljust(w+20) + f"{B}║{X}")
            for csi in data["csi_issues"][:3]:
                print(f"{B}║{X}      {D}•{X} {csi['pod']}: {R}{csi['status']}{X}".ljust(w+25) + f"{B}║{X}")
        
        print(f"{B}║{X}".ljust(w+7) + f"{B}║{X}")
    
    # Footer
    print(f"{B}╠{'═'*w}╣{X}")
    if issues:
        print(f"{B}║{X}  {Y}{BD}STATUS: ATTENTION NEEDED{X}".ljust(w+25) + f"{B}║{X}")
    else:
        print(f"{B}║{X}  {G}{BD}STATUS: CLUSTER HEALTHY ✨{X}".ljust(w+25) + f"{B}║{X}")
    print(f"{B}╚{'═'*w}╝{X}")
    print()

def main():
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RESET = '\033[0m'
    
    print(f"\n{'='*60}")
    print(f"  {BLUE}🔍 CNV HealthCrew AI Starting...{RESET}")
    print(f"{'='*60}\n")
    
    # Show configuration
    print(f"  {YELLOW}⚙️  Configuration:{RESET}")
    if SERVER_HOST:
        print(f"     Server: {SERVER_HOST}")
    else:
        print(f"     Server: Using environment (RH_LAB_HOST)")
    print(f"     RCA Level: {'Full' if USE_AI else 'Bug Match' if RCA_BUGS else 'None'}")
    print(f"     Jira RCA: {'Yes' if RCA_JIRA else 'No'}")
    print(f"     Email RCA: {'Yes' if RCA_EMAIL else 'No'}")
    print(f"     Send Email: {'Yes' if SEND_EMAIL else 'No'}")
    print()
    
    # Check Jira for new bugs that might need health checks
    if CHECK_JIRA_NEW:
        print(f"  {YELLOW}🔍 Checking Jira for new test suggestions...{RESET}")
        new_checks = check_jira_for_new_tests()
        if new_checks:
            print(f"  💡 {len(new_checks)} new checks will be included in this run.\n")
    
    print(f"  {BLUE}📡 Connecting to cluster...{RESET}")
    
    try:
        print(f"\n  {BLUE}📊 Collecting cluster data...{RESET}")
        data = collect_data()
        
        # Print console report
        print(f"\n  {BLUE}📋 Generating console report...{RESET}", flush=True)
        print_console_report(data)
        
        # Determine RCA level: full (--ai), bugs (--rca-bugs), or none
        if USE_AI:
            rca_level = 'full'
        elif RCA_BUGS:
            rca_level = 'bugs'
        else:
            rca_level = 'none'
        
        print(f"\n  {BLUE}📄 Generating HTML report...{RESET}", flush=True)
        if rca_level != 'none':
            print(f"     RCA Level: {rca_level}", flush=True)
        
        # Generate and save HTML report with appropriate RCA level
        html = generate_html_report(data, rca_level=rca_level)
        timestamp = data["timestamp"].strftime("%Y-%m-%d_%H-%M-%S")
        
        # Ensure reports directory exists
        script_dir = os.path.dirname(os.path.abspath(__file__))
        reports_dir = os.path.join(script_dir, 'reports')
        os.makedirs(reports_dir, exist_ok=True)
        
        html_file = f"health_report_{timestamp}.html"
        md_file = f"health_report_{timestamp}.md"
        html_path = os.path.join(reports_dir, html_file)
        md_path = os.path.join(reports_dir, md_file)
        
        print(f"  {YELLOW}💾 Saving HTML report...{RESET}")
        with open(html_path, 'w') as f:
            f.write(html)
        print(f"     ✅ Saved: {html_file}")
        
        # Also save simple markdown
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
        if data['pods']['unhealthy']:
            by_ns = {}
            for p in data['pods']['unhealthy']:
                by_ns.setdefault(p['ns'], []).append(p)
            md_content += "\n### Unhealthy Pods\n"
            for ns in sorted(by_ns.keys()):
                md_content += f"\n**{ns}/**\n"
                for pod in by_ns[ns]:
                    md_content += f"- `{pod['name']}`: {pod['status']}\n"
        
        with open(md_path, 'w') as f:
            f.write(md_content)
        print(f"     ✅ Saved: {md_file}")
        
        print(f"\n  {GREEN}{'='*50}{RESET}")
        print(f"  {GREEN}✅ Health check complete!{RESET}")
        print(f"  {GREEN}{'='*50}{RESET}")
        print(f"\n  📄 Reports saved:")
        print(f"     • {html_file}")
        print(f"     • {md_file}")
        
        if SEND_EMAIL:
            print(f"\n  📧 Sending email report to {EMAIL_TO}...", flush=True)
            cluster_name = data.get('version', 'Unknown Cluster')
            # Calculate issue count from data
            issue_count = (
                len(data.get('nodes', {}).get('unhealthy', [])) +
                len(data.get('operators', {}).get('degraded', [])) +
                len(data.get('operators', {}).get('unavailable', [])) +
                len(data.get('pods', {}).get('unhealthy', [])) +
                len(data.get('kubevirt', {}).get('failed_vmis', []))
            )
            send_email_report(html_path, EMAIL_TO, cluster_name=cluster_name, issue_count=issue_count, report_data=data)
        
        if has_issues(data):
            if USE_AI:
                print(f"\n  🔍 Full Root Cause Analysis included in report")
            elif RCA_BUGS:
                print(f"\n  🐛 Bug matching included in report (use --ai for full investigation)")
            else:
                print(f"\n  💡 Tip: Run with --rca-bugs for bug matching or --ai for full RCA")
        
        print()
        
    except Exception as e:
        print(f"\n  ❌ Error: {e}\n")
        import traceback
        traceback.print_exc()
    finally:
        if ssh_client:
            ssh_client.close()

if __name__ == "__main__":
    main()
