#!/usr/bin/env python3
"""Create a Gmail draft (unsent). Uses ~/.gmail_imap_mcp_credentials/token.json."""
from __future__ import annotations

import base64
import json
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

CREDS_DIR = Path.home() / ".gmail_imap_mcp_credentials"
TOKEN_JSON = CREDS_DIR / "token.json"

HTML_BODY = """\
<p>@Fabian Deutsch I was wondering the same thing: is what we have sufficient for customers, or should we open a bug / RFE?</p>

<p><b>From <a href="https://docs.redhat.com/en/documentation/monitoring_stack_for_red_hat_openshift/latest/html/configuring_core_platform_monitoring/storing-and-recording-data">Storing and recording data for core platform monitoring</a> (public doc):</b></p>
<ul>
<li><b>Persistent storage:</b> Highly recommended for production; on multi-node clusters, <b>must</b> configure persistent storage for Prometheus and Alertmanager for HA.</li>
<li><b>volumeClaimTemplate:</b> How to use a PVC for Prometheus (and resize).</li>
<li><b>Retention:</b> Default <b>15 days</b> for core platform monitoring is stated explicitly.</li>
<li><b>retentionSize:</b> Caps disk used by retained metrics; ties to controlling excessive disk usage.</li>
<li><b>Compaction:</b> A PV can fill before compaction catches up; <b>KubePersistentVolumeFillingUp</b> may fire until space drops.</li>
</ul>
<p>If a customer actually does <b>PVC + retentionSize + right-sized PVC</b>, the doc set is directionally enough.</p>

<p><b>Where it still feels thin for the failure we saw:</b></p>
<ul>
<li>It does <b>not</b> say clearly that <b>without</b> PVC, TSDB on <b>node-local / emptyDir</b> can <b>fill the worker root disk</b> and cause <b>DiskPressure / NotReady</b>, not just "Prometheus is unhappy."</li>
<li><b>"Highly recommended"</b> is weaker than how operators behave in practice at <b>very high metric load</b> (e.g. large CNV counts).</li>
<li><b>Sizing at scale</b> (cardinality / ingest) is not spelled out; small <b>retentionSize</b> examples are easy to copy without re-sizing.</li>
</ul>

<p><b>Red Hat KB (related pieces, not one full story):</b></p>
<table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse;font-size:14px;">
<thead><tr style="background:#f0f0f0;"><th>Article</th><th>URL</th><th>Public abstract (summary)</th></tr></thead>
<tbody>
<tr><td>Configure Prometheus retention</td><td><a href="https://access.redhat.com/solutions/4280821">KCS 4280821</a></td><td>Retention via cluster-monitoring-config (OCP 4, ROSA, OSD).</td></tr>
<tr><td>TSDB disk full / compaction</td><td><a href="https://access.redhat.com/solutions/6746431">KCS 6746431</a></td><td>PrometheusTSDBCompactionsFailing, full /prometheus, WAL after resize; touches permanent vs ephemeral in the issue text.</td></tr>
<tr><td>Investigate DiskPressure</td><td><a href="https://access.redhat.com/solutions/5341801">KCS 5341801</a></td><td>DiskPressure / NotReady; finding large disk users on the node (OCP 4).</td></tr>
<tr><td>EmptyDir in Prometheus pod</td><td><a href="https://access.redhat.com/solutions/5069151">KCS 5069151</a></td><td>Mostly config-out as EmptyDir; older OCP versions in the abstract.</td></tr>
</tbody>
</table>
<p>There is <b>no</b> single KCS that walks the full chain: <b>defaults + local TSDB + no byte cap + high ingest -&gt; node disk gone</b>.</p>

<p><b>Bottom line:</b> The docs help people who configure PVCs and limits on purpose; they do not stop a defaults-only cluster from filling worker disks at our scale.</p>
"""

PLAIN_BODY = (
    "Draft reply for Fabian (HTML version has links and table). "
    "Open this draft in Gmail and use the HTML part for sending.\n\n"
    + HTML_BODY.replace("<br>", "\n").replace("<p>", "\n").replace("</p>", "")
)


def load_credentials() -> Credentials:
    if not TOKEN_JSON.is_file():
        print(f"Missing {TOKEN_JSON}", file=sys.stderr)
        sys.exit(1)
    data = json.loads(TOKEN_JSON.read_text())
    creds = Credentials(
        token=data["token"],
        refresh_token=data.get("refresh_token"),
        token_uri=data["token_uri"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        scopes=data["scopes"],
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Optional: persist refreshed token
        data["token"] = creds.token
        if creds.expiry:
            data["expiry"] = creds.expiry.isoformat()
        TOKEN_JSON.write_text(json.dumps(data, indent=2))
    return creds


def main() -> None:
    to_addr = "Fabian Deutsch <fdeutsch@redhat.com>"
    subject = (
        "[DRAFT] Re: Performance Test Results - 10K VM Longevity CNV 4.21 "
        "(14-Day Stability) - PARTIAL"
    )

    msg = MIMEMultipart("alternative")
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(PLAIN_BODY, "plain", "utf-8"))
    msg.attach(MIMEText(HTML_BODY, "html", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    creds = load_credentials()
    service = build("gmail", "v1", credentials=creds)
    draft = (
        service.users()
        .drafts()
        .create(userId="me", body={"message": {"raw": raw}})
        .execute()
    )
    print(f"Draft created: id={draft.get('id')} messageId={draft.get('message', {}).get('id')}")
    print("Open Gmail - Drafts. Subject starts with [DRAFT]. Fabian is not notified until you Send.")


if __name__ == "__main__":
    main()
