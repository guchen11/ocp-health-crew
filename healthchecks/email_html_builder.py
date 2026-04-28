"""HTML body construction for CNV HealthCrew email reports."""

import os
from datetime import datetime

from healthchecks import hybrid_flags
from healthchecks.email_html_dashboard import render_email_summary_shell

DASHBOARD_BASE_URL = os.getenv("DASHBOARD_BASE_URL", "http://10.46.254.144:5000")


def create_gauge(value, total, color="#73BF69"):
    """Email-safe circular progress hint (not all clients render uniformly)."""
    if total == 0:
        percent = 100
    else:
        percent = (value / total) * 100
    return f'''<div style="width:80px;height:80px;margin:0 auto;position:relative;">
                <div style="width:80px;height:80px;border-radius:50%;border:8px solid #2a2a3e;box-sizing:border-box;"></div>
                <div style="position:absolute;top:0;left:0;width:80px;height:80px;border-radius:50%;border:8px solid {color};border-color:{color} {color} transparent transparent;box-sizing:border-box;transform:rotate({int(percent * 1.8 - 45)}deg);"></div>
            </div>'''


def collect_email_report_stats(data):
    """Normalize report_data dict for HTML and plain-text email bodies."""
    data = data or {}
    version = data.get("version", "N/A")
    nodes = data.get("nodes", {})
    healthy_nodes = len(nodes.get("healthy", []))
    unhealthy_nodes = len(nodes.get("unhealthy", []))
    operators = data.get("operators", {})
    healthy_ops = len(operators.get("healthy", []))
    degraded_ops = len(operators.get("degraded", []))
    unavailable_ops = len(operators.get("unavailable", []))
    pods = data.get("pods", {})
    healthy_pods = pods.get("healthy", 0)
    unhealthy_pods_list = pods.get("unhealthy", [])
    unhealthy_pods = len(unhealthy_pods_list)
    vms = data.get("vms", {})
    running_vms = len(vms.get("running", []))
    stopped_vms = len(vms.get("stopped", []))
    kubevirt = data.get("kubevirt", {})
    failed_vmis = kubevirt.get("failed_vmis", [])
    migrations = kubevirt.get("migrations", [])
    running_migrations = len(
        [m for m in migrations if isinstance(m, dict) and m.get("status") == "Running"]
    )
    etcd = data.get("etcd", {})
    etcd_members = etcd.get("member_count", 0) if isinstance(etcd, dict) else 0
    pvcs = data.get("pvcs", {})
    pending_pvcs = len(pvcs.get("pending", [])) if isinstance(pvcs, dict) else 0
    oom_events = len(data.get("oom_events", []))
    virt_handler = data.get("virt_handler", {})
    vh_count = (
        len(virt_handler.get("pods", [])) if isinstance(virt_handler, dict) else 0
    )
    vh_unhealthy = (
        len(virt_handler.get("unhealthy", [])) if isinstance(virt_handler, dict) else 0
    )
    return {
        "version": version,
        "nodes": nodes,
        "healthy_nodes": healthy_nodes,
        "unhealthy_nodes": unhealthy_nodes,
        "operators": operators,
        "healthy_ops": healthy_ops,
        "degraded_ops": degraded_ops,
        "unavailable_ops": unavailable_ops,
        "healthy_pods": healthy_pods,
        "unhealthy_pods_list": unhealthy_pods_list,
        "unhealthy_pods": unhealthy_pods,
        "running_vms": running_vms,
        "stopped_vms": stopped_vms,
        "failed_vmis": failed_vmis,
        "migrations": migrations,
        "running_migrations": running_migrations,
        "etcd_members": etcd_members,
        "pending_pvcs": pending_pvcs,
        "oom_events": oom_events,
        "alerts": data.get("alerts", []),
        "vh_count": vh_count,
        "vh_unhealthy": vh_unhealthy,
    }


def format_email_plain_text(stats, cluster_name, issue_count, status_text):
    """Plain-text fallback body."""
    version = stats["version"]
    lab_line = f"Lab: {hybrid_flags.LAB_NAME}\n" if hybrid_flags.LAB_NAME else ""
    total_nodes = stats["healthy_nodes"] + stats["unhealthy_nodes"]
    total_ops = (
        stats["healthy_ops"] + stats["degraded_ops"] + stats["unavailable_ops"]
    )
    total_pods = stats["healthy_pods"] + stats["unhealthy_pods"]
    total_vms = stats["running_vms"] + stats["stopped_vms"]
    return f"""CNV HealthCrew AI - Health Check Report

Cluster: {cluster_name or 'N/A'}
{lab_line}Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Version: {version}
Status: {status_text}

Nodes:      {stats['healthy_nodes']}/{total_nodes} Ready
Operators:  {stats['healthy_ops']}/{total_ops} Available
Pods:       {stats['healthy_pods']}/{total_pods} Running
VMs:        {stats['running_vms']}/{total_vms} Running
ETCD:       {stats['etcd_members']} Healthy
PVCs Pending: {stats['pending_pvcs']}
OOM Events:   {stats['oom_events']}
Migrations:   {stats['running_migrations']} Running

{'Issues Found: ' + str(issue_count) if issue_count > 0 else 'No issues detected.'}

Full HTML report attached - open in a browser for the interactive view with RCA details.
        """


def build_email_html(data, html_path, cluster_name=None, issue_count=0, stats=None):
    """Build the complete HTML email body (dashboard-style dark theme)."""
    stats = stats if stats is not None else collect_email_report_stats(data)
    version = stats["version"]
    healthy_nodes = stats["healthy_nodes"]
    unhealthy_nodes = stats["unhealthy_nodes"]
    total_nodes = healthy_nodes + unhealthy_nodes
    healthy_ops = stats["healthy_ops"]
    degraded_ops = stats["degraded_ops"]
    unavailable_ops = stats["unavailable_ops"]
    total_ops = healthy_ops + degraded_ops + unavailable_ops
    healthy_pods = stats["healthy_pods"]
    unhealthy_pods_list = stats["unhealthy_pods_list"]
    unhealthy_pods = stats["unhealthy_pods"]
    total_pods = healthy_pods + unhealthy_pods
    running_vms = stats["running_vms"]
    stopped_vms = stats["stopped_vms"]
    total_vms = running_vms + stopped_vms
    failed_vmis = stats["failed_vmis"]
    running_migrations = stats["running_migrations"]
    etcd_members = stats["etcd_members"]
    pending_pvcs = stats["pending_pvcs"]
    oom_events = stats["oom_events"]
    operators = stats["operators"]
    nodes = stats["nodes"]

    report_filename = os.path.basename(html_path)
    report_url = f"{DASHBOARD_BASE_URL}/report/{report_filename}"

    if issue_count > 0:
        status_text = "ATTENTION NEEDED"
        status_color = "#ff6b6b"
    else:
        status_text = "ALL SYSTEMS HEALTHY"
        status_color = "#73BF69"

    unhealthy_pods_html = ""
    if unhealthy_pods_list:
        pods_rows = ""
        for pod in unhealthy_pods_list[:6]:
            if isinstance(pod, dict):
                pod_name = pod.get("name", "unknown")
                pod_ns = pod.get("namespace", "")
                pod_status = pod.get("status", "Error")
                if len(pod_name) > 40:
                    pod_name = pod_name[:37] + "..."
                status_bg = (
                    "#ff6b6b"
                    if "Error" in pod_status or "Crash" in pod_status
                    else "#ffaa00"
                )
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

    html_content = render_email_summary_shell(
        status_color=status_color,
        status_text=status_text,
        cluster_name=cluster_name,
        version=version,
        report_url=report_url,
        unhealthy_pods_html=unhealthy_pods_html,
        healthy_nodes=healthy_nodes,
        unhealthy_nodes=unhealthy_nodes,
        total_nodes=total_nodes,
        healthy_ops=healthy_ops,
        degraded_ops=degraded_ops,
        unavailable_ops=unavailable_ops,
        total_ops=total_ops,
        healthy_pods=healthy_pods,
        unhealthy_pods=unhealthy_pods,
        total_pods=total_pods,
        running_vms=running_vms,
        total_vms=total_vms,
        etcd_members=etcd_members,
        pending_pvcs=pending_pvcs,
        oom_events=oom_events,
        running_migrations=running_migrations,
    )

    findings_html = ""
    degraded_list = operators.get("degraded", [])
    unavailable_list = operators.get("unavailable", [])
    if degraded_list or unavailable_list:
        op_rows = ""
        for op in degraded_list:
            op_rows += f'<tr><td style="padding:8px 12px;color:#e0e0e0;font-size:12px;font-family:monospace;border-bottom:1px solid #2a2a3e;">{op}</td><td style="padding:8px 12px;text-align:right;border-bottom:1px solid #2a2a3e;"><span style="background:#FF9830;color:#fff;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;">DEGRADED</span></td></tr>'
        for op in unavailable_list:
            op_rows += f'<tr><td style="padding:8px 12px;color:#e0e0e0;font-size:12px;font-family:monospace;border-bottom:1px solid #2a2a3e;">{op}</td><td style="padding:8px 12px;text-align:right;border-bottom:1px solid #2a2a3e;"><span style="background:#F2495C;color:#fff;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;">UNAVAILABLE</span></td></tr>'
        findings_html += f'''
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#1e1e2e;border-radius:12px;margin-bottom:16px;overflow:hidden;">
                <tr><td style="padding:14px 20px;border-bottom:1px solid #2a2a3e;"><span style="color:#FF9830;font-size:13px;font-weight:600;">⚙️ DEGRADED CLUSTER OPERATORS ({len(degraded_list) + len(unavailable_list)})</span></td></tr>
                <tr><td style="padding:0;"><table width="100%" cellpadding="0" cellspacing="0">{op_rows}</table></td></tr>
            </table>'''

    check_items = [
        ("🖥️", "Nodes", f"{healthy_nodes}/{total_nodes} Ready", unhealthy_nodes == 0),
        (
            "⚙️",
            "Cluster Operators",
            f"{healthy_ops}/{total_ops} Available",
            degraded_ops + unavailable_ops == 0,
        ),
        ("📦", "Pods", f"{healthy_pods}/{total_pods} Running", unhealthy_pods == 0),
        ("🗄️", "etcd", f"{etcd_members} members healthy", True),
        (
            "💾",
            "PVCs",
            f"{pending_pvcs} pending" if pending_pvcs > 0 else "All Bound",
            pending_pvcs == 0,
        ),
        ("🔄", "VM Migrations", f"{running_migrations} running", True),
        (
            "💥",
            "OOM Events",
            f"{oom_events}" if oom_events > 0 else "None",
            oom_events == 0,
        ),
    ]
    if stats["vh_count"] > 0:
        check_items.append(
            (
                "🔧",
                "virt-handler",
                f"{stats['vh_count'] - stats['vh_unhealthy']}/{stats['vh_count']} healthy",
                stats["vh_unhealthy"] == 0,
            )
        )

    check_rows = ""
    for icon, name, result, is_ok in check_items:
        status_icon = "✅" if is_ok else "❌"
        result_color = "#73BF69" if is_ok else "#FF9830"
        check_rows += f'''<tr>
                <td style="padding:10px 16px;border-bottom:1px solid #2a2a3e;font-size:14px;width:30px;">{status_icon}</td>
                <td style="padding:10px 8px;border-bottom:1px solid #2a2a3e;color:#e0e0e0;font-size:13px;font-weight:600;">{icon} {name}</td>
                <td style="padding:10px 16px;border-bottom:1px solid #2a2a3e;text-align:right;color:{result_color};font-size:13px;font-weight:600;">{result}</td>
            </tr>'''

    findings_html += f'''
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#1e1e2e;border-radius:12px;margin-bottom:16px;overflow:hidden;">
                <tr><td style="padding:14px 20px;border-bottom:1px solid #2a2a3e;"><span style="color:#5794F2;font-size:13px;font-weight:600;">📋 HEALTH CHECK RESULTS</span></td></tr>
                <tr><td style="padding:0;"><table width="100%" cellpadding="0" cellspacing="0">{check_rows}</table></td></tr>
            </table>'''

    unhealthy_node_list = nodes.get("unhealthy", [])
    if unhealthy_node_list:
        node_rows = ""
        for n in unhealthy_node_list[:10]:
            n_name = n.get("name", n) if isinstance(n, dict) else str(n)
            n_status = n.get("status", "NotReady") if isinstance(n, dict) else "NotReady"
            node_rows += f'<tr><td style="padding:8px 12px;color:#e0e0e0;font-size:12px;font-family:monospace;border-bottom:1px solid #2a2a3e;">{n_name}</td><td style="padding:8px 12px;text-align:right;border-bottom:1px solid #2a2a3e;"><span style="background:#F2495C;color:#fff;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;">{n_status}</span></td></tr>'
        findings_html += f'''
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#1e1e2e;border-radius:12px;margin-bottom:16px;overflow:hidden;">
                <tr><td style="padding:14px 20px;border-bottom:1px solid #2a2a3e;"><span style="color:#F2495C;font-size:13px;font-weight:600;">🖥️ UNHEALTHY NODES ({len(unhealthy_node_list)})</span></td></tr>
                <tr><td style="padding:0;"><table width="100%" cellpadding="0" cellspacing="0">{node_rows}</table></td></tr>
            </table>'''

    alerts = stats["alerts"]
    if alerts and isinstance(alerts, list) and len(alerts) > 0:
        alert_rows = ""
        for a in alerts[:15]:
            if isinstance(a, dict):
                a_name = a.get("name", a.get("alertname", "Unknown"))
                a_sev = a.get("severity", "warning")
            elif isinstance(a, str):
                a_name = a
                a_sev = "warning"
            else:
                continue
            sev_bg = "#F2495C" if a_sev == "critical" else "#FF9830"
            alert_rows += f'<tr><td style="padding:8px 12px;color:#e0e0e0;font-size:12px;border-bottom:1px solid #2a2a3e;">{a_name}</td><td style="padding:8px 12px;text-align:right;border-bottom:1px solid #2a2a3e;"><span style="background:{sev_bg};color:#fff;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;">{a_sev.upper()}</span></td></tr>'
        if alert_rows:
            findings_html += f'''
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#1e1e2e;border-radius:12px;margin-bottom:16px;overflow:hidden;">
                <tr><td style="padding:14px 20px;border-bottom:1px solid #2a2a3e;"><span style="color:#FF9830;font-size:13px;font-weight:600;">🔔 FIRING ALERTS ({len(alerts)})</span></td></tr>
                <tr><td style="padding:0;"><table width="100%" cellpadding="0" cellspacing="0">{alert_rows}</table></td></tr>
            </table>'''

    if failed_vmis:
        vmi_rows = ""
        for v in failed_vmis[:10]:
            v_name = v.get("name", v) if isinstance(v, dict) else str(v)
            v_ns = v.get("namespace", "") if isinstance(v, dict) else ""
            v_display = f"{v_ns}/{v_name}" if v_ns else v_name
            vmi_rows += f'<tr><td style="padding:8px 12px;color:#e0e0e0;font-size:12px;font-family:monospace;border-bottom:1px solid #2a2a3e;">{v_display}</td><td style="padding:8px 12px;text-align:right;border-bottom:1px solid #2a2a3e;"><span style="background:#F2495C;color:#fff;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600;">FAILED</span></td></tr>'
        findings_html += f'''
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#1e1e2e;border-radius:12px;margin-bottom:16px;overflow:hidden;">
                <tr><td style="padding:14px 20px;border-bottom:1px solid #2a2a3e;"><span style="color:#F2495C;font-size:13px;font-weight:600;">🗄️ FAILED VMIs ({len(failed_vmis)})</span></td></tr>
                <tr><td style="padding:0;"><table width="100%" cellpadding="0" cellspacing="0">{vmi_rows}</table></td></tr>
            </table>'''

    html_content = html_content.replace(
        "<!-- CTA Button -->",
        f'''<!-- Detailed Findings -->
                    <tr>
                        <td style="padding:0 24px 10px;">
                            {findings_html}
                            {unhealthy_pods_html}
                        </td>
                    </tr>
                    <!-- CTA Button -->''',
    )
    html_content = html_content.replace(
        f"""                    <!-- Unhealthy Pods Section -->
                    <tr>
                        <td style="padding:0 24px 20px;">
                            {unhealthy_pods_html}
                        </td>
                    </tr>""",
        "",
    )

    return html_content
