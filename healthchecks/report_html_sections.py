"""HTML subsection builders and shared widgets for Grafana-style health report."""

from healthchecks import hybrid_flags


def _health_card(title, icon, status_ok, value, subtitle="", color_override=None):
    if color_override:
        color = color_override
    else:
        color = "#73BF69" if status_ok else "#F2495C"
    status_class = "ok" if status_ok else "error"
    return f'''
        <div class="panel stat-panel {status_class}">
            <div class="panel-title">{icon} {title}</div>
            <div class="stat-value" style="color:{color}">{value}</div>
            <div class="stat-subtitle">{subtitle}</div>
        </div>'''


def _gauge_panel(title, icon, value, max_val, unit=""):
    pct = (value / max_val * 100) if max_val > 0 else 0
    color = "#73BF69" if pct >= 90 else "#FF9830" if pct >= 70 else "#F2495C"
    return f'''
        <div class="panel gauge-panel">
            <div class="panel-title">{icon} {title}</div>
            <div class="gauge-container">
                <svg viewBox="0 0 120 70" class="gauge-svg">
                    <path d="M 10 60 A 50 50 0 0 1 110 60" fill="none" stroke="#2c3235" stroke-width="8" stroke-linecap="round"/>
                    <path d="M 10 60 A 50 50 0 0 1 110 60" fill="none" stroke="{color}" stroke-width="8" stroke-linecap="round" 
                          stroke-dasharray="{pct * 1.57} 157" class="gauge-fill"/>
                </svg>
                <div class="gauge-value" style="color:{color}">{value}<span class="gauge-max">/{max_val}</span></div>
            </div>
            <div class="gauge-label">{unit}</div>
        </div>'''


def _render_css(issues, status_color):
    """Return CSS rules only (no <style> wrapper)."""
    return f''':root {{
    --bg-canvas: #111217;
    --bg-primary: #181b1f;
    --bg-secondary: #22252b;
    --border: #2c3235;
    --text-primary: #d8d9da;
    --text-secondary: #8e8e8e;
    --green: #73BF69;
    --yellow: #FF9830;
    --red: #F2495C;
    --blue: #5794F2;
    --purple: #B877D9;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg-canvas); color: var(--text-primary); min-height: 100vh; }}

/* Top Navigation */
.navbar {{ background: var(--bg-primary); border-bottom: 1px solid var(--border); padding: 0 24px; height: 52px; display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 100; }}
.navbar-brand {{ display: flex; align-items: center; gap: 12px; }}
.navbar-logo {{ width: 32px; height: 32px; background: linear-gradient(135deg, #FF6B35 0%, #F7931E 100%); border-radius: 8px; display: flex; align-items: center; justify-content: center; font-weight: 700; color: white; }}
.navbar-title {{ font-size: 18px; font-weight: 600; color: var(--text-primary); }}
.navbar-title span {{ color: var(--red); }}
.navbar-status {{ display: flex; align-items: center; gap: 8px; padding: 6px 16px; border-radius: 16px; font-size: 13px; font-weight: 500; background: {"rgba(242,73,92,0.15)" if issues else "rgba(115,191,105,0.15)"}; color: {status_color}; }}
.navbar-status::before {{ content: ''; width: 8px; height: 8px; border-radius: 50%; background: {status_color}; animation: pulse 2s infinite; }}
@keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}

/* Dashboard Container */
.dashboard {{ padding: 24px; max-width: 1800px; margin: 0 auto; }}

/* Dashboard Header */
.dash-header {{ margin-bottom: 24px; }}
.dash-header h1 {{ font-size: 24px; font-weight: 600; margin-bottom: 8px; }}
.dash-meta {{ display: flex; gap: 24px; color: var(--text-secondary); font-size: 13px; }}
.dash-meta span {{ display: flex; align-items: center; gap: 6px; }}

/* Grid Layout */
.grid {{ display: grid; gap: 16px; }}
.grid-4 {{ grid-template-columns: repeat(4, 1fr); }}
.grid-3 {{ grid-template-columns: repeat(3, 1fr); }}
.grid-2 {{ grid-template-columns: repeat(2, 1fr); }}
.grid-full {{ grid-template-columns: 1fr; }}
@media (max-width: 1400px) {{ .grid-4 {{ grid-template-columns: repeat(2, 1fr); }} }}
@media (max-width: 900px) {{ .grid-4, .grid-3, .grid-2 {{ grid-template-columns: 1fr; }} }}

/* Panel Base */
.panel {{ background: var(--bg-primary); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
.panel-title {{ font-size: 12px; font-weight: 500; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; padding: 12px 16px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 8px; }}

/* Stat Panels */
.stat-panel {{ text-align: center; padding-bottom: 16px; }}
.stat-panel.ok {{ border-top: 3px solid var(--green); }}
.stat-panel.error {{ border-top: 3px solid var(--red); }}
.stat-panel.warn {{ border-top: 3px solid var(--yellow); }}
.stat-value {{ font-size: 42px; font-weight: 700; padding: 20px 16px 8px; font-variant-numeric: tabular-nums; }}
.stat-subtitle {{ font-size: 13px; color: var(--text-secondary); }}

/* Gauge Panels */
.gauge-panel {{ text-align: center; padding-bottom: 16px; }}
.gauge-container {{ position: relative; padding: 16px; }}
.gauge-svg {{ width: 120px; height: 70px; }}
.gauge-fill {{ transition: stroke-dasharray 0.5s ease; }}
.gauge-value {{ font-size: 28px; font-weight: 700; margin-top: -10px; }}
.gauge-max {{ font-size: 16px; color: var(--text-secondary); font-weight: 400; }}
.gauge-label {{ font-size: 12px; color: var(--text-secondary); margin-top: 4px; }}

/* Health Check Grid */
.check-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; padding: 16px; }}
.check-card {{ background: var(--bg-secondary); border-radius: 6px; padding: 0; display: flex; flex-direction: column; transition: background 0.2s; cursor: pointer; overflow: hidden; }}
.check-card:hover {{ background: #2a2d33; }}
.check-card-row {{ display: flex; align-items: center; gap: 12px; padding: 14px 16px; }}
.check-icon {{ font-size: 20px; }}
.check-info {{ flex: 1; min-width: 0; }}
.check-name {{ font-size: 13px; font-weight: 500; margin-bottom: 2px; }}
.check-result {{ font-size: 12px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.check-status {{ font-size: 18px; }}
.check-cmd {{ display: none; padding: 8px 16px 12px; border-top: 1px solid var(--border); }}
.check-cmd.show {{ display: block; }}
.check-cmd code {{ display: block; background: #1a1d23; color: #79c0ff; font-family: 'SF Mono', 'Consolas', 'Courier New', monospace; font-size: 11px; padding: 8px 10px; border-radius: 4px; white-space: pre-wrap; word-break: break-all; line-height: 1.5; }}
.check-cmd-label {{ font-size: 10px; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; font-weight: 600; }}
.check-validates {{ font-size: 11px; color: #8b949e; line-height: 1.5; margin-top: 6px; padding: 6px 8px; background: rgba(139,148,158,0.08); border-radius: 4px; border-left: 2px solid #3b82f6; }}
.check-validates-label {{ font-size: 9px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; margin-bottom: 2px; }}
.check-expand {{ font-size: 10px; color: var(--text-secondary); margin-left: auto; transition: transform 0.2s; }}
.check-card.open .check-expand {{ transform: rotate(180deg); }}
.check-section-title {{ grid-column: 1 / -1; font-size: 11px; font-weight: 600; color: var(--blue); text-transform: uppercase; letter-spacing: 1px; padding: 8px 0 4px; border-bottom: 1px solid var(--border); margin-top: 8px; }}

/* Resource Usage */
.resource-header {{ display: grid; grid-template-columns: 200px 1fr 1fr; gap: 16px; padding: 8px 16px; font-size: 11px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; border-bottom: 1px solid var(--border); }}
.resource-body {{ max-height: 400px; overflow-y: auto; }}
.resource-row {{ display: grid; grid-template-columns: 200px 1fr 1fr; gap: 16px; padding: 10px 16px; border-bottom: 1px solid var(--bg-canvas); align-items: center; }}
.resource-row:last-child {{ border-bottom: none; }}
.resource-row:hover {{ background: var(--bg-secondary); }}
.resource-node-name {{ font-family: 'JetBrains Mono', Monaco, monospace; font-size: 12px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.resource-bar-wrap {{ display: flex; align-items: center; gap: 12px; }}
.resource-bar {{ flex: 1; height: 8px; background: var(--bg-canvas); border-radius: 4px; overflow: hidden; }}
.resource-bar-fill {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
.resource-pct {{ font-size: 12px; font-weight: 600; min-width: 45px; text-align: right; font-variant-numeric: tabular-nums; }}

/* Issues Panel */
.issues-body {{ padding: 16px; max-height: 350px; overflow-y: auto; }}
.issue-ns {{ font-size: 12px; font-weight: 600; color: var(--blue); padding: 8px 0 6px; border-bottom: 1px solid var(--border); margin-bottom: 8px; }}
.issue-item {{ display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: var(--bg-secondary); border-radius: 4px; margin-bottom: 6px; font-size: 12px; }}
.issue-name {{ font-family: 'JetBrains Mono', Monaco, monospace; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 70%; }}
.issue-status {{ color: var(--red); font-weight: 500; white-space: nowrap; }}
.issue-more {{ font-size: 11px; color: var(--text-secondary); padding: 4px 0 8px; }}

/* RCA Panel styling */
.rca-panel {{ margin-top: 16px; }}

/* Footer */
.dash-footer {{ margin-top: 32px; padding: 24px; text-align: center; color: var(--text-secondary); font-size: 12px; border-top: 1px solid var(--border); }}
.dash-footer-status {{ font-size: 14px; font-weight: 600; color: {status_color}; margin-bottom: 8px; }}
'''


def _build_resource_rows(data):
    resource_rows = ""
    for node in data["resources"]["nodes"][:12]:
        cpu_pct = node["cpu"]
        mem_pct = node["memory"]
        cpu_color = "#73BF69" if cpu_pct < 70 else "#FF9830" if cpu_pct < 85 else "#F2495C"
        mem_color = "#73BF69" if mem_pct < 70 else "#FF9830" if mem_pct < 85 else "#F2495C"
        resource_rows += f'''
        <div class="resource-row">
            <div class="resource-node-name">{node["name"][:25]}</div>
            <div class="resource-bar-wrap">
                <div class="resource-bar">
                    <div class="resource-bar-fill" style="width:{cpu_pct}%;background:{cpu_color}"></div>
                </div>
                <span class="resource-pct">{cpu_pct}%</span>
            </div>
            <div class="resource-bar-wrap">
                <div class="resource-bar">
                    <div class="resource-bar-fill" style="width:{mem_pct}%;background:{mem_color}"></div>
                </div>
                <span class="resource-pct">{mem_pct}%</span>
            </div>
        </div>'''
    return resource_rows


def _build_issues_html(data):
    pods_by_ns = {}
    for p in data["pods"]["unhealthy"]:
        pods_by_ns.setdefault(p["ns"], []).append(p)
    issues_html = ""
    if pods_by_ns:
        for ns in sorted(pods_by_ns.keys())[:6]:
            issues_html += f'<div class="issue-ns">{ns}</div>'
            for pod in pods_by_ns[ns][:3]:
                issues_html += f'''<div class="issue-item">
                    <span class="issue-name">{pod["name"][:40]}</span>
                    <span class="issue-status">{pod["status"]}</span>
                </div>'''
            if len(pods_by_ns[ns]) > 3:
                issues_html += f'<div class="issue-more">+{len(pods_by_ns[ns])-3} more</div>'
    return issues_html


def _render_navbar(status_text):
    return f'''<nav class="navbar">
    <div class="navbar-brand">
        <div class="navbar-logo">🏥</div>
        <div class="navbar-title">CNV <span>HealthCrew</span> AI</div>
    </div>
    <div class="navbar-status">{status_text}</div>
</nav>
'''


def _render_dash_header(data):
    lab_span = f"<span>🏠 Lab: {hybrid_flags.LAB_NAME}</span>" if hybrid_flags.LAB_NAME else ""
    return f'''    <div class="dash-header">
        <h1>{data["cluster"]}</h1>
        <div class="dash-meta">
            {lab_span}
            <span>📅 {data["timestamp"].strftime("%Y-%m-%d %H:%M:%S")}</span>
            <span>🏷️ Version {data["version"]}</span>
            <span>🔍 17 Health Checks</span>
        </div>
    </div>
'''


def _render_summary_gauges_row(data):
    total_nodes = len(data['nodes']['healthy']) + len(data['nodes']['unhealthy'])
    healthy_nodes = len(data['nodes']['healthy'])
    total_ops = len(data['operators']['healthy']) + len(data['operators']['degraded']) + len(data['operators']['unavailable'])
    healthy_ops = len(data['operators']['healthy'])
    total_pods = data['pods']['healthy'] + len(data['pods']['unhealthy'])
    vms = data['kubevirt']['vms_running']
    max_vms = vms or 1
    return f'''    <div class="grid grid-4" style="margin-bottom:16px;">
        {_gauge_panel("Nodes", "🖥️", healthy_nodes, total_nodes, "Ready")}
        {_gauge_panel("Operators", "⚙️", healthy_ops, total_ops, "Available")}
        {_gauge_panel("Pods", "📦", data['pods']['healthy'], total_pods, "Running")}
        {_gauge_panel("VMs", "💻", vms, max_vms, "Running")}
    </div>
'''


def _render_secondary_health_cards_row(data):
    return f'''    <div class="grid grid-4" style="margin-bottom:16px;">
        {_health_card("etcd Members", "🗄️", not data['etcd']['unhealthy'], data['etcd']['healthy'], "Healthy")}
        {_health_card("PVCs Pending", "💾", not data['pvcs']['pending'], len(data['pvcs']['pending']), "", "#73BF69" if not data['pvcs']['pending'] else "#F2495C")}
        {_health_card("OOM Events", "💥", not data['oom_events'], len(data['oom_events']), "Recent", "#73BF69" if not data['oom_events'] else "#F2495C")}
        {_health_card("Migrations", "🔄", data['migrations']['failed_count'] == 0, data['migrations']['running'], "Running")}
    </div>
'''


def _render_resources_and_issues_panels(data, resource_rows, issues_html):
    unhealthy_pods = len(data['pods']['unhealthy'])
    resource_body = resource_rows if resource_rows else '<div style="padding:40px;text-align:center;color:var(--text-secondary);">No resource data</div>'
    issues_body = issues_html if issues_html else '<div style="padding:40px;text-align:center;color:var(--green);">✅ All pods healthy</div>'
    return f'''    <div class="grid grid-2" style="margin-bottom:16px;">
        <div class="panel">
            <div class="panel-title">📊 Node Resource Usage</div>
            <div class="resource-header">
                <div>Node</div>
                <div>CPU</div>
                <div>Memory</div>
            </div>
            <div class="resource-body">
                {resource_body}
            </div>
        </div>
        <div class="panel">
            <div class="panel-title" style="color:var(--red);">⚠️ Unhealthy Pods ({unhealthy_pods})</div>
            <div class="issues-body">
                {issues_body}
            </div>
        </div>
    </div>
'''


def _render_footer(status_text):
    return f'''    <div class="dash-footer">
        <div class="dash-footer-status">Cluster Status: {status_text}</div>
        <div>Generated by CNV HealthCrew AI | Based on real CNV/OCP Jira bugs</div>
    </div>
'''


def _render_check_cards_script():
    return '''
<script>
document.querySelectorAll('.check-card').forEach(function(card) {
    card.addEventListener('click', function() {
        var cmd = this.querySelector('.check-cmd');
        if (cmd) {
            cmd.classList.toggle('show');
            this.classList.toggle('open');
        }
    });
});
</script>
'''
