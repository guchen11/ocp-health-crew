"""Page-rendering routes."""
from urllib.parse import urlparse

from flask import render_template, request, send_from_directory, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import or_

from config.settings import (
    AVAILABLE_CHECKS,
    CATEGORY_ICONS,
    CNV_CATEGORY_ORDER,
    CNV_GLOBAL_VARIABLES,
    CNV_SCENARIO_CATEGORIES,
    CNV_SCENARIOS,
    Config,
)

REPORTS_DIR = Config.REPORTS_DIR
from app.models import CustomCheck, Template

from app.decorators import operator_required

from app.routes import (
    dashboard_bp,
    _DEFAULT_CNV_SETTINGS,
    AVAILABLE_AGENTS,
    DEFAULT_SETTINGS,
    DEFAULT_THRESHOLDS,
    load_builds,
    load_settings,
    queued_jobs,
    running_jobs,
    _jobs_lock,
    get_hosts_for_user,
)

@dashboard_bp.route('/help')
@login_required
def help_page():
    """Help and documentation page"""
    categories = sorted(set(c['category'] for c in AVAILABLE_CHECKS.values()))
    return render_template('help.html',
                           active_page='help',
                           checks=AVAILABLE_CHECKS,
                           categories=categories,
                           category_icons=CATEGORY_ICONS)


@dashboard_bp.route('/')
@login_required
def dashboard():
    """Main dashboard"""
    all_builds = load_builds()

    # Get all running builds
    with _jobs_lock:
        running_list = list(running_jobs.values())

    # Filter for "my builds" if requested
    view = request.args.get('view', 'all')
    display_builds = all_builds
    if view == 'mine' and current_user.is_authenticated:
        display_builds = [b for b in all_builds if b.get('triggered_by') == current_user.username]

    # Calculate stats
    stats = {
        'total': len(all_builds) + len(running_list),
        'running': len(running_list),
        'success': sum(1 for b in all_builds if b.get('status') == 'success'),
        'unstable': sum(1 for b in all_builds if b.get('status') == 'unstable'),
        'failed': sum(1 for b in all_builds if b.get('status') == 'failed')
    }

    # Load user templates for sidebar
    from sqlalchemy import or_
    user_templates = [t.to_dict() for t in
                      Template.query.filter(
                          or_(Template.created_by == current_user.id, Template.shared == True)
                      ).order_by(Template.name).all()] if current_user.is_authenticated else []

    return render_template('dashboard.html',
                           builds=display_builds[:10],
                           recent_builds=display_builds[:10],
                           stats=stats,
                           running_builds=running_list,
                           running_build=running_list[0] if running_list else None,
                           queued_count=len(queued_jobs),
                           current_view=view,
                           user_templates=user_templates,
                           active_page='dashboard')


@dashboard_bp.route('/job/configure')
@operator_required
def configure():
    """Build configuration page"""
    categories = sorted(set(c['category'] for c in AVAILABLE_CHECKS.values()))
    preset = request.args.get('preset', '')
    settings = load_settings()
    thresholds = settings.get('thresholds', DEFAULT_THRESHOLDS)
    ssh_config = settings.get('ssh', DEFAULT_SETTINGS['ssh'])

    host_objects = get_hosts_for_user(current_user)
    saved_hosts = [h.to_dict() for h in host_objects]

    cnv_config = settings.get('cnv', _DEFAULT_CNV_SETTINGS)

    from app.models import CustomCheck
    custom_checks = [c.to_dict() for c in
                     CustomCheck.query.filter_by(created_by=current_user.id, enabled=True).order_by(CustomCheck.name).all()]

    # Load user templates (own + shared by others)
    from sqlalchemy import or_
    user_templates = [t.to_dict() for t in
                      Template.query.filter(
                          or_(Template.created_by == current_user.id, Template.shared == True)
                      ).order_by(Template.name).all()]

    # If loading a specific template
    load_template = None
    template_id = request.args.get('template', type=int)
    if template_id:
        tmpl = Template.query.get(template_id)
        if tmpl and (tmpl.created_by == current_user.id or tmpl.shared or current_user.is_admin):
            load_template = tmpl.to_dict()

    return render_template('configure.html',
                           checks=AVAILABLE_CHECKS,
                           categories=categories,
                           category_icons=CATEGORY_ICONS,
                           preset=preset,
                           thresholds=thresholds,
                           agents=AVAILABLE_AGENTS,
                           ssh_config=ssh_config,
                           saved_hosts=saved_hosts,
                           server_host=ssh_config.get('host', ''),
                           cnv_scenarios=CNV_SCENARIOS,
                           cnv_categories=CNV_SCENARIO_CATEGORIES,
                           cnv_category_order=CNV_CATEGORY_ORDER,
                           cnv_global_vars=CNV_GLOBAL_VARIABLES,
                           cnv_config=cnv_config,
                           custom_checks=custom_checks,
                           user_templates=user_templates,
                           load_template=load_template,
                           active_page='configure')


@dashboard_bp.route('/job/history')
@login_required
def history():
    """Build history page"""
    all_builds = load_builds()
    status_filter = request.args.get('status')
    view = request.args.get('view', 'all')

    filtered_builds = all_builds
    if view == 'mine' and current_user.is_authenticated:
        filtered_builds = [b for b in filtered_builds if b.get('triggered_by') == current_user.username]
    if status_filter:
        filtered_builds = [b for b in filtered_builds if b.get('status') == status_filter]

    return render_template('history.html',
                           builds=filtered_builds,
                           current_view=view,
                           active_page='history')


@dashboard_bp.route('/schedules')
@login_required
def schedules_page():
    """Scheduled tasks page"""
    load_schedules()
    status_filter = request.args.get('status')

    for schedule in schedules:
        schedule['next_run'] = get_next_run_time(schedule)
        schedule['cron_display'] = get_cron_display(schedule)

    filtered_schedules = schedules
    if status_filter:
        filtered_schedules = [s for s in schedules if s.get('status') == status_filter]

    scheduler_status = {
        'active_schedules': sum(1 for s in schedules if s.get('status') == 'active'),
        'runs_today': 0,
        'next_run': min((s.get('next_run') for s in schedules if s.get('status') == 'active' and s.get('next_run')), default=None)
    }

    return render_template('schedules.html',
                           schedules=filtered_schedules,
                           scheduler_status=scheduler_status,
                           active_page='schedules')


@dashboard_bp.route('/job/<int:build_num>')
@login_required
def build_detail(build_num):
    """Build detail page"""
    all_builds = load_builds()
    build = next((b for b in all_builds if b.get('number') == build_num), None)

    if not build:
        with _jobs_lock:
            for job_id, job in running_jobs.items():
                if job.get('number') == build_num:
                    build = job
                    break

    if not build:
        return "Build not found", 404

    # Build CNV scenario metadata lookup (remote_name -> display info)
    cnv_meta = {}
    for sid, sc in CNV_SCENARIOS.items():
        cnv_meta[sc['remote_name']] = {
            'name': sc['name'],
            'icon': sc['icon'],
            'category': sc.get('category', ''),
            'description': sc.get('description', ''),
        }

    settings = load_settings()
    cnv_config = settings.get('cnv', _DEFAULT_CNV_SETTINGS)
    grafana_url = cnv_config.get('grafana_url', '')
    grafana_base = ''
    if grafana_url:
        from urllib.parse import urlparse
        parsed = urlparse(grafana_url)
        grafana_base = f"{parsed.scheme}://{parsed.netloc}"

    return render_template('build_detail.html',
                           build=build,
                           checks=AVAILABLE_CHECKS,
                           cnv_meta=cnv_meta,
                           grafana_url=grafana_url,
                           grafana_base=grafana_base,
                           user_templates=[],
                           active_page='history')


@dashboard_bp.route('/job/<int:build_num>/console')
@login_required
def console_output(build_num):
    """Console output page"""
    all_builds = load_builds()
    build = next((b for b in all_builds if b.get('number') == build_num), None)

    if not build:
        with _jobs_lock:
            for job_id, job in running_jobs.items():
                if job.get('number') == build_num:
                    build = job
                    break

    if not build:
        return "Build not found", 404

    return render_template('console.html', build=build, active_page='history')


@dashboard_bp.route('/job/rebuild/<int:build_num>')
@operator_required
def rebuild(build_num):
    """Rebuild with same parameters"""
    from app.routes.build_executor import start_build

    all_builds = load_builds()
    build = next((b for b in all_builds if b.get('number') == build_num), None)

    if build:
        checks = build.get('checks', list(AVAILABLE_CHECKS.keys()))
        options = build.get('options', {'rca_level': 'none', 'jira': False, 'email': False})
        user_id = current_user.id if current_user.is_authenticated else None
        new_build_num = start_build(checks, options, user_id=user_id)
        return redirect(url_for('dashboard.console_output', build_num=new_build_num))

    return redirect(url_for('dashboard.dashboard'))


@dashboard_bp.route('/report/<filename>')
def serve_report(filename):
    """Serve report files (public, no login required)."""
    return send_from_directory(REPORTS_DIR, filename)


@dashboard_bp.route('/public/report/<filename>')
def serve_report_public(filename):
    """Alias for serve_report - kept for backward-compatible URLs."""
    return serve_report(filename)

