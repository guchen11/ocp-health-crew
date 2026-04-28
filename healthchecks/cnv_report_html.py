"""
CNV scenarios full-page HTML report (Grafana-style dashboard).
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


def generate_cnv_report_html(results, build_num=0, build_name="",
                              status="success", status_text="All Passed",
                              duration="", mode="sanity", server="",
                              checks=None, output="", cluster_info=None,
                              run_config=None):
    """Generate a Grafana-style dark HTML report for CNV scenario results.

    Parameters
    ----------
    results : dict
        Output from ``parse_cnv_results`` with keys: tests, passed, failed, total.
    build_num : int
    build_name : str
    status : str  -- 'success' | 'unstable' | 'failed'
    status_text : str
    duration : str  -- e.g. "4m 32s"
    mode : str  -- 'sanity' | 'full'
    server : str
    checks : list  -- scenario names that were requested
    output : str  -- raw console output for the collapsible section
    run_config : dict  -- full options dict for the configuration section
    """
    checks = checks or []
    meta = _get_scenario_meta()
    tests = results.get("tests", [])
    passed = results.get("passed", 0)
    failed = results.get("failed", 0)
    total = results.get("total", 0) or len(tests)

    has_failures = failed > 0 or status == 'failed'
    status_color = "#73BF69" if not has_failures else ("#FF9830" if status == "unstable" else "#F2495C")
    navbar_status = "ALL PASSED" if not has_failures else ("PARTIAL PASS" if status == "unstable" else "FAILURES DETECTED")

    # Pass rate for gauge
    pass_rate = int((passed / total * 100) if total > 0 else 0)
    gauge_color = "#73BF69" if pass_rate >= 90 else "#FF9830" if pass_rate >= 60 else "#F2495C"

    # Total duration from tests
    total_test_secs = sum(t.get("duration_secs", 0) for t in tests)
    total_test_dur = f"{total_test_secs // 60}m {total_test_secs % 60}s" if total_test_secs else duration

    # Build scenario result cards
    scenario_cards = ""
    # Group by category
    categories = {}
    for t in tests:
        m = meta.get(t["name"], {})
        cat = m.get("category", "Other")
        categories.setdefault(cat, []).append(t)

    # If no categories resolved, use flat list
    if not categories and tests:
        categories = {"Scenarios": tests}

    cat_order = ["Resource Limits", "Hot-plug", "Performance", "Scale", "Other", "Scenarios"]
    for cat in cat_order:
        if cat not in categories:
            continue
        cat_tests = categories[cat]
        cat_icon = {"Resource Limits": "📏", "Hot-plug": "🔌", "Performance": "⚡", "Scale": "📊"}.get(cat, "🔥")
        scenario_cards += f'''
        <div class="check-section-title">{cat_icon} {cat}</div>'''

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

            # Duration bar (relative to longest test)
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
                <div class="check-cmd-label">Description</div>
                <div style="font-size:12px;color:var(--text-secondary);margin-bottom:8px;line-height:1.5;">{description}</div>
                <div style="display:flex;gap:16px;margin-bottom:8px;">
                    <div>
                        <div class="check-cmd-label">Validation</div>
                        <div style="font-size:13px;color:var(--text-primary);font-weight:500;">{val}</div>
                    </div>
                    <div>
                        <div class="check-cmd-label">Duration</div>
                        <div style="font-size:13px;color:var(--text-primary);font-weight:500;">{dur}</div>
                    </div>
                    <div>
                        <div class="check-cmd-label">Category</div>
                        <div style="font-size:13px;color:var(--text-primary);font-weight:500;">{cat}</div>
                    </div>
                </div>
                <div class="check-cmd-label">Duration Bar</div>
                <div style="height:6px;background:var(--bg-canvas);border-radius:3px;overflow:hidden;margin-top:4px;">
                    <div style="height:100%;width:{dur_pct}%;background:{s_color};border-radius:3px;"></div>
                </div>
            </div>
        </div>'''

    # ── Build per-test detail sections (latency, PVC, validation) ──────
    iteration_data = results.get("iteration_data", {})
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

            # VMI Latency
            vmi_lat = idata.get("vmi_latency")
            if vmi_lat:
                vmi_html = _render_vmi_latency_html(vmi_lat)
                section_content += f'''
                <div style="margin-bottom:16px;">
                    <div style="font-size:11px;font-weight:600;color:var(--orange);text-transform:uppercase;letter-spacing:1px;padding:8px 0 8px;border-bottom:1px solid var(--border);">🏎️ VM Boot Latency</div>
                    <div style="padding:8px 0;">{vmi_html}</div>
                </div>'''

            # PVC Latency
            pvc_lat = idata.get("pvc_latency")
            if pvc_lat:
                pvc_html = _render_pvc_latency_html(pvc_lat)
                section_content += f'''
                <div style="margin-bottom:16px;">
                    <div style="font-size:11px;font-weight:600;color:var(--orange);text-transform:uppercase;letter-spacing:1px;padding:8px 0 8px;border-bottom:1px solid var(--border);">💾 PVC Latency</div>
                    <div style="padding:8px 0;">{pvc_html}</div>
                </div>'''

            # Validation Details
            validation = idata.get("validation")
            if validation:
                val_html = _render_validation_html(validation)
                section_content += f'''
                <div style="margin-bottom:16px;">
                    <div style="font-size:11px;font-weight:600;color:var(--orange);text-transform:uppercase;letter-spacing:1px;padding:8px 0 8px;border-bottom:1px solid var(--border);">🔍 Validation Details</div>
                    <div style="padding:8px 0;">{val_html}</div>
                </div>'''

            if section_content:
                detail_sections_html += f'''
    <div class="panel" style="margin-bottom:16px;">
        <div class="panel-title collapsible-toggle" onclick="this.nextElementSibling.classList.toggle('show'); this.querySelector('.arrow').textContent = this.nextElementSibling.classList.contains('show') ? '▲' : '▼'">
            {icon} {display_name} — Detailed Results <span class="arrow" style="margin-left:auto;font-size:10px;">▼</span>
        </div>
        <div class="collapsible-content show" style="padding:16px;">
            {section_content}
        </div>
    </div>'''

    # Build output excerpt (collapsible)
    output_lines = output.strip().split('\n') if output else []
    # Find summary section
    summary_start = None
    for i, line in enumerate(output_lines):
        if any(k in line for k in ['Results Summary', 'SUMMARY', 'scenarios complete', 'CNV Scenarios complete']):
            summary_start = max(0, i - 2)
            break
    if summary_start is not None:
        excerpt_lines = output_lines[summary_start:]
    else:
        excerpt_lines = output_lines[-50:]

    # More robust: filter out lines between markers
    clean_excerpt = []
    in_data_block = False
    for l in excerpt_lines:
        if '__CNV_ITERATION_DATA_START__' in l or '__CNV_CLUSTER_INFO_START__' in l:
            in_data_block = True
            continue
        if '__CNV_ITERATION_DATA_END__' in l or '__CNV_CLUSTER_INFO_END__' in l:
            in_data_block = False
            continue
        if not in_data_block:
            clean_excerpt.append(l)

    output_html = '<br>'.join(
        strip_ansi(l).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        for l in clean_excerpt
    )

    # Timestamp
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Executive summary (test scope + cluster environment)
    exec_summary_html = _render_executive_summary(tests, meta, cluster_info)

    # Configuration parameters section
    config_section_html = _render_config_params_html(run_config, checks, mode)

    html = f'''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>CNV Scenarios Report — Build #{build_num}</title>
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

/* Top Navigation */
.navbar {{ background: var(--bg-primary); border-bottom: 1px solid var(--border); padding: 0 24px; height: 52px; display: flex; align-items: center; justify-content: space-between; position: sticky; top: 0; z-index: 100; }}
.navbar-brand {{ display: flex; align-items: center; gap: 12px; }}
.navbar-logo {{ width: 32px; height: 32px; background: linear-gradient(135deg, #FF6B35 0%, #F7931E 100%); border-radius: 8px; display: flex; align-items: center; justify-content: center; font-weight: 700; color: white; font-size: 18px; }}
.navbar-title {{ font-size: 18px; font-weight: 600; color: var(--text-primary); }}
.navbar-title span {{ color: var(--orange); }}
.navbar-status {{ display: flex; align-items: center; gap: 8px; padding: 6px 16px; border-radius: 16px; font-size: 13px; font-weight: 500; background: {"rgba(115,191,105,0.15)" if not has_failures else "rgba(242,73,92,0.15)"}; color: {status_color}; }}
.navbar-status::before {{ content: ''; width: 8px; height: 8px; border-radius: 50%; background: {status_color}; animation: pulse 2s infinite; }}
@keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}

/* Dashboard Container */
.dashboard {{ padding: 24px; max-width: 1800px; margin: 0 auto; }}

/* Dashboard Header */
.dash-header {{ margin-bottom: 24px; }}
.dash-header h1 {{ font-size: 24px; font-weight: 600; margin-bottom: 8px; }}
.dash-meta {{ display: flex; gap: 24px; flex-wrap: wrap; color: var(--text-secondary); font-size: 13px; }}
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

/* Check Grid */
.check-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; padding: 16px; }}
.check-card {{ background: var(--bg-secondary); border-radius: 6px; padding: 0; display: flex; flex-direction: column; transition: background 0.2s; cursor: pointer; overflow: hidden; }}
.check-card:hover {{ background: #2a2d33; }}
.check-card-row {{ display: flex; align-items: center; gap: 12px; padding: 14px 16px; }}
.check-icon {{ font-size: 20px; }}
.check-info {{ flex: 1; min-width: 0; }}
.check-name {{ font-size: 13px; font-weight: 500; margin-bottom: 2px; }}
.check-result {{ font-size: 12px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.check-status {{ font-size: 18px; }}
.check-cmd {{ display: none; padding: 12px 16px 16px; border-top: 1px solid var(--border); }}
.check-cmd.show {{ display: block; }}
.check-card.open .check-cmd {{ display: block; }}
.check-cmd-label {{ font-size: 10px; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; font-weight: 600; }}
.check-expand {{ font-size: 10px; color: var(--text-secondary); margin-left: auto; transition: transform 0.2s; }}
.check-card.open .check-expand {{ transform: rotate(180deg); }}
.check-section-title {{ grid-column: 1 / -1; font-size: 11px; font-weight: 600; color: var(--orange); text-transform: uppercase; letter-spacing: 1px; padding: 8px 0 4px; border-bottom: 1px solid var(--border); margin-top: 8px; }}

/* Output Panel */
.output-body {{ padding: 16px; font-family: 'SF Mono', 'Consolas', 'Courier New', monospace; font-size: 12px; line-height: 1.6; color: var(--text-secondary); max-height: 500px; overflow-y: auto; background: var(--bg-canvas); }}

/* Footer */
.dash-footer {{ margin-top: 32px; padding: 24px; text-align: center; color: var(--text-secondary); font-size: 12px; border-top: 1px solid var(--border); }}
.dash-footer-status {{ font-size: 14px; font-weight: 600; color: {status_color}; margin-bottom: 8px; }}

/* Collapsible */
.collapsible-toggle {{ cursor: pointer; user-select: none; }}
.collapsible-content {{ display: none; }}
.collapsible-content.show {{ display: block; }}
</style>
</head>
<body>

<nav class="navbar">
    <div class="navbar-brand">
        <div class="navbar-logo">🔥</div>
        <div class="navbar-title">CNV <span>Scenarios</span></div>
    </div>
    <div class="navbar-status">{navbar_status}</div>
</nav>

<div class="dashboard">
    <div class="dash-header">
        <h1>CNV Scenarios Report{f' — {build_name}' if build_name else ''}</h1>
        <div class="dash-meta">
            <span>🔢 Build #{build_num}</span>
            {"<span>🖥️ " + server + "</span>" if server else ""}
            <span>📅 {now}</span>
            <span>⏱️ {duration}</span>
            <span>🎯 {mode.upper()} mode</span>
            <span>🔥 {total} Scenarios</span>
        </div>
    </div>

    <!-- Main Stats Row -->
    <div class="grid grid-4" style="margin-bottom:16px;">
        <!-- Pass Rate Gauge -->
        <div class="panel gauge-panel">
            <div class="panel-title">📊 Pass Rate</div>
            <div class="gauge-container">
                <svg viewBox="0 0 120 70" class="gauge-svg">
                    <path d="M 10 60 A 50 50 0 0 1 110 60" fill="none" stroke="#2c3235" stroke-width="8" stroke-linecap="round"/>
                    <path d="M 10 60 A 50 50 0 0 1 110 60" fill="none" stroke="{gauge_color}" stroke-width="8" stroke-linecap="round"
                          stroke-dasharray="{pass_rate * 1.57} 157" class="gauge-fill"/>
                </svg>
                <div class="gauge-value" style="color:{gauge_color}">{pass_rate}<span class="gauge-max">%</span></div>
            </div>
            <div class="gauge-label">{passed}/{total} Passed</div>
        </div>

        <!-- Passed -->
        <div class="panel stat-panel {"ok" if passed > 0 else "warn"}">
            <div class="panel-title">✅ Passed</div>
            <div class="stat-value" style="color:var(--green)">{passed}</div>
            <div class="stat-subtitle">Scenarios</div>
        </div>

        <!-- Failed -->
        <div class="panel stat-panel {"error" if failed > 0 else "ok"}">
            <div class="panel-title">{"❌" if failed > 0 else "✅"} Failed</div>
            <div class="stat-value" style="color:{"var(--red)" if failed > 0 else "var(--green)"}">{failed}</div>
            <div class="stat-subtitle">Scenarios</div>
        </div>

        <!-- Duration -->
        <div class="panel stat-panel ok">
            <div class="panel-title">⏱️ Duration</div>
            <div class="stat-value" style="color:var(--blue);font-size:32px;">{total_test_dur}</div>
            <div class="stat-subtitle">Total Runtime</div>
        </div>
    </div>

    <!-- Executive Summary -->
    {exec_summary_html}

    <!-- Configuration Parameters -->
    {config_section_html}

    <!-- Scenario Results -->
    <div class="panel" style="margin-bottom:16px;">
        <div class="panel-title">🔥 Scenario Results</div>
        <div class="check-grid">
            {scenario_cards}
        </div>
    </div>

    <!-- Detailed Results (Latency, PVC, Validation) -->
    {detail_sections_html}

    <!-- Output Excerpt -->
    <div class="panel" style="margin-bottom:16px;">
        <div class="panel-title collapsible-toggle" onclick="this.nextElementSibling.classList.toggle('show'); this.querySelector('.arrow').textContent = this.nextElementSibling.classList.contains('show') ? '▲' : '▼'">
            📋 Console Output <span class="arrow" style="margin-left:auto;font-size:10px;">▼</span>
        </div>
        <div class="output-body collapsible-content">
            {output_html}
        </div>
    </div>

    <!-- Footer -->
    <div class="dash-footer">
        <div class="dash-footer-status">{navbar_status}</div>
        Generated by CNV HealthCrew &middot; {now}
    </div>
</div>

</body>
</html>'''

    return html
