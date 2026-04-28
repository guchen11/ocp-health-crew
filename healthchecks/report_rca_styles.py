"""RCA HTML fragments: panel header, executive summary, and issue cards (inline styles)."""

from healthchecks.report_rca_common import (
    confidence_color,
    escape_html_basic,
    failures_severity_border_color,
    jira_assessment_badge_style,
)
from healthchecks.report_rca_investigation import render_rca_investigation_section

# Optional hook for pages that inject a shared stylesheet; currently empty (all inline).
RCA_CSS = ""


def render_rca_panel_header(
    category_count: int, open_bugs: int, regression_bugs: int, fixed_bugs: int
) -> str:
    return """
    <div class="panel rca-panel" style="border-color:#FF9830;">
        <div class="panel-title" style="background:#2d1f0f;color:#FF9830;">🔍 Root Cause Analysis & Recommendations</div>
        <div style="padding:20px;">
            <p style="color:var(--text-secondary);margin-bottom:12px;font-size:13px;">
                Analysis based on Red Hat Jira bug database (CNV, OCPBUGS projects) • {count} issue categories identified
            </p>
            <div style="display:flex;gap:16px;margin-bottom:20px;">
                <div style="background:#1a0a0a;border:1px solid #F2495C;border-radius:6px;padding:8px 16px;">
                    <span style="color:#F2495C;font-weight:600;">{open_count}</span>
                    <span style="color:#8b949e;font-size:12px;margin-left:4px;">Open Bugs</span>
                </div>
                <div style="background:#1a1a0a;border:1px solid #FF9830;border-radius:6px;padding:8px 16px;">
                    <span style="color:#FF9830;font-weight:600;">{regression_count}</span>
                    <span style="color:#8b949e;font-size:12px;margin-left:4px;">Potential Regressions</span>
                </div>
                <div style="background:#0a1a0a;border:1px solid #73BF69;border-radius:6px;padding:8px 16px;">
                    <span style="color:#73BF69;font-weight:600;">{fixed_count}</span>
                    <span style="color:#8b949e;font-size:12px;margin-left:4px;">Fixed (upgrade available)</span>
                </div>
            </div>
    """.format(
        count=category_count,
        open_count=open_bugs,
        regression_count=regression_bugs,
        fixed_count=fixed_bugs,
    )


def render_email_keywords_section(keywords: list) -> str:
    if not keywords:
        return ""
    html = '''
            <div style="margin-bottom:20px;padding:12px 16px;background:linear-gradient(135deg, #1a1a2e 0%, #0d1117 100%);border:1px solid #30363d;border-radius:8px;">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
                    <span style="font-size:16px;">📧</span>
                    <span style="color:#58a6ff;font-weight:600;font-size:13px;">Email Search Keywords</span>
                </div>
                <div style="display:flex;flex-wrap:wrap;gap:8px;">
        '''
    for keyword in keywords[:8]:
        html += f'''
                    <span style="background:#21262d;border:1px solid #30363d;padding:4px 10px;border-radius:12px;font-size:11px;color:#c9d1d9;">
                        🔍 {keyword}
                    </span>
            '''
    html += '''
                </div>
                <p style="color:#8b949e;font-size:11px;margin-top:10px;margin-bottom:0;">
                    💡 Use these keywords to search your inbox for related discussions, alerts, or previous incidents.
                </p>
            </div>
        '''
    return html


def build_executive_summary_html(grouped: dict) -> str:
    exec_rows = []
    for title, gdata in grouped.items():
        causes = gdata.get("determined_causes", [])
        drilldown = gdata.get("drilldown")
        followup = gdata.get("followup")
        best = causes[0] if causes else None
        num_affected = len(gdata["failures"])

        if best:
            cause_text = best["cause"]
            conf = best["confidence"]
            has_fix = bool(
                drilldown
                and drilldown.get("conclusion", {})
                and drilldown["conclusion"].get("fix")
            )
            has_dd = bool(drilldown and drilldown.get("results"))
            has_fu = bool(followup and followup.get("results"))
            has_ns = bool(best.get("next_steps"))
            has_doc = bool(
                best.get("doc_url")
                or (
                    drilldown
                    and drilldown.get("conclusion", {})
                    and drilldown["conclusion"].get("doc")
                )
            )
        else:
            cause_text = "Investigation pending"
            conf = "low"
            has_fix = False
            has_dd = False
            has_fu = False
            has_ns = False
            has_doc = False

        conf_color = confidence_color(conf)
        check = '<span style="color:#73BF69;">&#10003;</span>'
        dash = '<span style="color:#30363d;">-</span>'

        exec_rows.append(
            f'''
            <tr style="border-bottom:1px solid #21262d;">
                <td style="padding:10px 12px;color:#e6edf3;font-weight:600;font-size:12px;max-width:180px;">{title}</td>
                <td style="padding:10px 8px;text-align:center;"><span style="color:#c9d1d9;font-size:12px;">{num_affected}</span></td>
                <td style="padding:10px 12px;color:#c9d1d9;font-size:11px;max-width:280px;">{cause_text}</td>
                <td style="padding:10px 8px;text-align:center;"><span style="background:{conf_color}22;color:{conf_color};padding:2px 8px;border-radius:8px;font-size:10px;font-weight:600;text-transform:uppercase;">{conf}</span></td>
                <td style="padding:10px 8px;text-align:center;">{check if has_dd else dash}</td>
                <td style="padding:10px 8px;text-align:center;">{check if has_fu else dash}</td>
                <td style="padding:10px 8px;text-align:center;">{check if has_fix else dash}</td>
                <td style="padding:10px 8px;text-align:center;">{check if has_doc else dash}</td>
            </tr>
        '''
        )

    if not exec_rows:
        return ""

    total_issues = sum(len(g["failures"]) for g in grouped.values())
    total_with_rc = sum(
        1
        for g in grouped.values()
        if g.get("determined_causes")
        and g["determined_causes"][0].get("confidence") in ("high", "medium")
    )
    total_cats = len(grouped)

    return f'''
            <div style="margin-bottom:24px;padding:18px;background:linear-gradient(135deg, #0d1117 0%, #161b22 100%);border:1px solid #30363d;border-radius:10px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
                    <div style="color:#58a6ff;font-weight:700;font-size:14px;">📊 Executive RCA Summary</div>
                    <div style="display:flex;gap:12px;">
                        <span style="color:#8b949e;font-size:11px;">{total_cats} categories</span>
                        <span style="color:#8b949e;font-size:11px;">{total_issues} total issues</span>
                        <span style="color:#73BF69;font-size:11px;font-weight:600;">{total_with_rc}/{total_cats} root-caused</span>
                    </div>
                </div>
                <div style="overflow-x:auto;">
                    <table style="width:100%;border-collapse:collapse;font-family:'JetBrains Mono',Monaco,monospace;">
                        <thead>
                            <tr style="border-bottom:2px solid #30363d;">
                                <th style="padding:8px 12px;text-align:left;color:#8b949e;font-size:10px;text-transform:uppercase;font-weight:600;letter-spacing:0.5px;">Issue</th>
                                <th style="padding:8px 8px;text-align:center;color:#8b949e;font-size:10px;text-transform:uppercase;font-weight:600;">Affected</th>
                                <th style="padding:8px 12px;text-align:left;color:#8b949e;font-size:10px;text-transform:uppercase;font-weight:600;letter-spacing:0.5px;">Root Cause</th>
                                <th style="padding:8px 8px;text-align:center;color:#8b949e;font-size:10px;text-transform:uppercase;font-weight:600;">Confidence</th>
                                <th style="padding:8px 8px;text-align:center;color:#8b949e;font-size:10px;text-transform:uppercase;font-weight:600;" title="Deep Drill-Down Performed">Drill</th>
                                <th style="padding:8px 8px;text-align:center;color:#8b949e;font-size:10px;text-transform:uppercase;font-weight:600;" title="AI Investigation (auto-executed diagnostics)">AI</th>
                                <th style="padding:8px 8px;text-align:center;color:#8b949e;font-size:10px;text-transform:uppercase;font-weight:600;" title="Fix Instructions Provided">Fix</th>
                                <th style="padding:8px 8px;text-align:center;color:#8b949e;font-size:10px;text-transform:uppercase;font-weight:600;" title="Red Hat Documentation Linked">Docs</th>
                            </tr>
                        </thead>
                        <tbody>
                            {"".join(exec_rows)}
                        </tbody>
                    </table>
                </div>
            </div>
        '''


def _jira_links_html(jira_keys: list, bug_status_info: dict) -> str:
    jira_html_parts = []
    for jira_key in jira_keys:
        if jira_key in bug_status_info:
            bug_info = bug_status_info[jira_key]
            status = bug_info.get("status", "Unknown")
            assessment = bug_info.get("assessment", "unknown")
            badge_color, badge_bg = jira_assessment_badge_style(assessment)
            jira_html_parts.append(
                f'<div style="display:inline-flex;align-items:center;gap:6px;margin:2px 0;">'
                f'<a href="https://issues.redhat.com/browse/{jira_key}" style="color:#5794F2;" target="_blank">{jira_key}</a>'
                f'<span style="background:{badge_bg};color:{badge_color};padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600;">{status}</span>'
                f"</div>"
            )
        else:
            jira_html_parts.append(
                f'<a href="https://issues.redhat.com/browse/{jira_key}" style="color:#5794F2;" target="_blank">{jira_key}</a>'
            )
    return "<br>".join(jira_html_parts) if jira_html_parts else "N/A"


def render_rca_grouped_issue_cards(
    grouped: dict,
    bug_status_info: dict,
    cluster_version: str,
    show_investigation: bool,
) -> str:
    """HTML for each grouped RCA category (issue card + optional investigation)."""
    html = ""
    for _title, data in grouped.items():
        issue = data["issue"]
        failures = data["failures"]
        raw_outputs = data["raw_outputs"]
        jira_keys = issue.get("jira", [])
        verify_cmd = issue.get("verify_cmd", "")
        jira_links_html = _jira_links_html(jira_keys, bug_status_info)
        border_color = failures_severity_border_color(len(failures))

        html += f'''
            <div style="background:var(--bg-secondary);border-radius:8px;padding:20px;margin-bottom:16px;border-left:4px solid {border_color};">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
                    <span style="font-weight:600;color:#fff;font-size:16px;">⚠️ {issue["title"]}</span>
                    <span style="background:var(--bg-canvas);padding:4px 12px;border-radius:12px;color:#F2495C;font-size:12px;font-weight:600;">{len(failures)} affected</span>
                </div>
                
                <div style="background:var(--bg-canvas);border-radius:6px;padding:12px;margin-bottom:15px;">
                    <div style="color:var(--text-secondary);font-size:11px;margin-bottom:6px;text-transform:uppercase;">Affected Resources:</div>
                    <div style="display:flex;flex-wrap:wrap;gap:6px;">
        '''
        for f in failures[:6]:
            html += f'<span style="background:var(--bg-primary);padding:4px 8px;border-radius:4px;font-size:11px;color:#c9d1d9;font-family:monospace;">{f["name"]}</span>'
        if len(failures) > 6:
            html += f'<span style="color:var(--text-secondary);font-size:11px;padding:4px;">+{len(failures)-6} more</span>'
        html += '''
                    </div>
                </div>
        '''

        if verify_cmd or raw_outputs:
            html += '''
                <div style="background:#0a0e14;border:1px solid #30363d;border-radius:6px;margin-bottom:15px;overflow:hidden;">
                    <div style="background:#161b22;padding:10px 14px;border-bottom:1px solid #30363d;display:flex;align-items:center;gap:8px;">
                        <span style="color:#73BF69;font-size:12px;">▶</span>
                        <span style="color:#8b949e;font-size:11px;text-transform:uppercase;font-weight:600;">How to verify on server:</span>
                    </div>
            '''
            if verify_cmd:
                html += f'''
                    <div style="padding:12px 14px;border-bottom:1px solid #21262d;">
                        <div style="color:#58a6ff;font-size:11px;margin-bottom:6px;">COMMAND:</div>
                        <code style="display:block;background:#0d1117;padding:10px 12px;border-radius:4px;font-family:'JetBrains Mono',Monaco,monospace;font-size:12px;color:#e6edf3;white-space:pre-wrap;word-break:break-all;">$ {verify_cmd}</code>
                    </div>
                '''
            if raw_outputs:
                combined_output = raw_outputs[0] if raw_outputs else "(no output)"
                combined_output = escape_html_basic(combined_output)
                html += f'''
                    <div style="padding:12px 14px;">
                        <div style="color:#f85149;font-size:11px;margin-bottom:6px;">OUTPUT (detected issues):</div>
                        <pre style="background:#0d1117;padding:10px 12px;border-radius:4px;font-family:'JetBrains Mono',Monaco,monospace;font-size:11px;color:#f85149;white-space:pre-wrap;word-break:break-all;margin:0;max-height:250px;overflow-y:auto;">{combined_output}</pre>
                    </div>
                '''
            html += """
                </div>
            """

        html += f'''
                <div style="color:var(--text-secondary);font-size:13px;margin-bottom:15px;">
                    {issue["description"]}
                </div>
                
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:15px;">
                    <div>
                        <div style="color:#F2495C;font-weight:600;font-size:12px;margin-bottom:8px;">🎯 ROOT CAUSES</div>
                        <ul style="color:#c9d1d9;font-size:12px;margin-left:16px;line-height:1.6;">
        '''
        for cause in issue.get("root_cause", [])[:3]:
            html += f"<li>{cause}</li>"
        html += '''
                        </ul>
                    </div>
                    <div>
                        <div style="color:#73BF69;font-weight:600;font-size:12px;margin-bottom:8px;">💡 REMEDIATION</div>
                        <ul style="color:#c9d1d9;font-size:12px;margin-left:16px;line-height:1.6;">
        '''
        for suggestion in issue.get("suggestions", [])[:3]:
            html += f'<li><code style="background:var(--bg-canvas);padding:1px 4px;border-radius:3px;font-size:11px;">{suggestion}</code></li>'

        bug_assessment_html = ""
        for jira_key in jira_keys:
            if jira_key in bug_status_info:
                bug_info = bug_status_info[jira_key]
                detail = bug_info.get("assessment_detail", "")
                if detail:
                    bug_assessment_html += f'<div style="font-size:11px;color:#c9d1d9;margin-top:4px;">{detail}</div>'

        html += f'''
                        </ul>
                    </div>
                </div>
                
                <div style="margin-top:15px;padding:12px;background:#0d1117;border-radius:6px;">
                    <div style="color:#5794F2;font-weight:600;font-size:12px;margin-bottom:8px;">🐛 RELATED JIRA BUGS (vs {cluster_version})</div>
                    <div style="margin-bottom:8px;">
                        {jira_links_html}
                    </div>
                    {bug_assessment_html}
                </div>
        '''

        if show_investigation:
            investigations = data.get("investigations", [])
            determined_causes = data.get("determined_causes", [])
        else:
            investigations = []
            determined_causes = []

        html += render_rca_investigation_section(
            investigations, determined_causes, data
        )

        html += """
            </div>
        """

    return html
