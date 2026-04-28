"""
Email-safe HTML for CNV scenario reports.
"""

from .cnv_report import _get_scenario_meta, strip_ansi
from .cnv_report_html_helpers import (
    _fmt_ms,
    _VMI_STAGE_ICONS,
    _VMI_STAGE_LABELS,
    _VMI_STAGE_ORDER,
)


def _build_email_detail_sections(results, meta):
    """Build inline-styled detail sections for the email report."""
    iteration_data = results.get("iteration_data", {})
    tests = results.get("tests", [])
    if not iteration_data:
        return ""

    sections = ""
    for t in tests:
        tname = t["name"]
        idata = iteration_data.get(tname, {})
        if not idata:
            continue

        m = meta.get(tname, {})
        icon = m.get("icon", "🔥")
        display_name = m.get("name", tname)

        content = ""

        # VMI Latency (compact email table)
        vmi_lat = idata.get("vmi_latency")
        if vmi_lat:
            by_name = {d["quantileName"]: d for d in vmi_lat}
            rows = ""
            for stage in _VMI_STAGE_ORDER:
                if stage not in by_name:
                    continue
                d = by_name[stage]
                label = _VMI_STAGE_LABELS.get(stage, stage)
                s_icon = _VMI_STAGE_ICONS.get(stage, "⚙️")
                p50 = d.get("P50", 0)
                p99 = d.get("P99", 0)
                color = "#73BF69" if p99 < 30000 else "#FF9830" if p99 < 60000 else "#F2495C"
                rows += f'''<tr style="border-bottom:1px solid #21262d;">
                    <td style="padding:6px 10px;font-size:12px;color:#c9d1d9;">{s_icon} {label}</td>
                    <td style="padding:6px 10px;text-align:right;font-size:12px;color:{color};font-weight:600;">{_fmt_ms(p50)}</td>
                    <td style="padding:6px 10px;text-align:right;font-size:12px;color:{color};font-weight:600;">{_fmt_ms(p99)}</td>
                </tr>'''
            content += f'''
            <div style="font-size:11px;font-weight:600;color:#f97316;text-transform:uppercase;letter-spacing:1px;margin:12px 0 6px;">🏎️ VM Boot Latency</div>
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#0d1117;border:1px solid #30363d;border-radius:6px;overflow:hidden;">
            <tr style="border-bottom:1px solid #30363d;">
                <th style="padding:6px 10px;text-align:left;font-size:10px;font-weight:600;color:#8b949e;">Stage</th>
                <th style="padding:6px 10px;text-align:right;font-size:10px;font-weight:600;color:#8b949e;">P50</th>
                <th style="padding:6px 10px;text-align:right;font-size:10px;font-weight:600;color:#8b949e;">P99</th>
            </tr>
            {rows}
            </table>'''

        # PVC Latency (compact)
        pvc_lat = idata.get("pvc_latency")
        if pvc_lat:
            pvc_rows = ""
            for d in pvc_lat:
                name = d.get("quantileName", "?")
                p50 = d.get("P50", 0)
                p99 = d.get("P99", 0)
                pvc_rows += f'''<tr style="border-bottom:1px solid #21262d;">
                    <td style="padding:6px 10px;font-size:12px;color:#c9d1d9;">{name}</td>
                    <td style="padding:6px 10px;text-align:right;font-size:12px;">{_fmt_ms(p50)}</td>
                    <td style="padding:6px 10px;text-align:right;font-size:12px;">{_fmt_ms(p99)}</td>
                </tr>'''
            content += f'''
            <div style="font-size:11px;font-weight:600;color:#f97316;text-transform:uppercase;letter-spacing:1px;margin:12px 0 6px;">💾 PVC Latency</div>
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#0d1117;border:1px solid #30363d;border-radius:6px;overflow:hidden;">
            <tr style="border-bottom:1px solid #30363d;">
                <th style="padding:6px 10px;text-align:left;font-size:10px;font-weight:600;color:#8b949e;">Phase</th>
                <th style="padding:6px 10px;text-align:right;font-size:10px;font-weight:600;color:#8b949e;">P50</th>
                <th style="padding:6px 10px;text-align:right;font-size:10px;font-weight:600;color:#8b949e;">P99</th>
            </tr>
            {pvc_rows}
            </table>'''

        # Validation checks (compact)
        validation = idata.get("validation")
        if validation:
            val_items = ""
            for v in validation.get("validations", []):
                vstatus = v.get("status", "UNKNOWN")
                msg = v.get("message", "")
                v_icon = "✅" if vstatus == "PASS" else "❌"
                val_items += f'<div style="padding:4px 0;font-size:12px;color:#c9d1d9;">{v_icon} {msg}</div>'
            overall = validation.get("overallStatus", "UNKNOWN")
            o_icon = "✅" if overall == "SUCCESS" else "❌"
            content += f'''
            <div style="font-size:11px;font-weight:600;color:#f97316;text-transform:uppercase;letter-spacing:1px;margin:12px 0 6px;">🔍 Validation ({o_icon} {overall})</div>
            <div style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 12px;">
            {val_items}
            </div>'''

        if content:
            sections += f'''
<!-- Detail: {display_name} -->
<tr><td style="padding:0 32px 16px;">
<div style="font-size:13px;font-weight:600;color:#e6edf3;margin-bottom:8px;">{icon} {display_name}</div>
{content}
</td></tr>'''

    return sections


def _build_email_env_row(cluster_info):
    """Build an inline-styled cluster environment row for the email report."""
    if not cluster_info:
        return ""

    def _cell(label, value):
        return (
            f'<td style="padding:8px;background:#0d111788;border-radius:6px;text-align:center;border:1px solid #30363d;">'
            f'<div style="font-size:10px;color:#8b949e;text-transform:uppercase;margin-bottom:2px;">{label}</div>'
            f'<div style="font-size:14px;font-weight:600;color:#e6edf3;">{value}</div>'
            f'</td><td width="4"></td>'
        )

    ocp = cluster_info.get("ocp_version", "N/A")
    cnv = cluster_info.get("cnv_version", "N/A")
    net = cluster_info.get("network_type", "N/A")
    nodes = cluster_info.get("nodes_total", 0)
    workers = cluster_info.get("nodes_workers", 0)
    node_str = f"{nodes} ({workers}w)" if nodes else "N/A"

    cells = _cell("OCP", ocp) + _cell("CNV", cnv) + _cell("Network", net) + _cell("Nodes", node_str)

    return (
        '<!-- Cluster Environment -->\n'
        '<tr><td style="padding:0 32px 16px;">\n'
        '<div style="font-size:13px;font-weight:600;color:#8b949e;margin-bottom:8px;">CLUSTER ENVIRONMENT</div>\n'
        f'<table width="100%" cellpadding="0" cellspacing="0"><tr>{cells}</tr></table>\n'
        '</td></tr>'
    )


def generate_cnv_email_html(results, build_num=0, build_name="",
                             status="success", status_text="All Passed",
                             duration="", mode="sanity", checks=None,
                             output="", cluster_info=None,
                             dashboard_base_url=""):
    """Generate an email-safe HTML body for CNV scenario results.

    Uses inline styles and table layout for maximum email client compatibility.
    """
    checks = checks or []
    meta = _get_scenario_meta()
    tests = results.get("tests", [])
    passed = results.get("passed", 0)
    failed = results.get("failed", 0)
    total = results.get("total", 0) or len(tests)

    status_colors = {
        'success': '#73BF69',
        'unstable': '#FF9830',
        'failed': '#F2495C',
    }
    status_emoji = {'success': '✅', 'unstable': '⚠️', 'failed': '❌'}.get(status, '🔵')
    color = status_colors.get(status, '#5794F2')

    # Build per-test result rows
    test_rows = ""
    for t in tests:
        m = meta.get(t["name"], {})
        icon = m.get("icon", "🔥")
        display_name = m.get("name", t["name"])
        is_pass = t["status"] == "PASS"
        s_color = "#73BF69" if is_pass else "#F2495C"
        s_emoji = "✅" if is_pass else "❌"
        s_label = "PASS" if is_pass else "FAIL"
        dur = t.get("duration_str", "N/A")
        val = t.get("validation", "N/A")

        test_rows += f'''
<tr style="border-bottom:1px solid #21262d;">
    <td style="padding:10px 14px;font-size:13px;color:#c9d1d9;">{icon} {display_name}</td>
    <td style="padding:10px 14px;text-align:center;">
        <span style="display:inline-block;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700;background:{s_color}22;color:{s_color};">{s_emoji} {s_label}</span>
    </td>
    <td style="padding:10px 14px;font-size:12px;color:#8b949e;text-align:center;">{val}</td>
    <td style="padding:10px 14px;font-size:12px;color:#8b949e;text-align:right;">{dur}</td>
</tr>'''

    # Output excerpt (filter out iteration data block)
    output_lines = output.strip().split('\n') if output else []
    summary_start = None
    for i, line in enumerate(output_lines):
        if any(k in line for k in ['Results Summary', 'SUMMARY', 'scenarios complete', 'CNV Scenarios complete']):
            summary_start = max(0, i - 2)
            break
    if summary_start is not None:
        excerpt_lines = output_lines[summary_start:]
    else:
        excerpt_lines = output_lines[-30:]

    clean_excerpt = []
    in_data_block = False
    for l in excerpt_lines:
        if '__CNV_ITERATION_DATA_START__' in l or '__CNV_CLUSTER_INFO_START__' in l:
            in_data_block = True
            continue
        if '__CNV_ITERATION_DATA_END__' in l or '__CNV_CLUSTER_INFO_END__' in l:
            in_data_block = False
            continue
        if not in_data_block:
            clean_excerpt.append(l)

    html_summary = '<br>'.join(
        strip_ansi(l).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        for l in clean_excerpt
    )

    subject = f'{status_emoji} CNV Scenarios #{build_num} — {status_text}'
    if build_name:
        subject += f' ({build_name})'

    html = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0d1117;color:#c9d1d9;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0d1117;padding:20px 0;">
<tr><td align="center">
<table width="680" cellpadding="0" cellspacing="0" style="background:#161b22;border-radius:12px;overflow:hidden;border:1px solid #30363d;">

<!-- Header -->
<tr><td style="background:linear-gradient(135deg,#1a1a2e,#16213e);padding:28px 32px;">
<table width="100%"><tr>
<td><span style="font-size:28px;">🔥</span></td>
<td style="padding-left:14px;">
<div style="font-size:22px;font-weight:700;color:#e6edf3;">CNV Scenarios Report</div>
<div style="font-size:13px;color:#8b949e;margin-top:4px;">Build #{build_num} &middot; {duration}</div>
</td>
<td align="right">
<div style="display:inline-block;padding:8px 20px;border-radius:20px;background:{color}22;border:1px solid {color}44;">
<span style="font-size:16px;font-weight:700;color:{color};">{status_emoji} {status_text}</span>
</div>
</td>
</tr></table>
</td></tr>

<!-- Summary Stats -->
<tr><td style="padding:24px 32px;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr>
<td width="25%" style="padding:12px 8px;background:#0d111788;border-radius:8px;text-align:center;border:1px solid #30363d;">
<div style="font-size:28px;font-weight:700;color:{color};">{status_text}</div>
<div style="font-size:10px;color:#8b949e;margin-top:4px;text-transform:uppercase;">Status</div>
</td>
<td width="4"></td>
<td width="25%" style="padding:12px 8px;background:#0d111788;border-radius:8px;text-align:center;border:1px solid #30363d;">
<div style="font-size:28px;font-weight:700;color:#73BF69;">{passed}</div>
<div style="font-size:10px;color:#8b949e;margin-top:4px;text-transform:uppercase;">Passed</div>
</td>
<td width="4"></td>
<td width="25%" style="padding:12px 8px;background:#0d111788;border-radius:8px;text-align:center;border:1px solid #30363d;">
<div style="font-size:28px;font-weight:700;color:{"#F2495C" if failed > 0 else "#73BF69"};">{failed}</div>
<div style="font-size:10px;color:#8b949e;margin-top:4px;text-transform:uppercase;">Failed</div>
</td>
<td width="4"></td>
<td width="25%" style="padding:12px 8px;background:#0d111788;border-radius:8px;text-align:center;border:1px solid #30363d;">
<div style="font-size:28px;font-weight:700;color:#e6edf3;">{mode.upper()}</div>
<div style="font-size:10px;color:#8b949e;margin-top:4px;text-transform:uppercase;">Mode</div>
</td>
</tr>
</table>
</td></tr>

{_build_email_env_row(cluster_info)}

<!-- Per-Test Results Table -->
<tr><td style="padding:0 32px 20px;">
<div style="font-size:13px;font-weight:600;color:#8b949e;margin-bottom:10px;">SCENARIO RESULTS</div>
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0d1117;border:1px solid #30363d;border-radius:8px;overflow:hidden;">
<tr style="border-bottom:1px solid #30363d;">
    <th style="padding:10px 14px;text-align:left;font-size:11px;font-weight:600;color:#8b949e;text-transform:uppercase;">Scenario</th>
    <th style="padding:10px 14px;text-align:center;font-size:11px;font-weight:600;color:#8b949e;text-transform:uppercase;">Status</th>
    <th style="padding:10px 14px;text-align:center;font-size:11px;font-weight:600;color:#8b949e;text-transform:uppercase;">Validation</th>
    <th style="padding:10px 14px;text-align:right;font-size:11px;font-weight:600;color:#8b949e;text-transform:uppercase;">Duration</th>
</tr>
{test_rows}
</table>
</td></tr>

{_build_email_detail_sections(results, meta)}

<!-- Output Summary -->
<tr><td style="padding:0 32px 24px;">
<div style="font-size:13px;font-weight:600;color:#8b949e;margin-bottom:10px;">OUTPUT SUMMARY</div>
<div style="background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:16px 18px;font-family:monospace;font-size:12px;line-height:1.6;color:#c9d1d9;max-height:400px;overflow:auto;">
{html_summary}
</div>
</td></tr>

<!-- CTA Button -->
{f"""<tr><td style="padding:0 32px 24px;text-align:center;">
<a href="{dashboard_base_url}/job/{build_num}" style="display:inline-block;padding:14px 32px;background:linear-gradient(135deg,#73BF69 0%,#5ba350 100%);border-radius:8px;color:#ffffff;font-weight:600;font-size:14px;text-decoration:none;">📊 View Full Report on Dashboard</a>
</td></tr>""" if dashboard_base_url and build_num else ""}

<!-- Footer -->
<tr><td style="padding:20px 32px;background:#0d111788;border-top:1px solid #30363d;text-align:center;">
<span style="font-size:12px;color:#8b949e;">
🔥 CNV HealthCrew &middot; Automated scenario report
</span>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>'''

    return subject, html
