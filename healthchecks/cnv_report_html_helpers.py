"""
Shared HTML fragment builders for CNV scenario reports (latency, validation, config).
"""
from healthchecks.validation_commands import infer_command as _infer_command

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
    """Render validation details as styled cards with commands."""
    if not data:
        return ""
    overall = data.get("overallStatus", "UNKNOWN")
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
        cmd = v.get("command", "") or _infer_command(msg)
        v_icon = "✅" if vstatus == "PASS" else "❌" if vstatus == "FAIL" else "⚠️"
        v_color = "#73BF69" if vstatus == "PASS" else "#F2495C" if vstatus == "FAIL" else "#FF9830"
        cmd_html = ""
        if cmd:
            cmd_html = f'<div style="font-family:monospace;font-size:10px;color:var(--text-muted);margin-top:3px;padding:2px 6px;background:var(--bg-canvas);border-radius:3px;display:inline-block;">$ {cmd}</div>'
        checks_html += f'''
        <div style="display:flex;align-items:flex-start;gap:12px;padding:10px 16px;border-bottom:1px solid var(--border);">
            <span style="font-size:16px;margin-top:2px;">{v_icon}</span>
            <div style="flex:1;">
                <div style="font-size:13px;font-weight:500;color:var(--text-primary);">{phase.replace('_', ' ').title()}</div>
                <div style="font-size:11px;color:var(--text-secondary);">{msg}</div>
                {cmd_html}
            </div>
            <span style="padding:3px 10px;border-radius:12px;font-size:10px;font-weight:700;background:{v_color}22;color:{v_color};margin-top:2px;">{vstatus}</span>
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
