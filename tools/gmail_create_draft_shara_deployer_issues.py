#!/usr/bin/env python3
"""Create a Gmail draft with Cloud39 deployment issues for Shara."""
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
<h2>Cloud39 Deployment Issues & Recommended Fixes</h2>
<p style='color:#666;margin-bottom:20px;'>43-node MNO, OCP 4.22.0-ec.5, Scale Lab cloud39</p>

<hr style='margin:16px 0;'>
<h3>1. Dead Node - f19-h13-000-r640</h3>
<p><b>What happened:</b><br>
Node <code>f19-h13-000-r640</code> was unresponsive (down) when the deployment started. The original inventory had 45 nodes. I had to manually remove this node and create a filtered inventory file (<code>cloud39_ocpinventory_no_f19h13.json</code>) with 44 nodes (3 masters + 40 workers + 1 bastion). The deployment then proceeded successfully with the remaining nodes.</p>
<p><b>Recommended fix:</b> <span style='background:#e8f5e9;color:#2e7d32;padding:2px 8px;border-radius:4px;font-weight:bold;'>No code change needed</span><br>
The deployer already has a <code>hosts.exclude</code> config option (commit <code>40d3217</code>). Nice-to-have: a pre-deploy IPMI reachability check that auto-detects dead nodes.</p>

<hr style='margin:16px 0;'>
<h3>2. Boot Order Step Skipped - vendor/badfish Missing</h3>
<p><b>What happened:</b><br>
The <code>boot_order</code> pre-deploy step was configured but couldn't run because the <code>vendor/badfish/</code> directory was empty (only <code>.gitkeep</code>). The code expects <code>vendor/badfish/config/idrac_interfaces.yml</code> to exist. I had to disable it (<code>enabled: false</code>) and rely on nodes already being in the correct boot order.</p>
<p><b>Recommended fix:</b> <span style='background:#fff3e0;color:#e65100;padding:2px 8px;border-radius:4px;font-weight:bold;'>Small effort</span></p>
<ul>
<li>Improve the error message: tell the user <i>how</i> to populate the vendor directory</li>
<li>Add a Makefile target or README section documenting vendor setup</li>
</ul>

<hr style='margin:16px 0;'>
<h3>3. Podman / Ansible Collection Incompatibility</h3>
<p><b>What happened:</b><br>
The bastion had podman 5.6.0, but <code>containers.podman</code> Ansible collection was version 1.10.2 (incompatible with podman 5.x). Ansible tasks using podman modules failed silently or with cryptic errors. I had to manually upgrade to 1.19.2 with <code>ansible-galaxy</code> before jetlag playbooks would work.</p>
<p><b>Recommended fix:</b> <span style='background:#fff3e0;color:#e65100;padding:2px 8px;border-radius:4px;font-weight:bold;'>Medium effort</span></p>
<ul>
<li>Add <code>requirements.yml</code> pinning <code>containers.podman &gt;= 1.19.0</code></li>
<li>Add <code>ansible-galaxy collection install -r requirements.yml</code> to bastion pre_deploy, after dnf_install</li>
</ul>

<hr style='margin:16px 0;'>
<h3>4. Failed Installer Pods Left Behind</h3>
<p><b>What happened:</b><br>
After the cluster installed, 4 failed <code>installer-3-*</code> pods were left in the <code>openshift-kube-controller-manager</code> namespace on <code>f04-h32</code>. These were bootstrap artifacts from an earlier control plane revision, superseded by later revisions. They showed as <code>Failed</code> and would cause false positives in validation. I manually deleted them with <code>oc delete pod</code>.</p>
<p><b>Recommended fix:</b> <span style='background:#fff3e0;color:#e65100;padding:2px 8px;border-radius:4px;font-weight:bold;'>Small effort</span></p>
<ul>
<li>Add post-deploy cleanup: <code>oc delete pod --field-selector=status.phase=Failed -n openshift-kube-controller-manager</code></li>
<li>Safe to remove since later revisions supersede them</li>
</ul>

<hr style='margin:16px 0;'>
<h3>Summary</h3>
<table border='1' cellpadding='8' cellspacing='0' style='border-collapse:collapse;border-color:#ddd;'>
<tr style='background:#f5f5f5;'><th>Issue</th><th>Manual Work I Did</th><th>Code Change?</th><th>Effort</th></tr>
<tr><td>Dead node (f19-h13)</td><td>Edit inventory JSON</td><td style='color:#2e7d32;'>No</td><td>-</td></tr>
<tr><td>Boot order / badfish vendor</td><td>Disable in config</td><td style='color:#e65100;'>Yes</td><td>Small</td></tr>
<tr><td>Podman Ansible collection</td><td>Manual galaxy upgrade</td><td style='color:#e65100;'>Yes</td><td>Medium</td></tr>
<tr><td>Transient installer pods</td><td>Manual oc delete</td><td style='color:#e65100;'>Yes</td><td>Small</td></tr>
</table>
"""

PLAIN_BODY = (
    "Cloud39 Deployment Issues & Recommended Fixes\n"
    "43-node MNO, OCP 4.22.0-ec.5, Scale Lab cloud39\n\n"
    "1. Dead Node - f19-h13-000-r640\n"
    "Node was unresponsive. Manually removed from inventory, created filtered "
    "cloud39_ocpinventory_no_f19h13.json (44 nodes). No code change needed - "
    "hosts.exclude already exists.\n\n"
    "2. Boot Order Step Skipped\n"
    "vendor/badfish/ directory empty. Had to disable boot_order. Fix: better "
    "error message + docs on populating vendor dir.\n\n"
    "3. Podman Ansible Collection\n"
    "containers.podman 1.10.2 incompatible with podman 5.6.0. Had to manually "
    "upgrade to 1.19.2. Fix: add requirements.yml + galaxy install step.\n\n"
    "4. Failed Installer Pods\n"
    "4 failed installer-3-* pods left behind. Had to manually delete. Fix: add "
    "post-deploy cleanup step.\n"
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
        data["token"] = creds.token
        if creds.expiry:
            data["expiry"] = creds.expiry.isoformat()
        TOKEN_JSON.write_text(json.dumps(data, indent=2))
    return creds


def main() -> None:
    to_addr = "Sarah Bennert <sbennert@redhat.com>"
    subject = "openshift-deployer: Cloud39 Deployment Issues & Recommended Fixes"

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
    print(f"Draft created: id={draft.get('id')}")
    print("Open Gmail -> Drafts. Edit before sending if needed.")


if __name__ == "__main__":
    main()
