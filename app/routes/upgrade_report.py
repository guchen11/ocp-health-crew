"""Generate HTML reports and email notifications for upgrade pipelines."""
import logging
import os
import smtplib
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config.settings import Config

log = logging.getLogger(__name__)

REPORTS_DIR = Config.REPORTS_DIR


def generate_upgrade_report(run):
    """Generate an HTML report for an UpgradeRun and save to reports dir.

    Returns the filename (not full path).
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)
    ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    filename = f'upgrade_report_{run.id}_{ts}.html'
    filepath = os.path.join(REPORTS_DIR, filename)

    rd = run.report_data or {}
    steps = rd.get('steps', [])
    pipeline_name = rd.get('pipeline_name', run.operator_name)
    total_duration = rd.get('total_duration', '')
    status = rd.get('status', run.status)
    success = status == 'completed'

    html = _build_html(run, pipeline_name, steps, total_duration, success)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html)

    return filename


def _status_badge(status):
    colors = {
        'success': ('#166534', '#dcfce7'),
        'completed': ('#166534', '#dcfce7'),
        'failed': ('#991b1b', '#fef2f2'),
        'error': ('#991b1b', '#fef2f2'),
        'running': ('#1e40af', '#dbeafe'),
        'skipped': ('#6b7280', '#f3f4f6'),
    }
    fg, bg = colors.get(status, ('#6b7280', '#f3f4f6'))
    return f'<span style="background:{bg};color:{fg};padding:3px 12px;border-radius:12px;font-size:12px;font-weight:600;">{status.upper()}</span>'


def _step_icon(stype):
    icons = {
        'upgrade_olm': '🔄',
        'upgrade_cvo': '🔄',
        'test_suite': '🧪',
        'template': '📋',
        'health_check': '🩺',
    }
    return icons.get(stype, '▶')


def _step_rows(steps):
    rows = ''
    for s in steps:
        icon = _step_icon(s.get('type', ''))
        badge = _status_badge(s.get('status', 'pending'))
        dur = s.get('duration', '')
        started = s.get('started_at', '')
        rows += f"""
        <tr>
            <td style="padding:12px 16px;border-bottom:1px solid #e5e7eb;font-weight:700;text-align:center;width:40px;">{s.get('index', '')}</td>
            <td style="padding:12px 16px;border-bottom:1px solid #e5e7eb;">{icon} {s.get('label', s.get('type', ''))}</td>
            <td style="padding:12px 16px;border-bottom:1px solid #e5e7eb;">{badge}</td>
            <td style="padding:12px 16px;border-bottom:1px solid #e5e7eb;font-family:monospace;font-size:13px;">{dur}</td>
            <td style="padding:12px 16px;border-bottom:1px solid #e5e7eb;font-size:12px;color:#6b7280;">{started}</td>
        </tr>"""
        if s.get('error'):
            rows += f"""
        <tr>
            <td></td>
            <td colspan="4" style="padding:6px 16px;border-bottom:1px solid #e5e7eb;color:#991b1b;font-size:12px;">Error: {s['error']}</td>
        </tr>"""
    return rows


def _duration_bar(steps):
    if not steps:
        return ''
    total = sum(s.get('duration_s', 0) for s in steps) or 1
    bars = ''
    for s in steps:
        pct = max(2, int(s.get('duration_s', 0) / total * 100))
        color = {
            'success': '#22c55e', 'failed': '#ef4444', 'error': '#ef4444',
        }.get(s.get('status', ''), '#94a3b8')
        label = s.get('label', '')[:20]
        bars += f'<div style="width:{pct}%;background:{color};height:28px;display:flex;align-items:center;justify-content:center;font-size:10px;color:white;overflow:hidden;white-space:nowrap;" title="{s.get("label","")} ({s.get("duration","")})">{label}</div>'
    return f'<div style="display:flex;border-radius:6px;overflow:hidden;margin:16px 0;">{bars}</div>'


def _upgrade_cards(rd):
    """Build HTML cards for each operator that was upgraded."""
    upgrades = rd.get('upgrades', [])
    if not upgrades:
        return ''
    cards = ''
    for u in upgrades:
        op = u.get('operator', 'Unknown')
        ns = u.get('namespace', '')
        from_v = u.get('from_version', '')
        to_v = u.get('to_version', '')
        status = u.get('status', 'unknown')
        ok = status == 'success'
        bg = '#dcfce7' if ok else '#fef2f2'
        border = '#22c55e' if ok else '#ef4444'
        icon = '&#x2705;' if ok else '&#x274C;'
        from_short = from_v.split('.')[-1] if '.' in from_v else from_v
        to_short = to_v.split('.')[-1] if '.' in to_v else to_v
        cards += f"""
        <div style="background:{bg};border:1px solid {border};border-radius:10px;padding:18px 22px;margin-bottom:12px;">
            <div style="font-size:17px;font-weight:700;margin-bottom:8px;">{icon} {op}</div>
            <div style="display:flex;gap:24px;flex-wrap:wrap;font-size:13px;">
                <div><span style="color:#6b7280;">Namespace:</span> <strong>{ns}</strong></div>
                <div><span style="color:#6b7280;">Status:</span> <strong style="color:{'#166534' if ok else '#991b1b'};">{status.upper()}</strong></div>
            </div>
            <div style="margin-top:10px;background:{'#f0fdf4' if ok else '#fff5f5'};border-radius:8px;padding:12px 16px;font-family:monospace;font-size:12px;">
                <div style="color:#6b7280;margin-bottom:4px;">Version Change</div>
                <div><span style="color:#991b1b;">{from_v}</span></div>
                <div style="color:#6b7280;margin:2px 0;">&#x2193;</div>
                <div><span style="color:#166534;font-weight:700;">{to_v}</span></div>
            </div>
        </div>"""
    return f'<div class="section-title">&#x1F504; Operators Upgraded</div>{cards}'


def _build_html(run, pipeline_name, steps, total_duration, success):
    status_word = 'SUCCESS' if success else 'FAILED'
    status_emoji = '&#x2705;' if success else '&#x274C;'
    status_bg = '#dcfce7' if success else '#fef2f2'
    status_color = '#166534' if success else '#991b1b'
    status_border = '#22c55e' if success else '#ef4444'

    started = run.upgrade_started_at.strftime('%Y-%m-%d %H:%M:%S UTC') if run.upgrade_started_at else ''
    finished = run.upgrade_finished_at.strftime('%Y-%m-%d %H:%M:%S UTC') if run.upgrade_finished_at else ''

    step_html = _step_rows(steps)
    bar_html = _duration_bar(steps)
    rd = run.report_data or {}
    upgrade_html = _upgrade_cards(rd)

    n_upgrade = sum(1 for s in steps if s.get('type', '').startswith('upgrade'))
    n_test = sum(1 for s in steps if s.get('type') in ('test_suite', 'template', 'health_check'))
    n_pass = sum(1 for s in steps if s.get('status') == 'success')
    n_fail = sum(1 for s in steps if s.get('status') in ('failed', 'error'))

    log_html = (run.log or '').replace('<', '&lt;').replace('>', '&gt;')

    return f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<title>Upgrade Report: {pipeline_name} - {status_word}</title>
<style>
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; margin:0; background:#f9fafb; color:#111827; }}
.container {{ max-width:900px; margin:0 auto; padding:24px; }}
.header {{ background:linear-gradient(135deg,#1e3a5f,#2563eb); color:white; padding:28px 32px; border-radius:12px 12px 0 0; }}
.header h1 {{ margin:0; font-size:22px; }}
.header .sub {{ color:rgba(255,255,255,0.8); font-size:14px; margin-top:6px; }}
.content {{ background:white; padding:28px 32px; border:1px solid #e5e7eb; }}
.status-banner {{ background:{status_bg}; border-left:4px solid {status_border}; padding:18px 24px; border-radius:0 8px 8px 0; margin-bottom:24px; }}
.status-banner .title {{ font-size:20px; font-weight:700; color:{status_color}; }}
.status-banner .meta {{ color:{status_color}; font-size:13px; margin-top:4px; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ padding:10px 16px; text-align:left; font-size:11px; text-transform:uppercase; color:#6b7280; border-bottom:2px solid #e5e7eb; background:#f9fafb; }}
.section-title {{ font-size:16px; font-weight:700; margin:28px 0 12px 0; padding-bottom:8px; border-bottom:2px solid #e5e7eb; }}
.footer {{ background:#f9fafb; padding:16px 32px; border-radius:0 0 12px 12px; border:1px solid #e5e7eb; border-top:none; font-size:12px; color:#6b7280; }}
pre {{ background:#f3f4f6; padding:16px; border-radius:8px; font-size:11px; white-space:pre-wrap; word-wrap:break-word; max-height:500px; overflow-y:auto; line-height:1.5; }}
.info-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(160px, 1fr)); gap:16px; margin-bottom:24px; }}
.info-box {{ padding:12px 16px; border:1px solid #e5e7eb; border-radius:8px; }}
.info-box .label {{ font-size:11px; text-transform:uppercase; color:#6b7280; margin-bottom:4px; }}
.info-box .value {{ font-size:15px; font-weight:600; }}
.stat-pass {{ color:#166534; }}
.stat-fail {{ color:#991b1b; }}
</style>
</head><body>
<div class="container">
    <div class="header">
        <h1>&#x1F504; Upgrade Pipeline Report</h1>
        <div class="sub">{pipeline_name} - Run #{run.id}</div>
    </div>
    <div class="content">
        <div class="status-banner">
            <div class="title">{status_emoji} {status_word}</div>
            <div class="meta">Duration: {total_duration} | {len(steps)} steps ({n_upgrade} upgrade, {n_test} test) | Run #{run.id}</div>
        </div>

        <div class="info-grid">
            <div class="info-box">
                <div class="label">Started</div>
                <div class="value">{started}</div>
            </div>
            <div class="info-box">
                <div class="label">Finished</div>
                <div class="value">{finished}</div>
            </div>
            <div class="info-box">
                <div class="label">Duration</div>
                <div class="value">{total_duration}</div>
            </div>
            <div class="info-box">
                <div class="label">Steps Passed</div>
                <div class="value stat-pass">{n_pass} / {len(steps)}</div>
            </div>
            <div class="info-box">
                <div class="label">Steps Failed</div>
                <div class="value {'stat-fail' if n_fail else ''}">{n_fail}</div>
            </div>
        </div>

        {upgrade_html}

        <div class="section-title">&#x1F4CB; Pipeline Steps</div>
        {bar_html}
        <table>
            <tr>
                <th>#</th>
                <th>Step</th>
                <th>Status</th>
                <th>Duration</th>
                <th>Started</th>
            </tr>
            {step_html}
        </table>

        <div class="section-title">&#x1F4DD; Pipeline Log</div>
        <pre>{log_html}</pre>
    </div>
    <div class="footer">
        CNV HealthCrew AI | Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    </div>
</div>
</body></html>"""


def send_pipeline_email(run, steps, success, duration):
    """Send an HTML email with pipeline summary and attached report."""
    recipient = Config.DEFAULT_EMAIL
    smtp_server = os.getenv("SMTP_SERVER", "smtp.corp.redhat.com")
    smtp_port = int(os.getenv("SMTP_PORT", "25"))
    email_from = os.getenv("EMAIL_FROM", "cnv-healthcrew@redhat.com")

    status_emoji = "+" if success else "X"
    status_word = "SUCCESS" if success else "FAILED"

    rd = run.report_data or {}
    upgraded_ops = [u.get('operator', '') for u in rd.get('upgrades', []) if u.get('namespace')]
    op_label = ', '.join(upgraded_ops) if upgraded_ops else run.operator_name
    ts = run.upgrade_started_at.strftime('%Y-%m-%d %H:%M') if run.upgrade_started_at else ''
    subject = f"[CNV HealthCrew] {status_word}: {op_label} - {ts}"

    step_rows = ""
    for i, s in enumerate(steps):
        label = s.get('label', s['type'])
        stype = s['type']
        badge_color = '#f59e0b' if 'upgrade' in stype else '#22c55e' if stype == 'test_suite' else '#3b82f6' if stype == 'template' else '#6b7280'
        icon = _step_icon(stype)
        step_rows += f"""
        <tr>
            <td style="padding:10px 14px;border-bottom:1px solid #e5e7eb;font-weight:600;">{i+1}</td>
            <td style="padding:10px 14px;border-bottom:1px solid #e5e7eb;">{icon} {label}</td>
            <td style="padding:10px 14px;border-bottom:1px solid #e5e7eb;">
                <span style="background:{badge_color};color:white;padding:2px 10px;border-radius:10px;font-size:12px;">{stype.replace('_',' ')}</span>
            </td>
        </tr>"""

    s_bg = "#dcfce7" if success else "#fef2f2"
    s_color = "#166534" if success else "#991b1b"
    s_border = "#22c55e" if success else "#ef4444"
    host = os.getenv('FLASK_HOST', '10.46.254.144')
    report_link = f'<a href="http://{host}:5000/report/{run.report_file}" style="color:#3b82f6;">Full Report</a>' if run.report_file else ''

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:600px;margin:0 auto;">
        <div style="background:linear-gradient(135deg,#1e40af,#3b82f6);padding:24px 30px;border-radius:12px 12px 0 0;">
            <h1 style="color:white;margin:0;font-size:20px;">Upgrade Pipeline Report</h1>
            <p style="color:rgba(255,255,255,0.8);margin:8px 0 0 0;font-size:14px;">{run.operator_name}</p>
        </div>
        <div style="background:white;padding:24px 30px;border:1px solid #e5e7eb;">
            <div style="background:{s_bg};border-left:4px solid {s_border};padding:16px 20px;border-radius:0 8px 8px 0;margin-bottom:20px;">
                <div style="font-size:18px;font-weight:700;color:{s_color};">{status_word}</div>
                <div style="color:{s_color};font-size:13px;margin-top:4px;">Duration: {duration} | Steps: {len(steps)}</div>
            </div>
            <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
                <tr style="background:#f9fafb;">
                    <th style="padding:10px 14px;text-align:left;font-size:12px;color:#6b7280;border-bottom:2px solid #e5e7eb;">#</th>
                    <th style="padding:10px 14px;text-align:left;font-size:12px;color:#6b7280;border-bottom:2px solid #e5e7eb;">Step</th>
                    <th style="padding:10px 14px;text-align:left;font-size:12px;color:#6b7280;border-bottom:2px solid #e5e7eb;">Type</th>
                </tr>
                {step_rows}
            </table>
            <details style="margin-bottom:16px;">
                <summary style="cursor:pointer;font-weight:600;font-size:14px;color:#374151;">Pipeline Log</summary>
                <pre style="background:#f3f4f6;padding:12px;border-radius:6px;font-size:11px;white-space:pre-wrap;max-height:400px;overflow-y:auto;margin-top:8px;">{run.log or 'No log'}</pre>
            </details>
        </div>
        <div style="background:#f9fafb;padding:16px 30px;border-radius:0 0 12px 12px;border:1px solid #e5e7eb;border-top:none;font-size:12px;color:#6b7280;">
            CNV HealthCrew AI | {report_link} | <a href="http://{host}:5000/upgrades" style="color:#3b82f6;">View Upgrades</a>
        </div>
    </div>"""

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = recipient

    msg_alt = MIMEMultipart("alternative")
    plain = f"Upgrade Pipeline: {run.operator_name}\nStatus: {status_word}\nDuration: {duration}\nSteps: {len(steps)}\n\nLog:\n{run.log or 'No log'}"
    msg_alt.attach(MIMEText(plain, "plain"))
    msg_alt.attach(MIMEText(html, "html"))
    msg.attach(msg_alt)

    if run.report_file:
        report_path = os.path.join(REPORTS_DIR, run.report_file)
        if os.path.exists(report_path):
            with open(report_path, 'rb') as f:
                attachment = MIMEBase('text', 'html')
                attachment.set_payload(f.read())
                encoders.encode_base64(attachment)
                attachment.add_header('Content-Disposition', f'attachment; filename="{run.report_file}"')
                msg.attach(attachment)

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.sendmail(email_from, [recipient], msg.as_string())

    log.info("Pipeline email sent to %s", recipient)


def send_upgrade_step_email(run, step_data, tag, upgrade_info=None):
    """Send a notification email after an upgrade step completes (before tests)."""
    recipient = Config.DEFAULT_EMAIL
    smtp_server = os.getenv("SMTP_SERVER", "smtp.corp.redhat.com")
    smtp_port = int(os.getenv("SMTP_PORT", "25"))
    email_from = os.getenv("EMAIL_FROM", "cnv-healthcrew@redhat.com")

    success = step_data.get('status') == 'success'
    status_word = "SUCCESS" if success else "FAILED"
    label = step_data.get('label', step_data.get('type', 'Upgrade'))
    duration = step_data.get('duration', '')
    stype = step_data.get('type', '')

    if upgrade_info:
        operator = upgrade_info.get('operator', run.operator_name or label)
        from_ver = upgrade_info.get('from_version', '')
        to_ver = upgrade_info.get('to_version', '')
    else:
        operator = tag.get('operator_name', run.operator_name or label)
        from_ver = tag.get('from_version', run.from_version or '')
        to_ver = tag.get('to_version', run.to_version or '')
    version_info = f"{from_ver} -> {to_ver}" if from_ver and to_ver else ''

    subject = f"[CNV HealthCrew] Upgrade {status_word}: {operator}"
    if version_info:
        subject += f" ({version_info})"

    s_bg = "#dcfce7" if success else "#fef2f2"
    s_color = "#166534" if success else "#991b1b"
    s_border = "#22c55e" if success else "#ef4444"
    s_emoji = "&#x2705;" if success else "&#x274C;"
    host = os.getenv('FLASK_HOST', '10.46.254.144')

    next_info = ""
    if success and run.policy:
        policy_steps = run.policy.steps or []
        enabled_steps = [s for s in policy_steps if s.get('enabled', True)]
        upgrade_types = ('upgrade_olm', 'upgrade_cvo')
        current_found = False
        for s in enabled_steps:
            if s.get('type', '') in upgrade_types and not current_found:
                current_found = True
                continue
            if current_found:
                next_label = s.get('label', s.get('type', ''))
                next_info = f'<div style="margin-top:16px;padding:12px 16px;background:#eff6ff;border-left:4px solid #3b82f6;border-radius:0 8px 8px 0;font-size:13px;color:#1e40af;">Next step: <strong>{next_label}</strong> (starting automatically)</div>'
                break

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:600px;margin:0 auto;">
        <div style="background:linear-gradient(135deg,#1e3a5f,#2563eb);padding:24px 30px;border-radius:12px 12px 0 0;">
            <h1 style="color:white;margin:0;font-size:20px;">&#x1F504; Operator Upgrade {status_word}</h1>
            <p style="color:rgba(255,255,255,0.8);margin:8px 0 0 0;font-size:14px;">{operator}</p>
        </div>
        <div style="background:white;padding:24px 30px;border:1px solid #e5e7eb;">
            <div style="background:{s_bg};border-left:4px solid {s_border};padding:16px 20px;border-radius:0 8px 8px 0;margin-bottom:20px;">
                <div style="font-size:20px;font-weight:700;color:{s_color};">{s_emoji} {status_word}</div>
                <div style="color:{s_color};font-size:13px;margin-top:4px;">Duration: {duration}</div>
            </div>
            <table style="width:100%;border-collapse:collapse;margin-bottom:16px;">
                <tr><td style="padding:8px 0;color:#6b7280;width:120px;">Operator</td><td style="padding:8px 0;font-weight:600;">{operator}</td></tr>
                <tr><td style="padding:8px 0;color:#6b7280;">Type</td><td style="padding:8px 0;">{stype.replace('_', ' ').upper()}</td></tr>
                {"<tr><td style='padding:8px 0;color:#6b7280;'>Version</td><td style='padding:8px 0;font-family:monospace;'>" + version_info + "</td></tr>" if version_info else ""}
                <tr><td style="padding:8px 0;color:#6b7280;">Duration</td><td style="padding:8px 0;">{duration}</td></tr>
                <tr><td style="padding:8px 0;color:#6b7280;">Pipeline</td><td style="padding:8px 0;">{run.policy.name if run.policy else 'Manual'}</td></tr>
            </table>
            {next_info}
        </div>
        <div style="background:#f9fafb;padding:16px 30px;border-radius:0 0 12px 12px;border:1px solid #e5e7eb;border-top:none;font-size:12px;color:#6b7280;">
            CNV HealthCrew AI | <a href="http://{host}:5000/upgrades" style="color:#3b82f6;">View Upgrades</a>
        </div>
    </div>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = recipient

    plain = f"Upgrade {status_word}: {operator}\n"
    if version_info:
        plain += f"Version: {version_info}\n"
    plain += f"Duration: {duration}\nPipeline: {run.policy.name if run.policy else 'Manual'}\n"

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.sendmail(email_from, [recipient], msg.as_string())

    log.info("Upgrade step email sent to %s: %s %s", recipient, operator, status_word)


def save_upgrade_as_build(run, step_data, upgrade_info, tag):
    """Save the upgrade step as a Build record so it appears in the dashboard."""
    from app.routes import get_next_build_number, save_build_to_db

    operator = upgrade_info.get('operator', 'Unknown')
    from_ver = upgrade_info.get('from_version', '')
    to_ver = upgrade_info.get('to_version', '')
    ns = upgrade_info.get('namespace', '')
    status = step_data.get('status', 'success')
    duration = step_data.get('duration', '')
    ok = status == 'success'

    build_num = get_next_build_number()

    report_html = generate_upgrade_step_report(
        operator, ns, from_ver, to_ver, ok, duration, run
    )
    report_filename = f'upgrade_{operator}_{build_num}.html'
    os.makedirs(REPORTS_DIR, exist_ok=True)
    report_path = os.path.join(REPORTS_DIR, report_filename)
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_html)

    status_text = 'Upgrade Succeeded' if ok else 'Upgrade Failed'
    from_short = from_ver.split('.')[-1] if '.' in from_ver else from_ver
    to_short = to_ver.split('.')[-1] if '.' in to_ver else to_ver
    build_name = f"Upgrade: {operator} ({from_short} -> {to_short})"

    output_lines = [
        line for line in (run.log or '').splitlines()
        if any(k in line for k in ('Step 1/', 'Upgrading', 'CSV', 'healthy', 'Approved', 'Checking', 'rollout'))
    ]

    build_record = {
        'number': build_num,
        'name': build_name,
        'status': 'success' if ok else 'failed',
        'status_text': status_text,
        'checks': [operator],
        'checks_count': 1,
        'options': {
            'task_type': 'upgrade',
            'server_host': os.getenv('RH_LAB_HOST', ''),
            'upgrade_run_id': run.id,
            'operator': operator,
            'namespace': ns,
            'from_version': from_ver,
            'to_version': to_ver,
        },
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'duration': duration,
        'output': '\n'.join(output_lines),
        'report_file': report_filename,
    }

    save_build_to_db(build_record, user_id=run.created_by)
    return build_num


def generate_upgrade_step_report(operator, namespace, from_ver, to_ver, success, duration, run):
    """Generate an HTML report for a single upgrade step."""
    status_word = 'SUCCESS' if success else 'FAILED'
    s_bg = '#dcfce7' if success else '#fef2f2'
    s_color = '#166534' if success else '#991b1b'
    s_border = '#22c55e' if success else '#ef4444'
    s_emoji = '&#x2705;' if success else '&#x274C;'

    started = run.upgrade_started_at.strftime('%Y-%m-%d %H:%M:%S UTC') if run.upgrade_started_at else ''

    health_checks = [
        line.split('] ', 1)[-1] if '] ' in line else line
        for line in (run.log or '').splitlines()
        if any(k in line for k in ('Checking', 'rollout', 'healthy', 'stable', 'Ready'))
    ]

    health_html = ''
    if health_checks:
        rows = ''.join(
            f'<tr><td style="padding:6px 12px;border-bottom:1px solid #e5e7eb;font-size:12px;">{h}</td></tr>'
            for h in health_checks
        )
        health_html = f"""
        <div style="margin-top:24px;">
            <h3 style="font-size:15px;margin-bottom:8px;">Post-Upgrade Health Validation</h3>
            <table style="width:100%;border-collapse:collapse;">{rows}</table>
        </div>"""

    pipeline_name = run.policy.name if run.policy else 'Manual'

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>Upgrade Report: {operator} - {status_word}</title>
<style>
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; margin:0; background:#f9fafb; color:#111827; }}
.container {{ max-width:800px; margin:0 auto; padding:24px; }}
</style>
</head><body>
<div class="container">
    <div style="background:linear-gradient(135deg,#1e3a5f,#2563eb);color:white;padding:24px 28px;border-radius:12px 12px 0 0;">
        <h1 style="margin:0;font-size:20px;">&#x1F504; Operator Upgrade Report</h1>
        <p style="color:rgba(255,255,255,0.8);margin:6px 0 0 0;font-size:14px;">{operator}</p>
    </div>
    <div style="background:white;padding:24px 28px;border:1px solid #e5e7eb;">
        <div style="background:{s_bg};border-left:4px solid {s_border};padding:16px 20px;border-radius:0 8px 8px 0;margin-bottom:20px;">
            <div style="font-size:20px;font-weight:700;color:{s_color};">{s_emoji} {status_word}</div>
            <div style="color:{s_color};font-size:13px;margin-top:4px;">Duration: {duration}</div>
        </div>
        <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
            <tr><td style="padding:8px 0;color:#6b7280;width:120px;">Operator</td><td style="padding:8px 0;font-weight:700;">{operator}</td></tr>
            <tr><td style="padding:8px 0;color:#6b7280;">Namespace</td><td style="padding:8px 0;">{namespace}</td></tr>
            <tr><td style="padding:8px 0;color:#6b7280;">From</td><td style="padding:8px 0;font-family:monospace;color:#991b1b;">{from_ver}</td></tr>
            <tr><td style="padding:8px 0;color:#6b7280;">To</td><td style="padding:8px 0;font-family:monospace;color:#166534;font-weight:700;">{to_ver}</td></tr>
            <tr><td style="padding:8px 0;color:#6b7280;">Duration</td><td style="padding:8px 0;">{duration}</td></tr>
            <tr><td style="padding:8px 0;color:#6b7280;">Started</td><td style="padding:8px 0;">{started}</td></tr>
            <tr><td style="padding:8px 0;color:#6b7280;">Pipeline</td><td style="padding:8px 0;">{pipeline_name} (Run #{run.id})</td></tr>
        </table>
        {health_html}
    </div>
    <div style="background:#f9fafb;padding:12px 28px;border-radius:0 0 12px 12px;border:1px solid #e5e7eb;border-top:none;font-size:12px;color:#6b7280;">
        CNV HealthCrew AI | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    </div>
</div>
</body></html>"""
