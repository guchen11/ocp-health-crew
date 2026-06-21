"""Post-upgrade health validation - CR conditions, rollouts, pods, storage."""
import json
import logging
import shlex
import time

from app.routes.upgrade_pre_checks import (
    _ssh_run, _wait_cluster_operators_stable, _wait_nodes_ready,
    OPERATOR_HEALTH_TIMEOUT, OPERATOR_HEALTH_POLL, SSH_HEALTH_TIMEOUT,
)

log = logging.getLogger(__name__)

_OPERATOR_CR_MAP = {
    'kubevirt-hyperconverged': {
        'resource': 'hyperconverged/kubevirt-hyperconverged',
    },
    'ocs-operator': {
        'resource': 'storagecluster/ocs-storagecluster',
        'extra_checks': ['ceph', 'odf_pods'],
    },
    'odf-operator': {
        'resource': 'storagecluster/ocs-storagecluster',
        'extra_checks': ['ceph', 'odf_pods'],
    },
}

_STORAGE_NAMESPACES = {'openshift-storage'}

_ODF_SUB_NAMES = {
    'ocs-operator', 'odf-operator', 'odf-dependencies',
    'cephcsi-operator', 'mcg-operator', 'ocs-client-operator',
    'odf-csi-addons-operator', 'odf-external-snapshotter-operator',
    'odf-prometheus-operator', 'recipe', 'rook-ceph-operator',
}


def _is_storage_operator(sub_name, namespace):
    """Check if this is a storage/ODF-related operator."""
    if namespace in _STORAGE_NAMESPACES:
        return True
    for known in _ODF_SUB_NAMES:
        if known in sub_name:
            return True
    return False


def wait_operator_healthy(client, namespace, sub_name, run, step_label):
    """Full post-upgrade validation. Checks in order:
    1. CR conditions (for known operators)
    2. Deployment/DaemonSet rollouts
    3. Pod readiness
    4. Storage-specific checks (Ceph health, OSD, MDS for ODF operators)
    5. ClusterOperator conditions (if applicable)
    """
    from app.models import db
    cr_info = _OPERATOR_CR_MAP.get(sub_name)

    if cr_info:
        ok = _wait_cr_healthy(client, namespace, cr_info, run, step_label, sub_name)
        if not ok:
            return False

    run.append_log(f"{step_label}   Checking Deployment/DaemonSet rollouts...", level='wait')
    db.session.commit()
    if not _wait_rollouts_complete(client, namespace, run, step_label):
        return False

    run.append_log(f"{step_label}   Checking pod readiness...", level='wait')
    db.session.commit()
    if not _wait_pods_healthy(client, namespace, run, step_label):
        return False

    if _is_storage_operator(sub_name, namespace):
        run.append_log(f"{step_label}   Storage operator - checking Ceph/ODF health...", level='wait')
        db.session.commit()
        if not _wait_ceph_healthy(client, namespace, run, step_label):
            return False

    run.append_log(f"{step_label}   Checking MachineConfigPool rollouts...", level='wait')
    db.session.commit()
    if not _wait_mcp_stable(client, run, step_label):
        return False

    run.append_log(f"{step_label}   Checking all nodes Ready...", level='wait')
    db.session.commit()
    if not _wait_nodes_ready(client, run, step_label):
        return False

    run.append_log(f"{step_label}   Checking ClusterOperator stability...", level='wait')
    db.session.commit()
    if not _wait_cluster_operators_stable(client, run, step_label):
        return False

    return True


def _wait_cr_healthy(client, namespace, cr_info, run, step_label, name):
    """Poll a CR's conditions until Available=True, Degraded=False."""
    from app.models import db
    resource = cr_info['resource']
    ns_q = shlex.quote(namespace)

    start = time.time()
    last_msg = ''
    while time.time() - start < OPERATOR_HEALTH_TIMEOUT:
        out, _ = _ssh_run(
            client, f"oc get {resource} -n {ns_q} -o json 2>/dev/null", timeout=OPERATOR_HEALTH_POLL,
        )
        if out:
            try:
                conditions = {
                    c.get('type', ''): c
                    for c in json.loads(out).get('status', {}).get('conditions', [])
                }
                available = conditions.get('Available', {}).get('status', '')
                degraded = conditions.get('Degraded', {}).get('status', '')
                progressing = conditions.get('Progressing', {}).get('status', '')

                if available == 'True' and degraded == 'False' and progressing == 'False':
                    run.append_log(f"{step_label}   {name} CR conditions: healthy", level='ok')
                    db.session.commit()
                    return True

                msg = f"Available={available} Degraded={degraded} Progressing={progressing}"
                if msg != last_msg:
                    run.append_log(f"{step_label}   {name}: {msg}", level='wait')
                    db.session.commit()
                    last_msg = msg
            except (json.JSONDecodeError, ValueError):
                pass

        time.sleep(OPERATOR_HEALTH_POLL)

    return False


def _wait_rollouts_complete(client, namespace, run, step_label):
    """Wait until all Deployments and DaemonSets are fully rolled out."""
    from app.models import db
    ns_q = shlex.quote(namespace)

    start = time.time()
    while time.time() - start < OPERATOR_HEALTH_TIMEOUT:
        pending = []

        dep_out, _ = _ssh_run(
            client, f"oc get deploy -n {ns_q} -o json 2>/dev/null", timeout=OPERATOR_HEALTH_POLL,
        )
        if dep_out:
            try:
                for d in json.loads(dep_out).get('items', []):
                    name = d['metadata']['name']
                    replicas = d.get('spec', {}).get('replicas', 1)
                    st = d.get('status', {})
                    ready = st.get('readyReplicas', 0)
                    updated = st.get('updatedReplicas', 0)
                    unavail = st.get('unavailableReplicas', 0)
                    if ready < replicas or updated < replicas or unavail > 0:
                        pending.append(f"deploy/{name} ({ready}/{replicas})")
            except (json.JSONDecodeError, ValueError, KeyError):
                pass

        ds_out, _ = _ssh_run(
            client, f"oc get daemonset -n {ns_q} -o json 2>/dev/null", timeout=OPERATOR_HEALTH_POLL,
        )
        if ds_out:
            try:
                for d in json.loads(ds_out).get('items', []):
                    name = d['metadata']['name']
                    st = d.get('status', {})
                    desired = st.get('desiredNumberScheduled', 0)
                    ready = st.get('numberReady', 0)
                    unavail = st.get('numberUnavailable', 0)
                    if ready < desired or unavail > 0:
                        pending.append(f"ds/{name} ({ready}/{desired})")
            except (json.JSONDecodeError, ValueError, KeyError):
                pass

        if not pending:
            run.append_log(f"{step_label}   All rollouts complete", level='ok')
            db.session.commit()
            return True

        summary = ', '.join(pending[:3])
        if len(pending) > 3:
            summary += f" +{len(pending) - 3} more"
        run.append_log(f"{step_label}   Rollouts pending: {summary}", level='wait')
        db.session.commit()
        time.sleep(OPERATOR_HEALTH_POLL)

    run.append_log(f"{step_label}   Rollout timeout after {OPERATOR_HEALTH_TIMEOUT}s", level='fail')
    db.session.commit()
    return False


def _wait_pods_healthy(client, namespace, run, step_label):
    """Wait until all pods in namespace are Running/Completed."""
    from app.models import db
    ns_q = shlex.quote(namespace)

    start = time.time()
    while time.time() - start < OPERATOR_HEALTH_TIMEOUT:
        out, _ = _ssh_run(
            client, f"oc get pods -n {ns_q} --no-headers 2>/dev/null", timeout=OPERATOR_HEALTH_POLL,
        )
        if out:
            not_ready = []
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[2] not in ('Running', 'Completed', 'Succeeded'):
                    not_ready.append(f"{parts[0]}={parts[2]}")

            if not not_ready:
                run.append_log(f"{step_label}   All pods healthy", level='ok')
                db.session.commit()
                return True

            if len(not_ready) <= 3:
                run.append_log(f"{step_label}   Pods not ready: {', '.join(not_ready)}", level='wait')
            else:
                run.append_log(f"{step_label}   {len(not_ready)} pods not ready", level='wait')
            db.session.commit()
        time.sleep(OPERATOR_HEALTH_POLL)

    return False


def _wait_ceph_healthy(client, namespace, run, step_label):
    """Verify Ceph/ODF storage is healthy after upgrade.

    Checks:
    - CephCluster CR health (HEALTH_OK)
    - All OSDs are up and in
    - MDS daemons active (for CephFS)
    - MGR daemon active
    - StorageCluster phase = Ready
    - No PGs in degraded/recovering/backfilling state
    """
    from app.models import db
    ns_q = shlex.quote(namespace)

    start = time.time()
    while time.time() - start < OPERATOR_HEALTH_TIMEOUT:
        issues = []

        cc_out, _ = _ssh_run(
            client,
            f"oc get cephcluster -n {ns_q} -o json 2>/dev/null",
            timeout=SSH_HEALTH_TIMEOUT,
        )
        if cc_out:
            try:
                items = json.loads(cc_out).get('items', [])
                for cc in items:
                    name = cc['metadata']['name']
                    ceph_st = cc.get('status', {}).get('ceph', {})
                    health = ceph_st.get('health', '')
                    phase = cc.get('status', {}).get('phase', '')

                    if phase != 'Ready':
                        issues.append(f"CephCluster/{name} phase={phase}")
                    if health and health != 'HEALTH_OK':
                        issues.append(f"CephCluster/{name} health={health}")
                        details = ceph_st.get('details', {})
                        for key, val in (details or {}).items():
                            msg = val.get('message', '')[:80] if isinstance(val, dict) else str(val)[:80]
                            issues.append(f"  {key}: {msg}")
            except (json.JSONDecodeError, ValueError, KeyError):
                pass

        sc_out, _ = _ssh_run(
            client,
            f"oc get storagecluster -n {ns_q} -o json 2>/dev/null",
            timeout=OPERATOR_HEALTH_POLL,
        )
        if sc_out:
            try:
                for sc in json.loads(sc_out).get('items', []):
                    phase = sc.get('status', {}).get('phase', '')
                    if phase and phase != 'Ready':
                        issues.append(f"StorageCluster/{sc['metadata']['name']} phase={phase}")
            except (json.JSONDecodeError, ValueError, KeyError):
                pass

        osd_out, _ = _ssh_run(
            client,
            f"oc get pods -n {ns_q} -l app=rook-ceph-osd --no-headers 2>/dev/null",
            timeout=OPERATOR_HEALTH_POLL,
        )
        if osd_out:
            for line in osd_out.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[2] != 'Running':
                    issues.append(f"OSD {parts[0]}={parts[2]}")
                elif len(parts) >= 2 and '/' in parts[1]:
                    ready, total = parts[1].split('/')
                    if ready != total:
                        issues.append(f"OSD {parts[0]} containers {parts[1]}")

        mds_out, _ = _ssh_run(
            client,
            f"oc get pods -n {ns_q} -l app=rook-ceph-mds --no-headers 2>/dev/null",
            timeout=OPERATOR_HEALTH_POLL,
        )
        if mds_out:
            for line in mds_out.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[2] != 'Running':
                    issues.append(f"MDS {parts[0]}={parts[2]}")

        mgr_out, _ = _ssh_run(
            client,
            f"oc get pods -n {ns_q} -l app=rook-ceph-mgr --no-headers 2>/dev/null",
            timeout=OPERATOR_HEALTH_POLL,
        )
        if mgr_out:
            for line in mgr_out.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[2] != 'Running':
                    issues.append(f"MGR {parts[0]}={parts[2]}")

        if not issues:
            run.append_log(f"{step_label}   Ceph/ODF storage: healthy", level='ok')
            db.session.commit()
            return True

        summary = '; '.join(issues[:4])
        if len(issues) > 4:
            summary += f" +{len(issues) - 4} more"
        run.append_log(f"{step_label}   Storage: {summary}", level='wait')
        db.session.commit()
        time.sleep(OPERATOR_HEALTH_POLL)

    run.append_log(f"{step_label}   Storage health timeout after {OPERATOR_HEALTH_TIMEOUT}s", level='fail')
    db.session.commit()
    return False


MCP_TIMEOUT = 3600


def _wait_mcp_stable(client, run, step_label):
    """Wait until all MachineConfigPools are Updated and not Degraded.

    MCP rollouts happen when operator upgrades trigger machine config
    changes (e.g. CNV, ODF). Nodes reboot one by one per pool, which
    can take 10-30 minutes depending on pool size.
    """
    from app.models import db

    start = time.time()
    first_check = True
    while time.time() - start < MCP_TIMEOUT:
        out, _ = _ssh_run(
            client, "oc get mcp --no-headers 2>/dev/null",
            timeout=SSH_HEALTH_TIMEOUT,
        )
        if out:
            updating = []
            degraded = []
            for line in out.splitlines():
                parts = line.split()
                if len(parts) < 5:
                    continue
                name = parts[0]
                config_match = parts[1] if len(parts) > 1 else ''
                is_updated = parts[2] if len(parts) > 2 else ''
                is_updating = parts[3] if len(parts) > 3 else ''
                is_degraded = parts[4] if len(parts) > 4 else ''

                if is_degraded == 'True':
                    degraded.append(name)
                elif is_updating == 'True' or is_updated == 'False':
                    mc_from = parts[5] if len(parts) > 5 else ''
                    mc_to = parts[6] if len(parts) > 6 else ''
                    ready_count = ''
                    if len(parts) > 7:
                        ready_count = f" ({parts[7]} ready)"
                    updating.append(f"{name}{ready_count}")

            if degraded:
                run.append_log(
                    f"{step_label}   MCP degraded: {', '.join(degraded)}",
                    level='fail',
                )
                db.session.commit()
                return False

            if not updating:
                run.append_log(
                    f"{step_label}   All MachineConfigPools updated",
                    level='ok',
                )
                db.session.commit()
                return True

            msg = ', '.join(updating[:3])
            if len(updating) > 3:
                msg += f" +{len(updating) - 3} more"
            run.append_log(
                f"{step_label}   MCP updating: {msg}", level='wait'
            )
            db.session.commit()
            first_check = False

        time.sleep(30)

    run.append_log(
        f"{step_label}   MCP rollout timeout after {MCP_TIMEOUT}s",
        level='fail',
    )
    db.session.commit()
    return False


