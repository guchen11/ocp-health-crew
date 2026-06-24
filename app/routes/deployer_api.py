"""Deployer config and run API routes.

Manages saved deployer YAML configs and triggers deployer runs via SSH
to the bastion where openshift-deployer is installed.
"""

import logging
import threading
from datetime import datetime, timezone

from flask import current_app, jsonify, request
from flask_login import current_user, login_required

from app.decorators import log_audit, operator_required
from app.models import db
from app.models_operators import DeployerConfig, DeployerRun
from app.routes import dashboard_bp
from app.routes.operators_executor import _get_ssh_and_kubeconfig, _sanitize_log
from app.ssh_utils import ssh_exec, quote

log = logging.getLogger(__name__)

DEPLOYER_PATH = '/root/openshift-deployer'
DEPLOYER_CONFIGS_DIR = '/root'


@dashboard_bp.route('/api/deployer/configs', methods=['GET'])
@login_required
def api_deployer_configs_list():
    """List all saved deployer configs."""
    configs = (DeployerConfig.query
               .order_by(DeployerConfig.updated_at.desc())
               .all())
    return jsonify([c.to_dict() for c in configs])


@dashboard_bp.route('/api/deployer/configs', methods=['POST'])
@operator_required
def api_deployer_configs_create():
    """Create or update a deployer config."""
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    config_yaml = data.get('config_yaml', '').strip()

    if not name or not config_yaml:
        return jsonify({'error': 'Name and YAML are required'}), 400

    if not config_yaml.startswith('version:'):
        config_yaml = 'version: 0.0.0\n\n' + config_yaml

    config_id = data.get('id')
    if config_id:
        cfg = db.session.get(DeployerConfig, config_id)
        if not cfg:
            return jsonify({'error': 'Config not found'}), 404
        cfg.name = name
        cfg.description = data.get('description', '')
        cfg.config_yaml = config_yaml
    else:
        cfg = DeployerConfig(
            name=name,
            description=data.get('description', ''),
            config_yaml=config_yaml,
            created_by=current_user.id,
        )
        db.session.add(cfg)

    db.session.commit()
    return jsonify(cfg.to_dict())


@dashboard_bp.route('/api/deployer/configs/<int:config_id>', methods=['DELETE'])
@operator_required
def api_deployer_configs_delete(config_id):
    """Delete a deployer config."""
    cfg = db.session.get(DeployerConfig, config_id)
    if not cfg:
        return jsonify({'error': 'Not found'}), 404
    db.session.delete(cfg)
    db.session.commit()
    return jsonify({'status': 'deleted'})


@dashboard_bp.route('/api/deployer/configs/<int:config_id>/run', methods=['POST'])
@operator_required
def api_deployer_run(config_id):
    """Trigger a deployer run for a saved config."""
    cfg = db.session.get(DeployerConfig, config_id)
    if not cfg:
        return jsonify({'error': 'Config not found'}), 404

    data = request.get_json(silent=True) or {}
    phase = data.get('phase', 'post_deploy')
    if phase not in ('pre_deploy', 'deploy', 'post_deploy'):
        return jsonify({'error': 'Invalid phase'}), 400

    run = DeployerRun(
        config_id=cfg.id,
        config_name=cfg.name,
        phase=phase,
        status='running',
        triggered_by=current_user.id,
    )
    db.session.add(run)
    db.session.commit()

    log_audit(
        action='deployer_run',
        target=cfg.name,
        details=f"Running deployer config '{cfg.name}' phase={phase}",
    )

    app = current_app._get_current_object()
    threading.Thread(
        target=_execute_deployer_run,
        args=(app, run.id, cfg.config_yaml, phase),
        daemon=True,
    ).start()

    return jsonify({'id': run.id, 'status': 'running'})


@dashboard_bp.route('/api/deployer/runs', methods=['GET'])
@login_required
def api_deployer_runs_list():
    """List deployer run history."""
    runs = (DeployerRun.query
            .order_by(DeployerRun.started_at.desc())
            .limit(20)
            .all())
    return jsonify([r.to_dict() for r in runs])


@dashboard_bp.route('/api/deployer/runs/<int:run_id>', methods=['GET'])
@login_required
def api_deployer_run_status(run_id):
    """Get deployer run status and log."""
    run = db.session.get(DeployerRun, run_id)
    if not run:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(run.to_dict())


def _execute_deployer_run(app, run_id, config_yaml, phase):
    """Background: write config to bastion and run the deployer."""
    with app.app_context():
        run = db.session.get(DeployerRun, run_id)
        try:
            client, kubeconfig = _get_ssh_and_kubeconfig()
        except Exception as exc:
            run.append_log(f'SSH connection failed: {exc}')
            run.status = 'failed'
            run.finished_at = datetime.now(timezone.utc)
            db.session.commit()
            return

        try:
            config_file = f'/tmp/deployer-run-{run_id}.yaml'
            run.append_log(f'Uploading config to {config_file}')

            ssh_exec(client,
                     f'cat > {quote(config_file)} << \'DEPLOYER_EOF\'\n'
                     f'{config_yaml}\nDEPLOYER_EOF',
                     kubeconfig=None, timeout=10)
            db.session.commit()

            run.append_log(f'Running: ocp_deployer --phase {phase}')
            db.session.commit()

            cmd = (
                f'export KUBECONFIG={quote(kubeconfig)} && '
                f'cd {quote(DEPLOYER_PATH)} && '
                f'uv run python3 -m ocp_deployer '
                f'--config {quote(config_file)} --phase {quote(phase)} 2>&1'
            )
            stdout, stderr = ssh_exec(client, cmd, kubeconfig=None,
                                      timeout=600)

            output = _sanitize_log(stdout or stderr or '')
            run.append_log(output)

            if 'Error' in output or 'error' in output.lower():
                run.status = 'failed'
            else:
                run.status = 'success'
        except Exception as exc:
            run.append_log(f'Execution error: {exc}')
            run.status = 'failed'
        finally:
            client.close()
            run.finished_at = datetime.now(timezone.utc)
            db.session.commit()
