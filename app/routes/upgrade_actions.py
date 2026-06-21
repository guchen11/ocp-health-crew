"""Upgrade pipeline actions - test and chained upgrade steps."""
import json
import logging
import shlex
import time

from app.routes.upgrade_pre_checks import _ssh_run

log = logging.getLogger(__name__)

# Shared upgrade timing constants
CVO_POLL_INTERVAL = 30
CVO_TIMEOUT = 7200
OLM_POLL_INTERVAL = 15
OLM_TIMEOUT = 1800
SSH_CMD_TIMEOUT = 30
SSH_CMD_TIMEOUT_LONG = 60


def build_upgrade_tag(run):
    """Build a descriptive tag for post-upgrade test names and options."""
    op = run.operator_name
    ver_from = run.from_version or ''
    ver_to = run.to_version or ''
    utype = 'CVO' if run.upgrade_type == 'cvo' else 'OLM'
    if ver_from and ver_to:
        label = f"[{utype} Upgrade: {op} {ver_from} -> {ver_to}]"
    else:
        label = f"[Post-Upgrade Test: {op}]"
    return {
        'label': label,
        'upgrade_run_id': run.id,
        'upgrade_type': run.upgrade_type,
        'operator_name': op,
        'from_version': ver_from,
        'to_version': ver_to,
    }


def trigger_post_upgrade(run, app):
    """Trigger the post-upgrade actions defined in the policy (sequential)."""
    with app.app_context():
        from app.models import UpgradeRun, db

        run = UpgradeRun.query.get(run.id)
        if not run or not run.policy:
            return

        actions = run.policy.post_upgrade_actions or []
        tag = build_upgrade_tag(run)

        if not actions:
            run.test_status = 'skipped'
            run.append_log("No post-upgrade actions configured")
            db.session.commit()
            return

        run.test_status = 'running'
        run.append_log(f"Running {len(actions)} pipeline step(s)")
        db.session.commit()

        all_ok = True
        for idx, action_def in enumerate(actions):
            action_type = action_def.get('type', 'none')
            action_id = action_def.get('id')
            step_label = f"[{idx + 1}/{len(actions)}]"

            run.append_log(f"{step_label} Starting: {action_type}"
                           + (f" (#{action_id})" if action_id else ''))
            db.session.commit()

            try:
                ok = _run_single_action(run, action_def, tag, app, step_label)
                if not ok:
                    all_ok = False
                    run.append_log(f"{step_label} Failed, stopping pipeline")
                    db.session.commit()
                    break
            except Exception as exc:
                all_ok = False
                run.append_log(f"{step_label} Error: {exc}")
                db.session.commit()
                log.error("Pipeline step %d failed: %s", idx, exc)
                break

        run.test_status = 'success' if all_ok else 'failed'
        run.append_log(
            "All pipeline steps completed"
            if all_ok else "Pipeline stopped on failure"
        )
        db.session.commit()


def _run_single_action(run, action_def, tag, app, step_label):
    """Execute one pipeline step. Returns True on success."""
    from app.models import SuiteRun, Template, db
    from app.routes.build_executor import start_build
    from app.routes.suite_executor import run_suite

    action_type = action_def.get('type', 'none')
    action_id = action_def.get('id')
    user_id = run.created_by or run.policy.created_by

    if action_type == 'upgrade_cvo':
        return _chain_cvo_upgrade(run, tag, app, step_label)

    if action_type == 'upgrade_olm':
        target = action_def.get('target', '*')
        namespace = action_def.get('namespace', '')
        return _chain_olm_upgrade(run, target, namespace, tag, app, step_label)

    if action_type in ('test_suite', 'template', 'health_check'):
        if not _pre_test_health_gate(run, step_label):
            return False

    if action_type == 'test_suite' and action_id:
        from app.models import TestSuite
        suite = TestSuite.query.get(action_id)
        if not suite:
            run.append_log(f"{step_label} Suite #{action_id} not found", level='fail')
            return False

        run_items = []
        for item in (suite.items or []):
            cfg = dict(item.get('config', {}))
            cfg['_upgrade_context'] = tag
            orig_name = cfg.get('run_name', item.get('template_name', ''))
            cfg['run_name'] = f"{tag['label']} {orig_name}"
            run_items.append({
                'template_name': item.get('template_name', ''),
                'config': cfg,
                'item_status': 'pending',
                'build_number': None,
            })

        suite_run = SuiteRun(
            suite_id=suite.id,
            name=f"{tag['label']} {step_label} {suite.name}",
            status='pending',
            created_by=user_id,
            stop_on_failure=suite.stop_on_failure,
            items=run_items,
            total_items=len(run_items),
        )
        db.session.add(suite_run)
        db.session.commit()

        run.test_suite_run_id = suite_run.id
        run.append_log(f"{step_label} Started suite run #{suite_run.id} ({len(run_items)} items)")
        run.append_log(f"{step_label} Waiting for suite to complete...", level='wait')
        db.session.commit()

        run_suite(suite_run.id, user_id)
        return _wait_for_suite_run(suite_run.id)

    elif action_type == 'template' and action_id:
        tmpl = Template.query.get(action_id)
        if not tmpl:
            run.append_log(f"{step_label} Template #{action_id} not found", level='fail')
            return False

        config = tmpl.config or {}
        checks = config.get('scenario_tests', [])
        if not checks:
            checks = config.get('_checks', config.get('checks', []))
        options = dict(config)
        options.pop('_checks', None)
        options.pop('checks', None)
        options['run_name'] = f"{tag['label']} {step_label} {tmpl.name}"
        options['_upgrade_context'] = tag

        build_num = start_build(checks, options, user_id=user_id)
        run.test_build_number = build_num
        run.append_log(f"{step_label} Started build #{build_num}: {tmpl.name}")
        run.append_log(f"{step_label} Waiting for build to complete...", level='wait')
        db.session.commit()
        return _wait_for_build_completion(build_num)

    elif action_type == 'health_check':
        from config.settings import AVAILABLE_CHECKS
        options = {
            'task_type': 'health_check',
            'rca_level': 'none',
            'run_name': f"{tag['label']} {step_label} Health Check",
            '_upgrade_context': tag,
        }
        checks = list(AVAILABLE_CHECKS.keys())
        build_num = start_build(checks, options, user_id=user_id)
        run.test_build_number = build_num
        run.append_log(f"{step_label} Started health check build #{build_num}")
        run.append_log(f"{step_label} Waiting for health check to complete...", level='wait')
        db.session.commit()
        return _wait_for_build_completion(build_num)

    return True


def _pre_test_health_gate(run, step_label):
    """Block test actions until cluster operators, storage, virtctl, and namespaces are ready."""
    from app.models import db
    from app.routes.upgrade_health import _wait_ceph_healthy
    from app.routes.upgrade_pre_checks import (
        _wait_cluster_operators_stable, sync_virtctl_version,
        cleanup_stale_test_namespaces,
    )
    from app.ssh_utils import create_ssh_client

    run.append_log(f"{step_label} Health gate: waiting for cluster stability...", level='wait')
    db.session.commit()

    try:
        client = create_ssh_client()
    except Exception as exc:
        run.append_log(f"{step_label} Health gate SSH failed: {exc}", level='fail')
        db.session.commit()
        return False

    try:
        if not _wait_cluster_operators_stable(client, run, step_label):
            run.append_log(f"{step_label} Health gate failed: ClusterOperators not stable", level='fail')
            db.session.commit()
            return False

        run.append_log(f"{step_label} Health gate: checking Ceph/ODF storage...", level='wait')
        db.session.commit()

        if not _wait_ceph_healthy(client, 'openshift-storage', run, step_label):
            run.append_log(f"{step_label} Health gate failed: storage not healthy", level='fail')
            db.session.commit()
            return False

        if not sync_virtctl_version(client, run, step_label):
            run.append_log(f"{step_label} Health gate: virtctl sync failed (non-blocking)", level='warn')
            db.session.commit()

        cleanup_stale_test_namespaces(client, run, step_label)

        run.append_log(f"{step_label} Health gate passed: cluster stable", level='ok')
        db.session.commit()
        return True
    finally:
        client.close()


def _chain_cvo_upgrade(run, tag, app, step_label):
    """Run a CVO cluster upgrade as a chained pipeline step."""
    from app.models import db
    from app.routes.upgrade_scanner import scan_cvo
    from app.routes.upgrade_executor import _preflight_cvo
    from app.ssh_utils import create_ssh_client

    run.append_log(f"{step_label} Scanning for cluster version updates...", level='wait')
    db.session.commit()

    try:
        client = create_ssh_client()
    except Exception as exc:
        run.append_log(f"{step_label} SSH connection failed: {exc}", level='fail')
        db.session.commit()
        return False

    try:
        cvo = scan_cvo(client)
        updates = cvo.get('available_updates', [])
        if not updates:
            run.append_log(f"{step_label} No CVO updates available, skipping", level='skip')
            db.session.commit()
            return 'skipped'

        if not cvo.get('upgradeable', True):
            run.append_log(f"{step_label} Cluster upgrade BLOCKED:", level='warn')
            for w in cvo.get('warnings', []):
                run.append_log(f"  {w}", level='warn')
            db.session.commit()
            return False

        to_version = updates[-1]['version']
        from_version = cvo.get('current_version', '')
        run.append_log(f"{step_label} Pre-flight checks...", level='wait')
        db.session.commit()

        if not _preflight_cvo(client, run, db):
            return False

        run.append_log(f"{step_label} Applying cluster upgrade: {from_version} -> {to_version}", level='phase')
        db.session.commit()

        version_q = shlex.quote(to_version)
        stdout, stderr = _ssh_run(client, f"oc adm upgrade --to={version_q} 2>&1", timeout=SSH_CMD_TIMEOUT_LONG)
        run.append_log(f"{step_label} {stdout or stderr}")
        run.append_log(f"{step_label} Waiting for cluster rollout...", level='wait')
        db.session.commit()

        start = time.time()
        last_progress = ''
        while time.time() - start < CVO_TIMEOUT:
            cv_out, _ = _ssh_run(client, "oc get clusterversion version -o json", timeout=SSH_CMD_TIMEOUT)
            if cv_out:
                try:
                    cv = json.loads(cv_out)
                    conds = {c['type']: c for c in cv.get('status', {}).get('conditions', [])}
                    desired = cv.get('status', {}).get('desired', {}).get('version', '')
                    if (desired == to_version
                            and conds.get('Progressing', {}).get('status') == 'False'
                            and conds.get('Available', {}).get('status') == 'True'):
                        run.append_log(f"{step_label} Cluster upgraded to {to_version}", level='ok')
                        db.session.commit()
                        tag['from_version'] = from_version
                        tag['to_version'] = to_version
                        tag['label'] = f"[CVO Upgrade: {from_version} -> {to_version}]"
                        return True

                    prog_msg = conds.get('Progressing', {}).get('message', '')[:150]
                    if prog_msg and prog_msg != last_progress:
                        run.append_log(f"{step_label} {prog_msg}", level='wait')
                        db.session.commit()
                        last_progress = prog_msg
                except (json.JSONDecodeError, ValueError):
                    pass
            time.sleep(CVO_POLL_INTERVAL)

        run.append_log(f"{step_label} Cluster upgrade timed out after {CVO_TIMEOUT}s", level='fail')
        db.session.commit()
        return False
    finally:
        client.close()


def _chain_olm_upgrade(run, target, namespace, tag, app, step_label):
    """Run OLM operator upgrade(s) as a chained pipeline step."""
    from app.models import db
    from app.routes.upgrade_scanner import scan_olm
    from app.ssh_utils import create_ssh_client

    target_label = target if target and target != '*' else 'all operators'
    run.append_log(f"{step_label} Scanning OLM subscriptions ({target_label})...", level='wait')
    db.session.commit()

    try:
        client = create_ssh_client()
    except Exception as exc:
        run.append_log(f"{step_label} SSH connection failed: {exc}", level='fail')
        db.session.commit()
        return False

    try:
        olm_data = scan_olm(client)
        is_wildcard = not target or target == '*'
        matches = [s for s in olm_data
                   if (not namespace or s['namespace'] == namespace)
                   and (is_wildcard or s['name'] == target)]

        if not matches:
            run.append_log(f"{step_label} No pending OLM upgrades found, skipping", level='skip')
            db.session.commit()
            return 'skipped'

        if is_wildcard and len(matches) > 1:
            deferred = len(matches) - 1
            run.append_log(
                f"{step_label} Found {len(matches)} pending upgrade(s), "
                f"upgrading only the first; {deferred} deferred to next scan cycle"
            )
            for m in matches:
                run.append_log(f"  - {m['name']} ({m['namespace']}): {m.get('installed_csv','')} -> {m.get('current_csv','')}")
            matches = matches[:1]
        else:
            run.append_log(f"{step_label} Found {len(matches)} operator(s) to upgrade:")
            for m in matches:
                run.append_log(f"  - {m['name']} ({m['namespace']}): {m.get('installed_csv','')} -> {m.get('current_csv','')}")
        db.session.commit()

        match = matches[0]
        ns = match['namespace']
        run.append_log(f"{step_label} Upgrading {match['name']}", level='phase')
        db.session.commit()

        plans_out, _ = _ssh_run(client, f"oc get installplan -n {shlex.quote(ns)} -o json", timeout=SSH_CMD_TIMEOUT)
        approved_count = 0
        if plans_out:
            try:
                for plan in json.loads(plans_out).get('items', []):
                    if not plan.get('spec', {}).get('approved', True):
                        pname = shlex.quote(plan['metadata']['name'])
                        cmd = f"oc patch installplan {pname} -n {shlex.quote(ns)} --type merge -p '{{\"spec\":{{\"approved\":true}}}}'"
                        _ssh_run(client, cmd, timeout=OLM_POLL_INTERVAL)
                        run.append_log(f"{step_label}   Approved InstallPlan: {plan['metadata']['name']}")
                        approved_count += 1
            except (json.JSONDecodeError, ValueError, KeyError):
                pass

        if approved_count == 0:
            run.append_log(f"{step_label}   No pending InstallPlans, checking CSV directly")

        target_csv = match.get('current_csv', '')
        run.append_log(f"{step_label}   Waiting for CSV {target_csv}...", level='wait')
        db.session.commit()

        start = time.time()
        succeeded = False
        while time.time() - start < OLM_TIMEOUT:
            csv_out, _ = _ssh_run(client, f"oc get csv -n {shlex.quote(ns)} -o json 2>/dev/null", timeout=SSH_CMD_TIMEOUT)
            if csv_out:
                try:
                    for c in json.loads(csv_out).get('items', []):
                        if c['metadata']['name'] == target_csv and c.get('status', {}).get('phase') == 'Succeeded':
                            succeeded = True
                            break
                except (json.JSONDecodeError, ValueError, KeyError):
                    pass
            if succeeded:
                break
            time.sleep(OLM_POLL_INTERVAL)

        if not succeeded:
            run.append_log(f"{step_label}   CSV {target_csv} did not reach Succeeded", level='fail')
            db.session.commit()
            return False

        run.append_log(f"{step_label}   CSV succeeded, validating operator health...", level='wait')
        db.session.commit()

        healthy = _wait_operator_healthy(client, ns, match['name'], run, step_label)
        if healthy:
            run.append_log(f"{step_label}   {match['name']} fully healthy", level='ok')
            db.session.commit()
        else:
            run.append_log(f"{step_label}   {match['name']} not healthy after upgrade", level='fail')
            db.session.commit()
            return False

        run.from_version = match.get('installed_csv', '')
        run.to_version = match.get('current_csv', '')
        tag['operator_name'] = match['name']
        tag['from_version'] = match.get('installed_csv', '')
        tag['to_version'] = match.get('current_csv', '')
        tag['label'] = f"[OLM Upgrade: {match['name']} {tag['from_version']} -> {tag['to_version']}]"

        rd = dict(run.report_data or {})
        rd.setdefault('upgrades', []).append({
            'operator': match['name'],
            'namespace': ns,
            'from_version': match.get('installed_csv', ''),
            'to_version': match.get('current_csv', ''),
            'status': 'success',
        })
        from sqlalchemy.orm.attributes import flag_modified
        run.report_data = rd
        flag_modified(run, 'report_data')

        run.append_log(f"{step_label} Operator {match['name']} upgraded successfully", level='ok')
        db.session.commit()
        return True
    finally:
        client.close()


def _wait_operator_healthy(client, namespace, sub_name, run, step_label):
    """Delegate to upgrade_health module for full post-upgrade validation."""
    from app.routes.upgrade_health import wait_operator_healthy
    return wait_operator_healthy(client, namespace, sub_name, run, step_label)


def _wait_for_build_completion(build_num, timeout=172800):
    """Wait for a build to finish. Returns True if success/unstable."""
    from app.models import Build, db
    from app.routes import running_jobs, _jobs_lock

    start = time.time()
    while time.time() - start < timeout:
        with _jobs_lock:
            still_running = any(
                j.get('number') == build_num for j in running_jobs.values()
            )
        if not still_running:
            for _ in range(5):
                db.session.expire_all()
                build = Build.query.filter_by(build_number=build_num).first()
                if build:
                    return build.status in ('success', 'unstable')
                time.sleep(1)
            return False
        time.sleep(3)
    return False


def _wait_for_suite_run(suite_run_id, timeout=172800):
    """Wait for a suite run to finish. Returns True if completed."""
    from app.models import SuiteRun, db

    start = time.time()
    while time.time() - start < timeout:
        db.session.expire_all()
        sr = SuiteRun.query.get(suite_run_id)
        if sr and sr.status in ('completed', 'failed', 'aborted'):
            return sr.status == 'completed'
        time.sleep(5)
    return False
