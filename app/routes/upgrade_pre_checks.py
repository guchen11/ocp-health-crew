"""Pre-upgrade and pre-test readiness checks - cluster stability, virtctl sync, cleanup."""
import json
import logging
import shlex
import time

from config.settings import Config

log = logging.getLogger(__name__)

KUBECONFIG = Config.KUBECONFIG
SSH_HEALTH_TIMEOUT = 20
NODE_TIMEOUT = 600
OPERATOR_HEALTH_TIMEOUT = 1800
OPERATOR_HEALTH_POLL = 15


def _ssh_run(client, cmd, timeout=60):
    from app.ssh_utils import ssh_exec
    stdout, stderr = ssh_exec(client, cmd, kubeconfig=KUBECONFIG, timeout=timeout)
    return stdout, stderr


def sync_virtctl_version(client, run, step_label):
    """Download the cluster-matching virtctl binary to the bastion.

    After a KubeVirt/HCO upgrade the server-side version changes but the
    bastion's virtctl stays at the old version, causing
    "client virtctl version is different from the KubeVirt version" errors
    during SSH validation.  This fetches the correct binary via the
    ConsoleCLIDownload CR.
    """
    from app.models import db

    run.append_log(f"{step_label}   Syncing virtctl to match cluster version...", level='wait')
    db.session.commit()

    version_out, _ = _ssh_run(
        client,
        "virtctl version --client -o json 2>/dev/null || echo '{}'",
        timeout=SSH_HEALTH_TIMEOUT,
    )
    server_out, _ = _ssh_run(
        client,
        "oc get kubevirt -A -o jsonpath='{.items[0].status.observedKubeVirtVersion}' 2>/dev/null",
        timeout=SSH_HEALTH_TIMEOUT,
    )
    client_ver = ''
    server_ver = (server_out or '').strip().strip("'")
    if version_out:
        try:
            client_ver = json.loads(version_out).get('clientVersion', {}).get('gitVersion', '')
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass

    if client_ver and server_ver and client_ver == server_ver:
        run.append_log(f"{step_label}   virtctl already at {client_ver}", level='ok')
        db.session.commit()
        return True

    run.append_log(
        f"{step_label}   virtctl mismatch: client={client_ver or 'unknown'}, "
        f"server={server_ver or 'unknown'} - updating...",
        level='wait',
    )
    db.session.commit()

    dl_url_out, _ = _ssh_run(
        client,
        "oc get consoleclidownload virtctl-clidownloads-kubevirt-hyperconverged "
        "-o jsonpath='{.spec.links[?(@.text==\"Download virtctl for Linux for x86_64\")].href}' "
        "2>/dev/null",
        timeout=SSH_HEALTH_TIMEOUT,
    )
    dl_url = (dl_url_out or '').strip().strip("'")

    downloaded = False
    if dl_url:
        dl_url_q = shlex.quote(dl_url)
        install_cmd = (
            f"curl -sSLk {dl_url_q} | tar xz -C /usr/local/bin/ virtctl && "
            "chmod +x /usr/local/bin/virtctl"
        )
        _, err = _ssh_run(client, install_cmd, timeout=120)
        if not err or 'error' not in err.lower():
            downloaded = True
        else:
            run.append_log(
                f"{step_label}   curl download failed, trying oc cp fallback...",
                level='warn',
            )
            db.session.commit()

    if not downloaded:
        run.append_log(
            f"{step_label}   Copying virtctl from virt-operator pod...",
            level='wait',
        )
        db.session.commit()
        fallback_cmd = (
            "POD=$(oc get pods -n openshift-cnv -l kubevirt.io=virt-operator "
            "-o jsonpath='{.items[0].metadata.name}' 2>/dev/null) && "
            "oc cp openshift-cnv/$POD:/usr/bin/virtctl /usr/local/bin/virtctl 2>/dev/null && "
            "chmod +x /usr/local/bin/virtctl"
        )
        _, err = _ssh_run(client, fallback_cmd, timeout=60)
        if err and 'error' in err.lower():
            run.append_log(f"{step_label}   virtctl sync failed: {err[:200]}", level='warn')
            db.session.commit()
            return False

    new_ver_out, _ = _ssh_run(
        client,
        "virtctl version --client -o json 2>/dev/null || echo '{}'",
        timeout=SSH_HEALTH_TIMEOUT,
    )
    new_ver = ''
    if new_ver_out:
        try:
            new_ver = json.loads(new_ver_out).get('clientVersion', {}).get('gitVersion', '')
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass

    run.append_log(f"{step_label}   virtctl updated to {new_ver or 'unknown'}", level='ok')
    db.session.commit()
    return True


def cleanup_stale_test_namespaces(client, run, step_label):
    """Delete leftover cnv-sanity/cnv-scale test namespaces from prior runs.

    Stale namespaces contain VMs with the same kube-burner labels, which
    pollutes VM discovery and SSH validation in the next test run.
    """
    from app.models import db

    run.append_log(f"{step_label}   Checking for stale test namespaces...", level='wait')
    db.session.commit()

    ns_out, _ = _ssh_run(
        client,
        "{ oc get ns --no-headers -l kube-burner.io/job 2>/dev/null; "
        "oc get ns --no-headers 2>/dev/null | grep -E '^cnv-(sanity|scale)-'; "
        "} | awk '{print $1}' | sort -u",
        timeout=SSH_HEALTH_TIMEOUT,
    )
    if not ns_out or not ns_out.strip():
        run.append_log(f"{step_label}   No stale test namespaces found", level='ok')
        db.session.commit()
        return True

    stale = [ns.strip() for ns in ns_out.strip().splitlines() if ns.strip()]
    if not stale:
        run.append_log(f"{step_label}   No stale test namespaces found", level='ok')
        db.session.commit()
        return True

    run.append_log(
        f"{step_label}   Found {len(stale)} stale test namespace(s), deleting...",
        level='wait',
    )
    db.session.commit()

    for ns in stale:
        ns_q = shlex.quote(ns)
        _ssh_run(client, f"oc delete ns {ns_q} --wait=false 2>/dev/null", timeout=SSH_HEALTH_TIMEOUT)

    run.append_log(f"{step_label}   Initiated deletion of {len(stale)} stale namespace(s)", level='ok')
    db.session.commit()
    return True


def _wait_cluster_operators_stable(client, run, step_label):
    """Verify no ClusterOperators are degraded or progressing."""
    from app.models import db

    start = time.time()
    while time.time() - start < OPERATOR_HEALTH_TIMEOUT:
        out, _ = _ssh_run(client, "oc get co --no-headers 2>/dev/null", timeout=OPERATOR_HEALTH_POLL)
        if out:
            issues = []
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5:
                    name, available, progressing, degraded = (
                        parts[0], parts[2], parts[3], parts[4]
                    )
                    if available == 'False':
                        issues.append(f"{name}=Unavailable")
                    elif degraded == 'True':
                        issues.append(f"{name}=Degraded")
                    elif progressing == 'True':
                        issues.append(f"{name}=Progressing")

            if not issues:
                run.append_log(f"{step_label}   All ClusterOperators stable", level='ok')
                db.session.commit()
                return True

            summary = ', '.join(issues[:3])
            if len(issues) > 3:
                summary += f" +{len(issues) - 3} more"
            run.append_log(f"{step_label}   COs not stable: {summary}", level='wait')
            db.session.commit()

        time.sleep(OPERATOR_HEALTH_POLL)

    run.append_log(f"{step_label}   ClusterOperator stability timeout", level='fail')
    db.session.commit()
    return False


def _wait_nodes_ready(client, run, step_label):
    """Wait until all nodes report Ready status (post-MCP reboot)."""
    from app.models import db

    start = time.time()
    while time.time() - start < NODE_TIMEOUT:
        out, _ = _ssh_run(
            client, "oc get nodes --no-headers 2>/dev/null",
            timeout=SSH_HEALTH_TIMEOUT,
        )
        if out:
            not_ready = []
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    name, status = parts[0], parts[1]
                    if 'Ready' not in status or 'NotReady' in status:
                        not_ready.append(f"{name}={status}")

            if not not_ready:
                run.append_log(f"{step_label}   All nodes Ready", level='ok')
                db.session.commit()
                return True

            msg = ', '.join(not_ready[:3])
            if len(not_ready) > 3:
                msg += f" +{len(not_ready) - 3} more"
            run.append_log(
                f"{step_label}   Nodes not ready: {msg}", level='wait'
            )
            db.session.commit()
        time.sleep(15)

    run.append_log(
        f"{step_label}   Node readiness timeout after {NODE_TIMEOUT}s",
        level='fail',
    )
    db.session.commit()
    return False
