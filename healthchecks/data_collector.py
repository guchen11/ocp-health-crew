"""SSH data collection and SSH error HTML."""

from datetime import datetime

from healthchecks.data_parser import (
    parse_cordoned_vms,
    parse_csi_issues,
    parse_dynamic_check_issues,
    parse_dv_issues,
    parse_etcd,
    parse_hco_healthy,
    parse_kubevirt,
    parse_migrations,
    parse_nodes,
    parse_oom_events,
    parse_operators,
    parse_pods,
    parse_pvcs,
    parse_resources,
    parse_shell_kv_output,
    parse_snapshot_issues,
    parse_stuck_migrations,
    parse_version,
    parse_virt_ctrl,
    parse_virt_handler,
    parse_virt_launcher_bad,
)
from healthchecks.jira_integration import SUGGESTED_NEW_CHECKS
from healthchecks.report_generator import escape_html
from healthchecks.ssh_client import (
    HOST,
    KEY_PATH,
    KUBECONFIG,
    SSHConnectionError,
    USER,
    get_ssh_client,
    ssh_command,
)


def collect_data():
    """Collect all cluster health data. Raises SSHConnectionError if cannot connect."""

    def log(msg):
        print(f"  {msg}", flush=True)

    log("📊 Starting data collection...")

    # ── Validate SSH connection upfront ──
    log("  → Verifying SSH connection to host...")
    try:
        client = get_ssh_client()
    except SSHConnectionError:
        raise  # Propagate with full details

    # Quick smoke test — verify oc is reachable (capture stderr for diagnostics)
    log("  → Verifying oc CLI access...")
    import shlex as _shlex
    diag_cmd = (
        f"export KUBECONFIG={_shlex.quote(KUBECONFIG)}; "
        'echo "KUBECONFIG=$KUBECONFIG"; '
        'echo "KUBECONFIG_EXISTS=$(test -f $KUBECONFIG && echo yes || echo no)"; '
        'echo "OC_PATH=$(which oc 2>/dev/null || echo NOT_FOUND)"; '
        "OC_OUT=$(oc whoami 2>&1); OC_RC=$?; "
        'echo "OC_RC=$OC_RC"; '
        'echo "OC_OUT=$OC_OUT"'
    )
    try:
        raw_client = get_ssh_client()
        stdin, stdout, stderr = raw_client.exec_command(diag_cmd, timeout=15)
        diag_output = stdout.read().decode().strip()
    except SSHConnectionError:
        raise
    except Exception as e:
        diag_output = f"Failed to run diagnostics: {e}"

    diag = parse_shell_kv_output(diag_output)

    oc_rc = diag.get("OC_RC", "1")
    oc_out = diag.get("OC_OUT", "")
    oc_path = diag.get("OC_PATH", "NOT_FOUND")
    kc_exists = diag.get("KUBECONFIG_EXISTS", "no")

    if oc_rc != "0" or not oc_out or oc_out == "NOT_FOUND":
        is_auth_issue = any(
            kw in oc_out.lower()
            for kw in [
                "unauthorized", "must be logged in", "token", "forbidden",
                "certificate has expired", "certificate is not yet valid",
            ]
        ) if oc_out else False

        if is_auth_issue and oc_path != "NOT_FOUND" and kc_exists == "yes":
            log(f"  ⚠ Auth expired: {oc_out}")
            log("  → Attempting auto-login with kubeadmin credentials...")
            kc_dir = "/".join(KUBECONFIG.rsplit("/", 1)[:-1]) if "/" in KUBECONFIG else "."
            login_cmd = (
                f"export KUBECONFIG={_shlex.quote(KUBECONFIG)}; "
                f"PASS_FILE={kc_dir}/kubeadmin-password; "
                "if [ -f \"$PASS_FILE\" ]; then "
                "  oc login -u kubeadmin -p $(cat \"$PASS_FILE\") 2>&1; "
                '  echo "LOGIN_RC=$?"; '
                '  echo "LOGIN_USER=$(oc whoami 2>&1)"; '
                "else "
                '  echo "LOGIN_RC=1"; '
                '  echo "LOGIN_USER=PASS_FILE_NOT_FOUND: $PASS_FILE"; '
                "fi"
            )
            try:
                raw_client = get_ssh_client()
                stdin, stdout, stderr = raw_client.exec_command(login_cmd, timeout=20)
                login_output = stdout.read().decode().strip()
            except SSHConnectionError:
                raise
            except Exception as e:
                login_output = f"LOGIN_RC=1\nLOGIN_USER=auto-login failed: {e}"

            login_info = parse_shell_kv_output(login_output)

            login_rc = login_info.get("LOGIN_RC", "1")
            login_user = login_info.get("LOGIN_USER", "")

            if login_rc == "0" and login_user and "PASS_FILE_NOT_FOUND" not in login_user:
                log(f"  ✓ Auto-login successful! Connected as: {login_user}")
            else:
                fail_reason = login_user or "unknown error"
                log(f"  ✗ Auto-login failed: {fail_reason}")
                raise SSHConnectionError(
                    f"'oc' CLI check failed on {HOST}: {oc_out}\n"
                    f"  Auto-login attempted but failed: {fail_reason}\n"
                    f"  KUBECONFIG={KUBECONFIG} (exists: {kc_exists})\n"
                    f"  oc path: {oc_path}\n"
                    f"  Manually run: oc login -u kubeadmin -p $(cat {kc_dir}/kubeadmin-password)",
                    host=HOST, user=USER, key_path=KEY_PATH,
                )
        else:
            details = []
            if oc_path == "NOT_FOUND":
                details.append("'oc' binary not found in PATH")
            if kc_exists == "no":
                details.append(f"KUBECONFIG file not found: {KUBECONFIG}")
            if oc_out and oc_path != "NOT_FOUND":
                details.append(f"oc error: {oc_out}")
            if not details:
                details.append("oc whoami returned empty output")

            detail_str = "; ".join(details)
            raise SSHConnectionError(
                f"'oc' CLI check failed on {HOST}: {detail_str}\n"
                f"  KUBECONFIG={KUBECONFIG} (exists: {kc_exists})\n"
                f"  oc path: {oc_path}\n"
                "  Ensure the cluster API is reachable and the kubeconfig is valid.",
                host=HOST, user=USER, key_path=KEY_PATH,
            )
    else:
        log(f"  ✓ Connected as: {oc_out}")

    log("  → Checking nodes...")
    nodes_out = ssh_command("oc get nodes --no-headers", timeout=15)

    log("  → Checking cluster operators...")
    operators_out = ssh_command("oc get co --no-headers", timeout=15)

    log("  → Checking pod status...")
    pods_out = ssh_command(
        "oc get pods -A --no-headers --field-selector=status.phase!=Running,status.phase!=Succeeded 2>/dev/null",
        timeout=15,
    )
    pod_count = ssh_command("oc get pods -A --no-headers 2>/dev/null | wc -l", timeout=15)

    log("  → Checking KubeVirt status...")
    kubevirt_out = ssh_command("oc get kubevirt -A --no-headers 2>/dev/null", timeout=10)
    vmi_out = ssh_command("oc get vmi -A --no-headers 2>/dev/null", timeout=10)

    log("  → Checking node resources...")
    top_out = ssh_command("oc adm top nodes --no-headers 2>/dev/null", timeout=15)

    log("  → Getting cluster version...")
    version_out = ssh_command("oc version 2>/dev/null | grep 'Server Version'", timeout=10)

    log("  → Checking etcd health...")
    etcd_out = ssh_command(
        "oc get pods -n openshift-etcd -l app=etcd --no-headers 2>/dev/null", timeout=10
    )
    etcd_leader = ssh_command(
        "oc rsh -n openshift-etcd -c etcdctl $(oc get pods -n openshift-etcd -l app=etcd -o name 2>/dev/null | head -1) etcdctl endpoint status --cluster -w table 2>/dev/null | grep -v 'ENDPOINT' | head -5",
        timeout=15,
    )

    log("  → Checking certificates...")
    certs_out = ssh_command(
        "oc get certificates -A --no-headers 2>/dev/null; oc get secret -A -o json 2>/dev/null | grep -o '\"notAfter\":\"[^\"]*\"' | head -10",
        timeout=15,
    )

    log("  → Checking PVC status...")
    pvc_out = ssh_command("oc get pvc -A --no-headers 2>/dev/null | grep -v Bound | head -20", timeout=10)

    log("  → Checking VM migrations...")
    migrations_out = ssh_command(
        "oc get vmim -A --no-headers 2>/dev/null | grep -v Succeeded | head -20", timeout=10
    )

    log("  → Checking alerts...")
    alerts_out = ssh_command(
        "oc get prometheusrules -A --no-headers 2>/dev/null | wc -l; oc exec -n openshift-monitoring -c prometheus prometheus-k8s-0 -- curl -s 'http://localhost:9090/api/v1/alerts' 2>/dev/null | grep -o '\"alertname\":\"[^\"]*\"' | sort | uniq -c | sort -rn | head -10",
        timeout=20,
    )

    log("  → Checking CSI drivers...")
    csi_out = ssh_command(
        "oc get pods -A --no-headers 2>/dev/null | grep -E 'csi|driver' | grep -v Running", timeout=10
    )

    log("  → Checking OOM events...")
    oom_out = ssh_command(
        "oc get events -A --field-selector reason=OOMKilled --no-headers 2>/dev/null | tail -10",
        timeout=10,
    )

    log("  → Checking failed migrations...")
    failed_migrations = ssh_command(
        "oc get vmim -A -o json 2>/dev/null | grep -E '\"phase\":\"Failed\"' | wc -l", timeout=10
    )

    log("  → Checking virt-handler pods...")
    virt_handler_out = ssh_command(
        "oc get pods -n openshift-cnv -l kubevirt.io=virt-handler --no-headers 2>/dev/null", timeout=10
    )
    virt_handler_mem = ssh_command(
        "oc adm top pods -n openshift-cnv -l kubevirt.io=virt-handler --no-headers 2>/dev/null", timeout=10
    )

    log("  → Checking virt-launcher pods...")
    virt_launcher_issues = ssh_command(
        "oc get pods -A -l kubevirt.io=virt-launcher --no-headers 2>/dev/null | grep -v Running | head -10",
        timeout=10,
    )

    log("  → Checking virt-controller/virt-api...")
    virt_ctrl_out = ssh_command(
        "oc get pods -n openshift-cnv -l 'kubevirt.io in (virt-controller,virt-api)' --no-headers 2>/dev/null",
        timeout=10,
    )

    log("  → Checking DataVolumes...")
    dv_stuck = ssh_command(
        "oc get dv -A --no-headers 2>/dev/null | grep -vE 'Succeeded|PVCBound' | head -15", timeout=10
    )

    log("  → Checking VolumeSnapshots...")
    snapshots_out = ssh_command(
        "oc get volumesnapshot -A --no-headers 2>/dev/null | grep -v 'true' | head -10", timeout=10
    )

    log("  → Checking cordoned nodes...")
    cordoned_nodes = ssh_command("oc get nodes --no-headers 2>/dev/null | grep SchedulingDisabled", timeout=10)
    vms_on_cordoned = ""
    if cordoned_nodes:
        cordoned_list = [line.split()[0] for line in cordoned_nodes.split("\n") if line]
        if cordoned_list:
            log("  → Checking VMs on cordoned nodes...")
            vms_on_cordoned = ssh_command(
                f"oc get vmi -A -o wide --no-headers 2>/dev/null | grep -E '{'|'.join(cordoned_list)}' | head -10",
                timeout=10,
            )

    log("  → Checking stuck migrations...")
    stuck_migrations = ssh_command("oc get vmim -A --no-headers 2>/dev/null | grep Running", timeout=10)

    log("  → Checking HyperConverged status...")
    hco_status = ssh_command(
        "oc get hyperconverged -n openshift-cnv kubevirt-hyperconverged -o jsonpath='{.status.conditions}' 2>/dev/null",
        timeout=10,
    )

    log("✅ Data collection complete!")

    nodes = parse_nodes(nodes_out)
    operators = parse_operators(operators_out)
    pods = parse_pods(pods_out, pod_count)
    kubevirt = parse_kubevirt(kubevirt_out, vmi_out)
    resources = parse_resources(top_out)
    version = parse_version(version_out)
    etcd = parse_etcd(etcd_out, etcd_leader)
    pvcs = parse_pvcs(pvc_out)
    migrations = parse_migrations(migrations_out, failed_migrations)
    oom_events = parse_oom_events(oom_out)
    csi_issues = parse_csi_issues(csi_out)
    virt_handler = parse_virt_handler(virt_handler_out, virt_handler_mem)
    virt_launcher_bad = parse_virt_launcher_bad(virt_launcher_issues)
    virt_ctrl = parse_virt_ctrl(virt_ctrl_out)
    dv_issues = parse_dv_issues(dv_stuck)
    snapshot_issues = parse_snapshot_issues(snapshots_out)
    cordoned_vms = parse_cordoned_vms(vms_on_cordoned)
    stuck_migs = parse_stuck_migrations(stuck_migrations)
    hco_healthy = parse_hco_healthy(hco_status)

    dynamic_check_results = {}
    if SUGGESTED_NEW_CHECKS:
        for check in SUGGESTED_NEW_CHECKS:
            check_name = check.get("name", "unknown")
            try:
                if check_name == "etcd_latency":
                    result = ssh_command(
                        "oc exec -n openshift-etcd $(oc get pods -n openshift-etcd -l app=etcd -o name | head -1) -- etcdctl endpoint health --cluster -w json 2>/dev/null",
                        timeout=15,
                    )
                elif check_name == "kubelet_health":
                    result = ssh_command(
                        "oc get nodes -o jsonpath='{range .items[*]}{.metadata.name} {.status.conditions[?(@.type==\"Ready\")].status}{\"\\n\"}{end}' 2>/dev/null",
                        timeout=15,
                    )
                elif check_name == "cert_expiry":
                    result = ssh_command(
                        "oc get secret -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name} {.type}{\"\\n\"}{end}' 2>/dev/null | grep tls | head -10",
                        timeout=15,
                    )
                elif check_name == "network_migration":
                    result = ssh_command(
                        "oc get network.operator cluster -o jsonpath='{.spec.migration}' 2>/dev/null", timeout=10
                    )
                elif check_name == "catalog_source":
                    result = ssh_command(
                        "oc get catalogsource -n openshift-marketplace --no-headers 2>/dev/null", timeout=10
                    )
                elif check_name == "router_health":
                    result = ssh_command(
                        "oc get pods -n openshift-ingress -l ingresscontroller.operator.openshift.io/deployment-ingresscontroller --no-headers 2>/dev/null",
                        timeout=10,
                    )
                elif check_name == "image_pull":
                    result = ssh_command(
                        "oc get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded 2>/dev/null | grep -i imagepull | head -10",
                        timeout=15,
                    )
                else:
                    result = ssh_command("echo 'Check not implemented'", timeout=5)

                issues_found = parse_dynamic_check_issues(result)
                dynamic_check_results[check_name] = {
                    "raw_output": result[:500] if result else "",
                    "issues": issues_found,
                    "jira": check.get("jira", ""),
                    "description": check.get("description", ""),
                }
            except Exception as e:
                dynamic_check_results[check_name] = {
                    "raw_output": f"Error: {str(e)}",
                    "issues": [],
                    "jira": check.get("jira", ""),
                    "description": check.get("description", ""),
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
        "etcd": etcd,
        "pvcs": pvcs,
        "migrations": migrations,
        "oom_events": oom_events,
        "csi_issues": csi_issues,
        "virt_handler": virt_handler,
        "virt_launcher_bad": virt_launcher_bad,
        "virt_ctrl": virt_ctrl,
        "dv_issues": dv_issues,
        "snapshot_issues": snapshot_issues,
        "cordoned_vms": cordoned_vms,
        "stuck_migrations": stuck_migs,
        "hco_healthy": hco_healthy,
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
        len(data["etcd"]["unhealthy"]) > 0 or
        len(data["pvcs"]["pending"]) > 0 or
        len(data["migrations"]["failed"]) > 0 or
        data["migrations"]["failed_count"] > 0 or
        len(data["oom_events"]) > 0 or
        len(data["csi_issues"]) > 0 or
        len(data["virt_handler"]["unhealthy"]) > 0 or
        len(data["virt_handler"]["high_memory"]) > 0 or
        len(data["virt_launcher_bad"]) > 0 or
        len(data["virt_ctrl"]["unhealthy"]) > 0 or
        len(data["dv_issues"]) > 0 or
        len(data["snapshot_issues"]) > 0 or
        len(data["cordoned_vms"]) > 0 or
        len(data["stuck_migrations"]) > 0
    )


def generate_error_report_html(ssh_error):
    """Generate an HTML error report when SSH connection fails."""
    from datetime import datetime as _dt
    ts = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    host = escape_html(str(ssh_error.host or "(not set)"))
    user = escape_html(str(ssh_error.user or "(not set)"))
    key = escape_html(str(ssh_error.key_path or "(not set)"))
    error_msg = escape_html(str(ssh_error))
    orig = ""
    if ssh_error.original_error:
        orig = escape_html(f"{type(ssh_error.original_error).__name__}: {ssh_error.original_error}")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Health Check — Connection Error</title>
<style>
  :root {{ --bg:#1a1a2e; --card:#16213e; --red:#e74c3c; --yellow:#f39c12; --text:#e0e0e0; --muted:#888; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Segoe UI',system-ui,-apple-system,sans-serif; background:var(--bg); color:var(--text); padding:20px; }}
  .container {{ max-width:800px; margin:0 auto; }}
  .header {{ text-align:center; padding:30px 0; }}
  .header h1 {{ color:var(--red); font-size:2em; margin-bottom:10px; }}
  .header .ts {{ color:var(--muted); font-size:0.9em; }}
  .error-card {{ background:var(--card); border:2px solid var(--red); border-radius:12px; padding:24px; margin:20px 0; }}
  .error-card h2 {{ color:var(--red); margin-bottom:16px; font-size:1.3em; }}
  .error-msg {{ background:#1a1a1a; border-radius:8px; padding:16px; font-family:monospace; color:#ff6b6b;
    white-space:pre-wrap; word-break:break-word; margin-bottom:16px; font-size:0.95em; }}
  .details {{ margin:16px 0; }}
  .details table {{ width:100%; border-collapse:collapse; }}
  .details td {{ padding:8px 12px; border-bottom:1px solid #333; }}
  .details td:first-child {{ color:var(--yellow); font-weight:600; width:100px; }}
  .details td:last-child {{ font-family:monospace; }}
  .troubleshoot {{ background:var(--card); border:1px solid #333; border-radius:12px; padding:24px; margin:20px 0; }}
  .troubleshoot h2 {{ color:var(--yellow); margin-bottom:16px; }}
  .troubleshoot ol {{ padding-left:20px; }}
  .troubleshoot li {{ margin:8px 0; line-height:1.6; }}
  .troubleshoot code {{ background:#1a1a1a; padding:2px 8px; border-radius:4px; font-size:0.9em; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>&#x274C; Connection Error</h1>
    <div class="ts">{ts}</div>
  </div>
  <div class="error-card">
    <h2>SSH Connection Failed</h2>
    <div class="error-msg">{error_msg}</div>
    <div class="details">
      <table>
        <tr><td>Host</td><td>{host}</td></tr>
        <tr><td>User</td><td>{user}</td></tr>
        <tr><td>SSH Key</td><td>{key}</td></tr>
        {"<tr><td>Detail</td><td>" + orig + "</td></tr>" if orig else ""}
      </table>
    </div>
  </div>
  <div class="troubleshoot">
    <h2>&#x1F527; Troubleshooting</h2>
    <ol>
      <li>Verify the host is reachable: <code>ssh {user}@{host}</code></li>
      <li>Check the SSH key exists and has correct permissions (<code>chmod 600</code>)</li>
      <li>Ensure <code>RH_LAB_HOST</code> and <code>SSH_KEY_PATH</code> environment variables are set correctly</li>
      <li>If using <code>--server</code>, double-check the hostname/IP is correct</li>
      <li>Verify the target host allows SSH key-based authentication</li>
      <li>Check firewall rules and network connectivity to port 22</li>
    </ol>
  </div>
</div>
</body>
</html>"""
