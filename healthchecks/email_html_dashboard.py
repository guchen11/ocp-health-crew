"""Large static HTML shell for email summary (table layout for clients)."""

from datetime import datetime

from healthchecks import hybrid_flags


def render_email_summary_shell(
    *,
    status_color,
    status_text,
    cluster_name,
    version,
    report_url,
    unhealthy_pods_html,
    healthy_nodes,
    unhealthy_nodes,
    total_nodes,
    healthy_ops,
    degraded_ops,
    unavailable_ops,
    total_ops,
    healthy_pods,
    unhealthy_pods,
    total_pods,
    running_vms,
    total_vms,
    etcd_members,
    pending_pvcs,
    oom_events,
    running_migrations,
):
    """Return the main email HTML table shell before findings injection."""
    return f'''<!DOCTYPE html>
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
                                    <td style="color:#ffffff;font-size:20px;font-weight:600;padding-bottom:4px;">
                                        {hybrid_flags.LAB_NAME or cluster_name or 'Cluster Health Report'}
                                    </td>
                                </tr>
                                {'<tr><td style="padding-bottom:8px;"><span style="color:#8b8fa3;font-size:13px;">' + cluster_name + '</span></td></tr>' if hybrid_flags.LAB_NAME and cluster_name else ''}
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
                                        <a href="{report_url}" style="display:inline-block;padding:14px 32px;background:linear-gradient(135deg,#73BF69 0%,#5ba350 100%);border-radius:8px;color:#ffffff;font-weight:600;font-size:14px;text-decoration:none;">📊 View Full Report on Dashboard</a>
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
