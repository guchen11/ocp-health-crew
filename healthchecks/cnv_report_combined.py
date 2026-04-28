"""
CNV + health check combined HTML report.
"""

from datetime import datetime

from .cnv_report import _get_scenario_meta, strip_ansi
from .cnv_report_html_helpers import (
    _render_config_params_html,
    _render_executive_summary,
    _render_pvc_latency_html,
    _render_validation_html,
    _render_vmi_latency_html,
)


def _build_cleanup_console_section(cleanup_output_html):
    """Build the cleanup console output section (avoids nested f-string issues)."""
    if not cleanup_output_html:
        return ""
    return '''
    <div class="panel" style="margin-bottom:16px;">
        <div class="panel-title collapsible-toggle" onclick="this.nextElementSibling.classList.toggle('show'); this.querySelector('.arrow').textContent = this.nextElementSibling.classList.contains('show') ? '\\u25B2' : '\\u25BC'">
            &#x1F4CB; Console: Cleanup <span class="arrow" style="margin-left:auto;font-size:10px;">&#x25BC;</span>
        </div>
        <div class="output-body collapsible-content">''' + cleanup_output_html + '''</div>
    </div>'''


def generate_combined_report_html(cnv_results=None, health_output="",
                                   health_report_file=None,
                                   cleanup_status="skipped",
                                   build_num=0, build_name="",
                                   status="success", status_text="All Passed",
                                   duration="", mode="sanity", server="",
                                   checks=None,
                                   scenario_output="", health_check_output="",
                                   cleanup_output="",
                                   cluster_info=None, run_config=None):
    """Generate a Grafana-style dark HTML report for a combined run.

    Includes: scenario results + health check results + cleanup status.
    """
    checks = checks or []
    meta = _get_scenario_meta()
    cnv_results = cnv_results or {"tests": [], "passed": 0, "failed": 0, "total": 0, "iteration_data": {}}

    tests = cnv_results.get("tests", [])
    passed = cnv_results.get("passed", 0)
    failed = cnv_results.get("failed", 0)
    total = cnv_results.get("total", 0) or len(tests)

    has_failures = failed > 0 or status == 'failed'
    status_color = "#73BF69" if not has_failures else ("#FF9830" if status == "unstable" else "#F2495C")
    navbar_status = "ALL PASSED" if status == "success" else ("ISSUES FOUND" if status == "unstable" else "FAILURES DETECTED")

    pass_rate = int((passed / total * 100) if total > 0 else 0)
    gauge_color = "#73BF69" if pass_rate >= 90 else "#FF9830" if pass_rate >= 60 else "#F2495C"

    cleanup_color = {"success": "#73BF69", "failed": "#F2495C", "skipped": "#8e8e8e"}.get(cleanup_status, "#8e8e8e")
    cleanup_label = {"success": "CLEANED", "failed": "FAILED", "skipped": "SKIPPED"}.get(cleanup_status, "N/A")
    cleanup_icon = {"success": "✅", "failed": "❌", "skipped": "⏭️"}.get(cleanup_status, "—")

    # Parse health check output for key findings
    hc_clean = strip_ansi(health_output) if health_output else ""
    hc_has_issues = any(k in hc_clean for k in ['WARNING', 'Issues:', '⚠️', 'ISSUES'])
    hc_has_errors = any(k in hc_clean for k in ['ERROR', 'CRITICAL', '❌'])
    hc_status = "ERRORS" if hc_has_errors else ("WARNINGS" if hc_has_issues else "HEALTHY")
    hc_status_color = "#F2495C" if hc_has_errors else ("#FF9830" if hc_has_issues else "#73BF69")
    hc_status_icon = "❌" if hc_has_errors else ("⚠️" if hc_has_issues else "✅")

    # Extract health report summary lines
    hc_summary_lines = []
    in_report = False
    for line in hc_clean.split('\n'):
        stripped = line.strip()
        if 'HEALTH REPORT' in stripped or 'Health Report' in stripped:
            in_report = True
            continue
        if in_report:
            if stripped.startswith('=') and len(stripped) > 20:
                if hc_summary_lines:
                    break
                continue
            if stripped:
                hc_summary_lines.append(stripped)
            if len(hc_summary_lines) > 60:
                break

    hc_findings_html = ""
    if hc_summary_lines:
        for line in hc_summary_lines[:50]:
            escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            hc_findings_html += f'<div style="font-size:12px;color:var(--text-secondary);padding:2px 0;font-family:monospace;">{escaped}</div>'
    else:
        hc_findings_html = '<div style="font-size:13px;color:var(--text-secondary);padding:8px 0;">Health check output available in console section below.</div>'

    # Build scenario result cards (same logic as generate_cnv_report_html)
    scenario_cards = ""
    categories = {}
    for t in tests:
        m = meta.get(t["name"], {})
        cat = m.get("category", "Other")
        categories.setdefault(cat, []).append(t)

    if not categories and tests:
        categories = {"Scenarios": tests}

    cat_order = ["Resource Limits", "Hot-plug", "Performance", "Scale", "Other", "Scenarios"]
    for cat in cat_order:
        if cat not in categories:
            continue
        cat_tests = categories[cat]
        cat_icon = {"Resource Limits": "📏", "Hot-plug": "🔌", "Performance": "⚡", "Scale": "📊"}.get(cat, "🔥")
        scenario_cards += f'<div class="check-section-title">{cat_icon} {cat}</div>'

        for t in cat_tests:
            m = meta.get(t["name"], {})
            icon = m.get("icon", "🔥")
            display_name = m.get("name", t["name"])
            description = m.get("description", "")
            is_pass = t["status"] == "PASS"
            s_color = "#73BF69" if is_pass else "#F2495C"
            s_icon = "✅" if is_pass else "❌"
            s_label = "PASSED" if is_pass else "FAILED"
            val = t.get("validation", "N/A")
            dur = t.get("duration_str", "N/A")
            dur_secs = t.get("duration_secs", 0)
            max_dur = max((tt.get("duration_secs", 1) for tt in tests), default=1) or 1
            dur_pct = min(int(dur_secs / max_dur * 100), 100) if dur_secs else 5

            scenario_cards += f'''
        <div class="check-card" onclick="this.classList.toggle('open')">
            <div class="check-card-row">
                <span class="check-icon">{icon}</span>
                <div class="check-info">
                    <div class="check-name">{display_name}</div>
                    <div class="check-result">{t["name"]} &middot; {val}</div>
                </div>
                <div style="display:flex;align-items:center;gap:12px;">
                    <div style="text-align:right;">
                        <div style="font-size:12px;font-weight:600;color:{s_color};">{s_label}</div>
                        <div style="font-size:11px;color:var(--text-secondary);">{dur}</div>
                    </div>
                    <span class="check-status">{s_icon}</span>
                    <span class="check-expand">▼</span>
                </div>
            </div>
            <div class="check-cmd">
                <div style="font-size:12px;color:var(--text-secondary);margin-bottom:8px;line-height:1.5;">{description}</div>
                <div style="display:flex;gap:16px;">
                    <div><div class="check-cmd-label">Validation</div><div style="font-size:13px;color:var(--text-primary);">{val}</div></div>
                    <div><div class="check-cmd-label">Duration</div><div style="font-size:13px;color:var(--text-primary);">{dur}</div></div>
                </div>
                <div style="height:6px;background:var(--bg-canvas);border-radius:3px;overflow:hidden;margin-top:8px;">
                    <div style="height:100%;width:{dur_pct}%;background:{s_color};border-radius:3px;"></div>
                </div>
            </div>
        </div>'''

    # Build iteration detail sections (latency, PVC, validation)
    iteration_data = cnv_results.get("iteration_data", {})
    detail_sections_html = ""
    if iteration_data:
        for t in tests:
            tname = t["name"]
            idata = iteration_data.get(tname, {})
            if not idata:
                continue
            m = meta.get(tname, {})
            icon = m.get("icon", "🔥")
            display_name = m.get("name", tname)
            section_content = ""

            vmi_lat = idata.get("vmi_latency")
            if vmi_lat:
                section_content += f'''
                <div style="margin-bottom:16px;">
                    <div style="font-size:11px;font-weight:600;color:var(--orange);text-transform:uppercase;letter-spacing:1px;padding:8px 0;border-bottom:1px solid var(--border);">🏎️ VM Boot Latency</div>
                    <div style="padding:8px 0;">{_render_vmi_latency_html(vmi_lat)}</div>
                </div>'''

            pvc_lat = idata.get("pvc_latency")
            if pvc_lat:
                section_content += f'''
                <div style="margin-bottom:16px;">
                    <div style="font-size:11px;font-weight:600;color:var(--orange);text-transform:uppercase;letter-spacing:1px;padding:8px 0;border-bottom:1px solid var(--border);">💾 PVC Latency</div>
                    <div style="padding:8px 0;">{_render_pvc_latency_html(pvc_lat)}</div>
                </div>'''

            validation = idata.get("validation")
            if validation:
                section_content += f'''
                <div style="margin-bottom:16px;">
                    <div style="font-size:11px;font-weight:600;color:var(--orange);text-transform:uppercase;letter-spacing:1px;padding:8px 0;border-bottom:1px solid var(--border);">🔍 Validation Details</div>
                    <div style="padding:8px 0;">{_render_validation_html(validation)}</div>
                </div>'''

            if section_content:
                detail_sections_html += f'''
    <div class="panel" style="margin-bottom:16px;">
        <div class="panel-title collapsible-toggle" onclick="this.nextElementSibling.classList.toggle('show'); this.querySelector('.arrow').textContent = this.nextElementSibling.classList.contains('show') ? '▲' : '▼'">
            {icon} {display_name} — Detailed Results <span class="arrow" style="margin-left:auto;font-size:10px;">▼</span>
        </div>
        <div class="collapsible-content show" style="padding:16px;">{section_content}</div>
    </div>'''

    # Console output sections
    def _clean_output(raw):
        lines = raw.strip().split('\n') if raw else []
        clean = []
        in_data = False
        for l in lines:
            if '__CNV_ITERATION_DATA_START__' in l or '__CNV_CLUSTER_INFO_START__' in l:
                in_data = True
                continue
            if '__CNV_ITERATION_DATA_END__' in l or '__CNV_CLUSTER_INFO_END__' in l:
                in_data = False
                continue
            if not in_data:
                clean.append(strip_ansi(l).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
        return '<br>'.join(clean[-80:])

    scenario_output_html = _clean_output(scenario_output)
    hc_output_html = _clean_output(health_check_output)
    cleanup_output_html = _clean_output(cleanup_output) if cleanup_output else ""

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Executive summary (test scope + cluster environment)
    exec_summary_html = _render_executive_summary(tests, meta, cluster_info)

    # Configuration parameters section
    config_section_html = _render_config_params_html(run_config, checks, mode)

    html = f'''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>CNV Combined Report — Build #{build_num}</title>
<style>
:root {{
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
    --orange: #FF6B35;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg-canvas); color: var(--text-primary); min-height: 100vh; }}
.navbar {{ background: var(--bg-primary); border-bottom: 1px solid var(--border); padding: 0 24px; height: 52px; display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 100; }}
.navbar-brand {{ display: flex; align-items: center; gap: 12px; }}
.navbar-logo {{ width: 32px; height: 32px; background: linear-gradient(135deg, #8b5cf6 0%, #6366f1 100%); border-radius: 8px; display: flex; align-items: center; justify-content: center; font-weight: 700; color: white; font-size: 18px; }}
.navbar-title {{ font-size: 18px; font-weight: 600; color: var(--text-primary); }}
.navbar-title span {{ color: var(--purple); }}
.navbar-status {{ display: flex; align-items: center; gap: 8px; padding: 6px 16px; border-radius: 16px; font-size: 13px; font-weight: 500; background: {"rgba(115,191,105,0.15)" if status == "success" else "rgba(242,73,92,0.15)" if status == "failed" else "rgba(255,152,48,0.15)"}; color: {status_color}; }}
.navbar-status::before {{ content: ''; width: 8px; height: 8px; border-radius: 50%; background: {status_color}; animation: pulse 2s infinite; }}
@keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}
.dashboard {{ padding: 24px; max-width: 1800px; margin: 0 auto; }}
.dash-header {{ margin-bottom: 24px; }}
.dash-header h1 {{ font-size: 24px; font-weight: 600; margin-bottom: 8px; }}
.dash-meta {{ display: flex; gap: 24px; flex-wrap: wrap; color: var(--text-secondary); font-size: 13px; }}
.dash-meta span {{ display: flex; align-items: center; gap: 6px; }}
.grid {{ display: grid; gap: 16px; }}
.grid-5 {{ grid-template-columns: repeat(5, 1fr); }}
.grid-4 {{ grid-template-columns: repeat(4, 1fr); }}
@media (max-width: 1400px) {{ .grid-5 {{ grid-template-columns: repeat(3, 1fr); }} .grid-4 {{ grid-template-columns: repeat(2, 1fr); }} }}
@media (max-width: 900px) {{ .grid-5, .grid-4 {{ grid-template-columns: 1fr; }} }}
.panel {{ background: var(--bg-primary); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
.panel-title {{ font-size: 12px; font-weight: 500; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; padding: 12px 16px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 8px; }}
.stat-panel {{ text-align: center; padding-bottom: 16px; }}
.stat-panel.ok {{ border-top: 3px solid var(--green); }}
.stat-panel.error {{ border-top: 3px solid var(--red); }}
.stat-panel.warn {{ border-top: 3px solid var(--yellow); }}
.stat-value {{ font-size: 36px; font-weight: 700; padding: 16px 16px 6px; font-variant-numeric: tabular-nums; }}
.stat-subtitle {{ font-size: 12px; color: var(--text-secondary); }}
.gauge-panel {{ text-align: center; padding-bottom: 16px; }}
.gauge-container {{ position: relative; padding: 16px; }}
.gauge-svg {{ width: 120px; height: 70px; }}
.gauge-value {{ font-size: 28px; font-weight: 700; margin-top: -10px; }}
.gauge-max {{ font-size: 16px; color: var(--text-secondary); font-weight: 400; }}
.gauge-label {{ font-size: 12px; color: var(--text-secondary); margin-top: 4px; }}
.check-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; padding: 16px; }}
.check-card {{ background: var(--bg-secondary); border-radius: 6px; cursor: pointer; overflow: hidden; }}
.check-card:hover {{ background: #2a2d33; }}
.check-card-row {{ display: flex; align-items: center; gap: 12px; padding: 14px 16px; }}
.check-icon {{ font-size: 20px; }}
.check-info {{ flex: 1; min-width: 0; }}
.check-name {{ font-size: 13px; font-weight: 500; margin-bottom: 2px; }}
.check-result {{ font-size: 12px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.check-status {{ font-size: 18px; }}
.check-cmd {{ display: none; padding: 12px 16px 16px; border-top: 1px solid var(--border); }}
.check-card.open .check-cmd {{ display: block; }}
.check-cmd-label {{ font-size: 10px; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; font-weight: 600; }}
.check-expand {{ font-size: 10px; color: var(--text-secondary); transition: transform 0.2s; }}
.check-card.open .check-expand {{ transform: rotate(180deg); }}
.check-section-title {{ grid-column: 1 / -1; font-size: 11px; font-weight: 600; color: var(--orange); text-transform: uppercase; letter-spacing: 1px; padding: 8px 0 4px; border-bottom: 1px solid var(--border); margin-top: 8px; }}
.output-body {{ padding: 16px; font-family: 'SF Mono', 'Consolas', monospace; font-size: 12px; line-height: 1.6; color: var(--text-secondary); max-height: 400px; overflow-y: auto; background: var(--bg-canvas); }}
.dash-footer {{ margin-top: 32px; padding: 24px; text-align: center; color: var(--text-secondary); font-size: 12px; border-top: 1px solid var(--border); }}
.collapsible-toggle {{ cursor: pointer; user-select: none; }}
.collapsible-content {{ display: none; }}
.collapsible-content.show {{ display: block; }}
.phase-badge {{ display: inline-block; padding: 6px 16px; border-radius: 6px; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; text-transform: uppercase; }}
</style>
</head>
<body>

<nav class="navbar">
    <div class="navbar-brand">
        <div class="navbar-logo">🧬</div>
        <div class="navbar-title">CNV <span>Combined</span></div>
    </div>
    <div class="navbar-status">{navbar_status}</div>
</nav>

<div class="dashboard">
    <div class="dash-header">
        <h1>CNV Combined Report{f' — {build_name}' if build_name else ''}</h1>
        <div class="dash-meta">
            <span>🔢 Build #{build_num}</span>
            {"<span>🖥️ " + server + "</span>" if server else ""}
            <span>📅 {now}</span>
            <span>⏱️ {duration}</span>
            <span>🎯 {mode.upper()} mode</span>
            <span>🔥 {total} Scenarios</span>
        </div>
    </div>

    <!-- Pipeline Summary -->
    <div class="grid grid-5" style="margin-bottom:16px;">
        <div class="panel gauge-panel">
            <div class="panel-title">📊 Pass Rate</div>
            <div class="gauge-container">
                <svg viewBox="0 0 120 70" class="gauge-svg">
                    <path d="M 10 60 A 50 50 0 0 1 110 60" fill="none" stroke="#2c3235" stroke-width="8" stroke-linecap="round"/>
                    <path d="M 10 60 A 50 50 0 0 1 110 60" fill="none" stroke="{gauge_color}" stroke-width="8" stroke-linecap="round" stroke-dasharray="{pass_rate * 1.57} 157"/>
                </svg>
                <div class="gauge-value" style="color:{gauge_color}">{pass_rate}<span class="gauge-max">%</span></div>
            </div>
            <div class="gauge-label">{passed}/{total} Scenarios</div>
        </div>
        <div class="panel stat-panel {"ok" if passed > 0 else "warn"}">
            <div class="panel-title">✅ Passed</div>
            <div class="stat-value" style="color:var(--green)">{passed}</div>
            <div class="stat-subtitle">Scenarios</div>
        </div>
        <div class="panel stat-panel {"error" if failed > 0 else "ok"}">
            <div class="panel-title">{"❌" if failed > 0 else "✅"} Failed</div>
            <div class="stat-value" style="color:{"var(--red)" if failed > 0 else "var(--green)"}">{failed}</div>
            <div class="stat-subtitle">Scenarios</div>
        </div>
        <div class="panel stat-panel" style="border-top:3px solid {hc_status_color};">
            <div class="panel-title">🩺 Health Check</div>
            <div class="stat-value" style="color:{hc_status_color};font-size:24px;">{hc_status_icon} {hc_status}</div>
            <div class="stat-subtitle">Cluster Status</div>
        </div>
        <div class="panel stat-panel" style="border-top:3px solid {cleanup_color};">
            <div class="panel-title">🧹 Cleanup</div>
            <div class="stat-value" style="color:{cleanup_color};font-size:24px;">{cleanup_icon} {cleanup_label}</div>
            <div class="stat-subtitle">Resource Cleanup</div>
        </div>
    </div>

    <!-- Executive Summary -->
    {exec_summary_html}

    <!-- Configuration Parameters -->
    {config_section_html}

    <!-- Phase 1: Scenario Results -->
    <div class="panel" style="margin-bottom:16px;">
        <div class="panel-title">🔥 Phase 1 — Scenario Results</div>
        <div class="check-grid">{scenario_cards}</div>
    </div>

    {detail_sections_html}

    <!-- Phase 2: Health Check Results -->
    <div class="panel" style="margin-bottom:16px;">
        <div class="panel-title collapsible-toggle" onclick="this.nextElementSibling.classList.toggle('show'); this.querySelector('.arrow').textContent = this.nextElementSibling.classList.contains('show') ? '▲' : '▼'">
            🩺 Phase 2 — Health Check Results
            <span class="phase-badge" style="background:{hc_status_color}22;color:{hc_status_color};margin-left:auto;">{hc_status_icon} {hc_status}</span>
            <span class="arrow" style="margin-left:8px;font-size:10px;">▼</span>
        </div>
        <div class="collapsible-content show" style="padding:16px;">
            {hc_findings_html}
            {f'<div style="margin-top:12px;"><a href="/report/{health_report_file}" style="color:var(--blue);font-size:13px;text-decoration:none;">📄 View Full Health Report →</a></div>' if health_report_file else ''}
        </div>
    </div>

    <!-- Phase 3: Cleanup Status -->
    <div class="panel" style="margin-bottom:16px;">
        <div class="panel-title">
            🧹 Phase 3 — Cleanup
            <span class="phase-badge" style="background:{cleanup_color}22;color:{cleanup_color};margin-left:auto;">{cleanup_icon} {cleanup_label}</span>
        </div>
        <div style="padding:16px;">
            <div style="font-size:13px;color:var(--text-secondary);">
                {"Test resources were cleaned up successfully after the health check." if cleanup_status == "success" else "Cleanup failed — test resources may still exist on the cluster." if cleanup_status == "failed" else "Cleanup was skipped — test resources remain on the cluster."}
            </div>
        </div>
    </div>

    <!-- Console Output: Scenarios -->
    <div class="panel" style="margin-bottom:16px;">
        <div class="panel-title collapsible-toggle" onclick="this.nextElementSibling.classList.toggle('show'); this.querySelector('.arrow').textContent = this.nextElementSibling.classList.contains('show') ? '▲' : '▼'">
            📋 Console: Scenarios <span class="arrow" style="margin-left:auto;font-size:10px;">▼</span>
        </div>
        <div class="output-body collapsible-content">{scenario_output_html}</div>
    </div>

    <!-- Console Output: Health Check -->
    <div class="panel" style="margin-bottom:16px;">
        <div class="panel-title collapsible-toggle" onclick="this.nextElementSibling.classList.toggle('show'); this.querySelector('.arrow').textContent = this.nextElementSibling.classList.contains('show') ? '▲' : '▼'">
            📋 Console: Health Check <span class="arrow" style="margin-left:auto;font-size:10px;">▼</span>
        </div>
        <div class="output-body collapsible-content">{hc_output_html}</div>
    </div>

    {_build_cleanup_console_section(cleanup_output_html)}

    <div class="dash-footer">
        <div style="font-size:14px;font-weight:600;color:{status_color};margin-bottom:8px;">{navbar_status}</div>
        Generated by CNV HealthCrew Combined &middot; {now}
    </div>
</div>

</body>
</html>'''

    return html
