"""
CNV Scenarios Report Generator

Generates a beautiful dark-themed HTML report for CNV scenario runs,
matching the style of the health check report from hybrid_health_check.py.
"""

import re
from datetime import datetime


# ── Scenario metadata lookup ─────────────────────────────────────────────────
# Maps remote_name -> display info.  Imported lazily so the module stays
# self-contained when used outside the Flask app.
_SCENARIO_META = None


def _get_scenario_meta():
    global _SCENARIO_META
    if _SCENARIO_META is None:
        try:
            from config.cnv_scenarios import CNV_SCENARIOS
            _SCENARIO_META = {}
            for sid, sc in CNV_SCENARIOS.items():
                _SCENARIO_META[sc["remote_name"]] = {
                    "name": sc["name"],
                    "icon": sc["icon"],
                    "category": sc["category"],
                    "description": sc.get("description", ""),
                }
        except ImportError:
            _SCENARIO_META = {}
    return _SCENARIO_META


# ── Output parser ─────────────────────────────────────────────────────────────

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def strip_ansi(s):
    return _ANSI_RE.sub('', s)


def parse_cnv_results(raw_output):
    """Parse structured results from CNV scenario console output.

    Looks for:
      - The results summary table printed by cnv_scenarios.py
      - The PASSED: X | FAILED: Y | TOTAL: Z summary line
      - Individual test status lines

    Returns a dict:
        {
            "tests": [
                {"name": "cpu-limits", "status": "PASS", "validation": "OK", "duration_str": "2m 30s", "duration_secs": 150},
                ...
            ],
            "passed": int,
            "failed": int,
            "total": int,
        }
    """
    lines = raw_output.split('\n')
    tests = []
    passed = 0
    failed = 0
    total = 0

    # Regex to strip the [HH:MM:SS] timestamp prefix that cnv_scenarios.py adds
    _TS_RE = re.compile(r'^\[?\d{2}:\d{2}:\d{2}\]?\s*')

    def strip_ts(s):
        """Remove leading timestamp like '[14:30:00] '."""
        return _TS_RE.sub('', s)

    # Pattern 1: summary table rows like "  cpu-limits       PASS       OK          2m 30s"
    # Lines arrive as "[14:32:00]   cpu-limits    PASS    validated    2m 30s"
    in_summary_table = False
    for line in lines:
        clean = strip_ts(strip_ansi(line)).strip()

        # Detect start of summary table
        if 'Results Summary' in clean or ('Test' in clean and 'Status' in clean and 'Validation' in clean):
            in_summary_table = True
            continue

        if in_summary_table:
            # End of table
            if clean.startswith('===') or not clean:
                if clean.startswith('===') and tests:
                    in_summary_table = False
                continue
            if clean.startswith('---'):
                continue

            # Parse table row:  "  test-name    PASS    validated    3m 10s"
            parts = clean.split()
            if len(parts) >= 2:
                name = parts[0]
                status_val = parts[1].upper()
                if status_val not in ('PASS', 'FAIL'):
                    continue
                # Only accept names that look like test slugs (contain a hyphen or alphanumeric)
                if not re.match(r'^[a-zA-Z][\w-]+$', name):
                    continue
                validation = parts[2] if len(parts) >= 3 else 'N/A'
                dur_str = ' '.join(parts[3:]) if len(parts) >= 4 else 'N/A'

                # Parse duration to seconds
                dur_secs = 0
                m_match = re.search(r'(\d+)m', dur_str)
                s_match = re.search(r'(\d+)s', dur_str)
                if m_match:
                    dur_secs += int(m_match.group(1)) * 60
                if s_match:
                    dur_secs += int(s_match.group(1))

                tests.append({
                    "name": name,
                    "status": status_val,
                    "validation": validation,
                    "duration_str": dur_str,
                    "duration_secs": dur_secs,
                })

    # Pattern 2: "PASSED: X | FAILED: Y | TOTAL: Z"
    for line in lines:
        clean = strip_ansi(line)
        match = re.search(r'PASSED:\s*(\d+)\s*\|\s*FAILED:\s*(\d+)\s*\|\s*TOTAL:\s*(\d+)', clean)
        if match:
            passed = int(match.group(1))
            failed = int(match.group(2))
            total = int(match.group(3))

    # If we didn't find the summary table, try to extract individual PASS/FAIL lines
    if not tests:
        for line in lines:
            clean = strip_ts(strip_ansi(line)).strip()
            # Match lines containing a test-name slug followed by PASS or FAIL
            m = re.match(r'.*?\b([a-zA-Z][\w]*(?:-[\w]+)+)\s+.*?\b(PASS|FAIL)\b', clean)
            if m:
                name = m.group(1)
                status_val = m.group(2)
                # Avoid false positives
                if name.lower() in ('the', 'test', 'all', 'cnv', 'kube', 'run', 'kube-burner'):
                    continue
                if not any(t["name"] == name for t in tests):
                    tests.append({
                        "name": name,
                        "status": status_val,
                        "validation": "N/A",
                        "duration_str": "N/A",
                        "duration_secs": 0,
                    })

    # Fallback: derive passed/failed from tests list
    if total == 0 and tests:
        passed = sum(1 for t in tests if t["status"] == "PASS")
        failed = sum(1 for t in tests if t["status"] == "FAIL")
        total = len(tests)

    # Extract iteration data JSON block emitted by cnv_scenarios.py
    iteration_data = {}
    import json as _json
    start_marker = "__CNV_ITERATION_DATA_START__"
    end_marker = "__CNV_ITERATION_DATA_END__"
    start_idx = raw_output.find(start_marker)
    end_idx = raw_output.find(end_marker)
    if start_idx != -1 and end_idx != -1:
        json_block = raw_output[start_idx + len(start_marker):end_idx].strip()
        try:
            summaries_list = _json.loads(json_block)
            # Map test_name -> iteration_data
            for s in summaries_list:
                tname = s.get("test", "")
                idata = s.get("iteration_data", {})
                if tname and idata:
                    iteration_data[tname] = idata
        except _json.JSONDecodeError:
            pass

    return {
        "tests": tests,
        "passed": passed,
        "failed": failed,
        "total": total,
        "iteration_data": iteration_data,
    }


def parse_cluster_info(raw_output):
    """Extract __CNV_CLUSTER_INFO__ JSON block from raw console output.

    Returns a dict with cluster metadata, or empty dict if not found.
    """
    import json as _json
    start_marker = "__CNV_CLUSTER_INFO_START__"
    end_marker = "__CNV_CLUSTER_INFO_END__"
    start_idx = raw_output.find(start_marker)
    end_idx = raw_output.find(end_marker)
    if start_idx == -1 or end_idx == -1:
        return {}
    json_block = raw_output[start_idx + len(start_marker):end_idx].strip()
    try:
        return _json.loads(json_block)
    except _json.JSONDecodeError:
        return {}


# ── Iteration data renderers ─────────────────────────────────────────────────

# Logical boot-stage ordering for VMI latency
_VMI_STAGE_ORDER = [
    "VMICreated", "VMIPending", "VMIScheduling", "VMIScheduled",
    "PodCreated", "PodPodScheduled", "PodInitialized", "PodContainersReady",
    "VMIRunning", "VMReady",
]

_VMI_STAGE_LABELS = {
    "VMICreated": "VMI Created",
    "VMIPending": "VMI Pending",
    "VMIScheduling": "VMI Scheduling",
    "VMIScheduled": "VMI Scheduled",
    "PodCreated": "Pod Created",
    "PodPodScheduled": "Pod Scheduled",
    "PodInitialized": "Pod Initialized",
    "PodContainersReady": "Containers Ready",
    "VMIRunning": "VMI Running",
    "VMReady": "VM Ready",
}

_VMI_STAGE_ICONS = {
    "VMICreated": "🆕", "VMIPending": "⏳", "VMIScheduling": "📋",
    "VMIScheduled": "📌", "PodCreated": "📦", "PodPodScheduled": "🎯",
    "PodInitialized": "🔧", "PodContainersReady": "✅",
    "VMIRunning": "🟢", "VMReady": "🏁",
}


def _fmt_ms(ms):
    """Format milliseconds to a human-readable string."""
    if ms is None or ms == 0:
        return "—"
    if ms < 1000:
        return f"{ms}ms"
    secs = ms / 1000
    if secs < 60:
        return f"{secs:.1f}s"
    return f"{int(secs // 60)}m {int(secs % 60)}s"


def _render_vmi_latency_html(data_list):
    """Render VMI latency quantiles as a styled HTML table."""
    if not data_list:
        return ""
    # Sort by boot-stage order
    by_name = {d["quantileName"]: d for d in data_list}
    ordered = [by_name[s] for s in _VMI_STAGE_ORDER if s in by_name]
    # Append any unknown stages at end
    known = set(_VMI_STAGE_ORDER)
    for d in data_list:
        if d["quantileName"] not in known:
            ordered.append(d)

    max_p99 = max((d.get("P99", 0) for d in ordered), default=1) or 1

    rows = ""
    for d in ordered:
        name = d["quantileName"]
        label = _VMI_STAGE_LABELS.get(name, name)
        icon = _VMI_STAGE_ICONS.get(name, "⚙️")
        p50 = d.get("P50", 0)
        p95 = d.get("P95", 0)
        p99 = d.get("P99", 0)
        avg = d.get("avg", 0)
        mn = d.get("min", 0)
        mx = d.get("max", 0)
        bar_pct = min(int(p99 / max_p99 * 100), 100)
        # Color: green if fast, orange if moderate, red if slow
        color = "#73BF69" if p99 < 30000 else "#FF9830" if p99 < 60000 else "#F2495C"

        rows += f'''
        <tr>
            <td style="padding:10px 14px;font-size:13px;white-space:nowrap;">{icon} {label}</td>
            <td style="padding:10px 14px;text-align:right;font-variant-numeric:tabular-nums;color:{color};font-weight:600;">{_fmt_ms(p50)}</td>
            <td style="padding:10px 14px;text-align:right;font-variant-numeric:tabular-nums;">{_fmt_ms(p95)}</td>
            <td style="padding:10px 14px;text-align:right;font-variant-numeric:tabular-nums;font-weight:600;">{_fmt_ms(p99)}</td>
            <td style="padding:10px 14px;text-align:right;font-variant-numeric:tabular-nums;">{_fmt_ms(avg)}</td>
            <td style="padding:10px 14px;text-align:right;font-variant-numeric:tabular-nums;font-size:11px;color:var(--text-secondary);">{_fmt_ms(mn)}</td>
            <td style="padding:10px 14px;text-align:right;font-variant-numeric:tabular-nums;font-size:11px;color:var(--text-secondary);">{_fmt_ms(mx)}</td>
            <td style="padding:10px 14px;width:120px;">
                <div style="height:6px;background:var(--bg-canvas);border-radius:3px;overflow:hidden;">
                    <div style="height:100%;width:{bar_pct}%;background:{color};border-radius:3px;"></div>
                </div>
            </td>
        </tr>'''

    return f'''
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
        <tr style="border-bottom:1px solid var(--border);">
            <th style="padding:10px 14px;text-align:left;font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">Boot Stage</th>
            <th style="padding:10px 14px;text-align:right;font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">P50</th>
            <th style="padding:10px 14px;text-align:right;font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">P95</th>
            <th style="padding:10px 14px;text-align:right;font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">P99</th>
            <th style="padding:10px 14px;text-align:right;font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">Avg</th>
            <th style="padding:10px 14px;text-align:right;font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">Min</th>
            <th style="padding:10px 14px;text-align:right;font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">Max</th>
            <th style="padding:10px 14px;font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;"></th>
        </tr>
        {rows}
    </table>'''


def _render_pvc_latency_html(data_list):
    """Render PVC latency quantiles as a styled HTML table."""
    if not data_list:
        return ""
    pvc_icons = {"Bound": "🔗", "Pending": "⏳", "Lost": "❌"}
    rows = ""
    for d in data_list:
        name = d.get("quantileName", "?")
        icon = pvc_icons.get(name, "📦")
        p50 = d.get("P50", 0)
        p95 = d.get("P95", 0)
        p99 = d.get("P99", 0)
        avg = d.get("avg", 0)
        mn = d.get("min", 0)
        mx = d.get("max", 0)
        color = "#73BF69" if name == "Bound" else "#FF9830" if name == "Pending" else "#F2495C"
        rows += f'''
        <tr>
            <td style="padding:10px 14px;font-size:13px;white-space:nowrap;">{icon} {name}</td>
            <td style="padding:10px 14px;text-align:right;font-variant-numeric:tabular-nums;color:{color};font-weight:600;">{_fmt_ms(p50)}</td>
            <td style="padding:10px 14px;text-align:right;font-variant-numeric:tabular-nums;">{_fmt_ms(p95)}</td>
            <td style="padding:10px 14px;text-align:right;font-variant-numeric:tabular-nums;font-weight:600;">{_fmt_ms(p99)}</td>
            <td style="padding:10px 14px;text-align:right;font-variant-numeric:tabular-nums;">{_fmt_ms(avg)}</td>
            <td style="padding:10px 14px;text-align:right;font-variant-numeric:tabular-nums;font-size:11px;color:var(--text-secondary);">{_fmt_ms(mn)}</td>
            <td style="padding:10px 14px;text-align:right;font-variant-numeric:tabular-nums;font-size:11px;color:var(--text-secondary);">{_fmt_ms(mx)}</td>
        </tr>'''

    return f'''
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
        <tr style="border-bottom:1px solid var(--border);">
            <th style="padding:10px 14px;text-align:left;font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">Phase</th>
            <th style="padding:10px 14px;text-align:right;font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">P50</th>
            <th style="padding:10px 14px;text-align:right;font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">P95</th>
            <th style="padding:10px 14px;text-align:right;font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">P99</th>
            <th style="padding:10px 14px;text-align:right;font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">Avg</th>
            <th style="padding:10px 14px;text-align:right;font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">Min</th>
            <th style="padding:10px 14px;text-align:right;font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">Max</th>
        </tr>
        {rows}
    </table>'''


def _render_validation_html(data):
    """Render validation details as styled cards."""
    if not data:
        return ""
    overall = data.get("overallStatus", "UNKNOWN")
    overall_color = "#73BF69" if overall == "SUCCESS" else "#F2495C"
    overall_icon = "✅" if overall == "SUCCESS" else "❌"

    params = data.get("parameters", {})
    params_html = ""
    if params:
        param_items = ""
        for k, v in params.items():
            param_items += f'<span style="display:inline-block;padding:3px 10px;background:var(--bg-canvas);border-radius:4px;font-size:11px;margin:2px 4px;border:1px solid var(--border);"><b style="color:var(--text-secondary);">{k}:</b> <span style="color:var(--text-primary);">{v}</span></span>'
        params_html = f'<div style="padding:12px 16px;border-bottom:1px solid var(--border);display:flex;flex-wrap:wrap;gap:2px;">{param_items}</div>'

    checks_html = ""
    validations = data.get("validations", [])
    for v in validations:
        phase = v.get("phase", "unknown")
        vstatus = v.get("status", "UNKNOWN")
        msg = v.get("message", "")
        v_icon = "✅" if vstatus == "PASS" else "❌" if vstatus == "FAIL" else "⚠️"
        v_color = "#73BF69" if vstatus == "PASS" else "#F2495C" if vstatus == "FAIL" else "#FF9830"
        checks_html += f'''
        <div style="display:flex;align-items:center;gap:12px;padding:10px 16px;border-bottom:1px solid var(--border);">
            <span style="font-size:16px;">{v_icon}</span>
            <div style="flex:1;">
                <div style="font-size:13px;font-weight:500;color:var(--text-primary);">{phase.replace('_', ' ').title()}</div>
                <div style="font-size:11px;color:var(--text-secondary);">{msg}</div>
            </div>
            <span style="padding:3px 10px;border-radius:12px;font-size:10px;font-weight:700;background:{v_color}22;color:{v_color};">{vstatus}</span>
        </div>'''

    ns = data.get("namespace", "")
    func = data.get("function", "")
    ts = data.get("timestamp", "")
    header_meta = ""
    if ns:
        header_meta += f'<span style="font-size:11px;color:var(--text-secondary);">ns: {ns}</span>'
    if func:
        header_meta += f' <span style="font-size:11px;color:var(--text-secondary);">• {func}</span>'

    return f'''
    <div style="margin-bottom:12px;border:1px solid var(--border);border-radius:8px;overflow:hidden;background:var(--bg-secondary);">
        <div style="padding:12px 16px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--border);">
            <div>
                <span style="font-size:14px;font-weight:600;color:var(--text-primary);">{overall_icon} {overall}</span>
                {header_meta}
            </div>
            <span style="font-size:11px;color:var(--text-secondary);">{ts}</span>
        </div>
        {params_html}
        {checks_html}
    </div>'''


# ── Executive Summary renderer ────────────────────────────────────────────────

def _render_executive_summary(tests, meta, cluster_info=None):
    """Build executive summary HTML: test scope table + cluster environment grid."""

    # ── Test Scope Table ──────────────────────────────────────────────────
    rows = ""
    for t in tests:
        m = meta.get(t["name"], {})
        icon = m.get("icon", "🔥")
        display_name = m.get("name", t["name"])
        description = m.get("description", "")
        is_pass = t["status"] == "PASS"
        s_color = "#73BF69" if is_pass else "#F2495C"
        s_label = "PASSED" if is_pass else "FAILED"
        s_icon = "✅" if is_pass else "❌"
        dur = t.get("duration_str", "N/A")
        rows += f'''
        <tr style="border-bottom:1px solid var(--border);">
            <td style="padding:10px 14px;font-size:13px;white-space:nowrap;">{icon} {display_name}</td>
            <td style="padding:10px 14px;font-size:12px;color:var(--text-secondary);max-width:400px;">{description}</td>
            <td style="padding:10px 14px;text-align:center;">
                <span style="display:inline-block;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700;background:{s_color}22;color:{s_color};">{s_icon} {s_label}</span>
            </td>
            <td style="padding:10px 14px;text-align:right;font-size:12px;color:var(--text-secondary);">{dur}</td>
        </tr>'''

    scope_html = f'''
    <div class="panel" style="margin-bottom:16px;">
        <div class="panel-title">📋 Test Scope</div>
        <div style="overflow-x:auto;">
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
            <tr style="border-bottom:1px solid var(--border);">
                <th style="padding:10px 14px;text-align:left;font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">Scenario</th>
                <th style="padding:10px 14px;text-align:left;font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">Objective</th>
                <th style="padding:10px 14px;text-align:center;font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">Status</th>
                <th style="padding:10px 14px;text-align:right;font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;">Duration</th>
            </tr>
            {rows}
        </table>
        </div>
    </div>'''

    # ── Cluster Environment Grid ──────────────────────────────────────────
    env_html = ""
    if cluster_info:
        def _env_card(label, value, icon):
            return f'''
            <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:14px 16px;">
                <div style="font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">{icon} {label}</div>
                <div style="font-size:16px;font-weight:600;color:var(--text-primary);">{value}</div>
            </div>'''

        cards = ""
        cards += _env_card("OCP Version", cluster_info.get("ocp_version", "N/A"), "🔴")
        cards += _env_card("CNV Version", cluster_info.get("cnv_version", "N/A"), "🖥️")
        odf = cluster_info.get("odf_version", "N/A")
        if odf and odf != "N/A":
            cards += _env_card("ODF Version", odf, "💿")
        cards += _env_card("Network", cluster_info.get("network_type", "N/A"), "🌐")

        workers = cluster_info.get("nodes_workers", 0)
        masters = cluster_info.get("nodes_masters", 0)
        total = cluster_info.get("nodes_total", 0)
        node_val = f"{total} ({workers}w / {masters}m)" if total else "N/A"
        cards += _env_card("Nodes", node_val, "🖧")

        storage_total = cluster_info.get("storage_total_tib", 0)
        storage_used = cluster_info.get("storage_used_tib", 0)
        if storage_total:
            pct = int(storage_used / storage_total * 100) if storage_total else 0
            storage_val = f"{storage_used} / {storage_total} TiB ({pct}%)"
        else:
            storage_val = "N/A"
        cards += _env_card("Storage (Ceph)", storage_val, "💾")

        env_html = f'''
    <div class="panel" style="margin-bottom:16px;">
        <div class="panel-title">🏗️ Cluster Environment</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;padding:16px;">
            {cards}
        </div>
    </div>'''

    return scope_html + env_html


# ── Configuration parameters section ─────────────────────────────────────────

def _resolve_default(var_info, mode):
    """Return the default value string for a variable given the run mode."""
    d = var_info.get("default", "")
    if isinstance(d, dict):
        d = d.get(mode, d.get("sanity", ""))
    if isinstance(d, bool):
        return "true" if d else "false"
    return str(d) if d is not None else ""


def _config_card(label, value, icon, is_override=False):
    """Single config-parameter card for the grid."""
    color = "var(--blue)" if is_override else "var(--text-primary)"
    badge = '<span style="font-size:9px;color:var(--blue);margin-left:6px;">CUSTOM</span>' if is_override else ''
    return f'''
            <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:12px 14px;">
                <div style="font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:5px;">{icon} {label}{badge}</div>
                <div style="font-size:13px;font-weight:600;color:{color};word-break:break-all;">{value}</div>
            </div>'''


def _render_config_params_html(run_config, checks=None, mode="sanity"):
    """Build a collapsible panel showing all configuration parameters for the run."""
    if not run_config:
        return ""

    try:
        from config.cnv_scenarios import CNV_GLOBAL_VARIABLES, CNV_SCENARIOS
    except ImportError:
        return ""

    checks = checks or []
    mode = run_config.get("scenario_mode", mode)

    # Parse env_vars overrides into a lookup dict
    overrides = {}
    env_vars_str = run_config.get("env_vars", "")
    if env_vars_str:
        for pair in env_vars_str.split(","):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                overrides[k] = v

    # ── Run Settings cards ────────────────────────────────────────────────
    run_params = [
        ("Mode", mode.upper(), "🎯"),
        ("Parallel", "Yes" if run_config.get("scenario_parallel") else "No", "⚡"),
        ("CNV Path", run_config.get("cnv_path", ""), "📂"),
    ]
    if run_config.get("kb_log_level"):
        run_params.append(("Log Level", run_config["kb_log_level"], "📝"))
    if run_config.get("kb_timeout"):
        run_params.append(("Timeout", run_config["kb_timeout"], "⏱️"))
    if run_config.get("server_host"):
        run_params.append(("Server", run_config["server_host"], "🖥️"))

    run_cards = ""
    for label, value, icon in run_params:
        if value:
            run_cards += _config_card(label, value, icon)

    run_grid = f'''
        <div style="padding:16px 16px 8px;">
            <div style="font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;">🔧 Run Settings</div>
            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;">
                {run_cards}
            </div>
        </div>''' if run_cards else ""

    # ── Global Parameters cards ───────────────────────────────────────────
    global_cards = ""
    for var_name, var_info in CNV_GLOBAL_VARIABLES.items():
        label = var_info.get("label", var_name)
        icon = var_info.get("icon", "⚙️")
        default_val = _resolve_default(var_info, mode)
        actual = overrides.get(var_name, default_val)
        is_override = var_name in overrides
        if var_info.get("type") == "bool":
            display = "Enabled" if actual in ("true", "True", "1") else "Disabled"
        elif actual:
            display = actual
        else:
            ph = var_info.get("placeholder", "")
            if isinstance(ph, dict):
                ph = ph.get(mode, ph.get("sanity", ""))
            display = ph.replace("default: ", "") if ph else "(not set)"
        global_cards += _config_card(label, display, icon, is_override)

    global_html = f'''
        <div style="padding:12px 16px 8px;">
            <div style="font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;">⚙️ Global Parameters</div>
            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px;">
                {global_cards}
            </div>
        </div>'''

    # ── Per-scenario parameters ───────────────────────────────────────────
    # Build remote_name -> scenario config lookup
    by_remote = {sc["remote_name"]: (sid, sc) for sid, sc in CNV_SCENARIOS.items()}

    scenario_sections = ""
    for remote_name in checks:
        if remote_name not in by_remote:
            continue
        sid, sc = by_remote[remote_name]
        svars = sc.get("variables", {})
        if not svars:
            continue

        s_cards = ""
        for var_name, var_info in svars.items():
            label = var_info.get("label", var_name)
            default_val = _resolve_default(var_info, mode)
            actual = overrides.get(var_name, default_val)
            is_override = var_name in overrides
            if var_info.get("type") == "bool":
                display = "Enabled" if actual in ("true", "True", "1") else "Disabled"
            elif actual:
                display = actual
            else:
                ph = var_info.get("placeholder", "")
                display = ph.replace("default: ", "").replace("Default: ", "") if ph else "(not set)"
            s_cards += f'''
                <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--border);">
                    <span style="font-size:12px;color:var(--text-secondary);">{label}</span>
                    <span style="font-size:12px;font-weight:600;font-family:monospace;color:{"var(--blue)" if is_override else "var(--text-primary)"};">{display}{"" if not is_override else ' <span style="font-size:9px;color:var(--blue);">●</span>'}</span>
                </div>'''

        scenario_sections += f'''
            <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;overflow:hidden;">
                <div style="padding:10px 14px;border-bottom:1px solid var(--border);font-size:12px;font-weight:600;color:var(--text-primary);">{sc.get("icon", "🔥")} {sc["name"]}</div>
                <div style="padding:8px 14px;">{s_cards}</div>
            </div>'''

    scenario_html = ""
    if scenario_sections:
        scenario_html = f'''
        <div style="padding:12px 16px 16px;">
            <div style="font-size:10px;font-weight:600;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;">🧪 Test-Specific Parameters</div>
            <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;">
                {scenario_sections}
            </div>
        </div>'''

    return f'''
    <div class="panel" style="margin-bottom:16px;">
        <div class="panel-title collapsible-toggle" onclick="this.nextElementSibling.classList.toggle('show'); this.querySelector('.arrow').textContent = this.nextElementSibling.classList.contains('show') ? '▲' : '▼'">
            ⚙️ Configuration Parameters <span class="arrow" style="margin-left:auto;font-size:10px;">▼</span>
        </div>
        <div class="collapsible-content">
            {run_grid}
            {global_html}
            {scenario_html}
        </div>
    </div>'''


# ── Report HTML generator ────────────────────────────────────────────────────

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

    # Filter out the iteration data JSON block from display
    filtered_lines = [l for l in excerpt_lines
                      if '__CNV_ITERATION_DATA_' not in l and not l.strip().startswith('{') or 'CNV' in l]
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


# ── Combined Report HTML generator ────────────────────────────────────────────

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


# ── Email detail sections builder ────────────────────────────────────────────

def _build_email_detail_sections(results, meta):
    """Build inline-styled detail sections for the email report."""
    iteration_data = results.get("iteration_data", {})
    tests = results.get("tests", [])
    if not iteration_data:
        return ""

    sections = ""
    for t in tests:
        tname = t["name"]
        idata = iteration_data.get(tname, {})
        if not idata:
            continue

        m = meta.get(tname, {})
        icon = m.get("icon", "🔥")
        display_name = m.get("name", tname)

        content = ""

        # VMI Latency (compact email table)
        vmi_lat = idata.get("vmi_latency")
        if vmi_lat:
            by_name = {d["quantileName"]: d for d in vmi_lat}
            rows = ""
            for stage in _VMI_STAGE_ORDER:
                if stage not in by_name:
                    continue
                d = by_name[stage]
                label = _VMI_STAGE_LABELS.get(stage, stage)
                s_icon = _VMI_STAGE_ICONS.get(stage, "⚙️")
                p50 = d.get("P50", 0)
                p99 = d.get("P99", 0)
                color = "#73BF69" if p99 < 30000 else "#FF9830" if p99 < 60000 else "#F2495C"
                rows += f'''<tr style="border-bottom:1px solid #21262d;">
                    <td style="padding:6px 10px;font-size:12px;color:#c9d1d9;">{s_icon} {label}</td>
                    <td style="padding:6px 10px;text-align:right;font-size:12px;color:{color};font-weight:600;">{_fmt_ms(p50)}</td>
                    <td style="padding:6px 10px;text-align:right;font-size:12px;color:{color};font-weight:600;">{_fmt_ms(p99)}</td>
                </tr>'''
            content += f'''
            <div style="font-size:11px;font-weight:600;color:#f97316;text-transform:uppercase;letter-spacing:1px;margin:12px 0 6px;">🏎️ VM Boot Latency</div>
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#0d1117;border:1px solid #30363d;border-radius:6px;overflow:hidden;">
            <tr style="border-bottom:1px solid #30363d;">
                <th style="padding:6px 10px;text-align:left;font-size:10px;font-weight:600;color:#8b949e;">Stage</th>
                <th style="padding:6px 10px;text-align:right;font-size:10px;font-weight:600;color:#8b949e;">P50</th>
                <th style="padding:6px 10px;text-align:right;font-size:10px;font-weight:600;color:#8b949e;">P99</th>
            </tr>
            {rows}
            </table>'''

        # PVC Latency (compact)
        pvc_lat = idata.get("pvc_latency")
        if pvc_lat:
            pvc_rows = ""
            for d in pvc_lat:
                name = d.get("quantileName", "?")
                p50 = d.get("P50", 0)
                p99 = d.get("P99", 0)
                pvc_rows += f'''<tr style="border-bottom:1px solid #21262d;">
                    <td style="padding:6px 10px;font-size:12px;color:#c9d1d9;">{name}</td>
                    <td style="padding:6px 10px;text-align:right;font-size:12px;">{_fmt_ms(p50)}</td>
                    <td style="padding:6px 10px;text-align:right;font-size:12px;">{_fmt_ms(p99)}</td>
                </tr>'''
            content += f'''
            <div style="font-size:11px;font-weight:600;color:#f97316;text-transform:uppercase;letter-spacing:1px;margin:12px 0 6px;">💾 PVC Latency</div>
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#0d1117;border:1px solid #30363d;border-radius:6px;overflow:hidden;">
            <tr style="border-bottom:1px solid #30363d;">
                <th style="padding:6px 10px;text-align:left;font-size:10px;font-weight:600;color:#8b949e;">Phase</th>
                <th style="padding:6px 10px;text-align:right;font-size:10px;font-weight:600;color:#8b949e;">P50</th>
                <th style="padding:6px 10px;text-align:right;font-size:10px;font-weight:600;color:#8b949e;">P99</th>
            </tr>
            {pvc_rows}
            </table>'''

        # Validation checks (compact)
        validation = idata.get("validation")
        if validation:
            val_items = ""
            for v in validation.get("validations", []):
                vstatus = v.get("status", "UNKNOWN")
                msg = v.get("message", "")
                v_icon = "✅" if vstatus == "PASS" else "❌"
                val_items += f'<div style="padding:4px 0;font-size:12px;color:#c9d1d9;">{v_icon} {msg}</div>'
            overall = validation.get("overallStatus", "UNKNOWN")
            o_icon = "✅" if overall == "SUCCESS" else "❌"
            content += f'''
            <div style="font-size:11px;font-weight:600;color:#f97316;text-transform:uppercase;letter-spacing:1px;margin:12px 0 6px;">🔍 Validation ({o_icon} {overall})</div>
            <div style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 12px;">
            {val_items}
            </div>'''

        if content:
            sections += f'''
<!-- Detail: {display_name} -->
<tr><td style="padding:0 32px 16px;">
<div style="font-size:13px;font-weight:600;color:#e6edf3;margin-bottom:8px;">{icon} {display_name}</div>
{content}
</td></tr>'''

    return sections


def _build_email_env_row(cluster_info):
    """Build an inline-styled cluster environment row for the email report."""
    if not cluster_info:
        return ""

    def _cell(label, value):
        return (
            f'<td style="padding:8px;background:#0d111788;border-radius:6px;text-align:center;border:1px solid #30363d;">'
            f'<div style="font-size:10px;color:#8b949e;text-transform:uppercase;margin-bottom:2px;">{label}</div>'
            f'<div style="font-size:14px;font-weight:600;color:#e6edf3;">{value}</div>'
            f'</td><td width="4"></td>'
        )

    ocp = cluster_info.get("ocp_version", "N/A")
    cnv = cluster_info.get("cnv_version", "N/A")
    net = cluster_info.get("network_type", "N/A")
    nodes = cluster_info.get("nodes_total", 0)
    workers = cluster_info.get("nodes_workers", 0)
    node_str = f"{nodes} ({workers}w)" if nodes else "N/A"

    cells = _cell("OCP", ocp) + _cell("CNV", cnv) + _cell("Network", net) + _cell("Nodes", node_str)

    return (
        '<!-- Cluster Environment -->\n'
        '<tr><td style="padding:0 32px 16px;">\n'
        '<div style="font-size:13px;font-weight:600;color:#8b949e;margin-bottom:8px;">CLUSTER ENVIRONMENT</div>\n'
        f'<table width="100%" cellpadding="0" cellspacing="0"><tr>{cells}</tr></table>\n'
        '</td></tr>'
    )


# ── Email-friendly report snippet ────────────────────────────────────────────

def generate_cnv_email_html(results, build_num=0, build_name="",
                             status="success", status_text="All Passed",
                             duration="", mode="sanity", checks=None,
                             output="", cluster_info=None,
                             dashboard_base_url=""):
    """Generate an email-safe HTML body for CNV scenario results.

    Uses inline styles and table layout for maximum email client compatibility.
    """
    checks = checks or []
    meta = _get_scenario_meta()
    tests = results.get("tests", [])
    passed = results.get("passed", 0)
    failed = results.get("failed", 0)
    total = results.get("total", 0) or len(tests)

    status_colors = {
        'success': '#73BF69',
        'unstable': '#FF9830',
        'failed': '#F2495C',
    }
    status_emoji = {'success': '✅', 'unstable': '⚠️', 'failed': '❌'}.get(status, '🔵')
    color = status_colors.get(status, '#5794F2')

    # Build per-test result rows
    test_rows = ""
    for t in tests:
        m = meta.get(t["name"], {})
        icon = m.get("icon", "🔥")
        display_name = m.get("name", t["name"])
        is_pass = t["status"] == "PASS"
        s_color = "#73BF69" if is_pass else "#F2495C"
        s_emoji = "✅" if is_pass else "❌"
        s_label = "PASS" if is_pass else "FAIL"
        dur = t.get("duration_str", "N/A")
        val = t.get("validation", "N/A")

        test_rows += f'''
<tr style="border-bottom:1px solid #21262d;">
    <td style="padding:10px 14px;font-size:13px;color:#c9d1d9;">{icon} {display_name}</td>
    <td style="padding:10px 14px;text-align:center;">
        <span style="display:inline-block;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700;background:{s_color}22;color:{s_color};">{s_emoji} {s_label}</span>
    </td>
    <td style="padding:10px 14px;font-size:12px;color:#8b949e;text-align:center;">{val}</td>
    <td style="padding:10px 14px;font-size:12px;color:#8b949e;text-align:right;">{dur}</td>
</tr>'''

    # Output excerpt (filter out iteration data block)
    output_lines = output.strip().split('\n') if output else []
    summary_start = None
    for i, line in enumerate(output_lines):
        if any(k in line for k in ['Results Summary', 'SUMMARY', 'scenarios complete', 'CNV Scenarios complete']):
            summary_start = max(0, i - 2)
            break
    if summary_start is not None:
        excerpt_lines = output_lines[summary_start:]
    else:
        excerpt_lines = output_lines[-30:]

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

    html_summary = '<br>'.join(
        strip_ansi(l).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        for l in clean_excerpt
    )

    subject = f'{status_emoji} CNV Scenarios #{build_num} — {status_text}'
    if build_name:
        subject += f' ({build_name})'

    html = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0d1117;color:#c9d1d9;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0d1117;padding:20px 0;">
<tr><td align="center">
<table width="680" cellpadding="0" cellspacing="0" style="background:#161b22;border-radius:12px;overflow:hidden;border:1px solid #30363d;">

<!-- Header -->
<tr><td style="background:linear-gradient(135deg,#1a1a2e,#16213e);padding:28px 32px;">
<table width="100%"><tr>
<td><span style="font-size:28px;">🔥</span></td>
<td style="padding-left:14px;">
<div style="font-size:22px;font-weight:700;color:#e6edf3;">CNV Scenarios Report</div>
<div style="font-size:13px;color:#8b949e;margin-top:4px;">Build #{build_num} &middot; {duration}</div>
</td>
<td align="right">
<div style="display:inline-block;padding:8px 20px;border-radius:20px;background:{color}22;border:1px solid {color}44;">
<span style="font-size:16px;font-weight:700;color:{color};">{status_emoji} {status_text}</span>
</div>
</td>
</tr></table>
</td></tr>

<!-- Summary Stats -->
<tr><td style="padding:24px 32px;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr>
<td width="25%" style="padding:12px 8px;background:#0d111788;border-radius:8px;text-align:center;border:1px solid #30363d;">
<div style="font-size:28px;font-weight:700;color:{color};">{status_text}</div>
<div style="font-size:10px;color:#8b949e;margin-top:4px;text-transform:uppercase;">Status</div>
</td>
<td width="4"></td>
<td width="25%" style="padding:12px 8px;background:#0d111788;border-radius:8px;text-align:center;border:1px solid #30363d;">
<div style="font-size:28px;font-weight:700;color:#73BF69;">{passed}</div>
<div style="font-size:10px;color:#8b949e;margin-top:4px;text-transform:uppercase;">Passed</div>
</td>
<td width="4"></td>
<td width="25%" style="padding:12px 8px;background:#0d111788;border-radius:8px;text-align:center;border:1px solid #30363d;">
<div style="font-size:28px;font-weight:700;color:{"#F2495C" if failed > 0 else "#73BF69"};">{failed}</div>
<div style="font-size:10px;color:#8b949e;margin-top:4px;text-transform:uppercase;">Failed</div>
</td>
<td width="4"></td>
<td width="25%" style="padding:12px 8px;background:#0d111788;border-radius:8px;text-align:center;border:1px solid #30363d;">
<div style="font-size:28px;font-weight:700;color:#e6edf3;">{mode.upper()}</div>
<div style="font-size:10px;color:#8b949e;margin-top:4px;text-transform:uppercase;">Mode</div>
</td>
</tr>
</table>
</td></tr>

{_build_email_env_row(cluster_info)}

<!-- Per-Test Results Table -->
<tr><td style="padding:0 32px 20px;">
<div style="font-size:13px;font-weight:600;color:#8b949e;margin-bottom:10px;">SCENARIO RESULTS</div>
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0d1117;border:1px solid #30363d;border-radius:8px;overflow:hidden;">
<tr style="border-bottom:1px solid #30363d;">
    <th style="padding:10px 14px;text-align:left;font-size:11px;font-weight:600;color:#8b949e;text-transform:uppercase;">Scenario</th>
    <th style="padding:10px 14px;text-align:center;font-size:11px;font-weight:600;color:#8b949e;text-transform:uppercase;">Status</th>
    <th style="padding:10px 14px;text-align:center;font-size:11px;font-weight:600;color:#8b949e;text-transform:uppercase;">Validation</th>
    <th style="padding:10px 14px;text-align:right;font-size:11px;font-weight:600;color:#8b949e;text-transform:uppercase;">Duration</th>
</tr>
{test_rows}
</table>
</td></tr>

{_build_email_detail_sections(results, meta)}

<!-- Output Summary -->
<tr><td style="padding:0 32px 24px;">
<div style="font-size:13px;font-weight:600;color:#8b949e;margin-bottom:10px;">OUTPUT SUMMARY</div>
<div style="background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:16px 18px;font-family:monospace;font-size:12px;line-height:1.6;color:#c9d1d9;max-height:400px;overflow:auto;">
{html_summary}
</div>
</td></tr>

<!-- CTA Button -->
{f"""<tr><td style="padding:0 32px 24px;text-align:center;">
<a href="{dashboard_base_url}/job/{build_num}" style="display:inline-block;padding:14px 32px;background:linear-gradient(135deg,#73BF69 0%,#5ba350 100%);border-radius:8px;color:#ffffff;font-weight:600;font-size:14px;text-decoration:none;">📊 View Full Report on Dashboard</a>
</td></tr>""" if dashboard_base_url and build_num else ""}

<!-- Footer -->
<tr><td style="padding:20px 32px;background:#0d111788;border-top:1px solid #30363d;text-align:center;">
<span style="font-size:12px;color:#8b949e;">
🔥 CNV HealthCrew &middot; Automated scenario report
</span>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>'''

    return subject, html
