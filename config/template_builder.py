"""Shared helper for building CNV scenario template dicts."""


def build_template(name, description, icon, mode, tests, env_vars,
                   timeout='2h', parallel=False, email=True, os_type=''):
    """Build a template dict with standard structure."""
    config = {
        'task_type': 'cnv_scenarios',
        'run_name': name,
        'scenario_mode': mode,
        'scenario_tests': tests,
        'scenario_parallel': parallel,
        'kb_timeout': timeout,
        'kb_log_level': '',
        'email': email,
        'env_vars': env_vars,
    }
    if os_type:
        config['scenario_os'] = os_type
    return {
        'name': name,
        'description': description,
        'icon': icon,
        'config': config,
    }
