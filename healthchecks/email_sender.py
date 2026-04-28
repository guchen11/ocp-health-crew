"""HTML email report delivery via SMTP."""

import os
import smtplib
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from healthchecks import hybrid_flags
from healthchecks.email_html_builder import (
    build_email_html,
    collect_email_report_stats,
    format_email_plain_text,
)

EMAIL_FROM = os.getenv("EMAIL_FROM", "cnv-healthcrew@redhat.com")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.corp.redhat.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "25"))


def send_email_report(html_path, recipient=None, subject=None, cluster_name=None, issue_count=0, report_data=None):
    """
    Send a beautiful HTML email summary matching the dashboard style.

    Args:
        html_path: Path to the HTML report file
        recipient: Email recipient (defaults to hybrid_flags.EMAIL_TO)
        subject: Email subject (auto-generated if not provided)
        cluster_name: Cluster name for the subject line
        issue_count: Number of issues found (for subject line)
        report_data: Dict containing report data for email body

    Returns:
        bool: True if email sent successfully, False otherwise
    """
    recipient = recipient or hybrid_flags.EMAIL_TO

    if not subject:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        status = "⚠️ ISSUES FOUND" if issue_count > 0 else "✅ HEALTHY"
        lab_or_cluster = hybrid_flags.LAB_NAME or cluster_name or ""
        subject = (
            f"[CNV HealthCrew AI] {status} - {lab_or_cluster} ({timestamp})"
            if lab_or_cluster
            else f"[CNV HealthCrew AI] {status} ({timestamp})"
        )

    try:
        data = report_data or {}
        stats = collect_email_report_stats(data)

        status_text = "ATTENTION NEEDED" if issue_count > 0 else "ALL SYSTEMS HEALTHY"

        html_content = build_email_html(
            data, html_path, cluster_name, issue_count, stats=stats
        )
        plain_text = format_email_plain_text(stats, cluster_name, issue_count, status_text)

        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = recipient

        msg_alt = MIMEMultipart("alternative")
        part1 = MIMEText(plain_text, "plain")
        part2 = MIMEText(html_content, "html")
        msg_alt.attach(part1)
        msg_alt.attach(part2)
        msg.attach(msg_alt)

        with open(html_path, "rb") as f:
            attachment = MIMEBase("text", "html")
            attachment.set_payload(f.read())
            encoders.encode_base64(attachment)
            filename = os.path.basename(html_path)
            attachment.add_header("Content-Disposition", f'attachment; filename="{filename}"')
            msg.attach(attachment)

        print(f"  📧 Connecting to SMTP server ({SMTP_SERVER}:{SMTP_PORT})...", flush=True)

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            if server.has_extn("STARTTLS"):
                server.starttls()
                server.ehlo()
            smtp_user = os.getenv("SMTP_USER")
            smtp_pass = os.getenv("SMTP_PASS")
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)

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
